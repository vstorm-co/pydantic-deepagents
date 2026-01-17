# Filesystem Example

This example demonstrates working with files using LocalBackend.

!!! info "Full Documentation"
    For complete backend documentation, see **[pydantic-ai-backend docs](https://vstorm-co.github.io/pydantic-ai-backend/)**.

## LocalBackend

### Source Code

:material-file-code: `examples/filesystem_backend.py`

### Overview

```python
"""Working with local files."""

import asyncio
from pathlib import Path

from pydantic_deep import (
    create_deep_agent,
    DeepAgentDeps,
    LocalBackend,
)


async def main():
    # Create backend pointing to workspace directory
    backend = LocalBackend(root_dir="./workspace")

    agent = create_deep_agent()
    deps = DeepAgentDeps(backend=backend)

    result = await agent.run(
        """
        Create a Python project structure:
        1. src/app.py - Main application
        2. src/utils.py - Utility functions
        3. tests/test_app.py - Test file
        4. README.md - Project description
        """,
        deps=deps,
    )

    print(result.output)

    # Check what was created
    print("\nFiles created:")
    for path in Path("./workspace").rglob("*"):
        if path.is_file():
            print(f"  {path}")


asyncio.run(main())
```

### Security Options

```python
# Restrict to specific directories
backend = LocalBackend(
    allowed_directories=["./workspace", "./data"],
)

# Disable shell execution
backend = LocalBackend(
    root_dir="./workspace",
    enable_execute=False,
)
```

## CompositeBackend

### Source Code

:material-file-code: `examples/composite_backend.py`

### Overview

Route operations to different backends by path prefix:

```python
"""Mixed storage strategies with CompositeBackend."""

import asyncio

from pydantic_deep import (
    create_deep_agent,
    DeepAgentDeps,
    StateBackend,
    LocalBackend,
    CompositeBackend,
)


async def main():
    # Create backends:
    # - StateBackend for temporary scratch files
    # - LocalBackend for persistent project files
    memory = StateBackend()
    local = LocalBackend(root_dir="./workspace")

    # Route by path prefix
    backend = CompositeBackend(
        default=memory,  # Unmatched paths go here
        routes={
            "/project/": local,    # Project files to disk
            "/workspace/": local,  # Workspace files to disk
            # /temp/, /scratch/ go to memory (default)
        },
    )

    agent = create_deep_agent()
    deps = DeepAgentDeps(backend=backend)

    result = await agent.run(
        """
        Create files in different locations:
        1. /project/src/app.py - Persistent application code
        2. /project/README.md - Persistent documentation
        3. /scratch/notes.txt - Temporary notes (in memory)
        """,
        deps=deps,
    )

    print(result.output)

    # Show what's where
    print("\nIn memory (temporary):")
    for path in memory.files.keys():
        print(f"  {path}")


asyncio.run(main())
```

### Use Cases

| Pattern | Use Case |
|---------|----------|
| Memory default + Local routes | Scratch space + persistent output |
| Multiple local routes | Multi-project workspace |
| Docker route + Local route | Execute code + persist results |

## File Operations

All backends support these operations:

```python
# Find all Python files
matches = backend.glob_info("**/*.py", path="/project")
for match in matches:
    print(f"{match['path']} ({match['size']} bytes)")

# Search for function definitions
results = backend.grep_raw(r"def \w+\(", path="/project/src")
for result in results:
    print(f"{result['path']}:{result['line_number']}: {result['line']}")

# Read lines 100-200
content = backend.read("/large_file.py", offset=99, limit=100)

# Edit operations
result = backend.edit(
    "/src/app.py",
    old_string="old_function",
    new_string="new_function",
)
```

## Running the Examples

```bash
# Local backend
uv run python examples/filesystem_backend.py

# Composite backend
uv run python examples/composite_backend.py
```

## Next Steps

- [Docker Sandbox](docker-sandbox.md) - Isolated execution
- [pydantic-ai-backend docs](https://vstorm-co.github.io/pydantic-ai-backend/concepts/backends/) - Full backend reference
