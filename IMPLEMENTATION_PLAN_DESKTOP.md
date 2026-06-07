# pydantic-deep Desktop — Production Implementation Plan

**Date:** 2026-06-04
**Goal:** Ship a production-ready, cross-platform (macOS/Windows/Linux) desktop app for pydantic-deep, learning from Hermes Desktop (Python core + web frontend + thin shell over a streaming gateway). No feature left behind, efficient, properly engineered.

**Companion docs:** `DESKTOP_APP_FEASIBILITY.md` (why this is feasible), `FEATURE_GAP_REPORT.md` (what the agent should grow into).

---

## 0. Final architecture decision

```
┌──────────────────────────────────────────────────────────────┐
│  Desktop shell — Tauri 2 (Rust, OS webview)                   │
│  • window/tray/menus • spawn+supervise Python gateway         │
│  • auto-update • deep links • OS notifications • secure store │
└───────────────┬──────────────────────────────────────────────┘
                │  loopback HTTP + WebSocket (127.0.0.1:<port>, token)
┌───────────────▼──────────────────────────────────────────────┐
│  Gateway — FastAPI + WebSocket  (apps/gateway/, Python)       │
│  • REST: sessions/config/skills/memory/mcp/fork/files         │
│  • WS:   bidirectional streaming session protocol             │
│  • SessionManager (lifecycle, persistence, resume, cancel)    │
└───────────────┬──────────────────────────────────────────────┘
                │  in-process
┌───────────────▼──────────────────────────────────────────────┐
│  pydantic_deep core — create_deep_agent(), agent.iter()       │
│  (UNCHANGED — single source of truth; same core as CLI/ACP)   │
└──────────────────────────────────────────────────────────────┘

Frontend: React 18 + Vite + TypeScript + Tailwind, loaded by the Tauri webview.
```

**Why these choices**
- **Tauri over Electron:** ~10 MB vs ~100 MB, OS webview, Rust shell with a hardened IPC/permission model and built-in updater/signing — better for a security-sensitive coding agent. (Electron remains a fallback if a Tauri webview gap blocks a feature.)
- **Gateway in Python, agent untouched:** the agent core stays the single source of truth (mirrors Hermes; proven by our existing `apps/acp/server.py`). The gateway only *translates* `agent.iter()` events to a transport.
- **Reuse, don't rewrite:** the agent→event mapping already exists twice (Textual `_agent_stream_worker`, `apps/acp/server.py`). We extract it once into `pydantic_deep/session/` and have **three** consumers (Textual, ACP, WS gateway) share it.

**Monorepo layout (additions)**
```
pydantic_deep/session/            # NEW shared: event model + agent→event translator
apps/gateway/                     # NEW FastAPI+WS backend (extra: pydantic-deep[gateway])
  ├─ app.py  routes/  ws.py  session_manager.py  auth.py  schemas.py
apps/desktop/                     # NEW Tauri + React
  ├─ src-tauri/  (Rust shell)
  ├─ src/        (React/Vite/TS frontend)
  ├─ scripts/  package.json  vite.config.ts  tauri.conf.json
```

---

## 1. Phase 0 — Foundation: shared session layer + gateway  (the highest-leverage work)

### 1.1 `pydantic_deep/session/` — extract the streaming contract (framework, 100% covered)
A provider/UI-agnostic translator turning `agent.iter()` into a typed event stream. Refactor the duplicated logic out of `apps/cli/screens/chat.py:_agent_stream_worker` and `apps/acp/server.py:prompt`.

- `events.py` — frozen pydantic models for **every** event (the full taxonomy in §1.3). One discriminated union `SessionEvent`.
- `runner.py` — `async def run_session(agent, deps, user_text, history, *, on_event, approvals_channel, cancel_token) -> RunOutcome`. Wraps `agent.iter()`:
  - `ModelRequestNode` → `TextDelta`, `ThinkingDelta`, `ToolCallStarted` (reuse the title/kind derivation already in `acp/server.py:313-325`).
  - `CallToolsNode` → `ToolCallResult` (status, content, `is_error` via existing `looks_like_error`, elapsed).
  - `DeferredToolRequests` → emit `ApprovalRequested`, await decision on `approvals_channel` (the piece ACP skips and the Textual worker does via modal).
  - Terminal: `RunCompleted` / `RunCancelled` / `RunError`; persist `run.result.all_messages()`.
