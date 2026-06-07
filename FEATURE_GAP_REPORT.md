# Claude Code vs pydantic-deep — Feature Gap Report

**Date:** 2026-06-04
**Scope:** Full Claude Code documentation (145 pages, feature/capability subset analyzed in depth) cross-referenced against pydantic-deep (`pydantic_deep/` framework + `apps/cli/` Textual TUI).
**Method:** 5 parallel doc-research passes over Claude Code docs + full codebase inventory. Enterprise/billing/cloud-provider-plumbing pages (Bedrock, Vertex, Foundry, Slack, GitHub/GitLab CI, analytics, legal, ZDR) were intentionally de-prioritized as out of scope for a library/CLI feature comparison.

---

## 1. Executive summary

pydantic-deep already matches Claude Code on a surprising number of **core primitives** — subagents, agent teams, checkpointing, skills, persistent memory, hooks (tool-level), MCP client, output styles (in framework), context/summarization management, eviction, stuck-loop detection, cost tracking, periodic reminders, live-run forking, and now `/goal`. Several of these (live-run forking with autonomous judge, eviction, stuck-loop detection) have **no Claude Code equivalent** — we are ahead there.

The gaps fall into four buckets:

1. **Whole subsystems we don't have at all** — cloud/remote session portability, the scheduling stack (cron/routines/loop), channels, the background-agent supervisor daemon, dynamic JS workflows, the plugin+marketplace ecosystem, OS-level sandboxing, the auto-mode classifier, and LSP code intelligence.
2. **Depth gaps in systems we *do* have** — our hooks cover ~9 tool/run events vs Claude Code's 30–43 lifecycle events and 5 handler types; our permission model is a simple approve-list vs 6 modes + rule grammar; our memory lacks path-scoped rules and `@imports`.
3. **Framework features not wired into the CLI** — output styles, checkpointing/rewind, plan mode, and hooks all exist in `pydantic_deep/` but have **no slash command** in the TUI. These are the cheapest wins.
4. **TUI/UX polish** — customizable keybindings, scriptable statusline, fullscreen renderer, voice, vim mode, side-questions (`/btw`), transcript viewer, session resume/branch/naming.

**Highest-leverage recommendations** are in §13.

---

## 2. Parity — where we already match (condensed)

| Area | Claude Code | pydantic-deep | Notes |
|---|---|---|---|
| Subagents | `Agent` tool, `/agents` | `SubAgentToolset` | We lack the `/agents` library UI + frontmatter scopes |
| Agent teams | experimental, peer messaging, shared tasks | `TeamCapability` + `TeamToolset` + `TeamMessageBus` | Comparable design |
| Checkpointing | `/rewind`, auto-snapshot | `CheckpointToolset` + `CheckpointMiddleware` | **Not wired to a CLI command** (§11) |
| Skills | `SKILL.md`, scopes, frontmatter | `SkillsCapability` + `SkillsToolset` | We lack many frontmatter fields (§6) |
| Memory | auto-memory `MEMORY.md` | `MemoryCapability` + `/remember` | We lack path-scoped rules, `@imports` (§5) |
| Hooks | 30–43 events, 5 types | `HooksCapability` (~9 events, command/handler) | Major depth gap (§4) |
| MCP client | http/stdio/sse/ws, OAuth, tool-search | `MCPRegistry`, http/stdio, bearer/OAuth, 5 builtins | We lack tool-search deferral, ws/sse (§7) |
| Output styles | built-ins + custom + `/config` | `BUILTIN_STYLES`, `resolve_style` | **Not wired to a CLI command** (§11) |
| Context mgmt | `/compact`, auto-compaction | summarization + sliding window + `/compact` | Comparable |
| Cost tracking | `/usage`, statusline | `CostTracking`, status bar | Comparable |
| Structured output | `--json-schema`, SDK `output_format` | pydantic-ai `output_type` | We lack the CLI/headless `--json-schema` flag (§12) |
| Forking | `/branch`, `--fork-session` | `LiveForkCapability` + `/fork` + judge | **We're ahead** (autonomous judge/merge) |
| Large-output handling | — | `EvictionCapability` | **We're ahead** |
| Loop detection | — | `StuckLoopDetection` | **We're ahead** |

