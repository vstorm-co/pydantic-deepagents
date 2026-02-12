# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
