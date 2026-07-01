# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.34] - 2026-06-27

A large release: a full CLI/TUI overhaul, a vertical-slice re-organization of the
framework into `features/`, a new **Monitor** capability, broad edge-case
hardening, and a documentation rewrite.

### Added

#### Framework

- **Monitor — watch & react** (`pydantic_deep/features/monitoring/`). The agent starts a long-lived command (log tail, CI poll, file watch, dev server) with `start_monitor` / `list_monitors` / `stop_monitor`; each new line of matching output is pushed back into the conversation via the message queue, so the agent reacts without polling. `MonitorManager` drains the process on an interval, filters lines by an optional regex, and emits `MonitorEvent` batches through an `on_event` sink. Enabled by default (`include_monitoring=True`); needs a background-capable backend.
- **Background process tools** surfaced from `pydantic-ai-backend` 0.2.15 (`run_in_background` / `read_output` / `kill_shell` / `list_shells`), so dev servers and watchers outlive a single `execute()` call (which kills its whole process tree on timeout).
- **`ToolSearch` capability** (`pydantic_deep/features/tool_search/`) — defer situational toolsets so the model discovers them on demand. Off by default in the library, on in the CLI.
- A built-in **`general-purpose` subagent** so the agent can delegate arbitrary multi-step work.

#### CLI / TUI

- New slash commands: **`/retry`** (re-run the last prompt, dropping the previous turn), **`/export [path]`** (save the conversation to Markdown), **`/shells`** (list background processes).
- **Ctrl+P input-history picker** with fuzzy search; **fuzzy subsequence matching** in the `/` command and `@` file pickers (new `apps/cli/fuzzy.py`).
- **Background-shells panel** pinned in the activity dock.
- **Multi-line paste** switches the input to multiline, preserving code blocks.
- Visible **attachment chips** + **drag-and-drop** files onto the input; clipboard image paste; quoted **`@"path with spaces"`** so spaced screenshots attach as images.
- Interactive **`/settings`** modal (changes apply immediately) and an **`/info`** modal; `/help` and the command picker now list every command, guarded by a coverage test.
- Warm **amber (Tau-inspired) default theme** with theme-aware chrome (header, status line, input, tool calls, diffs), animated welcome, and a boxed prompt.

### Changed

- **`@file` references now pass the path** (backticked) to the agent instead of inlining the whole file — the agent decides how to read it (full, sliced, or grep). Images still attach as multimodal content.
- **`!shell` and `/diff` run off the event loop** (no UI freeze on long commands or large repos); the **`/load` session picker** loads asynchronously, sorts by modification time, and fuzzy-filters.
- **Lean behavioral prompt** sections when `tool_search` is on (tools carry their own descriptions); folders-first directory tree in the context prompt.
- **Prompt caching enabled on the OpenRouter path** (previously only the Anthropic cache keys were set), cutting cost on multi-turn / subagent runs.
- Left sidebar replaced by activity panels pinned above the input; session + workspace moved to a footer; the status line carries live metrics.
- Broad **type hardening** and de-duplication across the framework (pydantic models for improve insights, `Literal` status/action enums, typed deps/callbacks/coordinators, tightened public exports, drift guards on `DeepAgentSpec` and overloads); default models sourced from `pydantic_deep.models`.
- **Pinned `pydantic-ai-backend>=0.2.15`** (background processes, read output ceiling, glob mtime sort, edit staleness guard, image downscaling, Python grep build-dir skip, `AsyncCompositeBackend`) and **`subagents-pydantic-ai>=0.2.8`** (dropping the local `RunUsage` shim); added `pillow` to the `cli` extra for image downscaling.
- **Documentation rewritten in the FastAPI tutorial style** and restructured around FastAPI's Learn → Advanced → Reference model. New step-by-step **Tutorial — User Guide** (`docs/learn/`, 13 pages), a rewritten **Advanced User Guide** (`docs/advanced/`, 19 pages including new goal-loop and monitor pages), a full **CLI guide** (`docs/cli/`, 6 pages), an **Applications** section covering the reference apps (`docs/apps/`: DeepResearch, ACP/Zed, Harbor), and new API-reference pages (monitoring, goal, tool-search, message-queue). Concept/example/landing pages carry the same voice; the real Pydantic logo is used in the navbar/favicon; pages superseded by the tutorial were retired and cross-links updated. `mkdocs build --strict` passes clean. `CLAUDE.md` reflects the `features/` layout.
- **Reorganized features into vertical-slice packages under `pydantic_deep/features/`.** Each feature now lives in one folder (`capability.py` + `toolset.py` + `service.py`/`types.py`) instead of being smeared across `toolsets/` and `capabilities/`. Top-level imports (`from pydantic_deep import …`) are unchanged. The old deep import paths remain as deprecation shims (emitting `DeprecationWarning`) and will be removed in the next minor release.
  - `memory`: `pydantic_deep.toolsets.memory` / `pydantic_deep.capabilities.memory` → `pydantic_deep.features.memory`.
  - `context`: `pydantic_deep.toolsets.context` / `pydantic_deep.capabilities.context` → `pydantic_deep.features.context`.
  - `browser`: `pydantic_deep.toolsets.browser` / `pydantic_deep.capabilities.browser` → `pydantic_deep.features.browser`.
  - `eviction`: `pydantic_deep.processors.eviction` → `pydantic_deep.features.eviction`.
  - `patch`: `pydantic_deep.processors.patch` → `pydantic_deep.features.patch`.
  - `history_archive`: `pydantic_deep.processors.history_archive` → `pydantic_deep.features.history_archive`.
  - `stuck_loop`: `pydantic_deep.capabilities.stuck_loop` → `pydantic_deep.features.stuck_loop`.
  - `periodic_reminder`: `pydantic_deep.capabilities.periodic_reminder` → `pydantic_deep.features.periodic_reminder`.
  - `hooks`: `pydantic_deep.capabilities.hooks` → `pydantic_deep.features.hooks`.
  - `message_queue`: `pydantic_deep.capabilities.message_queue` → `pydantic_deep.features.message_queue`.
  - `teams`: `pydantic_deep.toolsets.teams` → `pydantic_deep.features.teams`.
  - `plan`: `pydantic_deep.toolsets.plan` → `pydantic_deep.features.plan`.
  - `checkpointing`: `pydantic_deep.toolsets.checkpointing` → `pydantic_deep.features.checkpointing`.
  - `improve`: `pydantic_deep.improve` / `pydantic_deep.toolsets.improve` → `pydantic_deep.features.improve`.
  - `skills`: `pydantic_deep.toolsets.skills` / `pydantic_deep.capabilities.skills` → `pydantic_deep.features.skills`.
  - `forking`: `pydantic_deep.toolsets.forking` / `pydantic_deep.capabilities.forking` → `pydantic_deep.features.forking`.
  - `liteparse`: `pydantic_deep.toolsets.liteparse` → `pydantic_deep.features.liteparse`.

### Fixed

- **Subagents crashing with `'RunUsage' object is not callable`** under pydantic-ai 2.0 (usage became a property), fixed upstream in `subagents-pydantic-ai` 0.2.8 and re-pinned here.
- **Context-usage warning spammed on every update** — it now warns once per crossing above 90% with hysteresis (re-arms below 85%), instead of on every `ContextUpdated`.
- **`/undo` left the removed turn on screen** — it now removes the turn's widgets too (`MessageList.remove_last_turn`), keeping the transcript in sync with history. `/retry` reuses the same path.
- **Status bar overflow** that ghosted text beside the input.
- Numerous edge cases: forking auto/vote merge and abort deadlocks; skills frontmatter / path containment / reserved words; eviction preview-on-write-failure and collision-safe ids; patch tool-call rebuild preserving `ModelRequest` fields; MCP stdio/stderr screen leaks; dropped uploads; corrupt-archive recovery; and Python warnings leaking onto the TUI.
- CI: docs build (stale `eviction.create_content_preview` reference) and `mypy` errors.

## [0.3.33] - 2026-06-26

### Fixed