---

## 3. Gap: cloud / remote / cross-surface (we have NONE of this)

Claude Code's biggest differentiator is session mobility. We have none of it.

- **Remote Control** — drive a local session from phone/browser (QR pairing, multi-device sync, outbound-HTTPS only). `/rc`, `claude remote-control`, `--spawn worktree`, `--capacity`.
- **Cloud sessions / web** — `claude --remote`, claude.ai/code VMs, `--teleport`/`/tp` to pull a cloud session back to the terminal, `/desktop` handoff.
- **Auto-fix PRs / Auto-merge** — cloud sessions subscribe to GitHub webhooks, fix CI failures & review comments, reply on PR threads.
- **Dispatch** — phone-spawned sessions; **Deep links** (`claude-cli://` OS URL scheme) to launch a terminal session in the right repo with a pre-filled prompt.
- **`PushNotification` tool** — desktop + phone push.

**Assessment:** Large, infra-heavy. Mostly out of scope for an open-source library unless we build a relay service. Note as "intentionally not pursued" rather than a true gap.

---

## 4. Gap: hooks depth

We have `HooksCapability` with ~9 events (`PRE_TOOL_USE`, `POST_TOOL_USE`, `POST_TOOL_USE_FAILURE`, run/model events) and two handler shapes (shell command, Python handler). Claude Code has **30–43 lifecycle events** and **5 handler types**.

**Missing events (high value):**
- `SessionStart` / `SessionEnd` / `Setup` — inject context at boot, one-time prep.
- `UserPromptSubmit` / `UserPromptExpansion` — validate/augment prompts before processing.
- `Stop` / `StopFailure` — block turn end to keep working (this is literally how Claude Code implements `/goal`! We hand-rolled it in the worker instead).
- `PreCompact` / `PostCompact`, `SubagentStart` / `SubagentStop`, `TaskCreated` / `TaskCompleted`, `TeammateIdle`.
- `FileChanged` (watch disk), `CwdChanged` (direnv-style env reload), `ConfigChange`, `InstructionsLoaded`, `MessageDisplay` (rewrite streamed text), `Notification`, `PermissionRequest` / `PermissionDenied`.

**Missing handler types:** `http` (POST to a service), `mcp_tool` (invoke an MCP tool), `prompt` (small-model yes/no judgment), `agent` (subagent verifier that reads code before deciding).

**Missing semantics:** the `if` field with permission-rule syntax (`Bash(git *)`) that parses compound commands subcommand-by-subcommand; `additionalContext` JSON injection; hooks overriding permission modes (unbypassable deny).

**Assessment:** Medium effort, high value. A `Stop`-style hook event would let us re-implement `/goal` and periodic-reminder on a unified primitive. **Recommended.**

---

## 5. Gap: memory & instruction loading

We have `MemoryCapability` (agent read/write/update + `/remember`) and `ContextFilesCapability` (auto-discovers AGENTS.md/CLAUDE.md/SOUL.md/etc.). Claude Code goes deeper:

- **Path-scoped rules** — `.claude/rules/*.md` with `paths:` glob frontmatter that load into context **only when a matching file is read**. We inject context files unconditionally.
- **`@path` imports** — inline other files into CLAUDE.md at launch (recursive up to 4 hops, approval on first external import).
- **Auto-memory** — agent writes its own per-repo `MEMORY.md` + topic files read on-demand. We have read/write tools but no automatic learning-capture loop or topic-file sharding.
- **Compaction survival semantics** — project-root CLAUDE.md re-injected after `/compact`; documented rules for what survives.
- **`claudeMdExcludes`** for monorepo noise; HTML-comment stripping; directory walk-up loading of ancestor CLAUDE.md.
- **`/memory` command** to list/toggle/edit loaded instruction files.

**Assessment:** Path-scoped rules + `@imports` are medium effort, high value for large codebases. **Recommended.**

---

