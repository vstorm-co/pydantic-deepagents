# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Core Development Tasks

- **Install dependencies**: `make install` (requires uv and pre-commit)
- **Run all checks**: `make all` or `pre-commit run --all-files`
- **Run tests**: `make test`
- **Build docs**: `make docs` or `make docs-serve` (local development)

### Single Test Commands

- **Run specific test**: `uv run pytest tests/test_agent.py::test_function_name -v`
- **Run test file**: `uv run pytest tests/test_agent.py -v`
- **Run with debug**: `uv run pytest tests/test_agent.py -v -s`

## Project Architecture

### Repository Layout

- `pydantic_deep/` — Core library (agent, deps, models, instructions, types)
- `pydantic_deep/features/<name>/` — One vertical-slice package per feature
  (`capability.py` + `toolset.py` + `service.py`/`types.py`). Organize by
  feature, not by kind — `features/` is the only import location; the old
  `toolsets/`, `capabilities/`, `processors/` and `improve/` shims were removed
  in 0.3.39.
- `apps/cli/` — CLI + TUI application (Textual-based terminal AI assistant)
- `apps/deepresearch/` — Full-featured research reference app
- `tests/` — Unit tests
- `docs/` — Documentation source (MkDocs)

### Core Components

**Agent Factory (`pydantic_deep/agent.py`)**
- `create_deep_agent()`: Main factory function for creating configured agents
- `create_default_deps()`: Helper for creating DeepAgentDeps with sensible defaults
- Built on top of pydantic-ai's Agent class
- Requires pydantic-ai>=2.52.0 (workspaces)
- `workspace=`: the capability that supplies each run's workspace; default `StateWorkspace()` (in-memory, no commands), `False` leaves it to `agent.run(workspace=...)`

**Dependencies (`pydantic_deep/deps.py`)**
- `DeepAgentDeps`: Dataclass holding agent dependencies (todos, subagents, uploads, checkpoint store, message queue)
- Passed to agent.run() for runtime configuration
- Holds no files: those live in the run's workspace, `ctx.workspace`. `upload_file()` queues bytes that `write_pending_uploads()` writes when the run starts

