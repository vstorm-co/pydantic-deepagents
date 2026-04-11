# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