- `mapping.py` — `_TOOL_KIND_MAP`, tool-title derivation, error detection — single home (deduped from both frontends).
- **Tests:** `tests/test_session_runner.py` with `FunctionModel`/`TestModel` asserting the event sequence for: plain text, tool call+result, tool error, approval approve/deny, cancel mid-stream, multi-turn history. 100% coverage (in-scope: `pydantic_deep/`).
- **Refactor both existing consumers** onto it (Textual worker + ACP server) → removes duplication, guarantees parity, and proves the abstraction before any GUI exists.

### 1.2 `apps/gateway/` — FastAPI + WebSocket
- **Bind loopback only** (`127.0.0.1`), ephemeral port, **bearer token** generated at launch and handed to the shell (never on disk in plaintext; passed via env/stdin). Reject cross-origin; CORS locked to the Tauri origin.
- **SessionManager:** create/get/list/resume/delete; per-session `Agent`, `DeepAgentDeps`, history, cwd, model, goal state, cost/context accumulators; concurrency-safe; idle eviction; persistence to `.pydantic-deep/sessions/<id>/` (reuse existing `messages.json` format + add `meta.json`, `goal.json`).
- **Lifespan:** build default agent via `create_deep_agent` from `CliConfig`; graceful shutdown cancels in-flight runs.

### 1.3 WebSocket protocol — complete event taxonomy
**Server→client** (one per agent signal the Textual TUI already surfaces — nothing dropped):
| Event | Payload | Source in current code |
|---|---|---|
| `text_delta` | `{text}` | assistant streaming |
| `thinking_delta` | `{text}` | extended thinking (gap-report item) |
| `tool_call_started` | `{id,name,args,title,kind}` | `FunctionToolCallEvent` |
| `tool_call_result` | `{id,status,content,is_error,elapsed}` | `FunctionToolResultEvent` |
| `tool_call_progress` | `{id,partial}` | streaming tool output |
| `approval_requested` | `{id,tool,args,position}` | `DeferredToolRequests`/ApprovalModal |
| `todos_update` | `{active,total,items}` | TodoToolset |
| `subagent_update` | `{tasks[]}` | subagents side panel |
| `fork_update` | `{branches[],costs,status}` | LiveForkCapability |
| `goal_update` | `{active,condition,turns,reason,achieved}` | `pydantic_deep/goal.py` |
| `cost_update` | `{run_usd,total_usd}` | CostTracking |
| `context_update` | `{pct,current,max,in,out}` | ContextManager |
| `message_count` | `{n}` | history length |
| `mcp_status` | `{servers[],degraded}` | MCP layer |
| `reminder` | `{turn,text}` | PeriodicReminder |
| `notification` | `{level,message,timeout}` | `app.notify` toasts |
| `run_started`/`run_completed`/`run_cancelled`/`run_error` | lifecycle | worker |
| `session_renamed`/`session_loaded` | session | session mgr |

**Client→server:** `prompt{text,attachments[]}`, `cancel`, `approval_response{id,decision}`, `steer{text}` / `queue{text}` (MessageQueue), `set_model`, `set_config{key,value}`, `command{name,arg}` (slash dispatch), `fork_action`, `merge_select{branch}`, `load_session{id}`, `rename_session{name}`, `attach_image{bytes}`.

- **Backpressure:** coalesce `text_delta`s (e.g. 30 ms flush), drop-and-summarize floods, virtualize on the client. Heartbeat ping/pong + auto-reconnect with resume cursor.

### 1.4 REST surface (non-streaming)
`GET/POST /sessions`, `GET /sessions/{id}`, `DELETE /sessions/{id}`, `POST /sessions/{id}/fork`; `GET/PUT /config`, `GET /config/schema` (drives Settings UI, generated from `CliConfig` fields); `GET /models`, `GET/POST /providers`; `GET/POST /mcp` (list/enable/login/test — wrap `apps/cli/mcp_store.py` + `pydantic_deep/mcp`); `GET /skills`, `GET /skills/{name}`; `GET/PUT /memory`; `GET /files?path=` + `GET /file?path=` (sandbox-scoped file browser, reuse backend `ls`/`read`); `GET /diff` (git); `POST /export`; `GET /health`, `GET /version`.

---

## 2. Phase 1 — Frontend (React/Vite/TS): full feature parity

### 2.1 Stack & state
- React 18 + Vite + TypeScript + Tailwind + Radix/shadcn primitives; TanStack Query for REST; a typed WS client (Zod-validated events shared with the gateway schema); Zustand for session/UI state; `react-window` for message virtualization; Shiki for code/diff syntax; KaTeX/markdown-it for rendering.
- **Generate TS types from the gateway's pydantic schemas** (`datamodel-codegen`/`pydantic2ts`) so the protocol is single-sourced and can't drift.

