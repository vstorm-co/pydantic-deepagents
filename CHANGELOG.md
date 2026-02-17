# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.17] - 2026-02-17

### Added

- **Checkpointing & Rewind**: Save conversation state at intervals, rewind to any checkpoint, or fork into a new session. `Checkpoint`, `CheckpointStore` protocol, `InMemoryCheckpointStore`, `FileCheckpointStore`, `CheckpointMiddleware` (auto-save every tool/turn/manual), `CheckpointToolset` (save_checkpoint, list_checkpoints, rewind_to tools), `RewindRequested` exception for app-level rewind, `fork_from_checkpoint()` utility for session forking. Enable via `include_checkpoints=True`.
- **Agent Teams**: Shared TODO lists with asyncio-safe claiming and dependency blocking (`SharedTodoList`), peer-to-peer message bus (`TeamMessageBus`), team coordinator (`AgentTeam`) with spawn, assign, broadcast, wait_all, dissolve operations, `create_team_toolset()` factory. Enable via `include_teams=True`.
- **Claude Code-Style Hooks**: `Hook`, `HookEvent` enum (PRE_TOOL_USE, POST_TOOL_USE, POST_TOOL_USE_FAILURE), `HookInput`, `HookResult`, `HooksMiddleware`. Execute shell commands or Python handlers on tool lifecycle events. Exit code conventions (0=allow, 2=deny), regex matchers, timeout, and background execution support.
- **Persistent Memory**: `AgentMemoryToolset` with read_memory, write_memory, update_memory tools. Per-agent MEMORY.md files auto-injected into system prompt (first 200 lines). Per-subagent memory with opt-out via `extra={"memory": False}`. Enable via `include_memory=True`.
- **Context Files**: `ContextToolset` for auto-discovering and injecting DEEP.md, AGENTS.md, CLAUDE.md, SOUL.md into system prompt. Subagent filtering (only DEEP.md + AGENTS.md forwarded). Per-subagent context_files via SubAgentConfig. Truncation support. Enable via `context_files=[...]` or `context_discovery=True`.
- **Eviction Processor**: `EvictionProcessor` saves large tool outputs (>20k tokens by default) to files and replaces with head/tail preview + file reference. Keeps conversation lean while preserving data access. Enable via `eviction_token_limit=20000`.
- **Output Styles**: 4 built-in styles (concise, explanatory, formal, conversational), custom `OutputStyle` instances, file-based styles with YAML frontmatter, directory discovery via `styles_dir`. Apply via `output_style="concise"`.
- **Plan Mode**: Built-in 'planner' subagent with `ask_user` (interactive options with headless mode) and `save_plan` tools. Plans saved as markdown files to configurable `plans_dir`. Enable via `include_plan=True` (default).
- **Patch Tool Calls Processor**: Fixes orphaned tool calls when resuming interrupted conversations by injecting synthetic "Tool call was cancelled." responses. Enable via `patch_tool_calls=True`.
- **`BASE_PROMPT`**: Exported default system prompt for inspection and customization.
- **`share_todos` on `DeepAgentDeps`**: When True, subagents share the same todo list reference as the parent agent. Default False (isolated).
- **`subagent_extra_toolsets` parameter**: Pass additional toolsets (e.g., MCP servers) to all subagents via `create_deep_agent()`.
- **`subagent_registry` parameter**: Optional `DynamicAgentRegistry` for runtime agent creation via `create_agent_factory_toolset`.

### Changed

- **Skills system rewrite**: Complete refactor from single-file `skills.py` to protocol-based `skills/` package. New abstractions: `Skill` dataclass, `SkillResource` / `SkillScript` / `SkillsDirectory` protocols, `SkillWrapper`. Two implementations: file-based (`FileBasedSkillResource`, `LocalSkillScriptExecutor`) and backend-based (`BackendSkillResource`, `BackendSkillScriptExecutor`, `BackendSkillsDirectory`). Skill scripts for executable actions. Comprehensive exception hierarchy (`SkillException`, `SkillNotFoundError`, `SkillValidationError`, `SkillResourceNotFoundError`, `SkillResourceLoadError`, `SkillScriptExecutionError`).
- **Cost tracking enabled by default**: `cost_tracking=True` via `CostTrackingMiddleware` from pydantic-ai-middleware. New params: `cost_budget_usd` (raises `BudgetExceededError`), `on_cost_update` callback.
- **Context manager enabled by default**: `context_manager=True` enables `ContextManagerMiddleware` for automatic token tracking and auto-compression when approaching token budget. New params: `context_manager_max_tokens` (default 200,000), `on_context_update` callback.
- **Middleware integration**: New `middleware`, `permission_handler`, `middleware_context` params for composable `AgentMiddleware` chains via pydantic-ai-middleware. Agent automatically wrapped in `MiddlewareAgent` when any middleware is active.
- Updated `pydantic-ai-todo` dependency to `>=0.1.8` (todo IDs in system prompt, improved active_form descriptions)
- Updated `subagents-pydantic-ai` dependency to `>=0.0.5`
- Updated `pydantic-ai-middleware` dependency to `>=0.2.1`
- Updated `summarization-pydantic-ai` dependency to `>=0.0.3`
- Updated `pydantic-ai-backend` dependency to `>=0.1.7`

