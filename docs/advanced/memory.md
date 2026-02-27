# Persistent Memory

Persistent memory gives agents a `MEMORY.md` file stored in the backend that survives across sessions. Memory is auto-loaded into the system prompt and writable via tools.

## Quick Start

```python
from pydantic_deep import create_deep_agent

agent = create_deep_agent(include_memory=True)
```

The agent gets three memory tools:

| Tool | Description |
|------|-------------|
| `read_memory` | Read full memory content |
| `write_memory` | Append new content to memory |
| `update_memory` | Find and replace text in memory |

Memory is also automatically injected into the system prompt (first 200 lines) so the agent sees it without needing to call `read_memory`.

## Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `include_memory` | `bool` | `False` | Enable persistent memory |
| `memory_dir` | `str` | `"/.deep/memory"` | Base directory for memory files |

### Storage Layout

Each agent gets its own memory file:

```
/.deep/memory/
  main/MEMORY.md          # Main agent's memory
  code-reviewer/MEMORY.md # Subagent's memory
  test-writer/MEMORY.md   # Another subagent's memory
```

## How It Works

### System Prompt Injection

When memory exists, the [`AgentMemoryToolset`][pydantic_deep.toolsets.memory.AgentMemoryToolset] injects it into the system prompt via `get_instructions()`:

```
## Agent Memory (main)

- User prefers TypeScript over JavaScript
- Project uses PostgreSQL with Prisma ORM
- Always run `npm test` before committing
```

Only the first 200 lines are included to stay within token budget. If truncated, a marker is added:

```
... [50 more lines in memory] ...
```

### Writing Memory

The agent appends to memory when it learns something worth remembering:

```
Agent: I notice you always prefer functional programming patterns.
       Let me save this to memory.
       [calls write_memory("- User prefers functional patterns over OOP")]
```

### Updating Memory

The agent can find-and-replace text to correct or update entries:

```
Agent: The project switched from MySQL to PostgreSQL.
       [calls update_memory("Uses MySQL", "Uses PostgreSQL")]
```

## Subagent Memory

When `include_memory=True`, all subagents automatically get their own memory files. Each subagent writes to `{memory_dir}/{subagent_name}/MEMORY.md`.

### Disabling Memory for Specific Subagents

Use `extra={"memory": False}` in the subagent config:

```python
from pydantic_deep import SubAgentConfig

subagents = [
    SubAgentConfig(
        name="code-reviewer",
        description="Reviews code",
        instructions="...",
        # Memory enabled by default
    ),
    SubAgentConfig(
        name="ephemeral-worker",
        description="One-off tasks",
        instructions="...",
        extra={"memory": False},  # No memory for this subagent
    ),
]

agent = create_deep_agent(
    include_memory=True,
    subagents=subagents,
)
```

### Custom Max Lines per Subagent

```python
SubAgentConfig(
    name="code-reviewer",
    description="Reviews code",
    instructions="...",
    extra={"memory_max_lines": 50},  # Only inject 50 lines
)
```

!!! warning "Multi-User Applications"
    Memory writes to the backend at `{memory_dir}/{agent_name}/MEMORY.md`. If multiple users
    share the same backend instance, they share the same memory files. For multi-user apps,
    give each user a separate backend instance. See [Multi-User Guide](multi-user.md).

## Custom Tool Descriptions

You can override the default tool descriptions with the `descriptions` parameter. This is useful when you want the LLM to interpret a tool differently or when integrating with a specific workflow:

```python
from pydantic_deep.toolsets.memory import AgentMemoryToolset

memory_toolset = AgentMemoryToolset(
    descriptions={
        "write_memory": "Save important findings to persistent memory",
        "read_memory": "Recall previously saved findings from memory",
    },
)
```

Only the keys you provide are overridden; any missing keys fall back to the built-in descriptions. Supported keys: `read_memory`, `write_memory`, `update_memory`.

## Standalone Usage

Use `AgentMemoryToolset` directly for custom setups:

```python
from pydantic_deep.toolsets.memory import AgentMemoryToolset

memory_toolset = AgentMemoryToolset(
    agent_name="my-agent",
    memory_dir="/.custom/memory",
    max_lines=100,
)
```

## Components

| Component | Description |
|-----------|-------------|
| [`AgentMemoryToolset`][pydantic_deep.toolsets.memory.AgentMemoryToolset] | Toolset with memory tools and system prompt injection |
| [`MemoryFile`][pydantic_deep.toolsets.memory.MemoryFile] | Loaded memory file (agent_name, path, content) |
| [`load_memory`][pydantic_deep.toolsets.memory.load_memory] | Load memory from backend |
| [`format_memory_prompt`][pydantic_deep.toolsets.memory.format_memory_prompt] | Format memory for system prompt |
| [`get_memory_path`][pydantic_deep.toolsets.memory.get_memory_path] | Compute memory file path |

## Next Steps

- [Context Files](context-files.md) — Project context (DEEP.md, AGENTS.md)
- [Hooks](hooks.md) — Claude Code-style lifecycle hooks
- [Checkpointing](checkpointing.md) — Save and rewind conversation state