### 2.2 Layout (panels — every TUI surface mapped)
- **Chat** (center): streaming markdown, code blocks with copy, collapsible tool-call cards (icon by `kind`, args, result, error state, elapsed) — parity with `assistant_message.py`/tool rendering. Image attachments (paste/drag) → multimodal.
- **Tool/activity stream** + **inline diffs** (`+/-`, the real difflib diffs we already compute for edit/write) + **execute** full-command display.
- **Right dock (tabbed):** Todos, Subagents, Fork overview (branch chips + costs + merge), MCP servers, Skills, Context/cost meters.
- **Preview pane** (Hermes parity): embedded webview for a dev server / rendered HTML / screenshots; `.pydantic-deep/launch.json` for the command.
- **File browser** (Hermes parity): sandbox-scoped tree, open file → read-only viewer with syntax highlight; click file paths in chat to open.
- **Approval dialog:** modal on `approval_requested`, Approve/Deny/Always, position `(i/n)` — parity with `ApprovalModal`.
- **Status bar:** model, manual/auto, `◎ goal`, todos, cost, in/out tokens, context bar, msg count — 1:1 with `status_bar.py`.
- **Command palette** (`/` or Ctrl/Cmd-K): every slash command (see §3) with args, plus dynamic skills.

### 2.3 Streaming UX
Optimistic user bubble → WS `prompt` → render deltas; interrupt button (Esc) → `cancel`; queue/steer while running (parity with MessageQueue badges); reconnect banner; per-message cost/usage footer.

---

## 3. Feature-completeness matrix — nothing forgotten

### 3.1 All 32 slash commands → desktop surface
| Command | Desktop surface |
|---|---|
| `/clear`,`/undo`,`/compact`,`/context`,`/tokens`,`/cost` | command palette + buttons; `/compact` supports focus arg |
| `/copy`,`/copy-all`,`/export`,`/screenshot` | message/conversation actions; OS clipboard via shell |
| `/model`,`/provider`,`/config`,`/settings`,`/theme` | Settings UI (§3.2) |
| `/fork`,`/fork-config`,`/merge` | Fork panel + dialogs (branch count/models/budgets/strategy/judge) |
| `/goal` | goal bar + set/clear control (engine `pydantic_deep/goal.py` already done) |
| `/mcp` | MCP panel (enable/login/test/import/add) |
| `/skills` | Skills panel (list/view/run) |
| `/memory`/`/remember` | Memory editor panel |
| `/remind` | Settings → reminder mode |
| `/diff` | Diff viewer |
| `/improve` | Self-improve dialog |
| `/load`,(`/save` auto),`/rename`(new),`/resume`(new),`/branch`(new) | Session sidebar (list/search/preview/rename/branch) |
| `/help`,`/version`,`/bug` | Help/About menu |
| `/quit` | window close |
> Also expose the framework features currently **not wired into the CLI** (per gap report §11): output styles, checkpoint/rewind, plan mode, hooks viewer — the desktop is the chance to surface them.

### 3.2 Settings UI — all 47 `CliConfig` fields, schema-driven
Auto-generate the form from `GET /config/schema` (derived from `CliConfig` dataclass) so new fields appear automatically. Grouped:
- **Model/reasoning:** `model`, `fallback_model`, `temperature`, `thinking_effort`, `reasoning_effort`.
- **Providers/keys:** provider selector (anthropic/openrouter/openai/google-gla/ollama) + secure key entry (OS keychain via shell, never plaintext).
- **Capabilities toggles:** `include_skills/plan/memory/subagents/todo/teams/browser/liteparse`, `web_search/web_fetch`, `context_discovery`, `periodic_reminder`+`reminder_mode`+`reminder_model`.
- **Execution/sandbox:** `sandbox` (local/docker), `sandbox_image`, `sandbox_env_vars`, `sandbox_env_file`, `shell_allow_list`, `approve_tools`.
- **Forking:** `fork_branch_count`, `fork_branch_models`, `fork_branch_budgets`, `fork_aggregate_budget_usd`, `fork_merge_strategy`, `fork_judge_model`, `fork_confidence_threshold`.
- **UI/telemetry:** `theme`, `charset`, `show_cost`, `show_tokens`, `max_history`, `logfire`, `working_dir`.

### 3.3 Capabilities/toolsets → UI presence
Forking, teams, checkpointing, skills, memory, hooks, MCP, plan, summarization/eviction (surface eviction notices + "open offloaded output"), stuck-loop (surface warnings), cost tracking, periodic reminders, goal, browser, liteparse, subagents — each has a panel, indicator, or settings toggle (matrix maintained in the repo).