### Documentation

- Added 11 new advanced feature guides: checkpointing, teams, hooks, memory, context-files, eviction, cost-tracking, middleware, output-styles, plan-mode, multi-user
- Updated agents, toolsets, and skills concept pages for all new features
- Updated API reference (agent, toolsets, types) with all new parameters and types
- Comprehensive CLAUDE.md with full architecture documentation

## [0.2.16] - 2025-02-12

### Changed

- Updated `subagents-pydantic-ai` dependency from `>=0.0.3` to `>=0.0.4` — fixes `AttributeError: 'Agent' object has no attribute '_register_toolset'` compatibility issue with pydantic-ai >= 1.38 ([subagents-pydantic-ai#5](https://github.com/vstorm-co/subagents-pydantic-ai/issues/5))
- Removed `_register_toolset` mock from test fixtures (`tests/conftest.py`) — no longer needed after subagents fix

## [0.2.15] - 2025-02-07

### Added

- **`retries` parameter for `create_deep_agent()`**: New explicit parameter (default: 3) that controls max retries for tool calls across all built-in toolsets. When the model sends invalid arguments (e.g. missing a required field), the validation error is fed back and the model can self-correct up to `retries` times. Previously, console tools (including `write_file`) were hardcoded to 1 retry via `FunctionToolset` default, making self-correction nearly impossible. ([#25](https://github.com/vstorm-co/pydantic-deepagents/issues/25))
- **llms.txt support**: Added `mkdocs-llmstxt` plugin to generate `/llms.txt` and `/llms-full.txt` files following the [llmstxt.org](https://llmstxt.org/) standard ([#26](https://github.com/vstorm-co/pydantic-deepagents/issues/26))
- Added `mkdocs-llmstxt>=0.2.0` to docs dependency group

### Fixed

- **`write_file` tool exceeded max retries count of 1**: The `write_file` (and all other console tools) had `max_retries=1` hardcoded via `FunctionToolset` default. When the model omitted a required argument like `content`, it got only 1 retry attempt before raising `UnexpectedModelBehavior`. The `retries` parameter passed to `create_deep_agent()` was forwarded to the `Agent` constructor but never propagated to toolsets. Now `retries` is applied to the console toolset and all its tools, and the default is raised from 1 to 3. ([#25](https://github.com/vstorm-co/pydantic-deepagents/issues/25))
- Fixed 404 when accessing `/llms.txt` - the file was referenced in documentation but never generated ([#26](https://github.com/vstorm-co/pydantic-deepagents/issues/26))

## [0.2.14] - 2025-01-21

### Changed

- **Breaking:** Removed local `pydantic_deep/processors/` module - now uses external [summarization-pydantic-ai](https://github.com/vstorm-co/summarization-pydantic-ai) library
- **Breaking:** Removed local `pydantic_deep/toolsets/subagents.py` module - now uses external [subagents-pydantic-ai](https://github.com/vstorm-co/subagents-pydantic-ai) library
- Added `summarization-pydantic-ai>=0.0.1` dependency
- Added `subagents-pydantic-ai>=0.0.3` dependency (fixed docs imports)
- Updated `pydantic-ai-todo>=0.1.5` dependency (added missing exports)
- Updated `summarization-pydantic-ai>=0.0.2` dependency (new documentation site)
- Updated `pydantic-ai-backend>=0.1.4` dependency (new documentation site)
- Re-exported `SummarizationProcessor`, `SlidingWindowProcessor`, `create_summarization_processor`, `create_sliding_window_processor` from summarization-pydantic-ai
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

- Added `chardet>=5.0.0` dependency back - was incorrectly removed in 0.2.13 but is still needed for `DeepAgentDeps.upload_file()` encoding detection ([#22](https://github.com/vstorm-co/pydantic-deep/issues/22))
- Subagents now automatically get `console_toolset` and `todo_toolset` like in previous versions - the migration to `subagents-pydantic-ai` accidentally removed these default tools ([#21](https://github.com/vstorm-co/pydantic-deep/issues/21))

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
- Fixed `pydantic_deep/agent.py` - corrected docstring model default from "Claude Sonnet 4" to "openai:gpt-4.1"

## [0.2.13] - 2025-01-17

### Changed

- **Breaking:** Updated `pydantic-ai-backend` dependency to `>=0.1.0`
- **Breaking:** Removed `FilesystemBackend` and `LocalSandbox` - use `LocalBackend` instead
- **Breaking:** Removed `FilesystemToolset` - use `create_console_toolset` from pydantic-ai-backend
- Replaced custom filesystem toolset with `create_console_toolset` from pydantic-ai-backend
- Re-exported `LocalBackend`, `create_console_toolset`, `get_console_system_prompt`, `ConsoleDeps` from pydantic-ai-backend

### Removed

- `pydantic_deep/toolsets/filesystem.py` - now provided by pydantic-ai-backend
- `chardet` dependency - moved to pydantic-ai-backend

### Documentation

- Simplified backend documentation - now links to [pydantic-ai-backend docs](https://vstorm-co.github.io/pydantic-ai-backend/)
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
