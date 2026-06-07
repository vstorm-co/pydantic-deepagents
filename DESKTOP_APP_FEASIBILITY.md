# Desktop App Feasibility — learning from Hermes Agent (Nous Research)

**Date:** 2026-06-04
**Question:** Hermes Agent (Nous Research) shipped a cross-platform desktop app. Hermes is a **Python** agent — same as us. Could pydantic-deep do something similar?

**Short answer: Yes — and we're better positioned than Hermes was when they started.** The hard part (a UI-agnostic agent core with a streaming session protocol) is *already built* in our repo. A desktop app is mostly a frontend + a thin gateway, not an agent rewrite.

---

## 1. How Hermes built their desktop app (the facts)

From the Nous Research repo (`NousResearch/hermes-agent`, MIT, Hermes Desktop released 2026-06-02) and docs:

- **Agent core: Python (84.3% of the repo)**, TypeScript (12%) only for the frontend. Same language profile we have.
- **The desktop app does NOT reimplement the agent.** It ships an **Electron shell** (`apps/desktop/electron/main.cjs`) + a **React/Vite/TypeScript renderer** (`apps/desktop/src/`).
- **The renderer talks to the existing Python agent over the standard "gateway APIs" (HTTP/WebSocket).** It "reuses the embedded TUI rather than reimplementing chat" — i.e. it renders the agent's existing streamed session events.
- **Same core as the CLI** — same config, API keys, sessions, skills, memory. The desktop app and CLI are interchangeable because both drive the one agent runtime in `~/.hermes`.
- **Electron main process** handles: installing the Python runtime into `HERMES_HOME` on first launch, backend resolution, self-update, native window lifecycle.
- **Packaging model:** the installer ships *only the Electron shell*; on first launch it runs the official Hermes install script to put the Python agent into `~/.hermes`. (Python runtime installed separately, not bundled.)
- Desktop features: streaming tool output, side-by-side preview pane, file browser, voice I/O, settings UI, sessions/profiles/memory/skills/scheduling/messaging-gateway management.
- Hermes' agent shape is **nearly identical to ours**: Python CLI + TUI, persistent memory, auto-generated skills, sessions, MCP, and sandboxed execution backends (local, Docker, SSH, Singularity, Modal, Daytona — we have local + Docker).

**The architectural lesson:** decouple the agent (Python) from the GUI via a local streaming API, then put any frontend on top. Hermes chose Electron+React over an HTTP/WS gateway.

---

## 2. Why this maps cleanly onto pydantic-deep

We have already done the structurally hard part — **our agent core is UI-agnostic and we have two independent frontends proving it:**

1. **Textual TUI** (`apps/cli/`) — consumes the agent's streamed events in `ChatScreen._agent_stream_worker` via pydantic-ai's `agent.iter()` (model-request nodes, `FunctionToolCallEvent`, `FunctionToolResultEvent`, text deltas).
2. **ACP server** (`apps/acp/server.py`, 375 lines) — an **Agent Client Protocol** (JSON-RPC) adapter that already exposes our agent to external editors like **Zed**: `new_session`, `set_session_model`, `set_config_option`, `cancel`, `prompt`, and streamed `start_tool_call` / `update_tool_call` / `update_agent_message_text` updates with per-session state (cwd, model, history, deps).

That second one is the key: **we already have a session-based, streaming, decoupled protocol layer over the agent** — the same role Hermes' "gateway API" plays. The desktop question is therefore *not* "can we decouple the agent?" (done) but "which frontend + transport do we put on top?"

The agent's streaming event source (`agent.iter()`) already fans out to two consumers. Adding a third (a WebSocket gateway for a desktop GUI) is a well-trodden path in this codebase.

---

## 3. Architecture options for a pydantic-deep desktop app

Ordered roughly fastest-MVP → most-native. All share **one foundational piece** (§4): a streaming gateway.

### Option A — Hermes model: web frontend + desktop shell + Python gateway  ★ recommended target
- **Backend:** add `pydantic-deep serve` — a FastAPI app exposing REST (sessions, config, skills, memory, fork, mcp) + a **WebSocket** that streams the same events the Textual worker consumes.
- **Frontend:** React/Vite/TS (or Svelte) chat UI — rich preview pane, file browser, diff view, settings.
- **Shell:** **Tauri** (Rust shell, OS webview, ~10 MB, lighter) *or* **Electron** (Chromium bundled, ~100 MB, simpler ops, what Hermes used).
- **Packaging:** bundle the Python backend with PyInstaller, *or* copy Hermes' model and install the `pydantic-deep` runtime into `~/.pydantic-deep` on first launch.
- **Pros:** most "native desktop" feel, reuses agent core, unlocks web/mobile/remote for free (ties to the cloud/remote gap in `FEATURE_GAP_REPORT.md` §3). **Cons:** new React app + a JS/Rust shell to maintain; most work.