### 3.4 Hermes-parity extras
Streaming tool output ✔, side-by-side preview ✔, file browser ✔, voice I/O (Phase 4), settings UI ✔, sessions/profiles/memory/skills management ✔, scheduling (`/loop` — gap report) Phase 4, messaging gateways (out of scope / community).

---

## 4. Phase 2 — Desktop shell (Tauri 2)

### 4.1 Rust main process responsibilities
- **Backend lifecycle:** spawn the Python gateway as a child (resolve interpreter per §5), pass token+port via env, health-poll `/health`, restart on crash, kill on quit (process-group); surface a clear error UI if Python is missing.
- **Window/tray/menus:** native menu bar (mapped to commands), system tray (background runs), multi-window (parallel sessions/worktrees).
- **OS integration:** notifications (bridge `notification` events + goal-achieved/PR-style alerts), `claude-cli://`-style **deep links** (gap report) to open a session in a repo, global clipboard, file open dialogs, "reveal in Finder/Explorer".
- **Secure storage:** API keys in the OS keychain (Tauri Stronghold/keyring), not config.toml.
- **Auto-update:** Tauri updater (signed manifests).
- **Hardened IPC:** Tauri capability allowlist; the webview can only reach the loopback gateway with the token.

### 4.2 IPC
Frontend → gateway directly over HTTP/WS for agent traffic; frontend → Rust via Tauri commands only for OS things (keychain, dialogs, notifications, updater, clipboard, deep links).

---

## 5. Phase 3 — Packaging, distribution, updates (the Python-specific hard part)

### 5.1 Python runtime strategy (pick per platform; default = bundled)
- **Bundled (default):** ship a self-contained backend via **PyInstaller** (one-dir) or **`uv` + a pinned standalone CPython** baked into the Tauri resource dir. No network on first run. Handle native deps: Playwright browsers, Docker SDK, liteparse Node CLI stay **optional extras**, lazily resolved, with graceful "feature unavailable — install X" UI.
- **First-launch install (Hermes model, fallback/Linux):** small shell installs `pydantic-deep` into `~/.pydantic-deep/runtime` via `uv`/`pipx` on first run; lets CLI and desktop share one runtime.

### 5.2 Build & signing
- **macOS:** `.dmg`/`.app`, Developer ID signing + **notarization** + stapling; hardened runtime; entitlements for network/JIT as needed.
- **Windows:** `.msi`/NSIS, Authenticode signing (EV cert), SmartScreen reputation.
- **Linux:** AppImage + `.deb` + `.rpm`; optional Flatpak.
- **Reproducible builds**, version stamped from `pydantic_deep.__version__`.

### 5.3 Auto-update
Signed update manifests per channel (stable/beta); delta where possible; the **gateway** version-checks against the shell to refuse mismatched pairs; rollback on failed health check.

---

## 6. Production-grade cross-cutting concerns

### 6.1 Security (a coding agent runs code — treat as security-critical)
- Gateway loopback-only + token; reject non-token WS; per-message origin check.
- Reuse the agent's **permission/approval** path end-to-end (approvals over WS); honor `approve_tools`, `shell_allow_list`; surface protected-path/secret blocks (`default_security_hook`).
- Secrets in OS keychain only; scrub from logs; redact in telemetry.
- Tauri CSP locked; no remote code in the webview; SRI on assets.
- Sandbox backends (local/Docker) selectable per session; Docker isolation surfaced in UI.
- Threat-model doc + a security review (`/security-review`) gate before GA.

### 6.2 Reliability & errors
- Structured error taxonomy → user-friendly toasts + a "Details/Report" affordance.
- Crash reporting (opt-in, e.g. Sentry) for shell + frontend + gateway; symbolicated.
- Gateway supervises runs (timeouts, cancellation, stuck-loop detection already in core); WS auto-reconnect with event-resume cursor so a blip doesn't lose a turn.
- Graceful degradation when optional deps/providers/MCP servers are missing.

### 6.3 Performance & efficiency
- Coalesced streaming (§1.3), virtualized message list, lazy-loaded panels/routes, code-split frontend.
- Reuse prompt-cache-friendly ordering (gap report §15); show `cache_read`/`cache_creation`.
- Idle-evict sessions in the gateway; cap in-memory history (`max_history`); offload large outputs (EvictionCapability) and link to them.
- Cold-start budget: shell window < 1 s; gateway ready < 2–3 s (lazy-import heavy deps).

