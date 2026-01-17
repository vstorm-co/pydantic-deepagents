# Docker Sandbox Example

!!! info "Full Documentation"
    For complete Docker sandbox documentation, see **[pydantic-ai-backend Docker docs](https://vstorm-co.github.io/pydantic-ai-backend/concepts/docker/)**.

This example demonstrates isolated code execution using DockerSandbox.

## Source Code

:material-file-code: `examples/docker_sandbox.py`

## Prerequisites

!!! warning "Docker Required"
    This example requires Docker to be installed and running.

```bash
# Install Docker: https://docs.docker.com/get-docker/

# Pull Python image
docker pull python:3.12-slim

# Install docker package
uv add pydantic-deep[sandbox]
```

## Overview

DockerSandbox provides:

- Isolated execution environment
- Safe code execution
- Container lifecycle management
- File operations within container

## Full Example

```python
"""Docker sandbox example for isolated code execution."""

import asyncio

from pydantic_deep import DockerSandbox, DeepAgentDeps, create_deep_agent


async def main():
    # Create Docker sandbox
    sandbox = DockerSandbox(
        image="python:3.12-slim",
        work_dir="/workspace",
    )

    try:
        # Create agent with sandbox backend
        agent = create_deep_agent(
            model="openai:gpt-4.1",
            instructions="""
            You are a Python development assistant.
            You can write code, save it to files, and execute it.
            Always test your code by running it.
            """,
            # Require approval for execute (safety)
            interrupt_on={"execute": True},
        )

        deps = DeepAgentDeps(backend=sandbox)

        # Run the agent
        result = await agent.run(
            """
            Create a Python script that:
            1. Defines a function to calculate fibonacci numbers
            2. Prints the first 10 fibonacci numbers
            3. Save it to /workspace/fibonacci.py
            4. Run it and show the output
            """,
            deps=deps,
        )

        print(result.output)

    finally:
        # Always clean up the container
        sandbox.stop()


if __name__ == "__main__":
    asyncio.run(main())
```

## Sandbox Configuration

### Basic Setup

```python
sandbox = DockerSandbox(
    image="python:3.12-slim",  # Docker image
    work_dir="/workspace",      # Working directory in container
)
```

### Custom Configuration

```python
sandbox = DockerSandbox(
    image="python:3.12",
    work_dir="/app",
    auto_remove=True,       # Remove container on stop
    idle_timeout=3600,      # Container lifetime in seconds
)
```

### Persistent Storage with Volumes

By default, files inside the Docker container are lost when the container stops. Use `volumes` to persist files on the host filesystem:

```python
sandbox = DockerSandbox(
    image="python:3.12-slim",
    volumes={
        "/path/on/host": "/workspace",  # host_path: container_path
    },
)

# Files written to /workspace persist on /path/on/host
sandbox.write("/workspace/data.json", '{"key": "value"}')
sandbox.stop()

# Later, files are still there when container restarts
sandbox = DockerSandbox(
    image="python:3.12-slim",
    volumes={"/path/on/host": "/workspace"},
)
content = sandbox.read("/workspace/data.json")  # '{"key": "value"}'
```

Multiple volume mappings are supported:

```python
sandbox = DockerSandbox(
    image="python:3.12-slim",
    volumes={
        "/host/workspace": "/workspace",
        "/host/data": "/data",
        "/host/config": "/config",
    },
)
```

### Automatic Persistent Storage with SessionManager

For multi-user applications, `SessionManager` provides automatic per-session persistent storage:

```python
from pydantic_deep import SessionManager

# Create manager with workspace_root
manager = SessionManager(
    workspace_root="/var/app/workspaces",  # Base directory for all sessions
)

# Each session gets its own persistent directory
sandbox = manager.get_or_create("user-123")
# Creates: /var/app/workspaces/user-123/workspace/
# Mounted as: /workspace in container

# User returns later - files still there
sandbox2 = manager.get_or_create("user-123")
content = sandbox2.read("/workspace/previous_file.py")  # Still exists!
```

!!! tip "When to Use Each Approach"
    - **`volumes`**: Direct control over mount points, custom paths
    - **`workspace_root`**: Automatic per-session directories, multi-user apps

## Execution

The `execute` tool runs commands inside the container:

```python
# Agent can call:
execute(command="python script.py", timeout=30)
```

Response includes:

```python
@dataclass
class ExecuteResponse:
    output: str        # stdout + stderr
    exit_code: int     # Process exit code
    truncated: bool    # True if output was truncated
```

## Human-in-the-Loop

Always require approval for execution:

```python
agent = create_deep_agent(
    interrupt_on={"execute": True},
)

result = await agent.run(prompt, deps=deps)

# Handle approval...
if hasattr(result, 'deferred_tool_calls'):
    for call in result.deferred_tool_calls:
        if call.tool_name == "execute":
            print(f"Command: {call.args['command']}")
            # Review and approve/deny
```

## Container Lifecycle

### Automatic Start

The container starts automatically on first operation:

```python
sandbox = DockerSandbox(image="python:3.12-slim")
sandbox.write("/test.py", "print('hello')")  # Starts container
```

### Manual Stop

Always stop the container when done:

```python
try:
    # Use sandbox...
finally:
    sandbox.stop()
```

Or use context manager pattern:

```python
async with DockerSandbox(...) as sandbox:
    # Use sandbox...
# Container automatically stopped
```

## File Operations

All standard file operations work inside the container:

```python
# Write file
sandbox.write("/workspace/app.py", "print('hello')")

# Read file
content = sandbox.read("/workspace/app.py")

# Edit file
sandbox.edit("/workspace/app.py", "hello", "world")

# List directory
files = sandbox.ls_info("/workspace")

# Glob pattern
python_files = sandbox.glob_info("**/*.py", "/workspace")

# Search content
matches = sandbox.grep_raw("def main", "/workspace")
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
3. **Set timeouts** on execution
4. **Review commands** before approval
5. **Clean up containers** after use

## Error Handling

```python
try:
    result = sandbox.execute("python script.py", timeout=30)
    if result.exit_code != 0:
        print(f"Script failed: {result.output}")
except TimeoutError:
    print("Execution timed out")
except Exception as e:
    print(f"Error: {e}")
finally:
    sandbox.stop()
```

## Alternative: LocalBackend

For development/testing without Docker, use `LocalBackend` which supports shell execution:

```python
from pydantic_deep import LocalBackend

# Executes on local machine
backend = LocalBackend(root_dir="./workspace", enable_execute=True)
```

!!! warning
    LocalBackend runs commands on your actual machine with no isolation.
    Only use for trusted code in development.

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

- [Concepts: Backends](../concepts/backends.md) - Deep dive
- [Human-in-the-Loop](../advanced/human-in-the-loop.md) - Approval workflows
- [API Reference](../api/backends.md) - SandboxProtocol API
