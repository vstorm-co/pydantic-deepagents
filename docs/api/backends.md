# Backends API

Backends are provided by [pydantic-ai-backend](https://vstorm-co.github.io/pydantic-ai-backend/).

!!! info "Full API Reference"
    For complete API documentation, see **[pydantic-ai-backend API Reference](https://vstorm-co.github.io/pydantic-ai-backend/api/)**.

## Quick Import Reference

```python
from pydantic_deep import (
    # Backends
    LocalBackend,
    StateBackend,
    CompositeBackend,
    DockerSandbox,
    BaseSandbox,
    # Protocols
    BackendProtocol,
    SandboxProtocol,
    # Session Management
    SessionManager,
    # Runtimes
    RuntimeConfig,
    BUILTIN_RUNTIMES,
    get_runtime,
    # Console Toolset
    create_console_toolset,
    get_console_system_prompt,
    ConsoleDeps,
    # Types
    FileInfo,
    FileData,
    WriteResult,
    EditResult,
    ExecuteResponse,
    GrepMatch,
)
```

## Available Backends

| Backend | Description | Docs |
|---------|-------------|------|
| `LocalBackend` | Local filesystem with shell execution | [Link](https://vstorm-co.github.io/pydantic-ai-backend/concepts/backends/#localbackend) |
| `StateBackend` | In-memory storage for testing | [Link](https://vstorm-co.github.io/pydantic-ai-backend/concepts/backends/#statebackend) |
| `DockerSandbox` | Docker container execution | [Link](https://vstorm-co.github.io/pydantic-ai-backend/concepts/docker/) |
| `CompositeBackend` | Route by path prefix | [Link](https://vstorm-co.github.io/pydantic-ai-backend/concepts/backends/#compositebackend) |

## Console Toolset

The console toolset provides file operation tools for pydantic-ai agents:

```python
from pydantic_deep import create_console_toolset, LocalBackend, DeepAgentDeps

toolset = create_console_toolset()
backend = LocalBackend(root_dir=".")
deps = DeepAgentDeps(backend=backend)
```

See [Console Toolset docs](https://vstorm-co.github.io/pydantic-ai-backend/concepts/console-toolset/) for details.

## SessionManager

For multi-user applications with isolated Docker sandboxes:

```python
from pydantic_deep import SessionManager

manager = SessionManager(
    default_runtime="python-datascience",
    workspace_root="/app/workspaces",
)

sandbox = await manager.get_or_create(user_id="alice")
```

See [Docker docs](https://vstorm-co.github.io/pydantic-ai-backend/concepts/docker/#sessionmanager-for-multi-user) for details.