### 6.4 Observability (opt-in)
Logfire hook already in config; structured logs to `~/.pydantic-deep/logs/`; in-app diagnostics panel (gateway health, versions, last errors, `/doctor`-style checks); OpenTelemetry traces optional.

### 6.5 Accessibility & i18n
Keyboard-navigable (focus rings, ARIA, screen-reader labels), high-contrast/theme support honoring `theme`, scalable fonts; i18n scaffolding (strings externalized) even if English-only at GA.

### 6.6 Testing strategy
- **Gateway:** unit (session manager, auth, schema) + integration (`httpx` + WS client) using `TestModel`/`FunctionModel`; `pydantic_deep/session/` at **100% coverage** (in-scope).
- **Frontend:** Vitest + React Testing Library (components, WS reducer); **Playwright** e2e against a real gateway with a test model — full flows: prompt→stream→tool→approval→result, fork, goal, settings, session load.
- **Shell:** Tauri smoke tests (spawn gateway, health, deep link, update check) per OS.
- **Contract tests:** assert generated TS types match gateway schemas (drift guard).

### 6.7 CI/CD
- PR: lint/type/test for gateway (ruff/pyright/mypy, pytest, 100% cov for in-scope), frontend (eslint/tsc/vitest), Rust (clippy); Playwright e2e on Linux.
- Release: build matrix (mac arm64/x64, win x64, linux x64/arm64), sign+notarize, generate update manifests, attach installers + checksums, publish channel.
- Version gates: `minimumVersion`-style refusal of incompatible shell/gateway pairs.

### 6.8 Docs
User guide (install, first run, settings, panels, keyboard shortcuts), troubleshooting, security model, and an `apps/desktop/README.md` mirroring `apps/acp/README.md` quality.

---

## 7. Phased roadmap, milestones, effort

| Phase | Deliverable | Definition of done | Rough effort |
|---|---|---|---|
| **0** | `pydantic_deep/session/` + `apps/gateway/` (REST+WS), both existing frontends refactored onto it | 100% cov; ACP+TUI behavior unchanged; WS streams full taxonomy; loopback+token auth | 2–3 wks |
| **0.5 (optional MVP)** | `textual-serve` wrapped in pywebview/Tauri | Existing TUI runs in a desktop window (validates demand in days) | ~days |
| **1** | React frontend, full chat + panels + settings (schema-driven) + approvals | Feature-parity matrix (§3) green; Playwright happy-paths pass | 4–6 wks |
| **2** | Tauri shell: lifecycle, tray/menus, keychain, deep links, notifications | App launches managed gateway; OS integration works on 3 OSes | 3–4 wks |
| **3** | Packaging, signing/notarization, auto-update, crash reporting, security review | Signed installers per OS; updater verified; threat model signed off | 3–4 wks |
| **4 (post-GA)** | Voice I/O, `/loop` scheduling, remote/web sessions, multi-window worktrees, plugin surface | per-feature DoD | ongoing |

**Critical path = Phase 0.** It is also the foundation for web/remote/mobile (gap report §3), so it pays for itself beyond the desktop.

---

## 8. Risks & mitigations
- **Python packaging fragility (native deps).** → optional extras resolved lazily; bundle core only; `uv` standalone CPython; graceful "install X" UI; CI builds the matrix early.
- **Tauri webview gaps** (e.g. preview pane behaviors). → isolate webview-specific code; Electron fallback kept viable.
- **Protocol drift** frontend/backend. → single-source schemas + generated TS + contract tests in CI.
- **Streaming flood/jank.** → coalescing + virtualization + backpressure (§6.3).
- **Security (arbitrary code exec by design).** → loopback+token, approvals over WS, keychain secrets, sandbox per session, signed builds, security review gate.
- **Scope creep / forgotten features.** → the §3 matrix is a living checklist; GA blocked until every TUI feature maps to a surface or is explicitly deferred.

---

## 9. Definition of done (GA)
1. Every Phase-0/1/2/3 DoD met.
2. **§3 matrix fully green** — all 32 commands, 47 config fields, and every capability reachable or explicitly deferred.
3. Signed/notarized installers for macOS, Windows, Linux; verified auto-update + rollback.
4. `pydantic_deep/session/` at 100% coverage; gateway integration + Playwright e2e green in CI on all OSes.
5. Security review passed; threat model documented; secrets only in OS keychain.
6. Crash reporting + diagnostics live; cold-start budgets met.
7. User + developer docs published.
8. Desktop, CLI, and ACP all drive the **same** agent core through the **same** `pydantic_deep/session/` layer — zero agent logic duplicated in the frontend.