## 6. Gap: subagents & teams depth

We have the core, but Claude Code's frontmatter/lifecycle is richer:

- **Subagent frontmatter fields** we lack: `permissionMode`, `maxTurns`, `skills` (preload), `mcpServers` (inline), `hooks`, `memory` scope, `background`, `effort`, `isolation: worktree`, `color`, `initialPrompt`.
- **`/agents` UI** — Running tab (live subagents) + Library tab (create/edit/"Generate with Claude").
- **Forked subagent inheriting full conversation + prompt cache** — `/fork <directive>`. Our `/fork` is live-run *branching*, a different concept; we lack a cheap "inherit my whole context, keep your tool calls out of mine" worker.
- **Git worktree isolation** — `isolation: worktree`, auto-cleanup. We have no worktree support at all.
- **Background subagents** + the supervisor daemon (§8).
- **Persistent per-subagent memory dirs.**

**Assessment:** Worktree isolation and subagent frontmatter are medium effort, moderate value.

---

## 7. Gap: tools we don't have

| Tool | What it does | Effort |
|---|---|---|
| **LSP / code intelligence** | Language-server definitions/references/diagnostics after edits | High (per-language) |
| **Monitor** | Run a background command, feed each output line back mid-turn (tail logs, poll CI) | Medium — **high value, recommended** |
| **Worktree tools** (`EnterWorktree`/`ExitWorktree`, `--worktree`, `#PR`) | First-class git worktree isolation | Medium |
| **NotebookEdit** | Jupyter cell edits | Low–Medium |
| **Computer use** | Native GUI control (macOS) | High, niche |
| **Chrome integration** | Login-state-sharing browser automation | We have Playwright `BrowserToolset` — **partial parity**, but not real-browser-with-your-login |
| **PowerShell tool** | Native PowerShell exec | Low |
| **MCP tool-search** | Defer MCP schemas; scale to 10k tools | Medium — **value grows with MCP usage** |
| **WebSearch/WebFetch** | We have these | parity |

---

## 8. Gap: background-agent supervisor (`claude agents` / agent view)

A per-user daemon hosting **detached background sessions** that survive terminal close, machine sleep, and binary auto-update; with per-session worktree isolation, Haiku-generated status one-liners, PR-status tracking, `attach`/`logs`/`stop`/`respawn`/`rm`, filters, and a roster UI. We have nothing comparable — our sessions are bound to the TUI process.

**Assessment:** Large effort. Interesting for "fire-and-forget" workflows but a big build.

---

## 9. Gap: scheduling stack

Three coordinated tiers we lack entirely:
- **`/loop [interval] [prompt]`** — re-run a prompt on an interval or self-paced; `loop.md` default; uses the Monitor tool.
- **Cron tools** — `CronCreate`/`CronList`/`CronDelete`, session-scoped, restored on resume, jittered.
- **Routines** — cloud-hosted, triggered by schedule / `/fire` webhook / GitHub PR events.

**Assessment:** `/loop` (in-session) is low–medium effort and composes nicely with our new `/goal`. Cloud routines are out of scope. **`/loop` recommended.**

---

## 10. Gap: channels & dynamic workflows

- **Channels** — MCP servers that **push** external events (Telegram/Discord/iMessage/webhooks) into a *running* session. Medium-high effort; depends on our MCP layer maturing.
- **Dynamic workflows** (`ultracode`, `/workflows`) — Claude writes a JS orchestration script run by a background runtime spawning up to 1,000 subagents, results kept out of context, savable as `/commands`. We have subagents + teams + forking but no script-driven fan-out orchestration primitive. High effort; our forking partially overlaps.

---

## 11. Gap: framework features NOT wired into the CLI (cheapest wins)

These already exist in `pydantic_deep/` but have **no slash command** in `apps/cli/commands.py`:

