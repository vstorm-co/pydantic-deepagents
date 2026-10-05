# Filesystem Example

Ready to move off in-memory storage and have the agent touch real files? Give
it `LocalWorkspace` and the same agent now reads and writes your actual disk —
and runs commands there. Here's what that looks like.

!!! info "Full Documentation"
    For how workspaces work, see **[Workspaces](../concepts/workspaces.md)**.

## LocalWorkspace

### Source Code

:material-file-code: `examples/local_workspace.py`

### Overview

```python
"""Working with local files."""

import asyncio
from pathlib import Path

from pydantic_deep import (
    create_deep_agent,
    DeepAgentDeps,
    LocalWorkspace,
)


async def main():
    workspace = Path("./workspace")
    workspace.mkdir(exist_ok=True)

    # The agent works in that directory: files and commands
    agent = create_deep_agent(workspace=LocalWorkspace(workspace))

    result = await agent.run(
        """
        Create a Python project structure:
        1. src/app.py - Main application
        2. src/utils.py - Utility functions
        3. tests/test_app.py - Test file
        4. README.md - Project description
        """,
        deps=DeepAgentDeps(),
    )

    print(result.output)

    # Check what was created
    print("\nFiles created:")
    for path in workspace.rglob("*"):
        if path.is_file():
            print(f"  {path}")


asyncio.run(main())
```

### Tightening it

```python
# Read the project, never change it
agent = create_deep_agent(workspace=LocalWorkspace("./project", read_only=True))

# Files only: no shell
agent = create_deep_agent(
    workspace=LocalWorkspace("./workspace"),
    include_execute=False,
)
```

## File Operations

Your own code reaches the same files through the run's workspace — in a tool as
`ctx.workspace`, after a run as `result.workspace`:

```python
workspace = result.workspace

# List a directory
for entry in await workspace.list_dir("src"):
    print(entry.path, "dir" if entry.is_dir else f"{entry.size} bytes")

# Read and write text
source = await workspace.read_text("src/app.py")
await workspace.write_text("src/app.py", source.replace("old_function", "new_function"))

# Commands, where the workspace runs them
result = await workspace.run(["python", "-m", "pytest", "-q"])
print(result.exit_code, result.stdout)
```

## Running the Examples

```bash
uv run python examples/local_workspace.py
```

## Next Steps

- [Docker Sandbox](docker-sandbox.md) - Isolated execution
- [Workspaces](../concepts/workspaces.md) - Every workspace, and how to choose
