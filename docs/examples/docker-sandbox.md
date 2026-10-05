# Docker Sandbox Example

!!! info "Full Documentation"
    For complete Docker documentation, see **[pydantic-ai-backend Docker docs](https://vstorm-co.github.io/pydantic-ai-backend/concepts/docker/)**.

This example demonstrates isolated code execution in a Docker container, with
`DockerWorkspace` as the agent's workspace.

## Source Code

:material-file-code: `examples/docker_sandbox.py`

## Prerequisites

!!! warning "Docker Required"
    This example requires Docker to be installed and running.

```bash
# Install Docker: https://docs.docker.com/get-docker/

# Pull Python image
docker pull python:3.12-slim

# Install the Docker extra
uv add "pydantic-deep[sandbox]"
```

## Overview

`DockerWorkspace` provides:

- An isolated environment for every file and command of a run
- A container created on first use and kept after the run
- Reattachment: a later run carrying the container's ref works in it again
- Removal when you say so, with `destroy`

## Full Example

```python
"""Docker sandbox example for isolated code execution."""

import asyncio

from pydantic_ai.workspaces import WorkspaceRef

from pydantic_deep import DeepAgentDeps, DockerWorkspace, create_deep_agent


async def main():
    docker = DockerWorkspace(
        image="python:3.12-slim",
        work_dir="/workspace",
        container_name="fibonacci-demo",
    )
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        instructions="""
        You are a Python development assistant.
        You can write code, save it to files, and execute it.
        Always test your code by running it.
        """,
        workspace=docker,
        # Require approval for execute (safety)
        interrupt_on={"execute": True},
    )

    try:
        result = await agent.run(
            """
            Create a Python script that:
            1. Defines a function to calculate fibonacci numbers
            2. Prints the first 10 fibonacci numbers
            3. Save it to /workspace/fibonacci.py
            4. Run it and show the output
            """,
            deps=DeepAgentDeps(),
        )
        print(result.output)
    finally:
        # The container outlives the run: remove it
        await docker.destroy(WorkspaceRef(provider="docker", id="fibonacci-demo"))


if __name__ == "__main__":
    asyncio.run(main())
```

## Configuration

### Basic Setup

```python
docker = DockerWorkspace(
    image="python:3.12-slim",  # Docker image
    work_dir="/workspace",      # Working directory in the container
)
```

### Limits and isolation

```python
docker = DockerWorkspace(
    image="python:3.12-slim",
    network_mode="none",  # no network
    mem_limit="512m",
    cpus=1.0,
    oci_runtime="runsc",  # gVisor, if installed: a kernel of its own
    env={"PYTHONUNBUFFERED": "1"},
)
```

A container is only as isolated as its runtime: Docker's default `runc` shares
the host kernel.

### Persistent Storage with Volumes

Files inside a container live as long as the container. Use `volumes` to keep
them on the host filesystem — or to let the agent work on a project in place:

```python
docker = DockerWorkspace(
    image="python:3.12-slim",
    volumes={
        "/path/on/host": "/workspace",  # host_path: container_path
    },
)
```

Multiple volume mappings are supported:

```python
docker = DockerWorkspace(
    volumes={
        "/host/workspace": "/workspace",
        "/host/data": "/data",
    },
)
```

### One container per session

For multi-user applications, name a container after each session and pass the
run its workspace — see [Multi-User](../advanced/multi-user.md):

```python
from pydantic_ai.workspaces import Workspace

def session_workspace(session_id: str) -> Workspace:
    return Workspace(
        DockerWorkspace(
            volumes={f"/var/app/workspaces/{session_id}": "/workspace"},
            container_name=f"session-{session_id}",
        ).backend()
    )

agent = create_deep_agent(workspace=False)
result = await agent.run(prompt, deps=deps, workspace=session_workspace("user-123"))
```

The same name reaches the same container from this process or the next; the
mounted directory keeps the files even after the container is removed.

## Execution

The `execute` tool runs commands inside the container:

```python
# Agent can call:
execute(command="python script.py", timeout=30)
```

It answers with the command's output, and with its exit code when that is not
zero.

## Human-in-the-Loop

Always require approval for execution:

```python
from pydantic_ai import DeferredToolRequests

agent = create_deep_agent(
    workspace=docker,
    interrupt_on={"execute": True},
)

result = await agent.run(prompt, deps=deps)

if isinstance(result.output, DeferredToolRequests):
    for call in result.output.approvals:
        if call.tool_name == "execute":
            print(f"Command: {call.args['command']}")
            # Review and approve/deny
```

See [Human-in-the-Loop](../learn/human-in-the-loop.md) for continuing the run.

## Container Lifecycle

The container is created on the run's first workspace operation, not when you
build `DockerWorkspace`. It is **kept** after the run — that is what lets a
conversation come back to it — so remove it yourself:

```python
await docker.destroy(WorkspaceRef(provider="docker", id="fibonacci-demo"))
```

Without a `container_name`, take the ref from the run: `result.workspace.ref`.

## File Operations

Your own code works in the container through the run's workspace:

```python
workspace = result.workspace

await workspace.write_text("/workspace/app.py", "print('hello')")
content = await workspace.read_text("/workspace/app.py")
entries = await workspace.list_dir("/workspace")

run = await workspace.run(["python", "/workspace/app.py"], timeout=30)
print(run.exit_code, run.stdout, run.stderr)
```

## Security Considerations

!!! danger "Security Warning"
    Even with Docker isolation, be cautious about:

    - Network access from container
    - Resource consumption
    - Malicious code execution
    - Container escape vulnerabilities

### Best Practices

1. **Always require approval** for `execute`
2. **Use minimal images** (slim variants)
3. **Limit the container**: `network_mode`, `mem_limit`, `cpus`, `oci_runtime`
4. **Review commands** before approval
5. **Remove containers** when you are done with them

## Alternative: LocalWorkspace

For development without Docker, `LocalWorkspace` runs commands on this machine:

```python
from pydantic_deep import LocalWorkspace

agent = create_deep_agent(workspace=LocalWorkspace("./workspace"))
```

!!! warning
    `LocalWorkspace` runs commands on your actual machine with no isolation.
    Only use it for trusted code in development.

## Running the Example

```bash
# Ensure Docker is running
docker ps

# Run example
uv run python examples/docker_sandbox.py
```

## Expected Output

```
Note: This example requires Docker to be installed and running.

Agent Response:
==================================================
I'll create a fibonacci script for you...

[Approval prompt for execute command]

Running: python /workspace/fibonacci.py

Output:
0, 1, 1, 2, 3, 5, 8, 13, 21, 34

The script successfully calculated and printed the first 10 Fibonacci numbers.
```

## Next Steps

- [Concepts: Workspaces](../concepts/workspaces.md) - Deep dive
- [Human-in-the-Loop](../learn/human-in-the-loop.md) - Approval workflows
- [API Reference](../api/workspaces.md) - Workspaces API