- **Output styles** — `BUILTIN_STYLES`, `resolve_style`, `format_style_prompt` exist; no `/output-style` or `/style` command. → Add a picker like `/remind`.
- **Checkpointing / rewind** — `CheckpointToolset`, `CheckpointMiddleware`, `fork_from_checkpoint` exist; no `/rewind` or `/checkpoint` command and not enabled by default in the CLI agent. → Add `/rewind` + Esc-Esc binding.
- **Plan mode** — `PlanCapability`, `create_plan_toolset`, built-in planner subagent exist; no `/plan` command or Shift+Tab mode cycle in the TUI.
- **Hooks** — `HooksCapability` exists; no `/hooks` viewer and no config-file loading of user hooks in the CLI.

**Assessment:** **Low effort, high value — do these first.** They turn already-built-and-tested framework capabilities into user-facing features.

---

## 12. Gap: permissions & sandboxing

- **Permission modes** — Claude Code has 6 (`default`/`acceptEdits`/`plan`/`auto`/`dontAsk`/`bypassPermissions`) cycled with Shift+Tab. We have a flat `approve_tools` list (default `["execute"]`) and a per-call approval modal. No mode cycling.
- **Auto-mode classifier** — a second LLM that reasons per-action about whether it's destructive/exfiltrating/injection-driven, configured in prose. Distinctive; we have nothing like it.
- **Permission rule grammar** — `Bash(npm test *)`, gitignore-style path patterns, symlink dual-path checks, shell-operator-aware parsing. We have a plain allow-list.
- **OS-level sandbox** — Seatbelt (macOS) / bubblewrap (Linux) binding child processes, per-domain network proxy, filesystem allow/deny. We have local/Docker **backends** (process isolation via Docker) but not OS-level sandboxing of the local backend.
- **Protected paths** — `.git`/`.claude`/dotfiles never auto-approved.

**Assessment:** Permission modes + a small rule grammar = medium effort, high value (safety + UX). OS sandbox = high effort; Docker backend partially covers it. **Permission modes recommended.**

---

## 13. Gap: TUI / interactive UX

| Feature | Claude Code | Us | Effort |
|---|---|---|---|
| Customizable keybindings | `~/.claude/keybindings.json`, 20 contexts, chords, hot-reload | Fixed bindings | Medium |
| Scriptable statusline | `statusLine` command + rich JSON stdin, `/statusline` | Fixed status bar | Medium |
| Fullscreen renderer | alt-screen, mouse, drag-select | Standard Textual | N/A (Textual differs) |
| Voice dictation | `/voice` hold/tap, 20 langs | — | High, niche |
| Vim editor mode | full NORMAL/INSERT/VISUAL | — | Medium |
| Side questions | `/btw` ephemeral, no-tools, reads context | — | **Low — recommended** |
| Transcript viewer | `Ctrl+O`, search, write-to-scrollback | — | Medium |
| Prompt suggestions | git-history grayed autocomplete | — | Medium |
| Session resume/branch | `--resume`/`--continue`/`/branch`/`-n` naming | `/load` only (no resume/branch/name) | **Low–Medium — recommended** |
| `/compact <focus>` | focus instructions | We have `/compact` | check focus-arg support |
| Background bash (`Ctrl+B`) | background a command, retrieve via Read | — | Medium |

---

## 14. Gap: review / quality tooling

- **`/code-review`** (local diff review, `--fix`/`--comment`, effort levels) and **`/simplify`**. We have `/improve` (session self-improvement) — a *different* thing. No diff-review command.
- **`/ultrareview` / `/code-review ultra`** — cloud multi-agent review with independent verification. Out of scope (cloud).
- **`/security-review`** + **security-guidance plugin** (3-tier self-review on hooks). We have `default_security_hook` + blocked-command/path/secret constants — a **partial** building block, not a review loop.
- **`/verify`**, **`/run`** skills — launch the app and confirm a change works.

**Assessment:** A local `/review` (diff → findings) is medium effort, high value and composes with our subagents/forking.

---

## 15. Gap: model / reasoning / caching

