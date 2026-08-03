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
    AsyncBaseSandbox,
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

## Writing your own backend

Subclass one of the two bases rather than implementing `BackendProtocol` by hand:
each derives every file operation from shell commands, so you implement `execute`
and `edit` and get the rest.

| Base | For a sandbox reached | Notes |
|---|---|---|
| `BaseSandbox` | synchronously — a socket, a subprocess | |
| `AsyncBaseSandbox` | over an async transport — `asyncssh`, an async HTTP SDK | Implement `execute` and `edit` as coroutines |

Pick `AsyncBaseSandbox` for a natively async sandbox rather than wrapping it in a
synchronous facade: `ensure_async` cannot see through a facade, so it thread-wraps
it and every call then occupies a worker thread that has to hop back onto the
event loop. A sandbox whose own recovery path also needs a thread deadlocks
against its own pool. `is_async_backend` is the check `ensure_async` uses, exposed
so a host can ask the same question.

See [Writing your own backend](https://vstorm-co.github.io/pydantic-ai-backend/concepts/backends/#writing-your-own-backend).

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