- **Agent memory injection now keeps the most recent lines, not the oldest** ([#157](https://github.com/vstorm-co/pydantic-deepagents/issues/157)) (`pydantic_deep/toolsets/memory.py`). `format_memory_prompt` truncated an over-budget `MEMORY.md` by keeping the first `max_lines`, but `write_memory` appends new content to the end of the file, so the newest observations were the first to drop out. Truncation now keeps the recency tail (the dropped-line marker moves above the kept tail). Two additions from the same report: authors can pin a foundational head with a `<!-- deep:pin-end -->` marker (`DEFAULT_PIN_END_MARKER`), which is always injected in full so it survives truncation; and injection can be budgeted in approximate tokens via a new `max_tokens` that takes precedence over `max_lines` (reusing the `NUM_CHARS_PER_TOKEN` heuristic). `AgentMemoryToolset` and `MemoryCapability` gain `max_tokens` / `pin_marker`; subagents accept `extra.memory_max_tokens` / `extra.memory_pin_marker`.
- **Subagent delegation no longer fails with a `read_memory` tool name collision** ([#155](https://github.com/vstorm-co/pydantic-deepagents/issues/155)) (`pydantic_deep/agent.py`). With `include_memory=True` and `include_subagents=True` (both default), the default subagent factory passed `include_memory=True` into each subagent's own `create_deep_agent`, which registered a second `AgentMemoryToolset` ('deep-memory', under the wrong "main" namespace) on top of the one `_inject_subagent_memory_toolset` already injects — a regression since 0.3.30 that made every delegation fail with `AgentMemoryToolset 'deep-memory' defines a tool whose name conflicts ...: 'read_memory'`. The factory no longer creates its own memory toolset; the injected one, correctly namespaced to the subagent, is the single source.

## [0.3.32] - 2026-06-26

### Changed

- **Migrated to pydantic-ai 2.0.** pydantic-ai 2.0 removed the deprecated `Agent(history_processors=...)` parameter and the `pydantic_ai.usage.Usage` class. User-supplied `history_processors` are now wrapped in `ProcessHistory` capabilities and registered via the capabilities API (`pydantic_deep/agent.py`); the `history_processors=` argument to `create_deep_agent()` is unchanged. The CLI headless runner now uses `RunUsage` instead of `Usage` (`apps/cli/run.py`); its JSON output keys (`request_tokens` / `response_tokens`) are unchanged, sourced from `RunUsage.input_tokens` / `output_tokens`.
- **`WebSearch` / `WebFetch` keep their local fallback under pydantic-ai 2.0** (`pydantic_deep/agent.py`). 2.0 changed the capability default to `local=None` (native-only), so a model whose provider lacks a native `WebFetchTool` now errored (`Native tool(s) ['WebFetchTool'] not supported by this model`) instead of falling back. We now pass `WebSearch(local="duckduckgo")` and `WebFetch(local=True)` to restore the pre-2.0 behaviour: the native tool is used when the provider supports it, and the local fallback kicks in otherwise.

### Fixed

- **`PatchToolCallsCapability` no longer drops a trailing `ModelRequest` left empty after stripping orphaned tool results** (`pydantic_deep/processors/patch.py`). Phase 2 removes `ToolReturnPart`s that have no matching `ToolCallPart`, then discarded any `ModelRequest` left with no parts. When that request was the **last** message — a resumed or interrupted history whose tail holds only orphaned results — dropping it left the history ending on a `ModelResponse`, which trips pydantic-ai's `Processed history must end with a `ModelRequest`` validation (`UserError`). This is the same class of bug as the upstream `LimitWarnerProcessor` fix. The stripped request is now kept as an empty `ModelRequest` structural placeholder (the shape pydantic-ai uses when resuming without a prompt) when it is the final message; interior empty requests are still dropped.

### Dependencies

- **Bumped `pydantic-ai-slim` to `>=2.0.0`** (`pyproject.toml`). pydantic-deep now targets the pydantic-ai 2.0 line (see *Changed* above). Consumers still pinned to pydantic-ai 1.x must stay on pydantic-deep 0.3.31.
- **Bumped `summarization-pydantic-ai` to `>=0.1.10`** (`pyproject.toml`). Picks up two history-rewriting fixes of the same trailing-`ModelRequest` class: `LimitWarnerProcessor` no longer drops the already-empty trailing `ModelRequest` that pydantic-ai appends when resuming without a prompt, and `SlidingWindowProcessor` no longer trims history down to empty on a zero `keep`.

## [0.3.31] - 2026-06-22

### Changed

- **Migrated all backend I/O from the sync `BackendProtocol` to the async `AsyncBackendProtocol`** ([#142](https://github.com/vstorm-co/pydantic-deepagents/pull/142), closes [#129](https://github.com/vstorm-co/pydantic-deepagents/issues/129)). Backends implemented over the network (HTTP/gRPC/etc.) can now be natively async instead of being forced through `asyncio.run(...)`. `DeepAgentDeps.__post_init__` auto-wraps any sync backend with `ensure_async()` (from `pydantic-ai-backend`), so **existing sync backends like `StateBackend` / `LocalBackend` keep working unchanged** — consumer code can always `await backend.X()`. Hooks, forking internals, skills discovery, context files, memory, eviction, and the examples were all updated to the async API (`pydantic_deep/deps.py`, `capabilities/hooks.py`, `toolsets/forking/*`, `toolsets/skills/backend.py`, `toolsets/context.py`, `toolsets/memory.py`, `toolsets/liteparse.py`, `processors/eviction.py`).

  **Breaking changes for code that touched the backend directly:**
  - `DeepAgentDeps.upload_file()` and `upload_files()` are now `async` — callers must `await` them.
  - `ctx.deps.backend` is now an `AsyncBackendProtocol` (a wrapping `AsyncBackendAdapter` for sync backends). Direct calls like `ctx.deps.backend.read_bytes(path)` must become `await ctx.deps.backend.read_bytes(path)`. Code that needs the raw sync backend (e.g. backend-specific attributes, `BranchOverlay`'s synchronous overlay ops) should use the new `unwrap_backend()` helper in `pydantic_deep/deps.py`.
  - `load_memory()` and related memory helpers in `pydantic_deep/toolsets/memory.py` are now `async`.

### Dependencies

- **Bumped vstorm-co packages** ([#156](https://github.com/vstorm-co/pydantic-deepagents/pull/156), Renovate) (`pyproject.toml`). `pydantic-ai-backend` to `>=0.2.14` (async backend adapter support: `ensure_async`, `AsyncBackendProtocol` / `AsyncSandboxProtocol`, `AsyncBackendAdapter` / `AsyncSandboxAdapter` — the foundation the async migration above is built on), and `summarization-pydantic-ai` to `>=0.1.9` (`ContextManagerCapability.after_tool_execute` no longer stringifies a `ToolReturn`, so large binary tool results are no longer inlined and rejected by the provider).

## [0.3.30] - 2026-06-18

### Fixed

- **`subagent_extra_toolsets` now reaches immediate (depth-1) subagents** ([#141](https://github.com/vstorm-co/pydantic-deepagents/issues/141)) (`pydantic_deep/agent.py`). The parameter was forwarded into the subagent factory's `create_deep_agent()` call, but the factory builds subagents with `include_subagents=False`, so the toolsets were only ever consumed by nested sub-agents (depth 2+) — the immediate subagent never received them. The extra toolsets are now injected into each subagent's config `toolsets` (new `_inject_subagent_extra_toolsets()`, mirroring the context/memory injection helpers) and the factory reads them back via `extra_toolsets=`, so depth-1 subagents get the toolsets as intended.
- **`write_todos` now persists to `deps.todos`** ([#148](https://github.com/vstorm-co/pydantic-deepagents/issues/148)) (`pydantic_deep/agent.py`). The todo tools are `tool_plain`, so the shared `_DepsTodoProxy` is their only channel to the per-run deps. The proxy was bound in `dynamic_instructions`, which pydantic-ai resolves in a throwaway `contextvars` context, so `write_todos` saw no deps and silently dropped every write (`read_todos` returned "No todos", `deps.todos` stayed `[]`). A new `_TodoProxyBinder` capability re-binds the proxy in `before_tool_execute` — in the tool's own context — so writes land while keeping per-run isolation.
- **`--verbose` mode now runs tool calls** ([#147](https://github.com/vstorm-co/pydantic-deepagents/issues/147)) (`apps/cli/run.py`). `_run_verbose` broke out of the model-request stream on `FinalResultEvent` and abandoned it mid-flight, truncating the model turn so the agent never reached its tool-call nodes — `--verbose` printed a summary but applied no fixes. The stream now iterates to natural completion, matching the non-verbose path, so tool calls execute.

### Changed

- **Bumped vstorm-co packages** ([#151](https://github.com/vstorm-co/pydantic-deepagents/pull/151), Renovate) (`pyproject.toml`). `pydantic-ai-backend` to `>=0.2.13` (Windows CRLF doubling fix in `LocalBackend.write()` / `edit()`), `pydantic-ai-todo` to `>=0.2.6` (`asyncpg` is now an optional `[postgres]` extra), and `summarization-pydantic-ai` to `>=0.1.8` (`ContextManagerCapability` compress hooks now reflect what actually happened).

## [0.3.29] - 2026-06-12

### Added

- **Goal-completion loop — `/goal` (framework engine + CLI command)** (new `pydantic_deep/goal.py`, `apps/cli/goal.py`, wired into `apps/cli/screens/chat.py`). Set a completion condition and the agent keeps working toward it across turns without per-turn prompting — a port of Claude Code's [`/goal`](https://code.claude.com/docs/en/goal).
  - **Framework.** `pydantic_deep/goal.py` is a provider/UI-agnostic engine. `GoalEvaluator` asks a small, fast model (default Haiku, matching the periodic-reminder tier) whether the condition is satisfied — judging *only* from the conversation transcript, never running tools, exactly like Claude Code. It returns a `GoalEvaluation(met, reason, …token counts)`. `GoalState` holds session-scoped state (condition, turns, achieved, last reason, cumulative evaluator tokens) with a hard `max_turns` safety cap so a vague condition can't loop forever. Pure helpers — `parse_goal_command` (set / clear / status, with `clear`/`stop`/`off`/`reset`/`none`/`cancel` aliases and the 4,000-char condition cap), `parse_verdict` (lenient YES/NO parsing that defaults to *not met* on ambiguity so the loop never declares premature success), `build_goal_transcript` (compact transcript that keeps assistant text and tool results as the evidence the evaluator judges), `goal_continue_directive`, and `format_goal_status` — let any CLI or headless driver wire the behaviour. All exported from the top-level package.
  - **CLI.** New `/goal <condition>` command sets a goal and kicks the first turn immediately (the condition is the directive); `/goal` with no argument opens an input modal to type a condition (or, when a goal is already active, shows its status — condition, elapsed time, turns evaluated, evaluator tokens, latest reason); `/goal clear` (and aliases) drops it early, as does `/clear`. After each turn the stream worker evaluates the active goal off the saved history: when met it clears with a `✓ Goal achieved` toast, otherwise the evaluator's reason is surfaced and fed into a fresh turn. A `◎ goal` indicator shows on the status bar while a goal is active. Listed in `/help` and the command picker.

### Changed

- **Bumped vstorm-co packages** ([#145](https://github.com/vstorm-co/pydantic-deepagents/pull/145), Renovate) (`pyproject.toml`). `pydantic-ai-todo` to `>=0.2.5` — adds the `update_todo_statuses` batch tool and defaults `TodoItem.status` to `"pending"` (one fewer validation round-trip on plan creation). `pydantic-ai-backend` to `>=0.2.12` (`console` + `docker` extras).

## [0.3.28] - 2026-06-07

### Changed

- **Bumped `pydantic-ai-backend` to `>=0.2.11`** (`pyproject.toml`, `console` + `docker` extras). 0.2.11 adds `document_support` / `max_document_bytes` to `create_console_toolset`, so `read_file` can return PDFs as `BinaryContent(application/pdf)` for document-capable models ([pydantic-ai-backend#48](https://github.com/vstorm-co/pydantic-ai-backend/pull/48)) instead of the empty string the binary-unaware text path produced.

## [0.3.27] - 2026-06-07

### Added

- **`subagent_usage_limits` on `create_deep_agent()`** ([subagents-pydantic-ai#43](https://github.com/vstorm-co/subagents-pydantic-ai/issues/43)) (`pydantic_deep/agent.py`). Deep-agent construction now forwards delegated-subagent usage limits straight into `create_subagent_toolset(usage_limits=...)`, so downstream callers no longer have to disable `include_subagents`, build the subagent toolset by hand, and re-wire the delegation prompt + task manager just to raise a specialist's `request_limit`. Accepts either a static `UsageLimits` (same budget for every delegated `agent.run(...)`, including retries) or a `UsageLimitsFactory` (`(ctx, config) -> UsageLimits | None`) that resolves per-specialist limits from the selected `SubAgentConfig` — e.g. a small budget for lightweight specialists and a larger one for heavy research/execution agents. Defaults to `None` (pydantic-ai's own default limit stays in place); only applies when `include_subagents=True`. The underlying capability already existed in `subagents-pydantic-ai`; this exposes it through the normal public deep-agent API.

## [0.3.26] - 2026-06-07

### Fixed

- **Memory tools now surface backend write and permission failures** ([#135](https://github.com/vstorm-co/pydantic-deepagents/issues/135)) (`pydantic_deep/toolsets/memory.py`). `AgentMemoryToolset` could report a successful persistent-memory write even when the backend rejected it, and could turn a *denied* memory read into the same `No memory saved yet.` result as a genuinely empty file — making a misconfigured memory directory (e.g. one outside the backend's `allowed_directories`) look like normal empty memory, with traces showing only successful tool calls.
  - **Write path:** `write_memory` and `update_memory` now inspect `WriteResult.error` and return an explicit `Error: failed to save memory ...` instead of a phantom `Memory updated (...)`.
  - **Read path:** new `MemoryAccessError` (exported from the package root) lets `load_memory` distinguish *denied* from *missing/empty*. Because `backend.read_bytes()` collapses missing, empty, and denied paths to empty bytes, `load_memory` now disambiguates via `backend.read()` (which reports access errors as `Error: ...` but a missing file as `... not found`), raising `MemoryAccessError` only on a real access failure. `read_memory`/`update_memory` surface it as an error string; `get_instructions` swallows it (prompt injection must not abort a run). Genuinely missing memory still returns `No memory saved yet.`.

## [0.3.25] - 2026-06-07

### Fixed

- **Approved shell commands could hang forever after the first attempt failed** ([#136](https://github.com/vstorm-co/pydantic-deepagents/issues/136)) (`apps/cli/screens/chat.py`). When `execute` requires approval, the TUI handled exactly **one** round of `DeferredToolRequests`. But the model frequently issues a follow-up command in the same turn when the first one fails — most visibly on Windows, where `rm -rf` errors (`'rm' is not recognized`) and the agent immediately retries with `rd`/`rmdir`. That retry is a *second* approval round, which the single-pass resume code silently dropped: the follow-up tool call stayed deferred-but-unsurfaced and its spinner spun indefinitely (reporters saw 460–693s). The deferred-approval resume is now a `while` loop that surfaces every subsequent approval round until the run no longer ends on a `DeferredToolRequests`, so each retried command is approved and actually executes. Not Windows-specific in cause (the subprocess path and Textual's event loop are fine); Windows just reliably triggers the multi-round retry that exposed it.
- **Project-local `.env` was shadowed by the global `~/.pydantic-deep/.env`** (`apps/cli/main.py`). The startup dotenv loads ran global-first with the project `./.env` last at `override=False`, so a key already set by the global file (e.g. a stale `OPENROUTER_API_KEY`) could never be corrected by the project's own working value — surfacing as a `401 "User not found"` from OpenRouter despite a valid project key. Loads are now ordered most-specific-first (all `override=False`): project files win over the global fallback, while real shell env vars still take precedence over every dotenv file.

## [0.3.24] - 2026-06-01

### Fixed

- **Branch cost no longer drops off freshly mounted fork-tab chips** (`apps/cli/widgets/fork_tabs.py`). `ForkTabsWidget.watch_statuses` mounts chips asynchronously (`await self.mount(...)`), so when the poll loop sets `statuses` then `branch_costs` in the same tick, `watch_branch_costs`'s single `call_after_refresh` pass could fire before a chip's mount completed and the `$x.xx` cost never landed — surfacing as a flaky full-suite test failure. Costs are now re-applied as a guaranteed final step at the end of `watch_statuses`, once the chips are actually mounted, closing the race deterministically.

## [0.3.23] - 2026-06-01

### Added

- **MCP (Model Context Protocol) client support — framework + CLI** (new `pydantic_deep/mcp/`, `apps/cli/mcp_store.py`, `apps/cli/modals/mcp_view.py`). Connect agents to MCP servers (GitHub, Figma, Context7, DeepWiki, or any custom server) with first-class auth handling.
  - **Framework.** `MCPServerConfig` / `MCPAuth` declaratively describe a server (stdio or HTTP/SSE transport) and how to authenticate — bearer/header injection, a subprocess env var, or interactive **OAuth** (`kind="oauth"`, for hosted servers like Figma's) — decoupled from any secret store. `MCPRegistry` manages configs and builds connected pydantic-ai `MCPToolset`s through a pluggable secret resolver; `build_mcp_server()` resolves the secret and injects it (or wires the OAuth flow); `probe_mcp_server()` connects and lists tools for a health check. `builtin_mcp_servers()` ships curated definitions: GitHub (hosted, PAT), **Figma (hosted `https://mcp.figma.com/mcp`, OAuth)**, `figma-local` (Dev Mode desktop server), Context7, DeepWiki. `create_deep_agent(mcp_servers=…)` attaches them. All exported from the top-level package; gated behind the optional `mcp` extra (`pip install 'pydantic-deep[mcp]'`) with a clear `MCPNotInstalledError` when absent.
  - **Import from Claude Code.** `parse_mcp_servers()` reads the standard `mcpServers` JSON shape (Claude Code / Claude Desktop / Cursor / MCP spec — stdio `command`/`args`/`env`, HTTP/SSE `type`/`url`/`headers`, with `${VAR}` / `${VAR:-default}` expansion). The CLI's `i` action in `/mcp` (`import_claude_code_servers`) merges Claude Code's three scopes with its precedence (local > project > user) from `.mcp.json` + `~/.claude.json`, carrying over tokens so imported servers work immediately. (File-configured servers only — claude.ai account connectors aren't stored locally and aren't imported.)
  - **CLI.** New interactive `/mcp` command: list configured servers with live status (enabled / disabled / needs-login), enable/disable, **log in** / **log out** (token stored in / revoked from the git-ignored keystore), **test** the connection (result shown inline per server, so repeated tests don't stack toasts), **add/remove** custom servers (custom commands parsed with `shlex`; built-in names protected), and **import** servers from Claude Code. User servers + per-builtin enabled-state persist to `.pydantic-deep/mcp.json`; tokens live in `keys.toml`. Enabled + authenticated servers are wired into the agent automatically (and on `/mcp` close via reconfigure).

- **CLI/TUI presentation polish — tool-call rendering, clipboard images, and turn feedback** (`apps/cli/`). A pass over how the terminal app *looks and feels*, driven by `apps/cli/PRODUCT_REPORT.md`:
  - **Clipboard image paste** — `/paste` and `Ctrl+V` attach a screenshot from the system clipboard to the next prompt as multimodal `BinaryContent`. New `apps/cli/clipboard_image.py` with a strategy chain (Pillow → `pngpaste` → macOS `osascript`, zero-dependency on macOS). `Ctrl+V` is handled in `PromptInput.on_key` (the focused `Input` consumed the key before app-level bindings could fire). `@image.png` file references now attach as images instead of being inlined as text.
  - **Real `+/-` diffs for edits** — `edit_file` renders a proper `difflib` diff (interleaved removed/added lines, `... N more` tail) and the header shows a `+N -M` badge. `write_file` now shows a true `-`/`+` diff when overwriting an existing file: the pre-write content is captured at `FunctionToolCallEvent` (which fires in the validation pass *before* the tool runs, so the read is race-free) and diffed against the new content; new files still render as additions. `execute` now displays the **full command** (`$ …`) plus output instead of truncating to 60 chars.
  - **Tool icons** — per-tool header glyphs (📖 read, ✏️ edit, ⚡ execute, 🔍 grep, 🤖 task, …) for faster visual scanning.
  - **Interrupt feedback** — `Esc`/`Ctrl+C` immediately flag in-flight tool calls as `⏹ stopping…` while cancellation propagates (subprocess kill is already handled by the backend's process-group `killpg`).
  - **Subagents side panel** — idle/configured subagents stay visible (dimmed) while one runs, instead of disappearing; live status is merged into the known-agent baseline by name.
  - **Multi-tool approval clarity** — the approval modal shows `(1 of N)` when several tool calls await confirmation in one turn.
  - **Turn summary toast** — after a turn, a compact `✓ 2 edits · 1 command · 3 reads · 1.2s` summary.
  - **`/screenshot`** — export the current TUI as an SVG for docs/marketing assets.
- **Live Run Forking — split an in-flight `agent.run()` into N parallel branches** ([#123](https://github.com/vstorm-co/pydantic-deepagents/pull/123), closes epic #101). Opt-in via `forking=True` on `create_deep_agent()`. Branches share history up to the fork point, each diverging with its own steer message; a coordinator resolves the fork via one of four acceptance modes (`manual`, `auto`, `auto_with_fallback` default, `vote`), and the winning branch's history is adopted as the parent run's continuation.
  - **Core (`LiveForkCapability`)** — `ForkCoordinator` (per-parent-run via `for_run()`, serialises mutations through an `asyncio.Lock`, captures partial history on cancellation); `BranchOverlay` copy-on-write backend (reads fall through to parent, writes land in an isolated overlay, `changes()` exposes the temporal `list[FileChange]` spine); `clone_for_branch` per-`BranchIsolation` policy; `InMemoryForkStateStore` / `ForkStateStore` protocol.
  - **Diff & merge** — `BranchDiffReport` builder with agreement classification (`unanimous_change`, `split`, `unique`); `ForkMaterializer` real-time disk mirror under `.pydantic-deep/forks/{fork_id}/`; `EditorDetector` (PyCharm / VS Code / custom / TUI fallback); `JudgeAgent` autonomous merge judge with structured `JudgeVerdict` on minimal context; `compute_confidence` (`quality_spread×0.4 + test_pass_ratio×0.4 + internal_consistency×0.2`, capped at 0.65 without a test signal).
  - **Test-runner hook** — `LiveForkCapability(test_command=…, test_timeout_s=…)` runs a shell command against each branch's materialised snapshot via `asyncio.create_subprocess_exec` (cross-platform, no shell dependency); exit code → `test_pass_ratio`; snapshot I/O on a thread executor; `UV_NO_SYNC=1` avoids dependency re-resolution in branch snapshots.
  - **Agent tools** — `fork_run`, `inspect_branches`, `merge_or_select`, `terminate_branch`, `diff_branches`, `fork_cost`.
  - **CLI** — `/fork`, `/merge`, `/fork-config`, `/fork diff [<path>]`, `/fork-branches N`, `/fork-budget`, `/fork-model` (persisted to `.pydantic-deep/config.toml`); `CLIForkSession` bridge with stash-and-adopt reconciliation of agent-initiated coordinators; live per-branch streaming panels (`BranchPanelWidget`, `ForkTabsWidget`, `ForkOverviewWidget`, `ForkBadgeWidget`), `JudgeLoadingScreen`, `MergeAcceptanceWidget`, `BranchApprovalModal` tool-approval gate; `>>label msg` per-branch steering; interactive follow-up chat on a focused `done` branch.
  - **Docs** — `docs/capabilities/live-fork.md` full reference.

- **Automatic fallback-model retry on primary-model failure** ([#125](https://github.com/vstorm-co/pydantic-deepagents/pull/125), closes [#112](https://github.com/vstorm-co/pydantic-deepagents/issues/112)) — new `fallback_model: str | Model | list[str | Model] | None = None` parameter on `create_deep_agent()`, wrapping the primary in pydantic-ai's `FallbackModel` (single model or ordered chain). Fallback fires on `ModelAPIError` but **not** on auth errors (messages containing `401`/`403`/`unauthorized`/`forbidden`, case-insensitive), which propagate instead of silently hopping to a model that would fail identically. New `HookEvent.MODEL_FALLBACK_TRIGGERED` + `HooksCapability.dispatch_model_fallback()` for observability (payload: `primary`, `fallback`, original exception). TUI: `/model` chains into a new `FallbackPickerModal` (provider/key-status indicators + "No fallback"), persisted to config; `CliConfig.fallback_model`. New `docs/advanced/fallback-models.md`.

- **Security hook preset — `default_security_hook()`** ([#127](https://github.com/vstorm-co/pydantic-deepagents/pull/127), closes [#110](https://github.com/vstorm-co/pydantic-deepagents/issues/110)) — batteries-included `list[Hook]` preset that blocks common tool-misuse patterns (destructive shell commands, path-traversal writes, sensitive-file reads) and redacts obvious secrets from tool output. Drop-in via `create_deep_agent(hooks=default_security_hook())`. Three `DEFAULT_*` regex tuples for blocked commands, sensitive read paths, and secret-token shapes; supports custom-pattern overrides and shadow/warn mode. Exported from the top-level package. New "Built-in Security Preset" docs section and runnable `examples/security_gate/` demo.

- **Three new built-in output styles** ([#126](https://github.com/vstorm-co/pydantic-deepagents/pull/126), closes [#111](https://github.com/vstorm-co/pydantic-deepagents/issues/111)) — `markdown`, `json-only`, and `bullet`, covering machine-readable / pipe-friendly response shapes the conversational styles (concise / explanatory / formal / conversational) don't address. Registered in `BUILTIN_STYLES`; docs gain usage examples and a `json-only`-vs-`output_type` comparison (the style is a prompt directive only — no validation guarantees, by design).

### Changed

- **Bumped core companion dependencies** to their latest releases: `pydantic-ai-backend` 0.2.9 → 0.2.10, `pydantic-ai-todo` 0.2.3 → 0.2.4, `pydantic-ai-shields` 0.3.3 → 0.3.4, `subagents-pydantic-ai` 0.2.5 → 0.2.6, `summarization-pydantic-ai` 0.1.5 → 0.1.6 (minimums raised in `pyproject.toml`, `uv.lock` updated). Full suite + type checks green against the new versions.
- **Docstring and import hygiene (internal; no behavior change).** Converted reStructuredText-style double-backtick inline code in docstrings, comments, and docs to single-backtick Markdown, so it renders correctly under the mkdocstrings Markdown handler. Hoisted function-local imports to module top where safe — 8 in `pydantic_deep/` and 101 across the bundled `apps/` — while leaving the CLI's intentionally-lazy entrypoint imports (which keep `--help`/`--version` fast and stay patchable in tests), conditional imports, optional-dependency `try` imports, and circular-import-avoidance imports in place.

### Fixed

- **Keystore could corrupt `keys.toml` and silently wipe every stored key.** `save_key`/`remove_key` wrote values via naive interpolation (`KEY = "{v}"`), so a key/token containing a `"`, `\`, or newline produced invalid TOML; the next read then failed to parse and every helper swallowed the error and returned `{}` — losing all stored provider keys and MCP tokens. Values are now serialized with `json.dumps` (a valid TOML basic string), so arbitrary tokens round-trip safely. Surfaced by the MCP login flow, which feeds user-pasted secrets into the keystore.
- **CLI write_file diff capture mutated the live message history.** The pre-write content stashed for the `write_file` `-`/`+` diff was written onto the parsed tool-call args dict, which (for dict-delivering providers) aliased the persisted `ToolCallPart.args` — bloating `messages.json` with the full old file and re-sending it to the model on the next turn. The UI now works on a copy, and the read is bounded (skips files > 256 KB and sandbox error sentinels).
- **Hosted-Figma (and any OAuth) MCP server now actually connects from the agent, not just the test.** OAuth tokens were stored in-memory per FastMCP client, so authorizing via `/mcp` test didn't carry to the agent (a separate client) and was lost on restart — the agent kept reporting Figma as unavailable. `build_mcp_server` / `MCPRegistry` now accept an `oauth_token_storage` (`AsyncKeyValue`) backend; the CLI (`mcp_oauth_storage()`) wires a disk-backed store at `~/.pydantic-deep/mcp-oauth`, keyed by server URL, so a single browser sign-in is shared between the connection test and the agent and persists across restarts. Requires the `py-key-value-aio[disk]` dependency added to the `mcp` extra. `MCPAuth` also gained a `client_name` field — Figma's hosted server allowlists OAuth client names during its beta (generic clients get `403 Registration failed`), so it's surfaced for users who know an allowlisted name; the `figma` built-in's description now points to `figma-local` (Dev Mode, no OAuth) as the reliable path meanwhile.
- **An enabled-but-unreachable MCP server no longer bricks the whole agent run.** Previously, attaching a configured MCP server whose endpoint wasn't reachable (e.g. the `figma` Dev Mode server when the desktop app is closed) made *every* `agent.run()` fail with `RuntimeError: Client failed to connect`. `MCPRegistry.build_active()` now wraps each server via `make_resilient()`: a server that can't connect/list logs a warning once and contributes zero tools for that run (retried next run), while every other toolset and the run itself proceed normally. Reachable servers are unaffected. The wrapper accepts an `on_degraded(name, reason)` callback (fired once per server); the CLI uses it to warn the user, after a run, *which* enabled servers were unreachable — so a configured-but-down server no longer silently provides no tools. The `/mcp` status label is now **enabled** (not "ready"), since enabling a server doesn't guarantee reachability — that's confirmed by the `t` test action.
- **File-descriptor leak in the macOS clipboard image grab** — `tempfile.mkstemp` returned a fd that was never closed; every `Ctrl+V`/`/paste` via the `osascript` fallback leaked one. Now closed immediately.
- **Multimodal prompts no longer send an empty text block** alongside pasted images (providers reject empty text content), and pending images are preserved if no agent is configured yet instead of being silently dropped.
- **`upload_files` aborted the whole batch on any non-`RuntimeError` failure, contradicting its own docstring** (`pydantic_deep/deps.py`). The per-file loop wrapped `upload_file` in `except RuntimeError`, but `upload_file` only raises `RuntimeError` from the (`# pragma: no cover`) backend-write-error path while also calling `chardet.detect`, `content.decode`, and `mimetypes.guess_type` — and a backend whose `write` raises directly rather than returning `WriteResult.error` would surface a different exception type. Any such failure propagated and aborted the entire batch, breaking the documented guarantee that "failures on one file don't affect others." The loop now catches `Exception` and continues, so one bad file is skipped and the remaining files still upload.

- **`LLMReminderGenerator` silently swallowed every LLM-summary failure with no logging** (`pydantic_deep/capabilities/periodic_reminder.py`). `__call__` wrapped the entire LLM path - agent construction, transcript build, and `self._agent.run()` - in a bare `except Exception:` that fell back to the zero-cost default reminder. Real misconfiguration (auth errors, budget/cost-budget errors, programming errors) was therefore converted into a generic reminder with no trace, hiding the failure from the operator. The fallback still fires for resilience, but the swallowed exception is now logged via `logger.warning(..., exc_info=True)` before returning the default, so failures are observable.

- **`BrowserCapability` re-attempted a known-failing browser launch on every run instead of staying disabled until restart** (`pydantic_deep/capabilities/browser.py`). `_state` is created once in `__post_init__` and shared across every `agent.run()`, but the `wrap_run` `finally` block reset `self._state.launch_error = None` at the end of each run. Once Chromium failed to launch, the user-facing message instructs the user to "restart the agent to enable browser tools" and `prepare_tools` hides the browser tools while `launch_error` is set — yet because the error was wiped after the run, the next run re-exposed the tools and re-ran the still-failing launch/auto-install, repeatedly paying the install cost. The `finally` block no longer clears `launch_error`, so a failed launch now persists across runs and the tools stay hidden until the process is restarted (which recreates `_state` via `__post_init__`), matching the message.

- **`apply_changes` silently dropped proposed changes with an unrecognized `change_type`** (`pydantic_deep/improve/analyzer.py`). The method branched only on `create`/`append`/`update` with no fallback, and `change_type` flowed in from LLM structured output as an unconstrained `str` (`_ProposedChangeModel`). Any other value (e.g. `modify`, `replace`, or a typo) was swallowed: no file written, yet the change was neither recorded as failed nor reflected in the returned `modified` list, so the caller believed it had been handled. `change_type` is now constrained to a shared `ChangeType = Literal["append", "update", "create"]` on both the `_ProposedChangeModel` structured-output schema (so the model's output is validated and bad values are rejected up front) and the `ProposedChange` dataclass; `apply_changes` also gains an `else` branch that raises `ValueError` for any unknown type as defense-in-depth.

- **`analyze()` collapsed all extraction failures into a single `last_error`, masking distinct failures** (`pydantic_deep/improve/analyzer.py`). The per-session extraction loop caught every exception and overwrote `last_error = exc` while incrementing `failed_sessions`, so when multiple sessions failed with different errors all but the last were silently discarded - the report claimed N failures but exposed only one, not necessarily a representative one, making diagnostics misleading (and genuine bugs masked as bare "session failed" counts). Failures are now accumulated into a new `ImprovementReport.extraction_errors: list[tuple[str, Exception]]` field, pairing each failing session id with its error; `last_error` is preserved (set to the final recorded failure) for backward compatibility. The CLI `/improve` warning now enumerates every failure (`session_id: error; ...`) instead of only the last.

- **`_load_tool_log` discarded the entire session tool log when any arg value was non-string** (`pydantic_deep/improve/extractor.py`). The compact arg summary built each entry as `f"{k}={v[:80]}"`, slicing the raw value. Tool-call args routinely carry non-string values (ints, bools, lists, dicts, `None`), and `v[:80]` raises `TypeError` for all of them. Because the whole loop is wrapped in `try/except Exception` that returns `""`, a single non-string arg silently dropped the entire `tool_log.jsonl` trace for that session — losing the diagnostic data the extraction agent relies on. The value is now stringified before slicing (`str(v)[:80]`), so mixed-type args are formatted instead of crashing.

- **`SessionInsights.message_count` / `tool_calls_count` were LLM-reported instead of computed from the loaded messages** (`pydantic_deep/improve/extractor.py`). `SessionExtractor.extract()` already loads the full `messages` list, yet both counts were taken from the extraction model's JSON output (defaulting to `0`), and the multi-chunk merge prompt even asked the model to sum chunk counts "minus an overlap estimate" — pure guesswork. LLMs are unreliable at counting, so these values were frequently wrong or zero for any populated session. `extract()` now computes the exact values directly — `message_count = len(messages)` and `tool_calls_count` via a new `_count_tool_calls` helper that counts `part_kind == "tool-call"` parts — and overrides the model-reported counts on the returned `SessionInsights` for both the single-chunk and multi-chunk paths.

- **Clearing the temperature field in the settings screen never reset it to the provider default** (`apps/cli/screens/settings.py`). `_save_config` only appended `temperature` to the save list when the input was non-empty, so emptying the field to revert to the provider default was skipped and the previously persisted value remained in `config.toml` — the setting could never be cleared from the UI. Temperature is now always persisted; an empty string is coerced to `None` by `set_config_value` / `_coerce_value` (temperature is an optional float field), correctly resetting it to the default.

- **Clearing the thinking-effort field in the settings screen never reset it to the default** (`apps/cli/screens/settings.py`, `apps/cli/config.py`). Same pattern as temperature: `_save_config` appended `thinking_effort` only when the input was non-empty, so blanking the field to revert left the prior value in `config.toml` and the UI could never clear a previously set value. `thinking_effort` is now always persisted, and `_coerce_value` coerces a blank string to `None` so `_write_toml` drops the key and `CliConfig`'s `"high"` default applies on the next load. This also prevents a bare `""` from being persisted and passed straight through as the agent's `thinking` value (`agent.py`).

- **Search-modal snippets were injected into Rich markup without escaping** (`apps/cli/modals/search.py`). Message text matched by the search modal was interpolated raw into the option label's `[bold]{role}[/bold]: {snippet}` markup string, so any message containing literal Rich markup (e.g. `[red]`, `[/]`, `[bold]`) was parsed as markup — garbling the rendered snippet or raising a Rich `MarkupError`. The snippet is now passed through `rich.markup.escape()` before embedding, matching how `merge_picker.py` already escapes user-derived text.

- **`/improve` background task was untracked and could be garbage-collected mid-run** (`apps/cli/commands.py`). The improve pipeline was launched via `asyncio.ensure_future(_run_improve())` with no retained reference. Since asyncio holds only a weak reference to tasks, this long-running coroutine (LLM calls across many sessions) could be garbage-collected mid-flight, silently dropping its work and exceptions — exactly the failure mode `DeepApp._spawn_tracked()` was written to prevent and which every other background task already uses. It now launches via `app._spawn_tracked(_run_improve(), label="/improve")`, holding a strong reference until completion and surfacing any failure via `notify`.

- **`every_tool` checkpoints snapshotted stale pre-request history, omitting the tool call and its result** (`pydantic_deep/toolsets/checkpointing.py`). In `every_tool` mode, `CheckpointMiddleware.after_tool_execute` saved `self._latest_messages`, a snapshot captured back in `before_model_request` that predated the `ModelResponse` carrying the `ToolCallPart` (and was empty on the very first tool of a run before any model request). Rewinding to a `tool-*` checkpoint therefore restored a state missing the very tool call/result it claimed to checkpoint. It now snapshots the live `ctx.messages` (which already contains the `ToolCallPart`) and appends a `ToolReturnPart` carrying the result, so the checkpoint accurately includes the tool call and its result. The now-unused `_latest_messages` field was removed.

- **Spec loading crashed on valid `create_deep_agent()` params not modeled in `DeepAgentSpec`** (`pydantic_deep/spec.py`). `DeepAgentSpec` declares `extra="forbid"` and validates merged file/dict `data` directly through it, but eight real, serializable parameters were absent as spec fields — `fallback_model`, `base_prompt`, `max_binary_content`, `include_improve`, `include_liteparse`, `stuck_loop_detection`, `periodic_reminder`, `forking` — so a YAML/JSON spec setting any of them raised a Pydantic `ValidationError` instead of being honored (the override path had a passthrough escape hatch, but file `data` did not). All eight are now modeled with defaults matching `create_deep_agent()`, restoring the docstring's "mirrors `create_deep_agent()` parameters 1:1" contract.

- **`from_spec` only routed non-spec / non-serializable keys to passthrough when supplied as overrides, never from `data`** (`pydantic_deep/spec.py`). The partitioning loop scanned only `**overrides`; the `data` dict (loaded from a spec file or passed by the caller) was merged straight into `DeepAgentSpec(**merged)`. Because of `extra="forbid"`, a non-spec key (e.g. a non-serializable `backend`, `tools`, or callback) or a non-serializable value for a spec field (e.g. `model=TestModel()`) placed in `data` raised a `ValidationError`, even though the identical key passed as an override kwarg was correctly forwarded to passthrough. The partitioning logic is now factored into a helper applied to both `data` and `overrides`, so a parameter behaves the same whether it lives in the spec dict/file or is supplied as an override.

- **Tool calls were invisible after a deferred-tool approval** (`apps/cli/screens/chat.py`). In the post-approval continuation run, the branch that renders call-tool events was nested one level too deep (an `elif` of the model-request node's `if final_found:` rather than a sibling of the node dispatch), making it dead code. Tools invoked after approving or denying a gated call ran but were never shown in the TUI. Re-aligned to the node-dispatch level, matching the main run loop.

- **`_sync_status_from_history` overwrote accurate cost data with a hardcoded Sonnet estimate** (`apps/cli/screens/chat.py`). After every run, `_sync_status_from_history` recomputed cost from message-usage tokens using a hardcoded $3/$15-per-MTok Sonnet heuristic and assigned it to `status.total_cost` / `current_cost`. Because it runs *after* the run completes, it clobbered the precise per-model values already delivered by `CostTracking` (genai-prices) via `on_cost_updated` / `app.total_cost`, producing inconsistent and often wrong figures for non-Sonnet models. The heuristic is now a fallback only — applied solely when no authoritative cost is available (`app.total_cost <= 0`).

- **`/cost` reported hardcoded Sonnet pricing regardless of the active model** (`apps/cli/commands.py`). The `/cost` command always estimated cost as `input × $3 + output × $15` per MTok (Sonnet-class rates) over the message-history token totals, so for cheaper or pricier models (Haiku, Opus, GPT, Gemini) the figure was materially wrong — even though `CostTracking` (genai-prices) already tracks accurate per-model cost into `app.total_cost`. `/cost` now reports the authoritative `app.total_cost` when available and falls back to the Sonnet-rate heuristic (still marked with a `~` prefix) only when no tracked cost exists, mirroring the `_sync_status_from_history` fix.

- **Security preset (`default_security_hook`) hardening and false-positive fixes** (`pydantic_deep/capabilities/hooks.py`):
  - Home-directory wipes `rm -rf ~/`, `rm -rf $HOME/` (and `${HOME}/`) now match. The previous `~(?=\s|$)` / `$HOME` lookaheads conflicted with the trailing `/` boundary, so the canonical "wipe home" forms slipped through. Replaced with per-target optional-trailing-slash boundaries; subdirectory deletes (`rm -rf ~/Downloads/cache`) stay allowed.
  - The `sk-` OpenAI-key redaction no longer shreds ordinary kebab-case text (e.g. `ask-the-user-...`, `task-management-...`). Anchored with `\b` and restricted the legacy body to alphanumerics, so prose containing an `sk-` substring is left intact while real `sk-proj-` / `sk-svcacct-` / `sk-admin-` keys are still fully redacted.
  - `dd ... of=/dev/null` (and other harmless pseudo-devices: `/dev/zero`, `/dev/random`, `/dev/urandom`, `/dev/full`, `/dev/tty`, `/dev/std*`) is no longer blocked as a block-device clobber; real disk targets (`/dev/sda`, `/dev/nvme0n1`) still match.

- **Background hooks were fire-and-forget tasks with no retained reference and could be garbage-collected mid-execution** (`pydantic_deep/capabilities/hooks.py`). All nine background-hook dispatch sites across `HooksCapability` (`before_tool_execute`, `after_tool_execute`, `on_tool_execute_error`, `before_run`, `after_run`, `on_run_error`, `before_model_request`, `after_model_request`, `dispatch_model_fallback`) called `asyncio.create_task(_run_background_hook(...))` without storing the returned `Task`. Since the event loop holds only a weak reference to tasks, a `background=True` hook could be collected before it finished — silently dropping the hook and emitting a "Task was destroyed but it is pending" warning. The dispatch is now funneled through a single `_spawn_background()` helper that retains each task in a `_background_tasks` set and discards it via an `add_done_callback`, so background hooks always run to completion.

- **`POST_TOOL_USE` `modified_result` was silently dropped for non-string tool results, defeating secret redaction** (`pydantic_deep/capabilities/hooks.py`). `HookInput.tool_result` is built via `str(result)` and `HookResult.modified_result` is always a `str`, but `after_tool_execute` only applied a hook's `modified_result` when the *original* result was already a `str` — otherwise it logged at debug and discarded the modification. Any tool returning a structured value (Pydantic model, dict, list, dataclass — common for file/grep tools) therefore bypassed redaction entirely, so secrets embedded in structured tool output were never scrubbed despite `redact_secrets=True`, even though `default_security_hook()` had computed the redacted string. The modification is now applied regardless of the original result type (replacing the structured result with the redacted string), closing the redaction gap.

- **`MessageQueueCapability` mutated the shared request-message list in place instead of reassigning a fresh one** (`pydantic_deep/capabilities/message_queue.py`). `before_model_request` took `msgs = request_context.messages` (a direct reference) and mutated it via `msgs[i] = replace(...)` / `msgs.append(...)`, unlike its sibling `PeriodicReminderCapability`, which builds a new list and reassigns `request_context.messages`. While the framework currently hands the hook a shallow copy, relying on that is fragile and the inconsistency made the contract ambiguous — any future change (or another capability holding a reference to the same list) would have let the in-place edit corrupt conversation state seen by later capabilities and by `message_history` accounting. It now builds a fresh list and reassigns `request_context.messages`, leaving the original list untouched.

- **Steering messages enqueued after a run's final model request were silently lost** (`pydantic_deep/capabilities/message_queue.py`). `run_with_queue` re-entered its loop only when `drain_follow_up()` returned messages, but steering messages are consumed solely by `MessageQueueCapability.before_model_request` *during* a run. If a caller steered the agent after the run's last model request completed and no follow-ups were pending, the loop exited and those steering messages stayed in `MessageQueue._steering` forever — never delivered, never surfaced. The loop now, when there are no follow-ups, drains any leftover steering and delivers it on a fresh turn (instead of dropping it); when follow-ups *are* pending it leaves steering queued so the capability injects it during the follow-up re-run, preserving the interrupt semantics.

- **`PeriodicReminderConfig(every_n_turns=0)` raised `ZeroDivisionError` mid-run instead of failing at construction** (`pydantic_deep/capabilities/periodic_reminder.py`). `every_n_turns` was an unvalidated plain `int` used as a modulo divisor in `_should_fire` (`(turn - first) % cfg.every_n_turns`). A value of `0` therefore raised `ZeroDivisionError` deep inside `before_model_request` on the first turn past `first_after` — aborting the entire `agent.run()` — and a negative value fired nonsensically on every turn. `PeriodicReminderConfig.__post_init__` now validates `every_n_turns >= 1` and raises a clear `ValueError` at construction, so the misconfiguration surfaces immediately instead of crashing a live run.

- **`allowed_domains` allowlist was only enforced on `navigate()`, not on `click` / `execute_js` / `go_back` / `go_forward`** (`pydantic_deep/toolsets/browser.py`, `pydantic_deep/capabilities/browser.py`). Only the `navigate` tool called `_check_allowed_domain`, so the documented "Allowed domains" boundary was trivially bypassable: the model could reach a disallowed domain by clicking a cross-domain link, running `execute_js("location.href='https://evil.com'")`, or stepping through history with `go_back` / `go_forward`. Enforcement is now defense-in-depth: `BrowserCapability` installs a Playwright route guard that aborts top-level navigation requests to disallowed domains at the network layer (covering every navigation path, sub-resource and sub-frame requests left untouched), and each navigating tool re-checks `page.url` after the action, navigating to `about:blank` and returning an error instead of surfacing disallowed page content. Inert when `allowed_domains` is `None` (allow all).

- **Fire-and-forget popup tasks could be garbage-collected and their errors were swallowed** (`pydantic_deep/capabilities/browser.py`). The single-tab popup handler scheduled `popup.close()` and `page.goto()` via two bare `asyncio.ensure_future(...)` calls inside a synchronous Playwright event callback, keeping no reference to either task. Since asyncio holds only weak references, both could be garbage-collected before completion, any exception (e.g. a navigation timeout) went unretrieved as a "Task exception was never retrieved" warning, and the two tasks raced with no ordering guarantee. Close-then-navigate is now sequenced inside a single coroutine (deterministic ordering), the resulting task is held on `_BrowserState._popup_tasks` until it finishes, and a done callback retrieves/logs any exception (ignoring cancellation) before discarding the reference.

- **`AgentTeam.wait_all()` returned immediately and `dissolve()` never stopped running subagents** (`pydantic_deep/toolsets/teams.py`). Both drove off `TeamMemberHandle.task`, which the real flow never sets (it sets `task_id` and delegates to the subagent `TaskManager`), so they were no-ops. `AgentTeam` now carries the `task_manager` and awaits / hard-cancels background subagents by `task_id`, syncing each result/error back onto the handle.

- **`reconfigure_agent` dropped the cost / context / reminder callbacks** (`apps/cli/app.py`, `apps/cli/tui.py`). After `/model` (or any reconfigure) the agent was rebuilt without the status-bar and reminder callbacks wired at startup, so the cost/token/context bar and reminder notifications went dead for the rest of the session. The three callbacks are now retained on `DeepApp` and re-passed on every reconfigure.

- **Eviction could destroy content instead of shrinking it** (`pydantic_deep/processors/eviction.py`):
  - Single-line payloads (minified JSON, base64) were written to a file but the preview returned the whole content, because the head/tail logic is line-based and sees one line, so the context was never reduced. Added an opt-in character cap, applied by both the capability and the legacy processor (and left off for line-only callers such as the unified-diff renderer).
  - A bare `BinaryContent` result (or a list containing one) not wrapped in `ToolReturn` was coerced to its multi-hundred-KB text repr, losing the image. Such multimodal payloads are now returned unchanged.
  - The legacy `EvictionProcessor`'s already-evicted-id set grew without bound for the whole session; it is now a bounded FIFO (`max_evicted_ids`).

- **`/config set sandbox_env_vars …` stored a raw string into the dict field** (`apps/cli/config.py`). `_coerce_value` had no branch for the `dict`-typed `sandbox_env_vars`, so `/config set sandbox_env_vars FOO=bar` fell through to `return value` and persisted a bare string. On the next load that string was fed into `CliConfig(sandbox_env_vars=<str>)`, and `agent.py`'s `{**config.sandbox_env_vars, …}` spread then raised `TypeError` ("str object is not a mapping") at agent build time. The setter now parses comma-separated `KEY=VALUE` pairs into a `dict[str, str]` (rejecting pairs missing `=` with a clear error), keeping the persisted shape aligned with the TOML table the loader expects.

- **Stale fallback hop counter after a partial recovery** (`pydantic_deep/agent.py`). The `MODEL_FALLBACK_TRIGGERED` hop counter reset only on full chain exhaustion, so when the primary failed but a fallback succeeded the counter leaked into the next request in the same coroutine context and mis-attributed (or skipped) the `primary -> fallback` pair. `FallbackModel` is now wrapped to zero the per-context counter at each request boundary, preserving per-task isolation for concurrent runs.

- **Built-in `planner` subagent silently overwrote a user-defined `planner`** (`pydantic_deep/agent.py`). The planner block appended its config unconditionally, while the research block guarded against clobbering a user-defined subagent via an `existing_names` check. Because the built-in planner is appended *after* the caller's configs and `create_subagent_toolset` keys compiled configs by name (last write wins), a user who defined their own `planner` had it silently replaced by the built-in one, and the planner was listed twice in the generated subagent system prompt. The planner block now mirrors the research guard: it computes `existing_names` and only appends `planner_config` when `'planner'` is not already present.

- **`create_deep_agent` mutated the caller's `subagents` config dicts** (`pydantic_deep/agent.py`). The list was shallow-copied but its dicts were mutated in place (injecting `agent_factory`, appending per-subagent context/memory toolsets), so a second call with the same list doubled the injected toolsets. Each config is now shallow-copied before injection; the default factory and the toolset-injection logic were extracted to module-level helpers.

- **`InMemoryCheckpointStore.remove_oldest()` evicted by insertion order while `FileCheckpointStore` evicted by `created_at`** (`pydantic_deep/toolsets/checkpointing.py`). The two interchangeable stores could evict different checkpoints under clock skew or relabeling. In-memory now evicts by `created_at` as well.

- **Per-message `delivery_mode` was ignored beyond the queue head** (`pydantic_deep/capabilities/message_queue.py`). An `all`-mode head drained the entire queue, overriding the `one_at_a_time` mode of later messages. Draining now respects each message's mode: an `all` head batches only the contiguous leading run of `all` messages and stops before the first `one_at_a_time`.

- **Vote-mode `judge_usage` was a list instead of a summed `RunUsage`** (`pydantic_deep/toolsets/forking/coordinator.py`). The single-judge path and the `ResolveOutcome.judge_usage` contract specify one usage object "summed across judges", but vote mode returned a per-judge list, breaking cost attribution. Vote mode now sums the per-judge usages into a single `RunUsage`.

- **Passive judge overlay leaked when a merge was cancelled mid-flight** (`apps/cli/screens/chat.py`). The `JudgeLoadingScreen` overlay was dismissed only on the `merge_or_select` result event; a cancel before that left it on screen. It is now also dismissed in the run's `finally`.

- **Branch transcript doubled in the poll-vs-stream window** (`apps/cli/screens/chat.py`, `apps/cli/widgets/branch_panel.py`). `_stream_branch_via_iter` rendered branch output live without advancing the panel's replay watermark, so a poll tick firing after streaming stopped (but before the branch was marked `done`) re-rendered the whole transcript via `replay_messages_append`. The streamer now advances the watermark (`note_streamed_messages`) past what it rendered.

- **Untracked background task in `handle_command`** (`apps/cli/app.py`). Slash-command dispatch was scheduled with a bare `asyncio.create_task`, which keeps only a weak reference (the task could be garbage-collected mid-flight) and swallowed exceptions. Commands now run via a tracked-task helper that holds a strong reference until completion and surfaces failures via `notify`.

- **Doc/behavior mismatch on `include_memory`** (`pydantic_deep/agent.py`). The docstring said it defaults to `False` while the parameter defaults to `True`; corrected.

- **`/compact` LLM mode never compacted** (`apps/cli/commands.py`). The handler looked up `getattr(cap, "compress", …)` on the context-manager capability, but that capability exposes `compact()` — so the lookup was always `None` and the LLM branch silently fell through to a 30-message trim. Even had the name matched, `await compress(history)` discarded the returned list (`compact()` returns a new list rather than mutating in place). Now calls `compact` and assigns its result (`app.message_history = await compact(history, focus)`), also threading the user's `focus` hint through.

- **`remember()` dropped all prior memory on every call** (`apps/deepresearch/src/deepresearch/agent.py`). The tool did `backend.read(...).decode("utf-8")`, but `BackendProtocol.read()` returns a `str` (with line-number prefixes), never `bytes` — so `.decode` raised `AttributeError`, the broad `except` reset content to `""`, and each `remember()` overwrote `MEMORY.md` with only the new fact. Now guards with `exists()` and reads raw via `read_bytes()`, preserving existing facts and appending the new one.

- **Binary file preview/serving corrupted images and PDFs** (`apps/deepresearch/src/deepresearch/app.py`). `get_file_binary` and `preview_file` served `backend.read()`'s line-numbered `str` — the `isinstance(result, bytes)` branch was dead, so binary files were emitted as `result.encode("utf-8")` of mangled, line-prefixed text. Both endpoints now use `read_bytes()` to serve faithful raw bytes (also fixing line-number injection in text/HTML/SVG previews).

- **Browser popup redirect bypassed the `allowed_domains` allowlist** (`pydantic_deep/capabilities/browser.py`). On a popup, `_on_popup` unconditionally navigated the single tab via `page.goto(popup.url)` with no allowlist check, letting a page on an allowed domain force navigation to any excluded domain — defeating the documented security boundary. The popup URL is now validated with `_check_allowed_domain` (the same check `navigate()` uses); disallowed popups are closed and the tab stays put.

- **Context-file section updates corrupted files via substring matching** (`pydantic_deep/improve/analyzer.py`). The `update`-with-`section` branch matched `change.section in line` anywhere on a line, so a section name appearing in body prose was mistaken for a heading, a trailing section's body (and anything after it) was silently discarded, and a later heading whose text contained the section name failed to terminate replacement. Replacement now matches only real heading lines whose normalized text equals the section, terminates at the next heading of the same-or-higher level, and handles the EOF (trailing-section) case explicitly without losing content.

- **Chunk overlap was always a no-op** (`pydantic_deep/improve/extractor.py`). `next_start = max(chunk_end - overlap_messages, chunk_end)` always equalled `chunk_end` (overlap is non-negative), so consecutive extraction chunks never shared messages despite the docstrings and merge-prompt assuming they did. The loop now carries back `overlap_messages` with a forward-progress guard (`max(start + 1, chunk_end - overlap_messages)`) and terminates once a chunk consumes the remaining messages, so overlap genuinely shares boundary messages between chunks.

- **Accurate pre-fork snapshot documentation** (`pydantic_deep/toolsets/forking/isolation.py`, `materializer.py`). The lazy parent snapshot is captured at a branch's first touch, not at fork time. Docstrings that claimed "pre-fork bytes" / "at fork time" now document the conflict-detection gap: a third actor writing a path between the fork and a branch's first touch is not flagged as a conflict.

- **A timed-out or crashed branch command discarded its partial filesystem mutations** (`pydantic_deep/toolsets/forking/isolation.py`). In `BranchOverlay._run_in_snapshot`, `_propagate_mutations` ran only on the success path: a `subprocess.TimeoutExpired` or any other exception from `subprocess.run` returned early *before* the post-state was captured and mirrored back into the overlay. A command that created or modified files and then hung past its timeout (or crashed) therefore had those changes made in the isolated snapshot but never recorded into the branch's `changes()`, so they were silently lost from `diff_branches`/merge even though the command demonstrably ran and altered files. Post-state capture and `_propagate_mutations` now run in a `finally` block, so partial mutations from a timed-out or crashed command are still propagated into the overlay.

- **`update` command silently failed for pip-installed users** ([#124](https://github.com/vstorm-co/pydantic-deepagents/pull/124), fixes [#122](https://github.com/vstorm-co/pydantic-deepagents/issues/122)). `run_update()` ran `uv tool upgrade pydantic-deep` whenever `uv` was on `PATH`, but that only works for installs done via `uv tool install`. Users who installed via `pip install pydantic-deep[cli]` saw the upgrade fail with no fallback. The early `return` on a non-zero `uv` exit code is removed, so the command now falls through to `pip install --upgrade pydantic-deep[cli]`.

- **Branch panel full replay left a tool row spinning when a tool call was followed by a text part** (`apps/cli/widgets/branch_panel.py`). `replay_messages()` completed each `ToolReturnPart` via `msg_list.current_assistant`, but a `TextPart` in the same response ends the assistant message and nulls `current_assistant`, so the return for a preceding `ToolCallPart` was dropped and its spinner never resolved. The incremental `replay_messages_append()` path already guarded against this by holding a per-call reference in `_rendered_call_msgs`; the full-replay path now does the same — recording each rendered call's message and completing returns through that held reference. As a side effect `_rendered_call_msgs` is now populated by `replay_messages()` too, so a later incremental append tick can complete a call first rendered by a full replay.

- **Shared `_DepsTodoProxy` raced on its bound deps across concurrent runs of one agent** (`pydantic_deep/agent.py`). A single `_DepsTodoProxy` is created per agent and rebound to the current run's deps inside `dynamic_instructions` on every model turn (`_todo_proxy._deps = ctx.deps`). Because the bound deps lived in a plain instance attribute, running the *same* agent instance concurrently (`asyncio.gather(agent.run(deps=A), agent.run(deps=B))`) let one run overwrite the other's binding between turns, so `read_todos` / `write_todos` could land in the wrong run's deps — contradicting the proxy's "always operates on the correct deps object" contract. The bound deps is now held in a `contextvars.ContextVar`; since asyncio copies the context per task, each concurrent run sees its own deps and the binding never leaks across runs.

- **`thinking_budget` listed in `_INT_FIELDS` was a dead, misleading config entry** (`apps/cli/config.py`). `_INT_FIELDS` included `"thinking_budget"`, but `CliConfig` declares no such field (it has `thinking_effort`, a string). Since `set_config_value` validates the key against `fields(CliConfig)` *before* `_coerce_value` ever runs, `/config set thinking_budget …` always raised `KeyError` and the int-coercion entry was unreachable — implying a config option that does not exist. Removed `"thinking_budget"` from `_INT_FIELDS`.

- **Live `/remind llm` switch dropped the configured `reminder_model`** (`apps/cli/reminder.py`). `_apply_reminder_mode` built the new config via `make_config_for_mode('llm')`, which attaches a default-model `LLMReminderGenerator()` — unlike `_build_reminder_config`, which wires `LLMReminderGenerator(model=reminder_model or config.reminder_model or config.model)` at startup. Live-switching to LLM mode therefore silently ran the reminder generator on the generator default (`claude-haiku`) instead of the user's configured `reminder_model` (or main model). `_apply_reminder_mode` now resolves the model the same way (new `_resolve_reminder_model` helper, reading `config.reminder_model` and falling back to the app's active model) and rebuilds the generator with it, so the live switch matches the startup configuration.

- **Orphaned image-reading docstring fragment misattached to `on_context_update`** (`pydantic_deep/agent.py`). The `on_context_update` parameter docstring ended its accurate description ("Called with `(percentage, current_tokens, max_tokens)` ... Useful for UI display.") but then carried three leftover sentences describing a boolean image-reading toggle ("When True, reading image files (.png, .jpg, ...) returns a BinaryContent object ... Defaults to False."). `on_context_update` is an `Any | None = None` callback with no True/False/image semantics — the text was a leftover from a removed image-support parameter (the behavior now lives in `create_console_toolset(image_support=True)`, not an exposed `create_deep_agent` argument) and mapped to no parameter, documenting behavior that no longer exists. Removed the orphaned sentences so the docstring describes only the callback's real contract.

- **`edit_file` diff preview silently dropped the 4th line of a 4-line old/new string** (`apps/cli/widgets/tool_call.py`). The mini-diff showed up to 3 lines via `splitlines()[:3]` but gated the "... (N more)" marker on `count("\n") > 3`. For an old/new string of exactly 4 lines (3 newlines), 3 lines were shown and the 4th was hidden, yet `3 > 3` is `False`, so the hidden line vanished with no marker. The gate also mixed `count("\n")` with `splitlines()`, which disagree for trailing-newline strings (e.g. `"a\nb\nc\n"` has 3 newlines but only 3 displayable lines), making both the gate and the `- 2` hidden-count math wrong in that case. Both the old and new sides now compute `splitlines()` once and gate/count off `len(lines) > 3` / `len(lines) - 3`, so the marker fires whenever any line is hidden and reports the exact count regardless of trailing newlines.

- **`clone_for_subagent` docstring omitted the intentional reset of context/fork bookkeeping fields** (`pydantic_deep/deps.py`). The docstring's "Subagents get:" list enumerated only `backend`/`todos`/`subagents`/`files`/`uploads`, while the constructor also (intentionally) does not propagate `context_middleware`, `fork_coordinator`, `_fork_depth`, `_branch_cost_tracking`, `_branch_id`, or `_parent_fork_coordinator` — making the omission read like a bug that silently disables forking/cost-tracking for subagents. It is not: `context_middleware` is a CLI-only handle (`/compact`, `/context`) over the *parent's* history; `fork_coordinator` is allocated lazily per-run by the fork capability (mirroring `clone_for_branch`, which also resets it); `_fork_depth` restarts at 0 because subagent nesting is bounded separately by `max_depth`; and the remaining branch-bookkeeping fields are only meaningful to an agent wired with the fork capability, so they are inert on a separately-compiled subagent. The docstring now documents these as deliberate resets and the rationale for each, so the divergence is no longer mistaken for missing logic.

- **`get_todo_prompt` rendered `blocked` todos identically to `pending`** (`pydantic_deep/deps.py`). The status-icon map covered only `pending`, `in_progress`, and `completed`, defaulting everything else to `[ ]`. Since the `Todo` model defines `status: Literal['pending', 'in_progress', 'completed', 'blocked']`, a `blocked` todo was rendered the same as a `pending` one in the generated system prompt, hiding the blocked state from the model. Added a `'blocked'` -> `[!]` entry so blocked tasks are visually distinct.

- **`_parse_json_response` crashed on a fenced response with no newline** (`pydantic_deep/improve/extractor.py`). After detecting a leading ```` ``` ```` fence, the parser called `str.index("\n")`, which raises an uncaught `ValueError` (not a `JSONDecodeError`) when the response is a single fenced line with no newline. In the single-chunk path this propagated out of `_extract_chunk` and was only caught by `analyze()`'s broad handler, turning a recoverable response into a counted session failure. It now uses `str.find("\n")` and falls back to stripping the leading fence characters, so malformed fences degrade gracefully to the fallback insights.

- **History search emitted overlapping, double-counted context windows** (`pydantic_deep/processors/history_archive.py`). The search tool recorded only each match's center line in `shown_indices`, but emitted a +/- context-line window per match, so two nearby matches repeated the same lines across results and the "Found N match(es)" count overstated distinct content. The fix records the entire emitted window range, so a match whose center is already covered by a previously shown window is skipped.

- **Orphaned-tool-call patching relied on an `assert` stripped under `python -O`** (`pydantic_deep/processors/patch.py`). The orphaned-result phase guarded `msg.parts` access with `assert isinstance(msg, ModelRequest)`, which `python -O` removes, leaving the attribute access unguarded if the invariant were ever violated. It is now an explicit `isinstance` check that skips non-`ModelRequest` messages, preserving the type-narrowing for Pyright/MyPy while remaining safe under optimized runs.

- **`DeepAgent.from_file` raised an opaque error on malformed spec files** (`pydantic_deep/spec.py`). `from_file` forwarded the loaded YAML/JSON directly to `from_spec`, which immediately did `data.items()`. An empty file (`yaml.safe_load` returns `None`) or a top-level scalar/list raised a bare `AttributeError`/`TypeError` with no hint that the spec file was malformed. `from_file` now validates that the loaded content is a top-level mapping and raises `ValueError("Spec file {path} must contain a mapping at the top level, got {type}")` for both the YAML and JSON paths.

- **`load_style_from_file` accepted style files with an empty body** (`pydantic_deep/styles.py`). The loader validated the `name` in frontmatter but never the body, so a file with frontmatter and a blank body produced an `OutputStyle` with `content=""`, and `format_style_prompt` then emitted a `## Output Style: <name>` section with no directive. It now raises `ValueError("Style file {path} has no content body")` when the body is blank, mirroring the existing `name` validation (`discover_styles` already skips files that fail to parse).

- **`scroll` silently treated invalid directions as "down"** (`pydantic_deep/toolsets/browser.py`). The tool mapped direction via `delta_map.get(direction.lower(), (0, 300))`, so any unrecognized direction (a typo, `top`, `bottom`, `""`) scrolled down and still reported `Scrolled <dir>.`, misleading the model into thinking its request succeeded. It now returns `Error: invalid direction <dir>; use up/down/left/right` and performs no scroll for directions outside the documented set.

- **`execute_js` stringified structured results with `str()`** (`pydantic_deep/toolsets/browser.py`). The tool returned `str(result)`, turning `dict`/`list` results from `page.evaluate` into Python reprs (single quotes, `True`/`False`/`None`) rather than valid JSON, and rendering an absent return value (`undefined` -> `None`) as the literal string `"None"`. It now returns strings unchanged, serializes objects and arrays as JSON (`json.dumps(..., default=str)`, falling back to `str()` on `TypeError`), and returns `"undefined"` for a null result; the tool description was updated to match.

- **`_truncate_content` failed to truncate (and grew the output) with a zero budget** (`pydantic_deep/toolsets/browser.py`, `pydantic_deep/toolsets/context.py`). When the character/token budget was 0, the tail length computed to 0 and the slice `content[-0:]` returned the entire string, so the function returned the truncation marker followed by the full untruncated content. Both copies now guard the tail (and head) slices so an empty budget yields only the marker.

- **`ContextToolset.get_instructions` assumed `ctx.deps.backend` always exists** (`pydantic_deep/toolsets/context.py`). It read `ctx.deps.backend` unconditionally and raised `AttributeError` for deps without a backend, even though the wrapping `ContextFilesCapability` guards with `hasattr`. Since `ContextToolset` is a documented public class usable directly, it now uses `getattr(ctx.deps, "backend", None)` and returns `None` when no backend is present, mirroring the capability.

- **Context-file discovery read each file twice on every model step** (`pydantic_deep/toolsets/context.py`). `discover_context_files` read every candidate file's bytes solely to test existence and discarded them, then `load_context_files` re-read the same paths; because `get_instructions` is `dynamic=True`, this doubled backend I/O for context discovery on every model request (an RPC round-trip per file for remote/sandbox backends). A new single-pass `_discover_and_load` helper reads each file once; the public `discover_context_files` and `load_context_files` signatures are unchanged.

- **`merge_or_select` spuriously raised for a winner cancelled before its first model request** (`pydantic_deep/toolsets/forking/coordinator.py`). When the picked winner was cancelled (e.g. by the budget watcher) before issuing any model request, `before_model_request` never ran, so `partial_history` was empty and the `state in _exhausted_states and partial_history` guard fell through to `raise RuntimeError("...was cancelled before merge")`, defeating the partial-history merge fallback for budget-exhausted winners. The coordinator now records the pre-fork parent history and falls back to it when the winner is in a valid exhausted state but has no partial history; non-exhausted cancellations still raise.

- **Binary diff agreement was keyed on a truncated 48-bit sha256 prefix** (`pydantic_deep/toolsets/forking/diff.py`). `_change_identity` compared the human-readable `[binary - {size} - sha256:{12 hex}]` placeholder for binary changes, so two distinct binaries of equal length whose sha256 collided in the leading 48 bits were classified as `unanimous_change` (agreement) in a correctness-sensitive merge decision. `BranchChange` now carries the full `binary_sha256` digest, which is used for agreement/conflict classification, while the truncated placeholder remains for display only.

- **`build_diff_report` silently mis-merged runtimes sharing a `status.id`** (`pydantic_deep/toolsets/forking/diff.py`). Several per-branch dicts were keyed solely on `runtime.status.id` with no uniqueness check, so an aliased/duplicate runtime would silently overwrite another's touched-set and under-count uniques. The builder now raises a clear `ValueError` (not an `assert`, so it survives `python -O`) when two runtimes share a `status.id`, failing loudly instead of producing a silently wrong report.

- **Confidence-weight invariant was an `assert` stripped under `python -O`** (`pydantic_deep/toolsets/forking/judge.py`). The module-level `assert` that the three confidence-signal weights sum to 1.0 disappears under optimized mode, even though a comment relied on it and `diff.py` deliberately uses `raise` over `assert` for the same reason. It is now an explicit `if not math.isclose(...): raise RuntimeError`, so the guard survives `-O` and tolerates float representation.

- **Forking docstring and comment fixes** (`pydantic_deep/toolsets/forking/`). Documented that `test_command` runs each branch's test against a full copy of the parent tree (including the venv) with the inherited environment, so operators avoid leaking provider keys (`coordinator.py`); corrected `snapshot()`/`_run_in_snapshot()` docstrings that claimed file-level symlinks where detached `shutil.copy2` copies are used (the actual isolation guarantee) (`isolation.py`); clarified the PyCharm 2-branch center-pane diff argument order versus the >2-branch order (`editor.py`); documented that `agreement_score` measures only same-path contention (so all-disjoint branches score 1.0) (`diff.py`); and aligned the `_majority_pick` confidence docstring with its actual averaging over every verdict that selected the winning branch (`judge.py`).

- **`update_memory` replaced only the first of multiple matches despite advertising find-and-replace** (`pydantic_deep/toolsets/memory.py`). `mem.content.replace(old_text, new_text, 1)` changed only the first occurrence, so when `old_text` recurred the other matches were silently left in place (e.g. when correcting an outdated fact), producing inconsistent memory with a success message. The tool now counts occurrences and returns an error when `old_text` is absent or appears more than once, replacing only when there is exactly one match; the tool description and docstring document the unique-match requirement.

- **The improve pipeline wrote `MEMORY.md` where the memory toolset never reads it** (`pydantic_deep/improve/analyzer.py`). The analyzer's default mapped `MEMORY.md` to `.pydantic-deep/main/MEMORY.md`, while `AgentMemoryToolset` reads from `/.deep/memory/main/MEMORY.md`, so improve-generated memory updates never reached the running agent unless the caller manually overrode `context_files`. The analyzer default now derives from the shared `get_memory_path(DEFAULT_MEMORY_DIR, "main")` helper (resolving to `.deep/memory/main/MEMORY.md`), keeping the two locations in sync.

- **`save_plan` produced empty/degenerate filenames for non-Latin titles** (`pydantic_deep/toolsets/plan/toolset.py`). The slug was built with `re.sub(r"[^a-z0-9]+", "-", title.lower())`, which strips every non-ASCII character: a fully non-Latin title (e.g. Chinese or Cyrillic) produced an empty slug and a filename like `-{short_id}.md`, while `Über Café` degraded to `ber-caf`. Slug generation now uses Unicode word characters (`re.UNICODE`) and falls back to `plan` when the result is empty.

- **`_get_relative_path` could mis-strip sibling paths sharing a directory prefix** (`pydantic_deep/toolsets/skills/backend.py`). The helper used `file_path.startswith(base_dir)` with no path-boundary check, so with `base_dir="/skills/foo"` a sibling like `/skills/foobar/data.json` would match and be mis-stripped to `bar/data.json`. It now matches on a path-boundary prefix (`base_dir.rstrip("/") + "/"`) and handles the exact-match case explicitly, so only true children are stripped.

- **`FileBasedSkillScript` shared a single mutable default executor across all instances** (`pydantic_deep/toolsets/skills/local.py`). The `executor` dataclass field defaulted to a single `LocalSkillScriptExecutor()` instance evaluated once at class-definition time, so every script created without an explicit executor shared it; mutating one script's executor (its `timeout`/`_python_executable`) affected all of them. It now uses `field(default_factory=LocalSkillScriptExecutor)` so each script gets its own executor.

- **`SkillsToolset(skills=[])` with no directories silently loaded nothing** (`pydantic_deep/toolsets/skills/toolset.py`). The default `./skills` directory loaded only in the `elif skills is None:` branch, so an explicit empty list with `directories=None` registered nothing and emitted no warning, diverging from the documented "if both are None, defaults to ['./skills']" behavior. The default-directory branch now also covers the empty-list case, loading `./skills` or warning when it is missing.

- **Skill metadata was injected into the system prompt without XML escaping** (`pydantic_deep/toolsets/skills/toolset.py`). `_build_resource_xml`, `_build_script_xml`, and `get_instructions` interpolated skill/resource/script names and free-form descriptions directly into XML tags and attributes, so a skill author could inject closing tags or fabricate `<skill>` blocks (prompt injection) or break attribute parsing with an embedded quote. All interpolation points now escape via `xml.sax.saxutils` (`quoteattr` for attributes, `escape` for text content).

- **`read_skill_resource` / `run_skill_script` omitted the available-skills list on a not-found error** (`pydantic_deep/toolsets/skills/toolset.py`). When the skill name was unknown, these tools returned `Error: Skill '<name>' not found.` with no list of valid names, unlike `load_skill`, making it harder for the model to recover. Both now append the same sorted `Available: ...` list `load_skill` provides.

### Documentation

- **Documentation overhaul — accuracy pass, new API reference pages, and a clean strict build.** Audited every page under `docs/` against the actual public API and corrected drifted content: the documented default model (`anthropic:claude-opus-4-6`, not Sonnet), the `Skill` type (a dataclass, not a `TypedDict` — removed the nonexistent `SkillDirectory`/`SkillFrontmatter` and dict-access examples in favor of `SkillsDirectory` and attribute access), the `create_deep_agent` parameter tables (dropped `permission_handler`/`middleware_context`; added `forking`, `message_queue`, `fallback_model`, `summarization_model`, `capabilities`, `mcp_servers`, `include_liteparse`/`include_improve`/`include_history_archive`, and more), `run_with_files`, and the stale `ContextManagerMiddleware` reference (now `ContextManagerCapability`). Removed references to private skills helpers. Added ten new mkdocstrings API-reference pages (`capabilities`, `mcp`, `forking`, `spec`, `checkpointing`, `context-files`, `memory`, `output-styles`, `hooks`, `teams`) and wired the previously-orphaned `message-queue`, `fallback-models`, and `agent-spec` pages into the nav. Configured mkdocstrings `inventories` (Python + pydantic-ai) so external cross-references resolve. `mkdocs build --strict` now passes with zero warnings (previously ~104 broken cross-references).

## [0.3.22] - 2026-05-24

### Fixed

- **`AttributeError: 'LocalBackend' object has no attribute '_read_bytes'` at toolset `get_instructions()` time** ([#118](https://github.com/vstorm-co/pydantic-deepagents/pull/118), independently authored by [@mcauthorn](https://github.com/mcauthorn) in [#119](https://github.com/vstorm-co/pydantic-deepagents/pull/119)). `pydantic-ai-backend 0.2.8` promoted the bytes-read entry point on `BackendProtocol` from private `_read_bytes` to public `read_bytes` and (deliberately) kept no transitional alias. With `pydantic-ai-backend>=0.2.7` unbounded, fresh resolutions pulled `0.2.8` transitively, so every toolset that reaches for bytes (`context`, `memory`, `liteparse`, `skills/backend`) blew up at instructions-load time. Word-boundary rename across all call sites and test mocks.

### Changed

- **Bumped `pydantic-ai-backend>=0.2.7 → >=0.2.8`** ([#118](https://github.com/vstorm-co/pydantic-deepagents/pull/118), Renovate) — pulls in the `exists()` predicate, the `read_bytes` rename (see Fixed above), `hashline_edit` per-`(backend, path)` serialization, and the `async_execute` wire-up in the console toolset's `execute` tool.
- **Bumped `summarization-pydantic-ai>=0.1.4 → >=0.1.5`** ([#118](https://github.com/vstorm-co/pydantic-deepagents/pull/118), Renovate) — batched with the backend bump; pure CI-housekeeping release on the summarization side, no behaviour change.

## [0.3.21] - 2026-05-24

### Changed

- **Bumped `pydantic-ai-todo` floor from `>=0.2.1` to `>=0.2.2`** ([#114](https://github.com/vstorm-co/pydantic-deepagents/pull/114), auto-opened by the new Renovate config). Brings in [`pydantic-ai-todo 0.2.2`](https://github.com/vstorm-co/pydantic-ai-todo/releases/tag/0.2.2): the new `AsyncRedisStorage` backend (Redis Hash + companion List, session-scoped, multi-tenant, event-emitter integration) plus a follow-up batch of correctness fixes (`remove_todo` atomicity via single pipeline, Redis Cluster–safe hash-tagged keys, idempotent `initialize()`).

## [0.3.20] - 2026-05-18

### Fixed

- **`[WinError 2]` crash on Windows when calling the `execute` tool** ([#108](https://github.com/vstorm-co/pydantic-deepagents/issues/108)) — bumped the `pydantic-ai-backend` floor from `>=0.2.4` to `>=0.2.7`. Releases before 0.2.7 hardcoded `["sh", "-c", command]` in `LocalBackend.execute()`, so every shell invocation on Windows failed with `FileNotFoundError: [WinError 2] The system cannot find the file specified`, regardless of whether the target executable (e.g. `powershell`, `pwsh.exe`) was on `PATH`. `pydantic-ai-backend 0.2.7` routes through `_shell_cmd()` (`cmd /c` on `win32`, `sh -c` elsewhere) and adds `async_execute()` with cancellation support.
- **`wait_tasks` cancellation cascade in subagent orchestration** — bumped `subagents-pydantic-ai` floor to `>=0.2.4`, which routes both `mode="all"` and `mode="any"` through `asyncio.wait` instead of `asyncio.wait_for(asyncio.gather(...))`. Previously, when pydantic-ai's `_call_tools` sibling-cancelled the `wait_tasks` tool call (or any outer cancel reached the orchestrator), the cascade silently killed every in-flight subagent — surfacing as `TaskStatus.CANCELLED` with an empty `error` even though the parent never requested it.

### Changed

- **Bumped minimum versions of all `pydantic-ai-*` sister packages** so a fresh install pulls the latest releases by default: `pydantic-ai-slim>=1.97.0` (was `>=1.77.0`), `pydantic-ai-backend>=0.2.7` (was `>=0.2.4`, for both `[console]` and `[docker]` extras), `summarization-pydantic-ai>=0.1.4` (was `>=0.1.3`), `subagents-pydantic-ai>=0.2.4` (was `>=0.2.1`), `pydantic-ai-shields>=0.3.2` (was `>=0.3.1`).

### Internal

- `# type: ignore[attr-defined]` on five `BinaryContent` attribute accesses in `pydantic_deep/processors/eviction.py`. `pydantic-ai-slim>=1.97` exposes `BinaryContent` as a `PydanticDataclass` whose fields and `identifier` property are invisible to pyright (the attributes exist at runtime — this is upstream type-info incompleteness). Keeps `make typecheck` green until upstream stubs catch up.

### Infrastructure

- **Renovate config** ([`renovate.json`](renovate.json)) — opt-in dependency bot scoped to the five vstorm-co sibling packages (`pydantic-ai-todo`, `pydantic-ai-backend`, `summarization-pydantic-ai`, `subagents-pydantic-ai`, `pydantic-ai-shields`). All other dependencies are explicitly disabled. New releases of these packages will get grouped PRs that bump both `pyproject.toml` floors and `uv.lock`, with auto-merge on green CI. Activates once the Renovate GitHub App is installed on the `vstorm-co` organization.

## [0.3.19] - 2026-05-14

### Added

- **`PeriodicReminderCapability` — periodic task reminders for long agent runs** ([#94](https://github.com/vstorm-co/pydantic-deepagents/pull/94)) — injects a "what are you supposed to be doing" reminder into the message history every N model-request turns to prevent agent drift on long, tool-heavy runs. Uses `before_model_request` and per-run state isolation via `for_run()`.
  - Four CLI modes via a new `/remind` command: `off`, `first` (zero-cost — re-states the first user message), `context` (zero-cost — compact transcript), `llm` (uses Claude Haiku / GPT mini / Gemini Flash to summarize progress).
  - `LLMReminderGenerator` with exception fallback to the zero-cost default.
  - Three render styles: `system_reminder_tag` (default), `developer_note`, `user_prompt`.
  - `create_deep_agent()` gains a `periodic_reminder: bool | PeriodicReminderConfig | None = None` parameter.
  - CLI: enabled by default in `llm` mode; configurable via `periodic_reminder` and `reminder_mode` keys in `config.toml`.
  - New top-level exports: `PeriodicReminderCapability`, `PeriodicReminderConfig`, `ReminderGenerator`, `LLMReminderGenerator`, `make_config_for_mode`.

- **`MessageQueue` — mid-run message delivery (steering & follow-up)** ([#100](https://github.com/vstorm-co/pydantic-deepagents/pull/100)) — lets external code (CLI keystrokes, webhooks, subagents) push messages into a running agent loop without cancelling and restarting it, preserving in-flight tool results and the prompt cache.
  - **Steering** messages are injected before the next LLM call via `MessageQueueCapability.before_model_request`. To avoid issues with downstream capabilities that strip lone trailing `ModelRequest` nodes, the steering `UserPromptPart` is merged into the last existing `ModelRequest`.
  - **Follow-up** messages are queued for delivery when the agent would otherwise stop, triggering a re-entry via the new `run_with_queue()` helper.
  - Two delivery modes: `one_at_a_time` (default) and `all` (drain entire queue based on the head message's mode).
  - `DeepAgentDeps.message_queue` field, propagated by reference through `clone_for_subagent()` so subagents can steer the parent.
  - `create_deep_agent()` gains a `message_queue: MessageQueue | None = None` parameter.
  - CLI: `>>text` mid-run = steering, plain text mid-run = follow-up, `!cmd` stays as shell command in all states. Side-panel `QueuedWidget` shows pending counts. Stale steering messages are surfaced as a warning when the run ends before reaching another LLM call, and follow-ups left over from a cancelled run are discarded with a count-only notification.
  - New top-level exports: `MessageQueue`, `MessageQueueCapability`, `QueuedMessage`, `run_with_queue`, `format_steering`, `format_follow_up`.

- **Programmatic `skills` parameter on `create_deep_agent`** ([#97](https://github.com/vstorm-co/pydantic-deepagents/pull/97)) — accepts `list[Skill]` instances directly, complementing the existing `skill_directories=` discovery path. Emits a `UserWarning` when `skills=` or `skill_directories=` are provided alongside `include_skills=False`.

- **Docker sandbox environment variable support** ([#99](https://github.com/vstorm-co/pydantic-deepagents/pull/99) — fixes [#98](https://github.com/vstorm-co/pydantic-deepagents/issues/98)) — wires up the `RuntimeConfig.env_vars` plumbing that the programmatic `DockerSandbox` API already supported but the CLI and `full_app` example never exposed.
  - `sandbox_env_vars: dict[str, str]` and `sandbox_env_file: str | None` fields on `CliConfig`; matching parameters on `create_cli_agent()`.
  - Three-level priority merge: `config.sandbox_env_vars` (lowest) → `.env` file → explicit `sandbox_env_vars` (highest).
  - `examples/full_app/app.py` auto-loads `examples/full_app/.env` into the `SessionManager`'s default `RuntimeConfig`.
  - Uses `RuntimeConfig(cache_image=False)` to prevent secrets from being baked into cached Docker image layers.
  - `_write_toml()` extended to emit `[table]` sections for `dict` values, enabling round-trip persistence via `set_config_value()`.

### Fixed

- **Esc to interrupt, tool spinner lifecycle, and empty message cleanup** ([#96](https://github.com/vstorm-co/pydantic-deepagents/pull/96) — closes [#93](https://github.com/vstorm-co/pydantic-deepagents/issues/93)):
  - **Esc** now interrupts a running agent (previously Ctrl+C only); focuses input when idle. Centralized on `DeepApp.action_escape_key` so any screen-level handler uses the same cancellation path.
  - Fixed a `ToolCallWidget.on_mount` race where `complete()` arriving before mount left the spinner timer uninitialized — the widget now renders its final state immediately when not in the `pending` state.
  - `AssistantMessage.complete_tool_call` is now idempotent (only acts on widgets still in the `pending` state), preventing the cancellation drain from overwriting correctly completed results.
  - `/load` session replay marks orphaned tool calls (from previously interrupted sessions) as "Interrupted" instead of leaving spinners hung; switched to `isinstance` checks against `ToolCallPart` / `ToolReturnPart` / `UserPromptPart` / `TextPart` and uses `part.args_as_dict()` for correct label display.
  - Empty assistant message bubbles are removed when a run is cancelled before producing any output, thinking, or tool calls.
  - The hints bar shows context-aware shortcuts (`Esc interrupt`) while the agent is running.

- **`create_deep_agent()` rejected `skills=` kwarg** ([#97](https://github.com/vstorm-co/pydantic-deepagents/pull/97) — fixes [#95](https://github.com/vstorm-co/pydantic-deepagents/issues/95)) — callers using `skills=[Skill(...)]` previously got `UserError: Unknown keyword arguments: 'skills'` because the kwarg fell through to pydantic-ai's `Agent()` constructor.

## [0.3.18] - 2026-05-05

### Fixed

- **`EvictionCapability` dropped `BinaryContent` (e.g. screenshots) from `ToolReturn` results** — previously, any `ToolReturn(return_value=..., content=[..., BinaryContent(...)])` was collapsed into a plain string before the size check, so the multimodal `content` (images, audio, PDFs) was silently discarded along with a text eviction message. The capability now only measures and evicts `return_value`; the `content` list and `metadata` are always preserved by re-wrapping the result. ([#90](https://github.com/vstorm-co/pydantic-deepagents/issues/90))

### Fixed

- **`DeepAgentDeps` was missing the `checkpoint_store` field** — the checkpointing middleware already resolved the store via `getattr(deps, "checkpoint_store", None)` and the docs instructed users to pass it at construction time, but the field was never declared on the dataclass so assignments were silently ignored and type checkers raised `attr-defined` errors. The field is now properly declared as `checkpoint_store: Any = None` and propagated as a shared reference through `clone_for_subagent()`. ([#87](https://github.com/vstorm-co/pydantic-deepagents/issues/87))

### Added

- **Binary content pruning via `max_binary_content`** — a new `before_model_request` hook in `EvictionCapability` bounds the number of multimodal binary parts kept in model-visible history. Older `BinaryContent` values (from both `UserPromptPart.content` and `ToolReturnPart.content`) are written to the backend at deterministic paths (`/large_tool_results/binary_{id}.{ext}`) and replaced with a compact `read_file`-able text reference so the agent can still retrieve them on demand. If a backend write fails, the binary is left in place to avoid data loss.
  - `EvictionCapability` gains a `max_binary_content: int | None` field (default `3`).
  - `create_deep_agent()` gains a matching `max_binary_content: int | None = 3` parameter across all overloads; pass `None` to keep every binary in history.
  - New constants exported from the top-level package: `DEFAULT_MAX_BINARY_CONTENT`, `BINARY_PRUNED_TEMPLATE`.
  - Storage paths use `BinaryContent.identifier` (a stable SHA1 of the bytes), making re-pruning the same binary idempotent.

## [0.3.17] - 2026-04-22

### Added

- **`LiteparseToolset` — document parsing via [LiteParse](https://github.com/run-llama/liteparse)**
  - New toolset at `pydantic_deep.toolsets.liteparse`
  - Tools: `parse_document` (text extraction) and `screenshot_document` (per-page images)
  - Reads files from any backend as bytes — works with `StateBackend`, `LocalBackend`, `DockerSandbox`
  - Optional OCR via built-in Tesseract or pluggable HTTP server (PaddleOCR, EasyOCR)
  - Lazy parser initialization — the Node.js CLI is found/installed on first tool call
  - Configurable: `ocr_enabled`, `ocr_language`, `ocr_server_url`, `dpi`, `max_pages`
  - Graceful error messages when the `liteparse` package or Node.js CLI is not installed
  - Enabled via `include_liteparse=True` in `create_deep_agent()`

- **`liteparse` optional extra in `pyproject.toml`**
  - `pip install pydantic-deep[liteparse]` installs the Python wrapper
  - Node.js >= 18 and `npm install -g @llamaindex/liteparse` are required separately

## [0.3.16] - 2026-04-22

### Changed

- **`instructions` now replaces `BASE_PROMPT` instead of appending to it** — previously, passing `instructions="..."` to `create_deep_agent()` produced a system prompt of `BASE_PROMPT + "\n\n" + instructions`. Now `instructions` is used verbatim as the full system prompt. `instructions=None` (the default) keeps the existing behaviour — `BASE_PROMPT` is used automatically. Users who want to extend the default rather than replace it can do so with an f-string: `instructions=f"{BASE_PROMPT}\n\nYour extra text"`. `BASE_PROMPT` is exported from the top-level package. ([#84](https://github.com/vstorm-co/pydantic-deepagents/issues/84), reported by [@rremilian](https://github.com/rremilian))
- **Subagent and team-member factories always prepend `BASE_PROMPT`** — agents spawned automatically by the `task()` tool or `spawn_team()` continue to receive `BASE_PROMPT` followed by their task-specific `instructions`, so subagent behaviour is unchanged.
- **`apps/deepresearch` double-prompt bug fixed** — `MAIN_INSTRUCTIONS` already contained `BASE_PROMPT`; it was previously duplicated in the final system prompt because the old append logic prepended it again. The new semantics resolve this without any change to the deepresearch app itself.

## [0.3.15] - 2026-04-17

### Fixed

- **`PatchToolCallsCapability` caused `ValidationException: duplicate Ids` on Bedrock when tools raised `ModelRetry`** — when a tool raised `ModelRetry`, pydantic-ai records the retry as a `RetryPromptPart` (carrying the original `tool_call_id`) on the following `ModelRequest`, not as a `ToolReturnPart`. The patch processor only scanned for `ToolReturnPart` when deciding whether a `ToolCallPart` was orphaned, so it injected a synthetic `ToolReturnPart` with the same id — leaving the request with two parts sharing one `tool_call_id`. Strict providers (Bedrock `minimax.minimax-m2.5` and others) rejected the request with `The toolResult blocks at messages.N.content contain duplicate Ids`. The processor now treats `RetryPromptPart` as a valid answer to a `ToolCallPart`, so no synthetic return is injected and the history remains valid. ([#79](https://github.com/vstorm-co/pydantic-deepagents/issues/79), reported by [@thatGreekGuy96](https://github.com/thatGreekGuy96))

## [0.3.14] - 2026-04-16

### Fixed

- **Subagents ignored parent `web_search`/`web_fetch` settings** — the default subagent factory in `create_deep_agent` hardcoded `web_search=True` and `web_fetch=True`, overriding the parent agent's configuration. On Bedrock and Vertex Anthropic models this produced a 400 error (`web_fetch_20250910` not accepted), because the beta web tools are not supported there. The factory now propagates the parent agent's `web_search` and `web_fetch` flags to spawned subagents. ([#77](https://github.com/vstorm-co/pydantic-deepagents/issues/77), reported by [@SvdR82](https://github.com/SvdR82))

## [0.3.13] - 2026-04-13

### Fixed

- **User-provided tools lost metadata when passed via `tools=` parameter** — tools registered through `create_deep_agent(tools=[...])` were previously added via `agent.tool(tool.function)` after construction, which hardcoded `takes_ctx=True` and discarded all `Tool`-level metadata (`name`, `description`, `prepare`, `max_retries`, `requires_approval`, `timeout`). Tools are now passed directly to the `Agent` constructor, preserving all metadata and correctly honouring the original `takes_ctx` value. (PR #75 by [@ilayu-blip](https://github.com/ilayu-blip))

## [0.3.12] - 2026-04-13

### Added

- **Bandit security scanner** — [Bandit](https://bandit.readthedocs.io/) is now part of the development toolchain and CI pipeline. It runs on every commit via the new `security` job in GitHub Actions and is also available locally via `make security`. The scanner checks production code (`pydantic_deep/`) for common Python security vulnerabilities (CWE-listed issues). No medium- or high-severity findings block a merge.
- **GitHub Issue Templates** — structured forms for bug reports and feature requests guide contributors to provide the right information. Blank issues are disabled; the config redirects security reports to `info@vstorm.co`.
- **Pull Request Template** — a checklist-based PR template ensures contributors verify tests, linting, type checking, and the security scan before requesting review.

### Fixed

- **MD5 `usedforsecurity` flag (`StuckLoopDetection`)** — `hashlib.md5()` calls used for tool-call fingerprinting in `stuck_loop.py` now pass `usedforsecurity=False`, correctly signalling that the hash is used for deduplication (not cryptographic security). This resolves a Bandit B324 High-severity finding.

### Changed

- **CONTRIBUTING.md** — expanded with an explicit test policy (new functionality requires tests; 100 % coverage is enforced mechanically), a coding-standards reference table (Ruff, Pyright, MyPy, Bandit with `pyproject.toml` links), English-language requirement, API docs pointer, and a static-analysis section documenting all quality gates.
- **`make all`** — now includes `make security` (Bandit scan) in addition to the existing format → lint → typecheck → testcov sequence.
- **Docs site** — homepage (`docs/index.md`) rewritten with a plain-language problem/solution description and explicit "Next Steps" links to Installation, Getting Help, and Contributing. New `docs/contributing.md` page added to the nav, covering setup, PR requirements, and test policy. `docs/index.md` subtitle updated to remove jargon.
- **OpenSSF Best Practices badge** — badge embedded in README and docs homepage; badge targets project ID 12495 at bestpractices.dev.

## [0.3.11] - 2026-04-13

### Fixed

- **Browser opens on every message (`BrowserCapability`)** — `async_playwright()` was entered eagerly
  at the start of `wrap_run`, spawning the Playwright Node.js driver process (which in turn opened a
  browser window) on every agent run — even when no browser tool was ever called. The Playwright context
  manager is now entered lazily inside the first-tool-call launcher, so runs that never use the browser
  incur zero Playwright overhead and no browser process is started.
- **Browser window always visible (`browser_headless` default)** — the CLI config defaulted
  `browser_headless = false`, meaning any browser launch produced a visible Chrome window. Changed to
  `browser_headless = true`.

## [0.3.10] - 2026-04-12

### Changed

- **Version re-release of 0.3.9** — 0.3.9 was published to PyPI and this release carries
  the same changes forward under a new version number. No functional differences from 0.3.9.

## [0.3.9] - 2026-04-12

### Added

- **Chromium auto-install (`BrowserCapability.auto_install`)** — when the Chromium binary is missing,
  `BrowserCapability` now automatically runs `playwright install chromium` via the current Python
  interpreter on the first tool call. On success the launch is retried immediately; on failure the
  browser degrades gracefully (tools hidden, no instructions injected) without crashing the agent.
  Controlled via `auto_install: bool = True` on `BrowserCapability`.

### Changed

- **Lazy Chromium launch** — Chromium is no longer started at the beginning of every agent run.
  The browser is now launched on demand — only when a browser tool (`navigate`, `click`, etc.) is
  actually invoked. Runs that never use the browser incur zero Playwright overhead. This fixes the
  bug where opening the TUI or asking any question would unconditionally launch a headless browser.
- **`install.sh` now ships browser support out of the box** — the one-line installer now installs
  `pydantic-deep[cli,browser]` (was `[cli]`) and runs `playwright install chromium` automatically.
  New users get a fully working browser without any manual steps.
- **Browser tool usage guidance** — `BROWSER_INSTRUCTIONS` now includes an explicit "when to use
  browser vs web_search / web_fetch" section. The model is instructed to prefer the lighter
  `web_search` / `web_fetch` tools for information lookup and static pages, and to reserve the
  Playwright browser for interactive workflows (login, forms, JS-heavy SPAs, screenshots).

## [0.3.8] - 2026-04-12

### Added

- **Automatic context limit warnings (`LimitWarnerCapability`)** — the agent now receives URGENT/CRITICAL
  warnings injected as user messages when approaching the context window limit. Warnings start at 70% usage
  (well before auto-compression at 90%), giving the model time to wrap up or use `/compact`. Previously only
  the TUI status bar showed context usage — the model itself had no awareness of approaching limits.
  Enabled automatically when `context_manager=True` (the default)
- **Stuck loop detection (`StuckLoopDetection`)** — new capability that detects repetitive agent behavior
  and intervenes before the agent wastes tokens. Detects three patterns: repeated identical tool calls,
  A-B-A-B alternating calls, and no-op calls (same result). Configurable threshold (`max_repeated`, default 3)
  and action (`warn` via `ModelRetry` or `error` via `StuckLoopError`). Per-run state isolation via `for_run()`.
  Enabled by default via `stuck_loop_detection=True` in `create_deep_agent()`
- **BM25-ranked history search** — `search_conversation_history` now uses BM25 ranking instead of naive
  substring matching. Multi-word queries are tokenized — each word is scored independently, rare terms
  (high IDF) rank higher than common ones, and results are sorted by relevance score. Zero dependencies
  (pure Python implementation using the standard Elasticsearch/Lucene BM25 formula)
- **Expanded context file discovery** — `DEFAULT_CONTEXT_FILENAMES` now discovers 7 convention file types
  instead of 2: added `CLAUDE.md`, `.cursorrules`, `.github/copilot-instructions.md`, `CONVENTIONS.md`,
  and `CODING_GUIDELINES.md` alongside the existing `AGENTS.md` and `SOUL.md`. Subagent allowlist updated
  to include `CLAUDE.md` (project instructions relevant to subagents)

### Changed

- **Eviction uses `after_tool_execute` hook instead of history processor** — large tool outputs are now
  intercepted **before** they enter message history via the new `EvictionCapability`, rather than after
  the fact via `EvictionProcessor` (history processor). This means the full output never bloats the message
  list in memory. The old `EvictionProcessor` is preserved for backward compatibility but
  `create_deep_agent()` now uses `EvictionCapability` by default
- **Orphan repair uses `before_model_request` hook instead of history processor** — `PatchToolCallsCapability`
  replaces `patch_tool_calls_processor` as the default in `create_deep_agent()`. Integrates with the
  pydantic-ai capabilities system instead of raw history processors. The old processor function is preserved
  for backward compatibility and standalone use

### Fixed

- **Browser tools never require approval** — `BrowserCapability` now uses `prepare_tools` to force
  `kind='function'` on all browser tools (navigate, click, execute_js, etc.), ensuring they never
  trigger approval dialogs even if a user adds browser tool names to `approve_tools`
- **Checkpoint per-run state isolation** — `CheckpointMiddleware` now implements `for_run()` to return a
  fresh instance per agent run with isolated `_turn_counter` and `_latest_messages`. Previously, concurrent
  `agent.run()` calls on the same agent would share and corrupt checkpoint state

## [0.3.7] - 2026-04-11

### Fixed

- **`web_search` not working for non-Anthropic and OpenRouter models** — `duckduckgo` local fallback was not
  included in `cli` / `tui` extras, so `WebSearch` silently fell back to native-only mode. Models accessed
  through OpenRouter (or any provider without native web-search support) would report no `web_search` tool.
  `pydantic-ai-slim[duckduckgo]` is now bundled in both `cli` and `tui` extras

## [0.3.6] - 2026-04-11

### Added

- **One-command installer (`install.sh`)** — macOS and Linux users can now install pydantic-deep without knowing
  Python or pip. A single curl command installs uv (if missing) and then the CLI:
  ```bash
  curl -fsSL https://raw.githubusercontent.com/vstorm-co/pydantic-deep/main/install.sh | bash
  ```
  The script auto-detects uv, falls back to installing it via `astral.sh/uv`, then runs
  `uv tool install "pydantic-deep[cli]"`. Verifies the installation and prints PATH instructions
  if the binary is not immediately discoverable
- **`pydantic-deep update` command** — self-update command that upgrades to the latest PyPI release.
  Uses `uv tool upgrade pydantic-deep` when uv is available; falls back to
  `pip install --upgrade "pydantic-deep[cli]"` otherwise
- **Startup update notifications** — on every CLI invocation the tool silently checks PyPI for a newer
  version and prints a one-line notice when one is found:
  ```
  Update available: v0.3.6 → v0.3.7  Run: pydantic-deep update
  ```
  The check is backed by a 24-hour file cache (`~/.pydantic-deep/update_check.json`) so the network
  is only hit once per day. A 2-second timeout ensures the check never blocks startup

### Fixed

- **`ModuleNotFoundError: No module named 'textual'` on fresh install** — `textual` was listed under the
  `tui` optional extra but missing from `cli`, so `uv tool install "pydantic-deep[cli]"` produced a broken
  installation that crashed immediately on launch. `textual>=3.0.0` is now included in both `cli` and `tui`

## [0.3.5] - 2026-04-10

### Added

- **Headless runner (`pydantic-deep run`)** — new CLI command for non-interactive task execution. Designed for
  benchmarks (Terminal Bench), CI/CD pipelines, and scripted automation. All feature flags mirror the TUI and default
  from `.pydantic-deep/config.toml`. Supports `--task-file`, `--json`, `--max-turns`, `--timeout`, `--model`,
  `--working-dir`, `--web-search/--no-web-search`, `--web-fetch/--no-web-fetch`, `--thinking`, `--todo/--no-todo`,
  `--subagents/--no-subagents`, `--skills/--no-skills`, `--plan/--no-plan`, `--memory/--no-memory`,
  `--teams/--no-teams`, `--context/--no-context`, `--temperature`
- **Harbor adapter (`apps/harbor/`)** — `BaseInstalledAgent` implementation for Terminal Bench evaluation via Harbor.
  Installs pydantic-deep in the container via `uv`, runs tasks with `pydantic-deep run --json`, parses JSON output for
  usage stats. Supports model name conversion (`provider/model` to `provider:model`), API key forwarding, custom git ref
  via `PYDANTIC_DEEP_GIT_REF` env var. All headless feature flags configurable via Harbor `--ak` kwargs (e.g.
  `--ak web_search=false`)
- **`DEFAULT_USAGE_LIMITS`** — framework-wide `UsageLimits(request_limit=None)` exported from `pydantic_deep.deps`.
  Removes pydantic-ai's default 50-request limit which caused `UsageLimitExceeded` crashes on complex benchmark tasks.
  Applied in both headless runner and TUI
- **Docker sandbox for CLI (`--sandbox docker`)** — run the agent inside a Docker container for isolated code execution.
  The TUI and headless runner stay in the terminal but all file operations and shell commands execute inside the
  container. The working directory is mounted at `/workspace` (read-write) so project files are shared. Container is
  automatically stopped on exit. Supports both `pydantic-deep tui --sandbox docker` and
  `pydantic-deep run "task" --sandbox docker`. Configurable via `sandbox` and `sandbox_image` in
  `.pydantic-deep/config.toml`. Requires `pydantic-ai-backend[docker]`
- **Named workspaces (`--workspace <name>`)** — shared Docker environment that persists across threads. Installed
  packages and any state outside the mounted volume survive between sessions. Multiple conversation threads can share
  the same workspace — each thread keeps its own history (`.pydantic-deep/sessions/{thread_id}/messages.json`) while the
  Docker container and its state are shared. Usage: `pydantic-deep tui --workspace ml-env` or
  `pydantic-deep run "task" --workspace dev`. Implies `--sandbox docker` automatically
- **Workspace management (`pydantic-deep sandbox`)** — new subcommands: `sandbox list` shows Docker workspaces for the
  current project with status/image/creation date; `sandbox stop <name>` stops a specific workspace;
  `sandbox stop all --rm` stops and removes all project workspaces
- **Browser automation (`BrowserCapability`)** — Playwright-based browser control via `pydantic-deep[browser]`.
  Gives agents 9 tools: `navigate`, `click`, `type_text`, `get_text`, `screenshot`, `scroll`, `go_back`, `go_forward`,
  `execute_js`. Single-tab design with automatic popup interception. Domain allowlist, content truncation, and optional
  auto-screenshot on navigate. Browser lifecycle managed by `wrap_run` — Chromium starts before agent runs, closes
  after (on success, exception, or cancellation). Requires `playwright>=1.40.0` and `playwright install chromium`.
  Optional `html2text>=2020.1` for better content extraction
- **`--browser/--no-browser` CLI flag** — opt-in browser automation for `pydantic-deep tui` and `pydantic-deep run`.
  Disabled by default (`include_browser = false`). Enable with `--browser` flag or `include_browser = true` in
  `config.toml`
- **`--browser-headless/--browser-headed` CLI flag** — control browser window visibility. Default is headed (window
  visible, `browser_headless = false`). Use `--browser-headless` for CI/scripted use, `--browser-headed` for
  interactive sessions
- **`BrowseResult` type** — structured result from browser operations: `url`, `title`, `content`, `screenshot`,
  `error` fields. Exported from `pydantic_deep.types`
- **`browser` extras** — `pip install 'pydantic-deep[browser]'` installs `playwright>=1.40.0` and `html2text>=2020.1`.
  Added to `all` extras

### Changed

- **`create_cli_agent()` feature flags now read from config.toml** — `include_skills`, `include_plan`, `include_memory`,
  `include_subagents`, `include_todo`, `context_discovery`, `web_search`, `web_fetch`, `thinking`, `include_teams`, and
  `temperature` all default to `None` (= read from config). Previously hardcoded to `True`, ignoring config.toml values.
  Explicit parameters still override config
- **Headless runner uses same defaults as TUI** — `pydantic-deep run` no longer hardcodes `include_plan=False` and
  `include_memory=False`. All features inherit from config.toml, overridable via CLI flags
- **Headless runner auto-initializes `.pydantic-deep/`** — `pydantic-deep run` now calls `ensure_initialized()` before
  creating the agent, ensuring config, skills, and memory scaffolding exist in the working directory
- **Default model changed to `anthropic:claude-opus-4-6`** — updated in `CliConfig`, `init.py` template, and model
  picker
- **Model picker updated** — 25 OpenRouter models (Anthropic, OpenAI, Google, Z-AI, X-AI), refreshed
  Anthropic/OpenAI/Google direct models
- **Prompt stack deduplicated** — `BASE_PROMPT` was included twice (framework + CLI layer). CLI prompt now only adds
  CLI-specific sections (Path Handling, Exactness, Provided Data). Removed redundant "Bias Towards Action", "Avoid
  Over-Engineering", "Parallel Tool Calls" from CLI layer (already in BASE_PROMPT)
- **Prompt streamlined** — removed "Executing Actions with Care" section (approve_tools handles this mechanically),
  merged "Tone and Formatting" + "Progress Updates" into 3-line "Output" section, added 5-step workflow (Research →
  Understand → Implement → Verify → Retry), strengthened error handling with "NEVER declare done if last test failed"
- **Directory tree excludes `.pydantic-deep/`** — sessions, logs, and config internals no longer leak into the system
  prompt tree
- **TUI: all tool calls now visible** — todo tools (`read_todos`, `write_todos`, `add_todo`, `update_todo_status`,
  `remove_todo`) are no longer hidden from the UI
- **TUI: side panel visible by default** — shows on startup when terminal >= 100 chars wide, responsive to resize
- **TUI: default subagents shown on startup** — side panel lists available subagents (planner, research) with idle
  status before any delegation occurs
- **TUI: thinking content displayed** — model thinking/reasoning streamed live as dimmed text, collapsed to summary
  after completion
- **TUI: per-turn token usage** — each assistant response shows `in:X · out:Y · total:Z · reqs:N` below the text
- **TUI: header shows cumulative tokens and cost** — `in:45K out:3K · $0.12` in the top bar after responses
- **TUI: all notifications logged** — `DeepApp.notify()` override and `notify_error/warning/success` helpers write to
  per-session log file
- **TUI: session saved on error** — `_save_session()` moved to `finally` block so `messages.json` is persisted even
  after agent crashes or cancellation
- **TUI: subagent output fully logged** — `tool_log.jsonl` stores up to 20K chars for subagent task results (was 2K),
  debug log includes full output for task tool calls

### Fixed

- **`ensure_initialized()` now always populates missing scaffolding** — previously only ran `init_project` when
  `.pydantic-deep/` didn't exist at all. Now always runs idempotent init, so missing built-in skills, config, or memory
  templates are added to existing directories
- **`contextlib` scope error in chat.py** — `import contextlib` was inside `except` block but used in `finally`. Moved
  to top-level import
- **CostUpdated message routing** — `_on_cost_update` callback now posts to `app.screen` (not `app`), fixing Textual
  message routing so `ChatScreen.on_cost_updated` actually receives cost/token updates

## [0.3.4] - 2026-04-09

### Changed

- **Merged TUI into `apps/cli/`** — removed old interactive/non-interactive CLI, TUI is now the default interface.
  Running `pydantic-deep` without a subcommand launches the TUI
- **Redesigned `/improve` pipeline** — added `UserFactInsight` and `AgentLearningInsight` extraction categories; relaxed
  synthesis rules so user facts from a single session are accepted; MEMORY.md is now the primary target for personal
  facts and agent learnings
- **Configurable context file paths in `/improve`** — `ImprovementAnalyzer` accepts `context_files` mapping for
  backend-agnostic path resolution (supports LocalBackend, Docker, etc.)
- **Structured tool call logging** — sessions now save `tool_log.jsonl` alongside `messages.json` for richer execution
  traces (inspired by Meta-Harness)
- **Raw tool traces in synthesis** — synthesis agent receives both extracted insights and raw tool call sequences,
  following Meta-Harness finding that raw traces >> summaries
- **Debug logging** — per-session logs in `.pydantic-deep/logs/` with `latest.log` symlink
- **Added `/config` command** to TUI for viewing and updating config.toml

### Fixed

- **`/improve` crash** — unescaped `{}` in prompt templates caused `str.format()` errors
- **`/improve` silent failures** — extraction errors were swallowed; now reports `failed_sessions` count and
  `last_error`
- **`/improve` API key missing** — improve pipeline now loads keys from keystore before creating agents
- **`/improve` wrong model** — used hardcoded OpenRouter fallback; now uses current agent's model
- **`/improve` MEMORY.md path mismatch** — wrote to project root instead of `.pydantic-deep/main/MEMORY.md`

### Removed

- Old interactive CLI (`apps/cli/interactive.py`, `non_interactive.py`, `display.py`, etc.)
- `run` and `chat` CLI commands (replaced by TUI)
- Dead `agent_worker.py` code

## [0.3.3] - 2026-04-02

### Changed

- Default models changed: main agent `anthropic:claude-opus-4-6`, subagents `anthropic:claude-sonnet-4-6`, summarization
  `anthropic:claude-haiku-4-5-20251001`
- Replaced `include_general_purpose_subagent` with `include_builtin_subagents` — adds a built-in "research" deep agent (
  filesystem + web + memory) instead of a plain pydantic-ai Agent
- **Subagents are now deep agents by default** — all subagents (built-in and custom) are created via
  `create_deep_agent()` with filesystem, web, memory, eviction, and patch support. Custom subagents that don't specify
  `agent` or `agent_factory` automatically get the deep agent factory
- Removed `skills` parameter from `create_deep_agent()` — pass pre-loaded skills via `SkillsToolset(skills=[...])` in
  the `toolsets` parameter instead
- Removed `image_support` parameter from `create_deep_agent()` — image support is now always enabled (multimodal
  `read_file` for `.png`, `.jpg`, `.gif`, `.webp`)
- Changed `include_memory` default from `False` to `True` — persistent agent memory is now enabled by default
- Changed `max_nesting_depth` default from `0` to `1` — subagents can now spawn their own subagents by default
- Simplified context file discovery to `AGENTS.md` and `SOUL.md` only (removed DEEP.md, AGENT.md, CLAUDE.md). Subagents
  see only `AGENTS.md`; `SOUL.md` is main-agent-only
- Replaced `include_web` with separate `web_search` and `web_fetch` parameters (both default `True`) — allows
  independent control of WebSearch and WebFetch capabilities
- Added `thinking` parameter (default `"high"`) — enables model thinking/reasoning via pydantic-ai `Thinking`
  capability. Supports `True`/`False`/`"minimal"`/`"low"`/`"medium"`/`"high"`/`"xhigh"`
- Changed `eviction_token_limit` default from `None` to `20_000` — large tool outputs automatically saved to files
- Changed `patch_tool_calls` default from `False` to `True` — orphaned tool calls fixed automatically
- `BASE_PROMPT` is now always included in system prompt — `instructions` parameter appends to it instead of replacing it
- Moved `model_settings` parameter next to `model` in `create_deep_agent()` signature

### Added

- 5 new hook events: `BEFORE_RUN`, `AFTER_RUN`, `RUN_ERROR`, `BEFORE_MODEL_REQUEST`, `AFTER_MODEL_REQUEST` — maps to
  pydantic-ai lifecycle hooks for session tracking, LLM call logging, and error alerts
- `compact_conversation` tool — agent can manually trigger context compression with optional focus topic (uses
  `ContextManagerCapability.request_compact()`)
- Anthropic prompt caching enabled by default (`anthropic_cache_instructions`, `anthropic_cache_tool_definitions`,
  `anthropic_cache_messages`) — silently ignored by non-Anthropic models
- Built-in "research" subagent (`pydantic_deep/subagents.py`) — full deep agent for codebase exploration and web
  research
- `upload_files()` batch method on `DeepAgentDeps` for uploading multiple files at once
- `approve_tools` config in CLI — configure which tools require user approval (default: `["execute"]`). Set via
  `/config set approve_tools "execute,write_file,edit_file"` or in `config.toml`
- Skills as slash commands in CLI — type `/code-review` to activate a skill directly from the picker
- 3-tier skill discovery: built-in (`apps/cli/skills/`) → user (`~/.pydantic-deep/skills/`) → project (
  `.pydantic-deep/skills/`), with later sources overriding earlier by name
- Provider setup wizard in CLI — first-run auto-detects missing API keys and guides through provider selection (
  Anthropic, OpenAI, Google, OpenRouter) with key input. Keys saved to `.pydantic-deep/.env`
- `/provider` slash command — switch AI provider and model mid-session
- `/config` slash command in CLI — view and change settings interactively (e.g., `/config set include_teams true`)
- `web_search`, `web_fetch`, `thinking_effort`, and `include_teams` as configurable options in `config.toml`
- ACP (Agent Client Protocol) adapter in `apps/acp/` — enables pydantic-deep agents to run inside editors like Zed.
  Streaming text deltas, tool call visibility with arguments and results, model switching, session management,
  auto-detect provider from API keys
- Enhanced `BASE_PROMPT` with Claude Code-inspired sections: code quality, executing actions with care, tone and
  formatting
- MCP documentation (`docs/advanced/mcp.md`) — shows how to use pydantic-ai's `MCP` capability with deep agents
- Documentation for `BackendSkillsDirectory` in `docs/concepts/skills.md` — covers usage with `StateBackend`,
  `LocalBackend`, `DockerSandbox`, and mixed configurations
- Cross-reference to backend-aware skills in `docs/concepts/backends.md`

### Fixed

- CLI bundled skills fallback path — was resolving to non-existent `apps/pydantic_deep/bundled_skills`, now correctly
  points to `apps/cli/skills/`

## [0.3.2] - 2026-03-31

### Added

- `capabilities` parameter on `create_deep_agent()` for user-provided
  capabilities ([#55](https://github.com/vstorm-co/pydantic-deepagents/pull/55))

### Fixed

- Pre-existing mypy `unused-ignore` error in `spec.py`

## [0.3.1] - 2026-03-31

### Changed

- Bump minimum `pydantic-ai-slim` to `>=1.74.0`
- Toolset `get_instructions()` methods are now `async` and return `list[str] | None` to match pydantic-ai 1.74.0's
  `AbstractToolset` signature
- Removed manual `get_instructions()` calls from `create_deep_agent()` — pydantic-ai 1.74.0's `CombinedToolset` handles
  this automatically
- Capability inner instruction callables are now `async` to properly `await` toolset `get_instructions()`

### Fixed

- Compatibility with pydantic-ai 1.74.0 which changed `CombinedToolset.get_instructions()` to use
  `asyncio.gather` ([#53](https://github.com/vstorm-co/pydantic-deepagents/issues/53))

## [0.3.0] - 2026-03-30

### Breaking Changes

- **Full migration to pydantic-ai Capabilities API** (requires `pydantic-ai>=1.71.0`)
- Removed `pydantic-ai-middleware` dependency entirely — replaced by `pydantic-ai-shields>=0.3.0`
- `HooksMiddleware` renamed to `HooksCapability` (extends `AbstractCapability`), moved from
  `pydantic_deep.middleware.hooks` to `pydantic_deep.capabilities.hooks`
- `CheckpointMiddleware` now extends `AbstractCapability` instead of `AgentMiddleware`
- Removed `LoopDetectionMiddleware` old API — now extends `AbstractCapability`
- Removed `web_search_provider`, `permission_handler`, `middleware_context` params from `create_deep_agent()`
- Removed `toolsets/web.py` — use pydantic-ai built-in `WebSearch()` and `WebFetch()` instead
- Removed ALL old middleware exports from `__init__.py` (`AgentMiddleware`, `MiddlewareAgent`, `MiddlewareChain`, etc.)
- Removed deprecated types: `LegacySkill`, `SkillFrontmatter`, `SkillDirectory`
- Tool hook method names changed: `before_tool_call` → `before_tool_execute`, `after_tool_call` → `after_tool_execute`,
  `on_tool_error` → `on_tool_execute_error`
- Deny semantics changed: `ToolPermissionResult(DENY)` → `raise ModelRetry("reason")`
- Moved `cli/` to `apps/cli/` — import paths changed from `cli.` to `apps.cli.`
- Removed `apps/harbor_agent/` and `apps/swebench_agent/`

### Added

- 5 internal capabilities: `SkillsCapability`, `ContextFilesCapability`, `MemoryCapability`, `TeamCapability`,
  `PlanCapability`
- **`DeepAgent`** and **`DeepAgentSpec`** — declarative YAML/JSON agent specs via `DeepAgent.from_file("agent.yaml")`
  and `DeepAgent.from_spec({...})`
- `on_eviction` callback on `EvictionProcessor` — notifies when tool output is saved to file
- `on_before_compress`, `on_after_compress` callbacks forwarded through `create_deep_agent()`
- CLI observability: compression start notice, eviction notice, active tasks in status bar
- **Teams + subagents integration** — `create_team_toolset()` accepts `registry`, `task_fn`, `task_manager`,
  `agent_factory` to delegate team member execution to the subagent engine. `spawn_team` registers members as subagents,
  `assign_task` runs them via `task()` in async mode
- Capabilities-first architecture: everything is now an `AbstractCapability`

### Changed

- `CostTracking` from `pydantic-ai-shields` replaces `CostTrackingMiddleware`
- `ContextManagerCapability` from `pydantic-ai-summarization` replaces `ContextManagerMiddleware`
- All capabilities use `before_tool_execute`/`after_tool_execute` instead of old `before_tool_call`/`after_tool_call`
- Web tools now use pydantic-ai built-in `WebSearch()` and `WebFetch()` capabilities
- Requires `subagents-pydantic-ai>=0.2.0` (custom agent support)

### Fixed

- **`examples/full_app`**: `DeepAgentDeps` was passed `checkpoint_store=` which is not a valid field —
  removed ([#40](https://github.com/vstorm-co/pydantic-deepagents/issues/40))
- **Skills URI leak in sandbox** — skill URIs (host filesystem paths) were exposed in system prompt and `load_skill`
  output, causing agents in Docker sandboxes to attempt `read_file` on non-existent paths. URIs are now omitted from
  prompts — agents use `load_skill`/`read_skill_resource` tools
  instead ([#43](https://github.com/vstorm-co/pydantic-deepagents/issues/43))
- **`examples/full_app`**: Updated from old middleware API to capabilities (`AuditCapability`, `PermissionCapability`)
- **`apps/deepresearch`**: Updated from old middleware API to capabilities

### Removed

- `pydantic_deep/middleware/` directory (hooks moved to `pydantic_deep/capabilities/hooks.py`)
- `pydantic_deep/toolsets/web.py` (replaced by pydantic-ai built-in)
- `apps/harbor_agent/`, `apps/swebench_agent/`
- `tests/test_web_toolset.py`, `tests/test_cost_tracking.py`, `tests/test_middleware_integration.py`
- Old middleware exports: `AgentMiddleware`, `MiddlewareAgent`, `MiddlewareChain`, `MiddlewareContext`,
  `PermissionHandler`, `ToolDecision`, `ToolPermissionResult`, `CostTrackingMiddleware`, `CostCallback`,
  `create_cost_tracking_middleware`, `UsageCallback`, `create_context_manager_middleware`, `before_run`, `after_run`,
  `before_model_request`, `before_tool_call`, `after_tool_call`, `on_tool_error`, `on_error`
- Deprecated types: `LegacySkill`, `SkillFrontmatter`, `SkillDirectory`
- `web-tools` optional dependency group

## [0.2.21] - 2026-03-19

### Fixed

- **Toolset instructions not injected into system prompt** — `SkillsToolset`, `ContextToolset`, `AgentMemoryToolset`,
  and user-provided toolsets (e.g. `LocalContextToolset`) defined `get_instructions()` but pydantic-ai's
  `AbstractToolset` does not call it automatically. Instructions were silently missing from the agent's system prompt.
  Fixed by calling `get_instructions()` explicitly in `dynamic_instructions()` and removing unnecessary `async` from the
  method signatures. ([#42](https://github.com/vstorm-co/pydantic-deepagents/pull/42),
  by [@ilayu-blip](https://github.com/ilayu-blip))

## [0.2.20] - 2026-03-11

### Fixed

- **CLI: multi-byte UTF-8 input garbled in raw mode** — Chinese, Japanese, Korean and other multi-byte characters
  appeared as replacement characters when typed in interactive mode. `_read_raw_key()` now reads the full UTF-8 byte
  sequence before decoding. ([#38](https://github.com/vstorm-co/pydantic-deepagents/pull/38),
  by [@huapingchen](https://github.com/huapingchen))

### Changed

- Updated `pydantic-ai-backend` dependency to `>=0.1.14` — `DockerSandbox` now resolves relative paths against
  `work_dir` instead of `/`, and returns clean error messages for missing
  files ([pydantic-ai-backend#22](https://github.com/vstorm-co/pydantic-ai-backend/pull/22),
  by [@ret2libc](https://github.com/ret2libc))
- Updated `pydantic-ai-middleware` dependency to `>=0.2.3` — `MiddlewareAgent.iter()` now calls `after_run` and
  `on_error` middleware ([pydantic-ai-middleware#17](https://github.com/vstorm-co/pydantic-ai-middleware/issues/17))

## [0.2.19] - 2026-03-06

### Fixed

- **`deps.todos` not synchronized with todo tools** — `create_todo_toolset()` was called without `storage=` parameter,
  creating an isolated `TodoStorage` disconnected from `deps.todos`. Todo tools wrote to their own internal list while
  `deps.todos`, `get_todo_prompt()`, and `share_todos` remained empty. Fixed with `_DepsTodoProxy` pattern that
  delegates reads/writes to `deps.todos` at runtime. Subagent todo toolsets use the same proxy pattern for
  consistency. ([#35](https://github.com/vstorm-co/pydantic-deepagents/issues/35))
- **`Model` objects discarded for subagents** — `isinstance(model, str)` guard silently replaced `Model` objects (e.g.
  `TestModel()`, `AnthropicModel()`) with `DEFAULT_MODEL`. Subagents always used `anthropic:claude-sonnet-4-6`
  regardless of the model passed to `create_deep_agent()`. Changed to
  `model or DEFAULT_MODEL`. ([#34](https://github.com/vstorm-co/pydantic-deepagents/pull/34),
  by [@ret2libc](https://github.com/ret2libc))
- **Binary file upload tests flaky on Linux** — `chardet` detected encoding for small byte sequences on Linux but not
  macOS, causing `line_count` assertions to fail in CI. Tests now mock `chardet.detect` for deterministic behavior.

### Changed

- Updated `subagents-pydantic-ai` dependency to `>=0.0.8` — accepts `Model` objects in `create_subagent_toolset()` and
  fixes `ask_parent` in async mode

## [0.2.18] - 2026-02-27

### Added

- **Custom tool descriptions** — all toolset factories now accept `descriptions: dict[str, str] | None` parameter to
  override any tool's built-in description. Applies to `SkillsToolset`, `AgentMemoryToolset`, `CheckpointToolset`,
  `create_team_toolset()`, `create_plan_toolset()`, and `create_web_toolset()`
- **Custom commands** — user-triggered slash commands from `.md` files (`cli/commands/`). Built-in commands: `/commit`,
  `/pr`, `/review`, `/test`, `/fix`, `/explain`. Three-scope discovery: built-in → user → project
- **Diff viewer for file approvals** (`cli/diff_display.py`) — colored unified diffs with gutter bars (▌ green/red) for
  `edit_file`, line-numbered head/tail previews for `write_file`, shown before Y/N/A approval prompt
- **Tool call success/error rendering** (`cli/tool_display.py`) — `render_tool_call_success()` shows ✓ with elapsed time
  in green, `render_tool_call_error()` shows ✗ in red
- **New glyphs** (`cli/theme.py`) — `gutter_bar` (▌), `box_vertical` (│), `progress_filled` (█), `progress_empty` (░)
  with ASCII fallbacks

### Changed

- **CLI streaming** — single `Live` context that starts as a braille spinner and transitions to Markdown rendering
  seamlessly, eliminating the visual gap between thinking and text output
- **CLI status bar** — visual context progress bar (`█████░░░░░ 45%`) with threshold colors (green <60%, amber 60–85%,
  red >85%) and auto-approve indicator
- **CLI tool calls** — pending → success (✓) or error (✗) state transitions with elapsed time display; reduced tool
  result preview from 6 to 3 lines
- **CLI file approval** — `edit_file` shows colored unified diff with `+N -M` stats; `write_file` shows syntax-aware
  preview with line numbers (head 20 / tail 10 for large files)
- **BrailleSpinner** — bold accent color for status text, muted for elapsed time
- **Moved tool-specific guidance from system prompt to tool descriptions** — All local toolsets now use exported
  description constants wired via `@toolset.tool(description=CONSTANT)`:
    - **Skills**: `LIST_SKILLS_DESCRIPTION`, `LOAD_SKILL_DESCRIPTION`, `READ_SKILL_RESOURCE_DESCRIPTION`,
      `RUN_SKILL_SCRIPT_DESCRIPTION`
    - **Memory**: `READ_MEMORY_DESCRIPTION`, `WRITE_MEMORY_DESCRIPTION`, `UPDATE_MEMORY_DESCRIPTION`
    - **Checkpointing**: `SAVE_CHECKPOINT_DESCRIPTION`, `LIST_CHECKPOINTS_DESCRIPTION`, `REWIND_TO_DESCRIPTION`
    - **Plan**: `ASK_USER_DESCRIPTION`, `SAVE_PLAN_DESCRIPTION`
    - **Teams**: `SPAWN_TEAM_DESCRIPTION`, `ASSIGN_TASK_DESCRIPTION`, `CHECK_TEAMMATES_DESCRIPTION`,
      `MESSAGE_TEAMMATE_DESCRIPTION`, `DISSOLVE_TEAM_DESCRIPTION`
- **Slimmed CLI system prompt** (`cli/prompts.py`) — Reduced from ~350 lines to ~100 lines. Removed `_SHELL_SECTION`,
  `_GIT_SECTION`, `_DEPENDENCIES_SECTION`, `_PLANNING_SECTION`, `_DELEGATION_SECTION` (all moved to tool descriptions in
  pydantic-ai-backend and pydantic-ai-subagents). Kept only general behavioral guidance: path handling, exactness
  requirements, code quality, verification.
- **Simplified `build_cli_instructions()`** — Removed tool-conditional sections. `include_execute`, `include_todo`,
  `include_subagents` params kept for backwards compatibility but are now no-ops.
- Updated `pydantic-ai-backend` dependency to `>=0.1.8` — fixes `DockerSandbox.grep_raw()` defaulting to `/` instead of
  `.`, which caused grep without explicit path to scan the entire container
  filesystem ([pydantic-ai-backend#13](https://github.com/vstorm-co/pydantic-ai-backend/pull/13))
- **Repository restructuring** — moved `swebench_agent/`, `harbor_agent/`, and `deepresearch/` into `apps/` directory.
  Internal imports converted to relative. Core library (`pydantic_deep/`) and CLI (`cli/`) remain at root.

### Fixed

- **Command injection in `BackendSkillScriptExecutor`** — shell metacharacters in skill script arguments are now escaped
  with `shlex.quote()` ([#31](https://github.com/vstorm-co/pydantic-deepagents/issues/31))

### Removed

- **Textual TUI** — removed `cli/tui/` directory (7 files), `pydantic-deep tui` command, and `textual` optional
  dependency due to fundamental scrolling issues with touchpad/wheel input

## [0.2.17] - 2026-02-17

### Added

- **Checkpointing & Rewind**: Save conversation state at intervals, rewind to any checkpoint, or fork into a new
  session. `Checkpoint`, `CheckpointStore` protocol, `InMemoryCheckpointStore`, `FileCheckpointStore`,
  `CheckpointMiddleware` (auto-save every tool/turn/manual), `CheckpointToolset` (save_checkpoint, list_checkpoints,
  rewind_to tools), `RewindRequested` exception for app-level rewind, `fork_from_checkpoint()` utility for session
  forking. Enable via `include_checkpoints=True`.
- **Agent Teams**: Shared TODO lists with asyncio-safe claiming and dependency blocking (`SharedTodoList`), peer-to-peer
  message bus (`TeamMessageBus`), team coordinator (`AgentTeam`) with spawn, assign, broadcast, wait_all, dissolve
  operations, `create_team_toolset()` factory. Enable via `include_teams=True`.
- **Claude Code-Style Hooks**: `Hook`, `HookEvent` enum (PRE_TOOL_USE, POST_TOOL_USE, POST_TOOL_USE_FAILURE),
  `HookInput`, `HookResult`, `HooksMiddleware`. Execute shell commands or Python handlers on tool lifecycle events. Exit
  code conventions (0=allow, 2=deny), regex matchers, timeout, and background execution support.
- **Persistent Memory**: `AgentMemoryToolset` with read_memory, write_memory, update_memory tools. Per-agent MEMORY.md
  files auto-injected into system prompt (first 200 lines). Per-subagent memory with opt-out via
  `extra={"memory": False}`. Enable via `include_memory=True`.
- **Context Files**: `ContextToolset` for auto-discovering and injecting DEEP.md, AGENTS.md, CLAUDE.md, SOUL.md into
  system prompt. Subagent filtering (only DEEP.md + AGENTS.md forwarded). Per-subagent context_files via SubAgentConfig.
  Truncation support. Enable via `context_files=[...]` or `context_discovery=True`.
- **Eviction Processor**: `EvictionProcessor` saves large tool outputs (>20k tokens by default) to files and replaces
  with head/tail preview + file reference. Keeps conversation lean while preserving data access. Enable via
  `eviction_token_limit=20000`.
- **Output Styles**: 4 built-in styles (concise, explanatory, formal, conversational), custom `OutputStyle` instances,
  file-based styles with YAML frontmatter, directory discovery via `styles_dir`. Apply via `output_style="concise"`.
- **Plan Mode**: Built-in 'planner' subagent with `ask_user` (interactive options with headless mode) and `save_plan`
  tools. Plans saved as markdown files to configurable `plans_dir`. Enable via `include_plan=True` (default).
- **Patch Tool Calls Processor**: Fixes orphaned tool calls when resuming interrupted conversations by injecting
  synthetic "Tool call was cancelled." responses. Enable via `patch_tool_calls=True`.
- **`BASE_PROMPT`**: Exported default system prompt for inspection and customization.
- **`share_todos` on `DeepAgentDeps`**: When True, subagents share the same todo list reference as the parent agent.
  Default False (isolated).
- **`subagent_extra_toolsets` parameter**: Pass additional toolsets (e.g., MCP servers) to all subagents via
  `create_deep_agent()`.
- **`subagent_registry` parameter**: Optional `DynamicAgentRegistry` for runtime agent creation via
  `create_agent_factory_toolset`.

### Changed

- **Skills system rewrite**: Complete refactor from single-file `skills.py` to protocol-based `skills/` package. New
  abstractions: `Skill` dataclass, `SkillResource` / `SkillScript` / `SkillsDirectory` protocols, `SkillWrapper`. Two
  implementations: file-based (`FileBasedSkillResource`, `LocalSkillScriptExecutor`) and backend-based (
  `BackendSkillResource`, `BackendSkillScriptExecutor`, `BackendSkillsDirectory`). Skill scripts for executable actions.
  Comprehensive exception hierarchy (`SkillException`, `SkillNotFoundError`, `SkillValidationError`,
  `SkillResourceNotFoundError`, `SkillResourceLoadError`, `SkillScriptExecutionError`).
- **Cost tracking enabled by default**: `cost_tracking=True` via `CostTrackingMiddleware` from pydantic-ai-middleware.
  New params: `cost_budget_usd` (raises `BudgetExceededError`), `on_cost_update` callback.
- **Context manager enabled by default**: `context_manager=True` enables `ContextManagerMiddleware` for automatic token
  tracking and auto-compression when approaching token budget. New params: `context_manager_max_tokens` (default
  200,000), `on_context_update` callback.
- **Middleware integration**: New `middleware`, `permission_handler`, `middleware_context` params for composable
  `AgentMiddleware` chains via pydantic-ai-middleware. Agent automatically wrapped in `MiddlewareAgent` when any
  middleware is active.
- Updated `pydantic-ai-todo` dependency to `>=0.1.8` (todo IDs in system prompt, improved active_form descriptions)
- Updated `subagents-pydantic-ai` dependency to `>=0.0.5`
- Updated `pydantic-ai-middleware` dependency to `>=0.2.1`
- Updated `summarization-pydantic-ai` dependency to `>=0.0.3`
- Updated `pydantic-ai-backend` dependency to `>=0.1.7`

### Documentation

- Added 11 new advanced feature guides: checkpointing, teams, hooks, memory, context-files, eviction, cost-tracking,
  middleware, output-styles, plan-mode, multi-user
- Updated agents, toolsets, and skills concept pages for all new features
- Updated API reference (agent, toolsets, types) with all new parameters and types
- Comprehensive CLAUDE.md with full architecture documentation

## [0.2.16] - 2025-02-12

### Changed

- Updated `subagents-pydantic-ai` dependency from `>=0.0.3` to `>=0.0.4` — fixes
  `AttributeError: 'Agent' object has no attribute '_register_toolset'` compatibility issue with pydantic-ai >=
  1.38 ([subagents-pydantic-ai#5](https://github.com/vstorm-co/subagents-pydantic-ai/issues/5))
- Removed `_register_toolset` mock from test fixtures (`tests/conftest.py`) — no longer needed after subagents fix

## [0.2.15] - 2025-02-07

### Added

- **`retries` parameter for `create_deep_agent()`**: New explicit parameter (default: 3) that controls max retries for
  tool calls across all built-in toolsets. When the model sends invalid arguments (e.g. missing a required field), the
  validation error is fed back and the model can self-correct up to `retries` times. Previously, console tools (
  including `write_file`) were hardcoded to 1 retry via `FunctionToolset` default, making self-correction nearly
  impossible. ([#25](https://github.com/vstorm-co/pydantic-deepagents/issues/25))
- **llms.txt support**: Added `mkdocs-llmstxt` plugin to generate `/llms.txt` and `/llms-full.txt` files following
  the [llmstxt.org](https://llmstxt.org/) standard ([#26](https://github.com/vstorm-co/pydantic-deepagents/issues/26))
- Added `mkdocs-llmstxt>=0.2.0` to docs dependency group

### Fixed

- **`write_file` tool exceeded max retries count of 1**: The `write_file` (and all other console tools) had
  `max_retries=1` hardcoded via `FunctionToolset` default. When the model omitted a required argument like `content`, it
  got only 1 retry attempt before raising `UnexpectedModelBehavior`. The `retries` parameter passed to
  `create_deep_agent()` was forwarded to the `Agent` constructor but never propagated to toolsets. Now `retries` is
  applied to the console toolset and all its tools, and the default is raised from 1 to
  3. ([#25](https://github.com/vstorm-co/pydantic-deepagents/issues/25))
- Fixed 404 when accessing `/llms.txt` - the file was referenced in documentation but never
  generated ([#26](https://github.com/vstorm-co/pydantic-deepagents/issues/26))

## [0.2.14] - 2025-01-21

### Changed

- **Breaking:** Removed local `pydantic_deep/processors/` module - now uses
  external [summarization-pydantic-ai](https://github.com/vstorm-co/summarization-pydantic-ai) library
- **Breaking:** Removed local `pydantic_deep/toolsets/subagents.py` module - now uses
  external [subagents-pydantic-ai](https://github.com/vstorm-co/subagents-pydantic-ai) library
- Added `summarization-pydantic-ai>=0.0.1` dependency
- Added `subagents-pydantic-ai>=0.0.3` dependency (fixed docs imports)
- Updated `pydantic-ai-todo>=0.1.5` dependency (added missing exports)
- Updated `summarization-pydantic-ai>=0.0.2` dependency (new documentation site)
- Updated `pydantic-ai-backend>=0.1.4` dependency (new documentation site)
- Re-exported `SummarizationProcessor`, `SlidingWindowProcessor`, `create_summarization_processor`,
  `create_sliding_window_processor` from summarization-pydantic-ai
- Re-exported `SubAgentToolset`, `create_subagent_toolset`, `get_subagent_system_prompt` from subagents-pydantic-ai
- Re-exported `SubAgentConfig`, `CompiledSubAgent` types from subagents-pydantic-ai
- Updated `DeepAgentDeps.clone_for_subagent()` to accept optional `max_depth` parameter for nested subagent support

### Added

- `SlidingWindowProcessor` - zero-cost message trimming without LLM calls (new from summarization-pydantic-ai)
- `create_sliding_window_processor()` - factory function for sliding window processors
- **Dual-mode execution**: Subagents can now run in sync (blocking) or async (background) modes
- **Auto mode**: Intelligent mode selection based on task characteristics
- **Task management tools**: `check_task`, `list_active_tasks`, `soft_cancel_task`, `hard_cancel_task`
- **Subagent communication**: `ask_parent` tool for subagents to query the parent agent
- **Dynamic agent creation**: Runtime agent creation via `create_agent_factory_toolset`
- New types: `TaskHandle`, `TaskStatus`, `TaskPriority`, `TaskCharacteristics`, `ExecutionMode`

### Fixed

- Added `chardet>=5.0.0` dependency back - was incorrectly removed in 0.2.13 but is still needed for
  `DeepAgentDeps.upload_file()` encoding detection ([#22](https://github.com/vstorm-co/pydantic-deep/issues/22))
- Subagents now automatically get `console_toolset` and `todo_toolset` like in previous versions - the migration to
  `subagents-pydantic-ai` accidentally removed these default
  tools ([#21](https://github.com/vstorm-co/pydantic-deep/issues/21))

### Documentation

- Updated `docs/advanced/processors.md` with SlidingWindowProcessor documentation
- Updated `docs/api/processors.md` with full API reference for both processors
- Updated `CLAUDE.md` with new processor imports and subagent imports from external packages
- Updated `README.md` with subagents-pydantic-ai references in modular architecture
- Updated `docs/advanced/subagents.md` with dual-mode execution and new SubAgentConfig fields
- Updated `docs/api/toolsets.md` with complete SubAgentToolset API including task management tools
- Updated `docs/api/types.md` with new subagent types (TaskHandle, TaskStatus, TaskPriority, ExecutionMode)
- Updated `docs/examples/subagents.md` with correct tool names and updated SubAgentConfig example
- Updated `docs/concepts/toolsets.md` with SubAgentToolset tools and correct parameter names
- Fixed `CLAUDE.md` - corrected `LocalBackend(root=...)` to `LocalBackend(root_dir=...)`
- Fixed `CLAUDE.md` - corrected `CompositeBackend` API signature (uses `default` and `routes`, not `backends`)
- Fixed `README.md` - corrected import path `pydantic_deep.processors` to `pydantic_deep`
- Fixed `docs/api/agent.md` - added missing `include_execute` parameter to signature and parameters table
- Fixed `pydantic_deep/agent.py` - corrected docstring model default from "Claude Sonnet 4" to "anthropic:
  claude-sonnet-4-6"

## [0.2.13] - 2025-01-17

### Changed

- **Breaking:** Updated `pydantic-ai-backend` dependency to `>=0.1.0`
- **Breaking:** Removed `FilesystemBackend` and `LocalSandbox` - use `LocalBackend` instead
- **Breaking:** Removed `FilesystemToolset` - use `create_console_toolset` from pydantic-ai-backend
- Replaced custom filesystem toolset with `create_console_toolset` from pydantic-ai-backend
- Re-exported `LocalBackend`, `create_console_toolset`, `get_console_system_prompt`, `ConsoleDeps` from
  pydantic-ai-backend

### Removed

- `pydantic_deep/toolsets/filesystem.py` - now provided by pydantic-ai-backend
- `chardet` dependency - moved to pydantic-ai-backend

### Documentation

- Simplified backend documentation - now links
  to [pydantic-ai-backend docs](https://vstorm-co.github.io/pydantic-ai-backend/)
- Updated all examples to use `LocalBackend` instead of `FilesystemBackend`
- Updated toolsets documentation to reference Console Toolset from pydantic-ai-backend

## [0.2.12] - 2025-01-16

### Changed

- Updated `pydantic-ai-backend` dependency to `>=0.0.4` for persistent storage support
- `__version__` now dynamically reads from package metadata (pyproject.toml) via `importlib.metadata`

### Documentation

- Added persistent storage documentation to `docs/examples/docker-sandbox.md`:
    - `volumes` parameter for DockerSandbox
    - `workspace_root` parameter for SessionManager
- Added `workspace_root` documentation to `docs/examples/docker-runtimes.md`:
    - Configuration options section
    - New "Persistent Storage with workspace_root" section with examples
    - Directory structure diagram
- Updated `docs/examples/full-app.md` with `workspace_root` in SessionManager example
- Updated `examples/full_app/app.py` to use `workspace_root` for persistent user files
