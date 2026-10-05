# API Reference

Complete API documentation for pydantic-deep.

## Modules

| Module | Description |
|--------|-------------|
| [`pydantic_deep.agent`](agent.md) | Agent factory and configuration |
| [Workspaces](workspaces.md) | Where a run works (via Pydantic AI and [pydantic-ai-backend](https://github.com/vstorm-co/pydantic-ai-backend)) |
| [Toolsets](toolsets.md) | Tool collections |
| [Capabilities](capabilities.md) | Lifecycle capabilities |
| [Processors](processors.md) | History processors |
| [`pydantic_deep.mcp`](mcp.md) | MCP client support |
| [Forking](forking.md) | Live Run Forking (parallel branches) |
| [`pydantic_deep.spec`](spec.md) | Declarative agent specs (YAML/JSON) |
| [`pydantic_deep.types`](types.md) | Type definitions |

## Quick Reference

### Main Entry Points

```python
from pydantic_deep import (
    # Agent
    create_deep_agent,
    create_default_deps,
    DeepAgentDeps,

    # Workspaces (LocalWorkspace from Pydantic AI, the rest from pydantic-ai-backend)
    LocalWorkspace,
    StateWorkspace,
    DockerWorkspace,
    SandboxdWorkspace,
    KubernetesWorkspace,
    DaytonaWorkspace,

    # Processors
    SummarizationProcessor,
    create_summarization_processor,

    # Types
    FileData,
    FileInfo,
    Todo,
    SubAgentConfig,
    CompiledSubAgent,
    Skill,
    SkillResource,
    SkillScript,
    SkillsDirectory,
    ResponseFormat,
)

# Toolsets (from their respective packages)
from pydantic_ai_backends import create_console_toolset
from pydantic_ai_todo import create_todo_toolset
from pydantic_deep import SubAgentToolset, SkillsToolset
```

### Creating an Agent

```python
agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    instructions="You are a helpful assistant.",
    include_todo=True,
    include_filesystem=True,
    include_subagents=True,
    include_skills=True,
    subagents=[...],
    skills=[...],
    skill_directories=[...],
    workspace=LocalWorkspace("."),  # default: StateWorkspace(), in memory
    interrupt_on={"execute": True},
)
```

### Creating Dependencies

```python
deps = DeepAgentDeps(
    todos=[],
    subagents={},
)

# Or use helper
deps = create_default_deps()
```

### Running

```python
# Basic run
result = await agent.run(prompt, deps=deps)

# With history
result = await agent.run(
    prompt,
    deps=deps,
    message_history=previous_result.all_messages(),
)

# In a workspace of this run's own (overrides the agent's)
result = await agent.run(prompt, deps=deps, workspace=session_workspace)

# The files the run left
print(await result.workspace.read_text("notes.md"))

# Streaming
async with agent.iter(prompt, deps=deps) as run:
    async for node in run:
        ...
    result = run.result
```

## Type Annotations

pydantic-deep is fully typed. The main agent type is:

```python
Agent[DeepAgentDeps, str]
```

Where:

- `DeepAgentDeps` - Dependencies type
- `str` - Output type (agent returns strings)

## Workspaces

Tools reach the run's workspace as `ctx.workspace`, a Pydantic AI `Workspace`:

```python
await ctx.workspace.read_text(path)
await ctx.workspace.write_text(path, text)
await ctx.workspace.list_dir(path)
await ctx.workspace.run(["python", "script.py"], timeout=30)  # where it runs commands
```

See [Workspaces](../concepts/workspaces.md).

## Exceptions

pydantic-deep uses standard Python exceptions:

| Exception | When Raised |
|-----------|-------------|
| `ValueError` | Invalid arguments (bad paths, missing files) |
| `FileNotFoundError` | File doesn't exist |
| `PermissionError` | Write to a read-only workspace, path traversal attempt |
| `TimeoutError` | Execution timeout |

## Next Steps

- [Agent API](agent.md) - Detailed agent documentation
- [Workspaces API](workspaces.md) - Workspace capabilities
- [Toolsets API](toolsets.md) - Tool collection details
