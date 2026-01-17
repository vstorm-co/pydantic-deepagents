# Backends

Backends provide file storage for deep agents. pydantic-deep uses backends from [pydantic-ai-backend](https://vstorm-co.github.io/pydantic-ai-backend/).

!!! info "Full Documentation"
    For complete backend documentation, see **[pydantic-ai-backend docs](https://vstorm-co.github.io/pydantic-ai-backend/concepts/backends/)**.

## Available Backends

| Backend | Persistence | Execution | Use Case |
|---------|-------------|-----------|----------|
| `LocalBackend` | Persistent | Yes | CLI tools, local development |
| `StateBackend` | Ephemeral | No | Testing, temporary files |
| `DockerSandbox` | Ephemeral | Yes | Safe code execution |
| `CompositeBackend` | Mixed | Depends | Route by path prefix |

## Quick Examples

### LocalBackend

For CLI tools and local development:

```python
from pydantic_deep import create_deep_agent, DeepAgentDeps, LocalBackend

backend = LocalBackend(root_dir="./workspace")
deps = DeepAgentDeps(backend=backend)

agent = create_deep_agent()
result = await agent.run("Create a Python script", deps=deps)
```

### StateBackend

For testing (in-memory, no side effects):

```python
from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend

backend = StateBackend()
deps = DeepAgentDeps(backend=backend)

# Files stored in memory only
backend.write("/src/app.py", "print('hello')")
```

### DockerSandbox

For safe code execution:

```python
from pydantic_deep import create_deep_agent, DeepAgentDeps, DockerSandbox

sandbox = DockerSandbox(runtime="python-datascience")

try:
    deps = DeepAgentDeps(backend=sandbox)
    agent = create_deep_agent()
    result = await agent.run("Analyze data with pandas", deps=deps)
finally:
    sandbox.stop()
```

### CompositeBackend

Route operations by path prefix:

```python
from pydantic_deep import CompositeBackend, StateBackend, LocalBackend

backend = CompositeBackend(
    default=StateBackend(),
    routes={
        "/project/": LocalBackend(root_dir="/my/project"),
    },
)
```

## Learn More

- **[Backends Documentation](https://vstorm-co.github.io/pydantic-ai-backend/concepts/backends/)** - Full backend reference
- **[Docker Sandbox](https://vstorm-co.github.io/pydantic-ai-backend/concepts/docker/)** - Docker execution environments
- **[Console Toolset](https://vstorm-co.github.io/pydantic-ai-backend/concepts/console-toolset/)** - File operation tools