### Option B — Textual-native: `textual-serve` wrapped in a desktop shell  ★ fastest MVP
- Textual can already **serve the existing TUI to a browser** (`textual serve` / `textual-web`). Wrap that browser view in **pywebview / Tauri / Electron** → instant desktop app that **reuses 100% of our current TUI** (`apps/cli/`).
- **Pros:** days, not weeks; zero UI rewrite; everything we already built (forking, `/goal`, modals) works immediately. A genuine advantage Hermes does *not* have (their TUI isn't a Textual app). **Cons:** it's a terminal-grid UI in a window, not native widgets / preview panes; mouse/clipboard UX is terminal-flavored.
- **Use as:** the v0 desktop app to ship in days, while Option A is built behind it.

### Option C — PyWebView (pure-Python shell) + web frontend + gateway
- **PyWebView** opens a native OS webview from Python (no Node/Rust shell), with a Python↔JS bridge; packages with PyInstaller/Briefcase as a single Python app.
- **Pros:** all-Python toolchain, lightest dependency footprint, one language. **Cons:** thinner ecosystem than Electron/Tauri; still need to build the web frontend; auto-update is DIY.

### Option D — Native Python GUI (Flet / Toga / PySide)
- **Flet** (Flutter-in-Python) or **BeeWare/Toga** (native widgets) build cross-platform GUIs in **pure Python, no JS at all**.
- **Pros:** single language end-to-end, no web stack, native look. **Cons:** reimplement the chat UI from scratch (can't reuse Textual widgets); rich streaming/diff/preview UIs are more work than in React; less mature for this use case.

| Option | Shell tech | Reuse TUI? | New UI work | Footprint | Time-to-MVP |
|---|---|---|---|---|---|
| **B** textual-serve + shell | pywebview/Tauri/Electron | **100%** | ~none | small–med | **days** |
| **C** PyWebView + web UI | PyWebView (Python) | no | full web UI | small | weeks |
| **A** Electron/Tauri + web UI | Electron/Tauri | no | full web UI | med–large | weeks–months |
| **D** Flet/Toga | Python-native | no | full native UI | small–med | weeks–months |

---

## 4. The foundational piece (do this first regardless of option): a streaming gateway

Everything above (except B's quick path) needs one thing we don't yet have: a **server/gateway mode** that exposes the agent's streamed session over HTTP/WebSocket. Concretely:

- `pydantic-deep serve [--host --port]` → FastAPI + WebSocket.
- **Reuse, don't rebuild:** the event-translation logic already exists twice — in `ChatScreen._agent_stream_worker` (Textual) and `apps/acp/server.py` (ACP). Factor the agent→UI-event mapping into a shared module (`pydantic_deep/session/` or `apps/gateway/`) that all three consumers (Textual, ACP, WebSocket) use.
- Endpoints mirror what the ACP server already models: create/list/resume session, set model/config, send prompt, cancel, plus streamed events (text deltas, tool-call start/update/result, todos, cost/context updates, fork status).

**Strategic bonus:** this same gateway is the missing primitive behind several items in `FEATURE_GAP_REPORT.md` — remote control, web sessions, mobile, push. Building it for the desktop app pays for those too. It's the highest-leverage single investment.

---

## 5. Packaging the Python runtime (the one genuinely Python-specific hurdle)

Shipping a Python app to non-developers is the part Hermes solved by **installing the runtime on first launch** rather than bundling it. Our options:

- **First-launch install (Hermes model):** ship a small shell; on first run, `pipx`/`uv`-install `pydantic-deep` into `~/.pydantic-deep`. Simplest to build, smallest download, requires network on first run.
- **Bundle with PyInstaller / Briefcase:** one self-contained installer per OS, no network needed; larger artifact; care needed for native deps (Playwright/`pydantic-deep[browser]`, Docker SDK, liteparse/Node).
- **uv-powered installer:** `uv` can provision a pinned Python + deps fast and reproducibly — a clean middle ground.

Native/optional deps (Playwright browser, Docker, liteparse Node CLI) should stay **optional extras**, resolved lazily, exactly as they are today — the desktop app degrades gracefully without them.

---

## 6. Verdict & recommended path

**Feasible: clearly yes.** Hermes is an existence proof that a Python-core agent of our exact shape can ship a polished cross-platform desktop app, and our codebase is *further along the critical path* than a from-scratch start because the agent is already decoupled (Textual + ACP) and already streams a session protocol.

**Recommended sequencing:**
1. **Week-scale MVP — Option B:** wrap the existing Textual TUI via `textual-serve` in pywebview/Tauri. Ships a real desktop app immediately, reusing everything (forking, `/goal`, modals, MCP). Validates demand cheaply.
2. **Foundational investment — §4 gateway:** factor the shared agent→event module out of the Textual worker + ACP server; add `pydantic-deep serve` (FastAPI + WebSocket). Unlocks desktop *and* web/remote/mobile.
3. **Polished product — Option A:** React/Vite renderer (streaming chat, preview pane, file browser, diff view, settings) in a Tauri shell over the §4 gateway; package via uv/PyInstaller or first-launch install.

**The one thing to avoid:** rewriting the agent or its UI logic in TypeScript. Hermes didn't, our ACP adapter shows we don't have to, and the gateway in §4 is what keeps the agent the single source of truth.

---

### Appendix — relevant existing assets in this repo
- `apps/cli/` — Textual TUI; `ChatScreen._agent_stream_worker` is the reference event-stream consumer.
- `apps/acp/server.py` — ACP (JSON-RPC) session adapter; proves the agent is UI-agnostic and already speaks a streaming session protocol. Closest existing analog to Hermes' "gateway API."
- `pydantic_deep/agent.py` — `create_deep_agent()` core, shared by all frontends.
- `apps/cli/main.py` — Typer entry (`pydantic-deep` + `pydantic-deep run` headless); a `serve` subcommand slots in here.
- Sandboxed backends (local/Docker) already match Hermes' lower execution tiers.