- **Effort levels** (`/effort low…max/ultracode`) and **`opusplan`** (Opus plan → Sonnet exec) auto-switching. We have `thinking_effort` config but no `/effort` command or plan/exec model switching.
- **Fast mode** (`/fast`, 2.5× Opus) — Anthropic-specific, out of scope.
- **1M context variants** (`opus[1m]`) — we pass model strings through, so usable, but no UX around it.
- **Extended-thinking toggle** (`Option+T`), `showThinkingSummaries`. The TUI improvements memo already notes thinking display is missing.
- **Prompt-caching discipline** — Claude Code orders prefix layers most-stable-first and avoids cache-invalidating actions; surfaces `cache_read`/`cache_creation` tokens. We don't expose cache metrics or document cache-stable ordering.

---

## 16. Gap: headless / SDK ergonomics

We have `pydantic-deep run` (headless) with rich flags and a programmatic `create_deep_agent()` API. Claude Code adds:
- **`--bare`** — skip ALL auto-discovery for reproducible CI. We always load config.
- **`--json-schema`** flag for schema-constrained CLI output (we support `output_type` programmatically but not as a headless flag).
- **`stream-json` / `--include-partial-messages`** token-level streaming events; `system/api_retry`, `system/init` events.
- **`--append-system-prompt` / `--system-prompt`** replace/extend at true system-prompt level.

**Assessment:** `--json-schema` and `--append-system-prompt` headless flags are low effort, high value for automation users. **Recommended.**

---

## 17. Prioritized recommendations

### Tier 1 — quick wins (wire up what we already built)
1. **`/output-style` (or `/style`) command** — picker over `BUILTIN_STYLES` + custom styles. (framework done)
2. **`/rewind` + `/checkpoint` commands** and enable `CheckpointMiddleware` in the CLI agent; bind Esc-Esc. (framework done)
3. **`/plan` command + Shift+Tab permission-mode cycle.** (framework `PlanCapability` done)
4. **`/hooks` viewer + load user hooks from config** into the CLI agent. (framework done)
5. **Session `/resume`, `/branch`, `-n`/`/rename`** — extend the existing `/load` + sessions dir.
6. **Headless `--json-schema` and `--append-system-prompt` flags.**

### Tier 2 — medium effort, high value
7. **Generalize hooks to lifecycle events** — add `Stop`, `SessionStart/End`, `UserPromptSubmit`, `PreCompact/PostCompact`; refactor `/goal` + periodic-reminder onto the `Stop` hook. Add `prompt` and `agent` handler types.
8. **`/loop [interval] [prompt]`** in-session scheduler (composes with `/goal`).
9. **Monitor tool** — background command streaming lines back mid-turn.
10. **Permission modes + a small rule grammar** (`Bash(git *)`, path patterns) and Shift+Tab cycling.
11. **Path-scoped rules** (`paths:` frontmatter) + **`@imports`** in context files.
12. **`/review`** — local diff review via a subagent (reuse forking/judge).
13. **`/btw` side-questions** overlay.

### Tier 3 — big bets (scope before committing)
14. **Git worktree isolation** (`--worktree`, `isolation: worktree`, `EnterWorktree` tool).
15. **MCP tool-search deferral** (scales MCP usage).
16. **Customizable keybindings + scriptable statusline.**
17. **Dynamic workflows** orchestration primitive (overlaps our forking).
18. **Background-agent supervisor daemon** (detached sessions).

### Out of scope (cloud/Anthropic-specific) — note, don't build
Remote Control, cloud sessions / web / teleport, routines, auto-fix PRs, fast mode, voice (hosted), computer use, ultrareview/ultraplan, channels (unless community-driven), enterprise managed-settings/MDM governance.

---

## 18. Where we lead Claude Code

Worth preserving and marketing:
- **Live-run forking** with autonomous judge, confidence scoring, and merge strategies (`vote`/`auto_with_fallback`).
- **EvictionCapability** — automatic large-tool-output offloading.
- **StuckLoopDetection** — A-B-A-B / repeat / no-op detection.
- **Provider breadth** — Anthropic / OpenRouter / OpenAI / Google / Ollama out of the box (Claude Code is Anthropic-first).
- **Document parsing** (`LiteparseToolset`) and **first-class Playwright browser** as a built-in toolset.
