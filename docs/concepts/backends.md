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

Route operations to different backends based on path prefix:

```python
from pydantic_deep import CompositeBackend, StateBackend, LocalBackend, DockerSandbox

backend = CompositeBackend(
    default=StateBackend(),
    routes={
        "/project/": LocalBackend(root_dir="/my/project"),
        "/sandbox/": DockerSandbox(runtime="python-minimal"),
    },
)
```

**Routing Logic:**

1. Paths are matched by prefix (longest match wins)
2. Operations are forwarded to the matched backend
3. Unmatched paths go to `default` backend

**Example routing:**

```python
backend = CompositeBackend(
    default=StateBackend(),  # For /tmp, /cache, etc.
    routes={
        "/src/": LocalBackend(root_dir="./src"),       # Source files
        "/data/": LocalBackend(root_dir="./data"),     # Data files
        "/output/": StateBackend(),                     # Temporary output
    },
)

# Route: /src/app.py → LocalBackend("./src")
backend.write("/src/app.py", "print('hello')")

# Route: /data/input.csv → LocalBackend("./data")
content = backend.read("/data/input.csv")

# Route: /tmp/cache.json → default StateBackend
backend.write("/tmp/cache.json", "{}")

# Route: /output/result.txt → StateBackend (explicit route)
backend.write("/output/result.txt", "done")
```

**Use cases:**

| Use Case | Configuration |
|----------|---------------|
| Read-only source + writable output | `routes={"/src/": LocalBackend()}`, `default=StateBackend()` |
| Multiple project directories | Multiple LocalBackend routes |
| Safe execution with local files | `routes={"/code/": DockerSandbox()}`, `default=LocalBackend()` |
| Testing with fixtures | `routes={"/fixtures/": LocalBackend("./test/fixtures")}` |

**Path transformation:**

Routes strip the prefix when forwarding to the target backend:

```python
backend = CompositeBackend(
    routes={"/project/": LocalBackend(root_dir="/home/user/myproject")}
)

# Write to /project/src/main.py
# → LocalBackend receives path: /src/main.py
# → Actual file: /home/user/myproject/src/main.py
backend.write("/project/src/main.py", "code")
```

## Learn More

- **[Backends Documentation](https://vstorm-co.github.io/pydantic-ai-backend/concepts/backends/)** - Full backend reference
- **[Docker Sandbox](https://vstorm-co.github.io/pydantic-ai-backend/concepts/docker/)** - Docker execution environments
- **[Console Toolset](https://vstorm-co.github.io/pydantic-ai-backend/concepts/console-toolset/)** - File operation tools
