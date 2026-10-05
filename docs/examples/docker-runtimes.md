# Docker Runtimes

This guide shows how to use `RuntimeConfig` with `DockerWorkspace` for
pre-configured environments, and how to give each user a container of their own.

## Quick Start

```python
from pydantic_ai.workspaces import WorkspaceRef
from pydantic_deep import DeepAgentDeps, DockerWorkspace, create_deep_agent

# Use a built-in runtime with pre-installed packages
docker = DockerWorkspace(runtime="python-datascience", container_name="analysis")
agent = create_deep_agent(workspace=docker)

deps = DeepAgentDeps()
await deps.upload_file("data.csv", csv_bytes)  # lands at /workspace/uploads/data.csv
try:
    result = await agent.run("Load uploads/data.csv and create a visualization", deps=deps)
finally:
    await docker.destroy(WorkspaceRef(provider="docker", id="analysis"))
```

## RuntimeConfig

The `RuntimeConfig` class defines a pre-configured execution environment.

### Using Built-in Runtimes

pydantic-deep provides several built-in runtimes:

| Runtime | Description | Packages |
|---------|-------------|----------|
| `python-minimal` | Clean Python 3.12 | None |
| `python-datascience` | Data science stack | pandas, numpy, matplotlib, scikit-learn, seaborn |
| `python-web` | Web development | FastAPI, SQLAlchemy, httpx, uvicorn |
| `node-minimal` | Clean Node.js 20 | None |
| `node-react` | React development | TypeScript, Vite, React |

```python
from pydantic_deep import BUILTIN_RUNTIMES, DockerWorkspace

# Option 1: Use runtime name (string)
docker = DockerWorkspace(runtime="python-datascience")

# Option 2: Use RuntimeConfig directly
docker = DockerWorkspace(runtime=BUILTIN_RUNTIMES["python-datascience"])
```

### Creating Custom Runtimes

```python
from pydantic_deep import DockerWorkspace, RuntimeConfig

# Custom ML runtime
ml_runtime = RuntimeConfig(
    name="ml-env",
    description="Machine learning environment with PyTorch",
    base_image="python:3.12-slim",
    packages=["torch", "transformers", "datasets", "accelerate"],
    setup_commands=["apt-get update", "apt-get install -y git"],
    env_vars={"TOKENIZERS_PARALLELISM": "false"},
    work_dir="/workspace",
)

docker = DockerWorkspace(runtime=ml_runtime)
```

### Runtime Configuration Options

```python
RuntimeConfig(
    name="my-runtime",           # Unique identifier
    description="...",           # Human-readable description

    # Image source (choose one):
    image="my-registry/image:v1",  # Pre-built image
    # OR
    base_image="python:3.12",      # Base image to build upon

    # Packages (only with base_image):
    packages=["pandas", "numpy"],
    package_manager="pip",  # pip, npm, apt, cargo

    # Additional setup:
    setup_commands=["apt-get update"],
    env_vars={"DEBUG": "true"},
    work_dir="/workspace",

    # Caching:
    cache_image=True,  # Cache built images locally
)
```

The image is built the first time a container needs it; with `cache_image=True`
later containers reuse it.

## A container per user

For multi-user applications, give each user a named container and pass every
run its user's workspace. The agent itself stays shared and stateless.

```python
from pathlib import Path

from pydantic_ai.workspaces import Workspace, WorkspaceRef
from pydantic_deep import DeepAgentDeps, DockerWorkspace, create_deep_agent

WORKSPACES = Path("/var/app/workspaces")

agent = create_deep_agent(workspace=False)


def user_container(user_id: str) -> DockerWorkspace:
    host_dir = WORKSPACES / user_id / "workspace"
    host_dir.mkdir(parents=True, exist_ok=True)
    return DockerWorkspace(
        runtime="python-datascience",
        volumes={str(host_dir): "/workspace"},  # files outlive the container
        container_name=f"agent-{user_id}",
    )


async def handle_user_request(user_id: str, query: str) -> str:
    workspace = Workspace(user_container(user_id).backend())
    result = await agent.run(query, deps=DeepAgentDeps(), workspace=workspace)
    return result.output


async def remove_user_container(user_id: str) -> None:
    await user_container(user_id).destroy(
        WorkspaceRef(provider="docker", id=f"agent-{user_id}")
    )
```

### Persistence

The same `container_name` reaches the same container, from this process or the
next, so a user's installed packages and running state survive between
requests. The mounted host directory keeps their files even after the container
is removed:

!!! tip "Directory Structure"
    ```
    /var/app/workspaces/
    ├── user-123/
    │   └── workspace/        → mounted as /workspace
    │       ├── report.pdf
    │       └── data.csv
    ├── user-456/
    │   └── workspace/
    │       └── analysis.py
    └── user-789/
        └── workspace/
    ```

### Cleanup

Containers are never removed for you. Remove a user's when their session ends,
and every user's when the application shuts down — the files stay on the host.
For idle cleanup, remove the containers of users you have not seen for a while
from a periodic task of your own.

## Best Practices

1. **Use built-in runtimes when possible** - They're tested and optimized.

2. **Enable image caching** - Set `cache_image=True` (default) to avoid rebuilding images.

3. **Mount a host directory per user** - The files then outlive the container.

4. **Always clean up** - `await capability.destroy(ref)` removes a container.

5. **Limit the container** - `network_mode`, `mem_limit`, `cpus` and `oci_runtime`
   on `DockerWorkspace`; see [Docker Sandbox](docker-sandbox.md#limits-and-isolation).
