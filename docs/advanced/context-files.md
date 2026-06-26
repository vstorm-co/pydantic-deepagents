# Context Files

Every project has its own rules — coding conventions, the tools you use, a tone
you want. **Context files** are project-level markdown (`AGENTS.md`, `CLAUDE.md`,
`SOUL.md`, …) that the agent loads from the backend and folds into its system
prompt automatically. Drop a file in the project; every agent run picks it up.
It's how you give an agent a sense of *this* codebase without re-explaining it
each time.

## Supported Files

pydantic-deep auto-discovers these convention files:

| File | Purpose | Shared with Subagents |
|------|---------|----------------------|
| `AGENTS.md` | Project instructions, conventions, architecture. Compatible with the [agents.md spec](https://agents.md/) | Yes |
| `CLAUDE.md` | Claude Code project instructions | Yes |
| `SOUL.md` | Agent personality, tone, style, user preferences | No (main agent only) |
| `.cursorrules` | Cursor editor conventions | No (main agent only) |
| `.github/copilot-instructions.md` | GitHub Copilot instructions | No (main agent only) |
| `CONVENTIONS.md` | Project coding conventions | No (main agent only) |
| `CODING_GUIDELINES.md` | Coding guidelines | No (main agent only) |
| `MEMORY.md` | Persistent agent memory (read/write/update) | Per-agent (isolated) |

Compatible with Claude Code, Cursor, GitHub Copilot, and other agent frameworks.

!!! note "`MEMORY.md` uses a separate system"
    `MEMORY.md` is managed by the [memory system](memory.md) (`include_memory=True`), not by context discovery. It has dedicated tools (`read_memory`, `write_memory`, `update_memory`) and per-agent isolation.

## Quick Start

=== "Auto-Discovery"
    ```python
    from pydantic_deep import create_deep_agent

    agent = create_deep_agent(context_discovery=True)
    # Scans backend root for AGENTS.md, CLAUDE.md, SOUL.md, .cursorrules, etc.
    ```

=== "Explicit Paths"
    ```python
    from pydantic_deep import create_deep_agent

    agent = create_deep_agent(
        context_files=["/project/AGENTS.md", "/project/SOUL.md"],
    )
    ```

## Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `context_files` | `list[str] \| None` | `None` | Explicit list of file paths to load |
| `context_discovery` | `bool` | `False` | Auto-discover AGENTS.md and SOUL.md at backend root |

## Writing Context Files

### AGENTS.md

Project instructions visible to the main agent and all subagents:

```markdown
# Project: MyApp

## Architecture
- FastAPI backend with PostgreSQL
- React frontend with TypeScript

## Conventions
- Use snake_case for Python, camelCase for TypeScript
- All API endpoints return JSON
- Tests required for all new features

## Build & Test
- `make test` to run tests
- `make lint` to check code style
```

### SOUL.md

Agent personality and user preferences. Only the main agent sees this file — subagents don't have access:

```markdown
# Personality

- Be concise and direct
- Prefer functional programming patterns
- Always explain trade-offs when suggesting solutions

# User Preferences

- Senior Python developer, no need for beginner explanations
- Prefers pytest over unittest
- Uses vim keybindings
```

## How It Works

### Loading

The [`ContextToolset`][pydantic_deep.toolsets.context.ContextToolset] uses `get_instructions()` to load files from the runtime backend (`ctx.deps.backend`) and format them for the system prompt:

```
## Project Context

### AGENTS.md

[content of AGENTS.md]

### SOUL.md

[content of SOUL.md]
```

Missing files are silently skipped.

### Truncation

Files exceeding 20,000 characters are truncated with a head/tail split (70% head, 30% tail):

```
[first 14,000 chars]

... [6000 chars truncated] ...

[last 6,000 chars]
```

### Subagent Filtering

Subagents receive `AGENTS.md` and `CLAUDE.md` (project instructions). All other files (`SOUL.md`, `.cursorrules`, `CONVENTIONS.md`, etc.) are filtered out — they contain personality, editor-specific, or user preferences intended for the main agent only.

## Per-Subagent Context Files

Individual subagents can have their own context files:

```python
from pydantic_deep import SubAgentConfig

subagents = [
    SubAgentConfig(
        name="code-reviewer",
        description="Reviews code for quality",
        instructions="...",
        context_files=["/project/REVIEW_GUIDELINES.md"],
    ),
]

agent = create_deep_agent(
    subagents=subagents,
    context_files=["/project/AGENTS.md"],
)
```

## Components

| Component | Description |
|-----------|-------------|
| [`ContextToolset`][pydantic_deep.toolsets.context.ContextToolset] | Toolset that injects context into system prompt |
| [`ContextFile`][pydantic_deep.toolsets.context.ContextFile] | Loaded context file (name, path, content) |
| [`discover_context_files`][pydantic_deep.toolsets.context.discover_context_files] | Auto-discover context files in backend |
| [`load_context_files`][pydantic_deep.toolsets.context.load_context_files] | Load context files from backend |
| [`format_context_prompt`][pydantic_deep.toolsets.context.format_context_prompt] | Format files for system prompt |
| `DEFAULT_CONTEXT_FILENAMES` | Default filenames: AGENTS.md, CLAUDE.md, SOUL.md, .cursorrules, .github/copilot-instructions.md, CONVENTIONS.md, CODING_GUIDELINES.md |
| `SUBAGENT_CONTEXT_ALLOWLIST` | Files allowed for subagents: AGENTS.md, CLAUDE.md |

## Next Steps

- [Memory](memory.md) -- Persistent agent memory (MEMORY.md)
- [Output Styles](output-styles.md) -- Control response formatting
- [Hooks](hooks.md) -- Claude Code-style lifecycle hooks