**Workspaces (Pydantic AI; capabilities from [pydantic-ai-backend](https://github.com/vstorm-co/pydantic-ai-backend))**
- Every file and command goes through the run's workspace, `ctx.workspace` (read_bytes/write_bytes/read_text/write_text/list_dir/stat/exists/make_dir/remove, and `run` where the backend `SupportsCommands`)
- `StateWorkspace`: In-memory `StateBackend` document, files only (the default)
- `LocalWorkspace`: A directory on this machine (from `pydantic_ai.capabilities`)
- `DockerWorkspace`, `SandboxdWorkspace`, `KubernetesWorkspace`, `DaytonaWorkspace`: sandboxes, created on first use, kept after the run, removed with `await capability.destroy(ref)`
- A files-only workspace raises `UserError` from `run`: check `isinstance(workspace.backend, SupportsCommands)` before running anything a model asked for
- Tests: `tests/workspaces.py` has `state_workspace(files)`, `as_workspace(state)` and `run_context(deps, workspace)`

**Toolsets (`pydantic_deep/features/<name>/toolset.py`)**
- `TodoToolset`: Task planning and tracking tools (read_todos, write_todos) - from [pydantic-ai-todo](https://github.com/vstorm-co/pydantic-ai-todo)
- `create_console_toolset`: File operations (ls, read, write, edit, glob, grep, execute) - from [pydantic-ai-backend](https://github.com/vstorm-co/pydantic-ai-backend)
- `SubAgentToolset`: Spawn and delegate to subagents - from [subagents-pydantic-ai](https://github.com/vstorm-co/subagents-pydantic-ai)
- `SkillsToolset`: Load and use skill definitions from markdown files
- Web search and fetch use pydantic-ai built-in `WebSearch()` and `WebFetch()` tools

**Subagents (from [subagents-pydantic-ai](https://github.com/vstorm-co/subagents-pydantic-ai))**
- `create_subagent_toolset()`: Factory function to create subagent toolsets
- `get_subagent_system_prompt()`: Generate system prompt for subagent tools
- Dual-mode execution: sync (blocking) or async (background)
- Task management: check_task, list_active_tasks, soft_cancel_task, hard_cancel_task
- Types: `SubAgentConfig`, `CompiledSubAgent`, `TaskHandle`, `TaskStatus`, `TaskPriority`

**Processors (from [summarization-pydantic-ai](https://github.com/vstorm-co/summarization-pydantic-ai))**
- `SummarizationProcessor`: LLM-based conversation summarization for token management
- `SlidingWindowProcessor`: Zero-cost message trimming without LLM calls
- `create_summarization_processor()`: Factory function for summarization processors
- `create_sliding_window_processor()`: Factory function for sliding window processors

**Types (`pydantic_deep/types.py`)**
- Pydantic models for all data structures
- `FileData`, `FileInfo` (re-exported from pydantic-ai-backend), `UploadedFile`
- `Todo`, `SubAgentConfig`, `CompiledSubAgent`
- `Skill`, `SkillDirectory`, `SkillFrontmatter`
- `ResponseFormat`: Alias for structured output specification

**Checkpointing (`pydantic_deep/features/checkpointing/`)**
- `Checkpoint`: Immutable snapshot of conversation state (id, label, turn, messages, metadata)
- `CheckpointStore`: Protocol for storage backends (save, get, list_all, remove, etc.)
- `InMemoryCheckpointStore`: Default in-memory store
- `FileCheckpointStore`: Persistent JSON file store
- `CheckpointMiddleware`: Auto-checkpoint capability extending `AbstractCapability` (every_tool, every_turn, manual_only)
- `CheckpointToolset`: Agent tools (save_checkpoint, list_checkpoints, rewind_to)
- `RewindRequested`: Exception for app-level rewind (propagates out of agent.run())
- `fork_from_checkpoint()`: Utility for session forking

**Agent Teams (`pydantic_deep/features/teams/`)**
- `SharedTodoItem`: Task with assignment, dependencies, and status tracking
- `SharedTodoList`: Asyncio-safe shared TODO list with claiming and dependency blocking
- `TeamMessage`: Message between team members
- `TeamMessageBus`: Peer-to-peer message bus using asyncio.Queue per agent
- `TeamMember`: Member definition (name, role, description, instructions, model)
- `TeamMemberHandle`: Runtime handle to a running team member
- `AgentTeam`: Coordinator — spawn, assign, broadcast, wait_all, dissolve
- `create_team_toolset()`: Factory for team management tools (spawn_team, assign_task, check_teammates, message_teammate, dissolve_team)

**Output Styles (`pydantic_deep/styles.py`)**
- `OutputStyle`: Dataclass (name, description, content)
- `BUILTIN_STYLES`: Dict of 4 built-in styles (concise, explanatory, formal, conversational)
- `resolve_style()`: Resolve style name -> OutputStyle (built-ins -> styles_dir -> error)
- `discover_styles()`: Discover .md style files from a directory
- `load_style_from_file()`: Load a single style with frontmatter parsing
- `format_style_prompt()`: Format for system prompt injection

**Hooks (`pydantic_deep/features/hooks/capability.py`)**
- `HookEvent`: Enum (PRE_TOOL_USE, POST_TOOL_USE, POST_TOOL_USE_FAILURE)
- `Hook`: Definition — event, command/handler, matcher regex, timeout, background
- `HookInput`: Data passed to hooks (event, tool_name, tool_input, tool_result, tool_error)
- `HookResult`: Result from hook (allow, reason, modified_args, modified_result)
- `HooksCapability`: Capability (extends `AbstractCapability`) that dispatches hooks on tool events
- Hook methods: `before_tool_execute`, `after_tool_execute`, `on_tool_execute_error`
- `EXIT_ALLOW = 0`, `EXIT_DENY = 2`: Claude Code exit code conventions

**Capabilities (`pydantic_deep/features/<name>/capability.py`)**
- `SkillsCapability`: Injects skills system prompt and manages skill discovery
- `ContextFilesCapability`: Auto-discovers and injects context files (DEEP.md, AGENTS.md, CLAUDE.md, SOUL.md)
- `BrowserCapability`, `StuckLoopDetection`, `PeriodicReminderCapability`,
  `HooksCapability`, `EvictionCapability`, `PatchToolCallsCapability`
- All extend pydantic-ai's `AbstractCapability`

**Persistent Memory (`pydantic_deep/features/memory/`)**
- The `pydantic-ai-harness` `Memory` capability over a `FileStore` in the run's workspace
- `build_memory_capability()` (`store.py`): builds it for the main agent and each subagent
- Tools: `write_memory` (append, or replace with `old_text=`), `read_memory`, `search_memory`, `delete_memory`
- `MEMORY.md` is injected into each request as user-role context; listed after compaction
- Path: `{memory_dir}/{namespace}/{agent_name}/MEMORY.md`; `memory_namespace=` isolates users sharing a workspace
- `AgentMemoryToolset`, `MemoryCapability`, `MemoryFile`, `load_memory()`, `format_memory_prompt()` are deprecated (import with a warning)

**Context Files (`pydantic_deep/features/context/`)**
- `ContextFile`: Loaded context file (name, path, content)
- `ContextToolset`: FunctionToolset that injects context files via get_instructions()
- `discover_context_files()`: Auto-discover DEEP.md, AGENTS.md, CLAUDE.md, SOUL.md
- `load_context_files()`: Load from the workspace (missing files silently skipped)
- `format_context_prompt()`: Format with subagent filtering and truncation
- `DEFAULT_CONTEXT_FILENAMES`: [DEEP.md, AGENTS.md, CLAUDE.md, SOUL.md]
- `SUBAGENT_CONTEXT_ALLOWLIST`: {AGENTS.md, CLAUDE.md} — subagents don't see SOUL.md/.cursorrules/etc.

**Eviction (`pydantic_deep/features/eviction/capability.py`)**
- `EvictionCapability`: Capability — intercepts large tool outputs via `after_tool_execute` before they enter history
- `create_content_preview()`: Head/tail preview with truncation marker
- Default threshold: 20,000 tokens (80,000 chars)
- Writes into `ctx.workspace` (`.deep/large_tool_results/`); a failed write keeps the output in history
- Supports `on_eviction` callback for notification when content is evicted

**Monitor — watch & react (`pydantic_deep/features/monitoring/`)**
- `MonitorManager`: runs a long-lived command in the workspace with its output redirected to a log under `.deep/monitors/`, drains the log on an interval, filters new lines by an optional regex, and pushes each batch as a `MonitorEvent` through an `on_event` sink
- `create_monitor_toolset()`: agent tools `start_monitor` / `list_monitors` / `stop_monitor`
- `MonitorEvent`, `MonitorInfo`: event batch + status snapshot
- "React" path: the toolset wires `on_event` to `ctx.deps.message_queue` (steering), so new output is delivered back into the conversation and the agent reacts without polling
- Requires a workspace that runs commands; tools no-op gracefully otherwise
- Enabled by default via `include_monitoring=True`; lives on `deps.monitor_manager` (lazily created, reset for subagents)

**Stuck Loop Detection (`pydantic_deep/features/stuck_loop/capability.py`)**
- `StuckLoopDetection`: Capability — detects repetitive agent behavior via `after_tool_execute`
- Three patterns: repeated identical calls, A-B-A-B alternating, no-op (same result)
- `max_repeated`: Threshold (default 3), `action`: "warn" (ModelRetry) or "error" (StuckLoopError)
- Per-run state isolation via `for_run()`
- Enabled by default via `stuck_loop_detection=True`

**Cost Tracking (from pydantic_ai_shields)**
- Enabled by default via `cost_tracking=True`
- `CostTracking`: Capability that tracks token usage and USD costs per run and cumulative
- `CostInfo`: Per-run and cumulative token/cost data
- `BudgetExceededError`: Raised when cumulative cost exceeds `cost_budget_usd`
- Pricing from `genai-prices` package

**Patch Tool Calls (`pydantic_deep/features/patch/capability.py`)**
- `PatchToolCallsCapability`: Capability — fixes orphaned tool calls via `before_model_request`
- `patch_tool_calls_processor()`: Legacy function (backward compatibility)
- Injects synthetic `ToolReturnPart` with "Tool call was cancelled." message
- Used when resuming interrupted conversations (`patch_tool_calls=True`)

**Plan Mode (`pydantic_deep/features/plan/`)**
- `create_plan_toolset()`: Factory for ask_user + save_plan tools
- Built-in 'planner' subagent registered when `include_plan=True`
- `PLANNER_INSTRUCTIONS`, `PLANNER_DESCRIPTION`: Planner configuration
- Plans saved as markdown files in `plans_dir` (default: `/plans`)
- `ask_user` supports headless mode (auto-selects recommended option)

**Context Manager (from summarization-pydantic-ai)**
- Enabled by default via `context_manager=True`
- `ContextManagerCapability`: Capability extending `AbstractCapability` — handles history processing and token tracking
- Token tracking with `on_context_update` callback (percentage, current, max)
- Auto-compression when approaching token budget (compress_threshold=0.9)

**Capabilities Integration**
- `capabilities` param on `create_deep_agent()`: List of `AbstractCapability` instances
- Capabilities hook into the agent lifecycle via pydantic-ai's native Capabilities API
- Tool event hooks: `before_tool_execute`, `after_tool_execute`, `on_tool_execute_error`
- No wrapping needed — capabilities are registered directly on the Agent

**`share_todos` on DeepAgentDeps**
- `DeepAgentDeps.share_todos: bool = False`
- When True, `clone_for_subagent()` passes same todos list reference (shared)
- When False (default), subagents get an empty todos list (isolated)

### Key Design Patterns

**Workspaces**
```python
from pydantic_deep import DockerWorkspace, LocalWorkspace, create_deep_agent

# In-memory for testing (the default: StateWorkspace())
agent = create_deep_agent()

# Real filesystem
agent = create_deep_agent(workspace=LocalWorkspace("/path/to/workspace"))

# Container; kept after the run, removed with `await docker.destroy(ref)`
agent = create_deep_agent(workspace=DockerWorkspace(runtime="python-datascience"))

# Per run (one workspace per session)
agent = create_deep_agent(workspace=False)
result = await agent.run(prompt, deps=deps, workspace=session_workspace)
```

**Toolset Registration**
```python
from pydantic_deep import create_deep_agent, DeepAgentDeps
from pydantic_ai_backends import create_console_toolset
from pydantic_ai_todo import create_todo_toolset

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    toolsets=[create_todo_toolset(), create_console_toolset()],
)
```

**Capabilities Registration**
```python
from pydantic_deep import create_deep_agent
from pydantic_ai_shields import CostTracking
from pydantic_deep.features.hooks import HooksCapability, Hook, HookEvent

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    capabilities=[
        CostTracking(cost_budget_usd=5.0),
        HooksCapability(hooks=[
            Hook(event=HookEvent.PRE_TOOL_USE, handler=my_handler),
        ]),
    ],
)
```

**Skills System**
```python
# Skills are markdown files with YAML frontmatter, in folders on this machine
# or in the run's workspace
from pydantic_deep import WorkspaceSkillsDirectory

agent = create_deep_agent(
    skill_directories=["/path/to/skills", WorkspaceSkillsDirectory(path="skills")],
)
```

**Structured Output**
```python
from pydantic import BaseModel
from pydantic_deep import create_deep_agent

class TaskResult(BaseModel):
    status: str
    details: str

# Agent returns TaskResult instead of str
agent = create_deep_agent(output_type=TaskResult)
```

**Context Management / Summarization**
```python
from pydantic_deep import (
    create_deep_agent,
    create_summarization_processor,
    create_sliding_window_processor,
)

# Automatically summarize when reaching token limits
processor = create_summarization_processor(
    trigger=("tokens", 100000),  # or ("messages", 50) or ("fraction", 0.8)
    keep=("messages", 20),       # Keep last N messages after summarization
)

# Or use sliding window for zero-cost trimming
window = create_sliding_window_processor(
    trigger=("messages", 100),
    keep=("messages", 50),
)

agent = create_deep_agent(history_processors=[processor])
```

## Testing Strategy

- **Unit tests**: `tests/` directory with comprehensive coverage
- **Test models**: Use `TestModel` from pydantic-ai for deterministic testing
- **Async testing**: pytest-asyncio with `asyncio_mode = "auto"`
- **Coverage requirement**: 100% coverage is required for all PRs

## Key Configuration Files

- **`pyproject.toml`**: Main configuration (dependencies, tools, coverage)
- **`Makefile`**: Development task automation
- **`mkdocs.yml`**: Documentation configuration
- **`.pre-commit-config.yaml`**: Pre-commit hook configuration

## Important Implementation Notes

- **Workspaces**: All file and command access goes through `ctx.workspace`; never reach into a provider directly
- **Async-First**: Most operations are async, use `await` appropriately
- **Type Safety**: Full type annotations with Pyright strict mode
- **Sandbox Support**: DockerWorkspace requires the `sandbox` optional dependency
- **Minimum pydantic-ai version**: Requires pydantic-ai>=2.52.0 for workspaces

## Documentation Development

- **Local docs**: `make docs-serve` (serves at http://localhost:8000)
- **Docs source**: `docs/` directory (MkDocs with Material theme)
- **API reference**: Auto-generated from docstrings using mkdocstrings

## Dependencies Management

- **Package manager**: uv (fast Python package manager)
- **Lock file**: `uv.lock` (commit this file)
- **Sync command**: `make sync` to update dependencies
- **Optional extras**: sandbox, cli, dev

## Best Practices

### Coverage

Every pull request MUST have 100% coverage. You can check the coverage by running `make test`.

Use `# pragma: no cover` for legitimately untestable code (e.g., platform-specific branches).

### Type Annotations

All code must pass both Pyright and MyPy strict checking:
- `make typecheck` for Pyright
- `make typecheck-mypy` for MyPy

### Writing Documentation

Always reference Python objects with backticks and link to API reference:

```markdown
The [`create_deep_agent`][pydantic_deep.agent.create_deep_agent] function creates a configured agent.
```

### Rename a Function (private → public)

When renaming a function from private (`_fun`) to public (`fun`), be careful with test names. A naive find-and-replace of `_fun` → `fun` will mangle test names like `test_fun` into `testfun`, which is invalid. Always rename the function first, then update test names separately (or use a more targeted replacement that won't match the `test_` prefix).

### Rename a Class

When renaming a class, add deprecation warning:

```python
from typing_extensions import deprecated

class NewClass: ...

@deprecated("Use `NewClass` instead.")
class OldClass(NewClass): ...
```
