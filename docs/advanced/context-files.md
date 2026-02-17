# Context Files

Context files (DEEP.md, AGENTS.md, CLAUDE.md, SOUL.md) are project-level configuration files that are loaded from the backend and injected into the agent's system prompt. They provide project-specific instructions, conventions, and personality.

## Quick Start

=== "Explicit Paths"
    ```python
    from pydantic_deep import create_deep_agent

    agent = create_deep_agent(
        context_files=["/project/DEEP.md", "/project/AGENTS.md"],
    )
    ```

=== "Auto-Discovery"
    ```python
    from pydantic_deep import create_deep_agent

    agent = create_deep_agent(context_discovery=True)
    # Scans backend root for DEEP.md, AGENTS.md, CLAUDE.md, SOUL.md
    ```

## Context File Types

| File | Purpose | Shared with Subagents |
|------|---------|----------------------|
| `DEEP.md` | Project conventions, architecture, coding standards | Yes |
| `AGENTS.md` | Agent-specific instructions, team roles | Yes |
| `CLAUDE.md` | Claude Code-style project instructions | No |
| `SOUL.md` | Agent personality, tone, values | No |

## Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `context_files` | `list[str] \| None` | `None` | Explicit list of file paths to load |
| `context_discovery` | `bool` | `False` | Auto-discover context files at backend root |

## How It Works

### Loading

The [`ContextToolset`][pydantic_deep.toolsets.context.ContextToolset] uses `get_instructions()` to load files from the runtime backend (`ctx.deps.backend`) and format them for the system prompt:

```
## Project Context

### DEEP.md

[content of DEEP.md]

### AGENTS.md

[content of AGENTS.md]
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

Subagents only receive `DEEP.md` and `AGENTS.md`. Sensitive files (`CLAUDE.md`, `SOUL.md`) are filtered out for security isolation:

```python
# Main agent sees all context files
# Subagents only see DEEP.md and AGENTS.md
```

This filtering is automatic — no configuration needed.

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
    context_files=["/project/DEEP.md"],
)
```

## Writing Context Files

Context files are simple markdown. Write them to your backend:

```python
from pydantic_ai_backends import LocalBackend

backend = LocalBackend("/workspace")

# Write a DEEP.md file
backend.write("/DEEP.md", """
# Project: MyApp

## Architecture
- FastAPI backend with PostgreSQL
- React frontend with TypeScript

## Conventions
- Use snake_case for Python, camelCase for TypeScript
- All API endpoints return JSON
- Tests required for all new features
""".encode())
```

## Components

| Component | Description |
|-----------|-------------|
| [`ContextToolset`][pydantic_deep.toolsets.context.ContextToolset] | Toolset that injects context into system prompt |
| [`ContextFile`][pydantic_deep.toolsets.context.ContextFile] | Loaded context file (name, path, content) |
| [`discover_context_files`][pydantic_deep.toolsets.context.discover_context_files] | Auto-discover context files in backend |
| [`load_context_files`][pydantic_deep.toolsets.context.load_context_files] | Load context files from backend |
| [`format_context_prompt`][pydantic_deep.toolsets.context.format_context_prompt] | Format files for system prompt |
| `DEFAULT_CONTEXT_FILENAMES` | Default filenames: DEEP.md, AGENTS.md, CLAUDE.md, SOUL.md |
| `SUBAGENT_CONTEXT_ALLOWLIST` | Files allowed for subagents: DEEP.md, AGENTS.md |

## Next Steps

- [Memory](memory.md) — Persistent agent memory
- [Output Styles](output-styles.md) — Control response formatting
- [Hooks](hooks.md) — Claude Code-style lifecycle hooks
