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

- `pydantic_deep/` — Core library (agent, deps, toolsets, middleware, processors)
- `cli/` — CLI application (terminal AI assistant)
- `apps/swebench_agent/` — SWE-bench evaluation agent
- `apps/harbor_agent/` — Harbor benchmark agent
- `apps/deepresearch/` — Full-featured research reference app
- `tests/` — Unit tests
- `docs/` — Documentation source (MkDocs)

### Core Components

**Agent Factory (`pydantic_deep/agent.py`)**
- `create_deep_agent()`: Main factory function for creating configured agents
- `create_default_deps()`: Helper for creating DeepAgentDeps with sensible defaults
- Built on top of pydantic-ai's Agent class

**Dependencies (`pydantic_deep/deps.py`)**
- `DeepAgentDeps`: Dataclass holding agent dependencies (backend, working_dir, skills_dirs, subagents)
- Passed to agent.run() for runtime configuration

**Backends (from [pydantic-ai-backend](https://github.com/vstorm-co/pydantic-ai-backend))**
- `BackendProtocol`: Interface for file storage backends
- `StateBackend`: In-memory file storage (for testing, ephemeral use)
- `LocalBackend`: Real filesystem operations
- `DockerSandbox`: Isolated Docker container execution
- `CompositeBackend`: Combines multiple backends with routing

**Toolsets (`pydantic_deep/toolsets/`)**
- `TodoToolset`: Task planning and tracking tools (read_todos, write_todos) - from [pydantic-ai-todo](https://github.com/vstorm-co/pydantic-ai-todo)
- `create_console_toolset`: File operations (ls, read, write, edit, glob, grep, execute) - from [pydantic-ai-backend](https://github.com/vstorm-co/pydantic-ai-backend)
- `SubAgentToolset`: Spawn and delegate to subagents - from [subagents-pydantic-ai](https://github.com/vstorm-co/subagents-pydantic-ai)
- `SkillsToolset`: Load and use skill definitions from markdown files

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
- `FileData`, `FileInfo`, `WriteResult`, `EditResult`, `GrepMatch`
- `Todo`, `SubAgentConfig`, `CompiledSubAgent`
- `Skill`, `SkillDirectory`, `SkillFrontmatter`
- `ResponseFormat`: Alias for structured output specification

**Checkpointing (`pydantic_deep/toolsets/checkpointing.py`)**
- `Checkpoint`: Immutable snapshot of conversation state (id, label, turn, messages, metadata)
- `CheckpointStore`: Protocol for storage backends (save, get, list_all, remove, etc.)
- `InMemoryCheckpointStore`: Default in-memory store
- `FileCheckpointStore`: Persistent JSON file store
- `CheckpointMiddleware`: Auto-checkpoint via middleware hooks (every_tool, every_turn, manual_only)
- `CheckpointToolset`: Agent tools (save_checkpoint, list_checkpoints, rewind_to)
- `RewindRequested`: Exception for app-level rewind (propagates out of agent.run())
- `fork_from_checkpoint()`: Utility for session forking

**Agent Teams (`pydantic_deep/toolsets/teams.py`)**
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
- `resolve_style()`: Resolve style name → OutputStyle (built-ins → styles_dir → error)
- `discover_styles()`: Discover .md style files from a directory
- `load_style_from_file()`: Load a single style with frontmatter parsing
- `format_style_prompt()`: Format for system prompt injection

**Hooks (`pydantic_deep/middleware/hooks.py`)**
- `HookEvent`: Enum (PRE_TOOL_USE, POST_TOOL_USE, POST_TOOL_USE_FAILURE)
- `Hook`: Definition — event, command/handler, matcher regex, timeout, background
- `HookInput`: Data passed to hooks (event, tool_name, tool_input, tool_result, tool_error)
- `HookResult`: Result from hook (allow, reason, modified_args, modified_result)
- `HooksMiddleware`: AgentMiddleware that dispatches hooks on tool events
- `EXIT_ALLOW = 0`, `EXIT_DENY = 2`: Claude Code exit code conventions

**Persistent Memory (`pydantic_deep/toolsets/memory.py`)**
- `MemoryFile`: Loaded memory (agent_name, path, content)
- `AgentMemoryToolset`: FunctionToolset with read_memory, write_memory, update_memory
- `get_instructions()`: Injects memory into system prompt (first N lines)
- `load_memory()`, `format_memory_prompt()`, `get_memory_path()`
- Default path: `{memory_dir}/{agent_name}/MEMORY.md`

**Context Files (`pydantic_deep/toolsets/context.py`)**
- `ContextFile`: Loaded context file (name, path, content)
- `ContextToolset`: FunctionToolset that injects context files via get_instructions()
- `discover_context_files()`: Auto-discover DEEP.md, AGENTS.md, CLAUDE.md, SOUL.md
- `load_context_files()`: Load from backend (missing files silently skipped)
- `format_context_prompt()`: Format with subagent filtering and truncation
- `DEFAULT_CONTEXT_FILENAMES`: [DEEP.md, AGENTS.md, CLAUDE.md, SOUL.md]
- `SUBAGENT_CONTEXT_ALLOWLIST`: {DEEP.md, AGENTS.md} — subagents don't see SOUL.md/CLAUDE.md

**Eviction Processor (`pydantic_deep/processors/eviction.py`)**
- `EvictionProcessor`: History processor — saves large tool outputs to files, replaces with preview
- `create_eviction_processor()`: Factory function
- `create_content_preview()`: Head/tail preview with truncation marker
- Default threshold: 20,000 tokens (80,000 chars)
- Uses runtime `ctx.deps.backend` for writing

**Cost Tracking (from pydantic-ai-middleware)**
- Enabled by default via `cost_tracking=True`
- `CostTrackingMiddleware`: Tracks token usage and USD costs per run and cumulative
- `CostInfo`: Per-run and cumulative token/cost data
- `BudgetExceededError`: Raised when cumulative cost exceeds `cost_budget_usd`
- Pricing from `genai-prices` package

**Patch Tool Calls (`pydantic_deep/processors/patch.py`)**
- `patch_tool_calls_processor()`: HistoryProcessor that fixes orphaned tool calls
- Injects synthetic `ToolReturnPart` with "Tool call was cancelled." message
- Used when resuming interrupted conversations (`patch_tool_calls=True`)

**Plan Mode (`pydantic_deep/toolsets/plan/`)**
- `create_plan_toolset()`: Factory for ask_user + save_plan tools
- Built-in 'planner' subagent registered when `include_plan=True`
- `PLANNER_INSTRUCTIONS`, `PLANNER_DESCRIPTION`: Planner configuration
- Plans saved as markdown files in `plans_dir` (default: `/plans`)
- `ask_user` supports headless mode (auto-selects recommended option)

**Context Manager (from summarization-pydantic-ai)**
- Enabled by default via `context_manager=True`
- `ContextManagerMiddleware`: Dual-protocol — history processor + AgentMiddleware
- Token tracking with `on_context_update` callback (percentage, current, max)
- Auto-compression when approaching token budget (compress_threshold=0.9)
- `create_context_manager_middleware()`: Factory function

**Middleware Integration (from pydantic-ai-middleware)**
- `middleware` param: List of AgentMiddleware instances
- `permission_handler`: Async callback for ToolDecision.ASK
- `middleware_context`: Shared state between hooks
- Automatically wraps Agent in MiddlewareAgent when any middleware is used

**`share_todos` on DeepAgentDeps**
- `DeepAgentDeps.share_todos: bool = False`
- When True, `clone_for_subagent()` passes same todos list reference (shared)
- When False (default), subagents get an empty todos list (isolated)

### Key Design Patterns

**Backend Abstraction**
```python
from pydantic_ai_backends import StateBackend, LocalBackend, CompositeBackend

# In-memory for testing
backend = StateBackend()

# Real filesystem
backend = LocalBackend(root_dir="/path/to/workspace")

# Combined backends with routing
backend = CompositeBackend(
    default=StateBackend(),
    routes={
        "/project/": LocalBackend(root_dir="/home/user/project"),
    },
)
```

**Toolset Registration**
```python
from pydantic_deep import create_deep_agent, DeepAgentDeps
from pydantic_ai_backends import create_console_toolset
from pydantic_ai_todo import create_todo_toolset

agent = create_deep_agent(
    model="openai:gpt-4.1",
    toolsets=[create_todo_toolset(), create_console_toolset()],
)
```

**Skills System**
```python
# Skills are markdown files with YAML frontmatter
# Located in skills_dirs specified in DeepAgentDeps
deps = DeepAgentDeps(
    backend=StateBackend(),
    skills_dirs=["/path/to/skills"],
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

- **Backend Protocol**: All backends implement `BackendProtocol` for consistent file operations
- **Async-First**: Most operations are async, use `await` appropriately
- **Type Safety**: Full type annotations with Pyright strict mode
- **Sandbox Support**: DockerSandbox requires `docker` optional dependency

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

### Rename a Class

When renaming a class, add deprecation warning:

```python
from typing_extensions import deprecated

class NewClass: ...

@deprecated("Use `NewClass` instead.")
class OldClass(NewClass): ...
```
