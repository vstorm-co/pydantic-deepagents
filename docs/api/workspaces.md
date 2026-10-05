# Workspaces API

The workspace capabilities come from Pydantic AI (`LocalWorkspace`) and
[pydantic-ai-backend](https://vstorm-co.github.io/pydantic-ai-backend/) (the
rest); pydantic-deep re-exports them. See [Workspaces](../concepts/workspaces.md)
for how to choose one.

!!! info "Full API Reference"
    For complete API documentation, see **[pydantic-ai-backend API Reference](https://vstorm-co.github.io/pydantic-ai-backend/api/)**
    and Pydantic AI's **[workspaces](https://ai.pydantic.dev/workspaces/)**.

## Quick Import Reference

```python
from pydantic_deep import (
    # Workspace capabilities
    LocalWorkspace,
    StateWorkspace,
    DockerWorkspace,
    SandboxdWorkspace,
    KubernetesWorkspace,
    DaytonaWorkspace,
    # The document a StateWorkspace works in
    StateBackend,
    # Keeps file operations inside a workspace's working directory
    ConfinedWorkspace,
    # Docker runtimes
    RuntimeConfig,
    BUILTIN_RUNTIMES,
    get_runtime,
    # Console toolset
    create_console_toolset,
    get_console_system_prompt,
    # Types
    FileData,
    FileInfo,
)
```

## Workspace capabilities

| Capability | Where a run works | Docs |
|------------|-------------------|------|
| `LocalWorkspace(path)` | A directory on this machine | [Link](https://ai.pydantic.dev/workspaces/) |
| `StateWorkspace()` | An in-memory `StateBackend` document, files only | [Link](https://vstorm-co.github.io/pydantic-ai-backend/concepts/workspaces/) |
| `DockerWorkspace(...)` | A Docker container on this host | [Link](https://vstorm-co.github.io/pydantic-ai-backend/concepts/docker/) |
| `SandboxdWorkspace(...)` | A `sandboxd` session | [Link](https://vstorm-co.github.io/pydantic-ai-backend/concepts/remote/) |
| `KubernetesWorkspace(...)` | A pod | [Link](https://vstorm-co.github.io/pydantic-ai-backend/concepts/kubernetes/) |
| `DaytonaWorkspace(...)` | A Daytona sandbox | [Link](https://vstorm-co.github.io/pydantic-ai-backend/concepts/daytona/) |

Each sandbox capability creates its environment on first use and keeps it after
the run; `await capability.destroy(ref)` removes it.

`ConfinedWorkspace(workspace)` wraps a workspace and refuses a file operation
whose real path leaves its working directory; the console's `glob` and `grep`
check their search root the same way. Commands are not confined. See
[Workspaces](../concepts/workspaces.md#localworkspace-real-files-on-disk).

## Console Toolset

`create_deep_agent` builds the console toolset for you. To give a plain Pydantic
AI agent the same file and shell tools:

```python
from pydantic_ai import Agent, DeferredToolRequests
from pydantic_deep import LocalWorkspace, create_console_toolset

agent = Agent(
    "anthropic:claude-sonnet-4-6",
    capabilities=[LocalWorkspace(".")],
    toolsets=[create_console_toolset()],
    # `execute` asks for approval by default; or pass require_execute_approval=False
    output_type=[str, DeferredToolRequests],
)
```

See [Console Toolset docs](https://vstorm-co.github.io/pydantic-ai-backend/concepts/console-toolset/) for details.
