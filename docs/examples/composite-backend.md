# Composite Backend Example

Combine multiple backends with path-based routing.

!!! info "Full Documentation"
    For complete backend documentation, see **[pydantic-ai-backend docs](https://vstorm-co.github.io/pydantic-ai-backend/concepts/backends/)**.

## Source Code

:material-file-code: `examples/composite_backend.py`

## Overview

This example demonstrates:

- Combining multiple backends (memory + local)
- Routing operations by path prefix
- Using persistent and ephemeral storage together

## When to Use CompositeBackend

CompositeBackend is useful when:

- Some files should persist (project files) while others are temporary (scratch)
- Different paths need different storage characteristics
- You want to isolate certain operations

## Full Example

```python
"""Example using CompositeBackend for mixed storage."""

import asyncio

from pydantic_deep import (
    CompositeBackend,
    DeepAgentDeps,
    LocalBackend,
    StateBackend,
    create_deep_agent,
)


async def main():
    # Create backends:
    # - StateBackend for temporary/scratch files
    # - LocalBackend for persistent project files
    memory_backend = StateBackend()
    local_backend = LocalBackend(root_dir="./workspace")

    # Create composite backend with routing rules
    backend = CompositeBackend(
        default=memory_backend,  # Default to memory for unmatched paths
        routes={
            "/project/": local_backend,    # Project files go to disk
            "/workspace/": local_backend,  # Workspace files go to disk
        },
    )

    # Create the agent
    agent = create_deep_agent(
        model="openai:gpt-4.1",
        instructions="""
        You are a project assistant.

        File organization:
        - /project/ - Persistent project files (saved to disk)
        - /workspace/ - Working files (saved to disk)
        - /temp/ or /scratch/ - Temporary files (in memory only)

        Use the appropriate location based on whether files should persist.
        """,
    )

    deps = DeepAgentDeps(backend=backend)

    # Run the agent
    result = await agent.run(
        """Create a small Python project:
        1. Create /project/src/app.py with a simple Flask app
        2. Create /project/requirements.txt with dependencies
        3. Create /scratch/notes.txt with implementation notes (temporary)
        4. Create /project/README.md with project description
        """,
        deps=deps,
    )

    print("Agent output:")
    print(result.output)

    # Show what's in memory (temporary files)
    print("\nTemporary files (in memory):")
    for path in sorted(memory_backend.files.keys()):
        print(f"  {path}")


if __name__ == "__main__":
    asyncio.run(main())
```

## Running the Example

```bash
export OPENAI_API_KEY=your-api-key
uv run python examples/composite_backend.py
```

## Key Concepts

### Route Configuration

```python
backend = CompositeBackend(
    default=memory_backend,     # Fallback for unmatched paths
    routes={
        "/project/": local_backend,    # Paths starting with /project/
        "/workspace/": local_backend,  # Paths starting with /workspace/
    },
)
```

Routes are matched by prefix. The first matching route wins.

### How Routing Works

```python
# These go to local_backend (match /project/ prefix)
backend.write("/project/src/main.py", "...")
backend.read("/project/config.json")

# These go to memory_backend (default, no route matches)
backend.write("/scratch/temp.txt", "...")
backend.read("/notes.md")
```

## Variations

### Docker + Local Hybrid

```python
from pydantic_deep import DockerSandbox, LocalBackend

backend = CompositeBackend(
    default=DockerSandbox(runtime="python-datascience"),  # Isolated execution
    routes={
        "/local/": LocalBackend(root_dir="./local"),  # Local access
    },
)
```

### Read-Only Source + Writable Workspace

```python
# Source files are read-only
source_backend = LocalBackend(
    root_dir="./src",
    enable_execute=False,
)

# Workspace for modifications
workspace_backend = StateBackend()

backend = CompositeBackend(
    default=workspace_backend,
    routes={
        "/src/": source_backend,  # Read-only source
    },
)
```

## Best Practices

1. **Clear path conventions** - Document which paths go where
2. **Default to memory** - Safe fallback for unexpected paths
3. **Consider persistence needs** - What should survive restarts?

## Next Steps

- [Filesystem Example](filesystem.md) - Single backend usage
- [Docker Sandbox](docker-sandbox.md) - Isolated execution
- [pydantic-ai-backend docs](https://vstorm-co.github.io/pydantic-ai-backend/concepts/backends/) - Full reference
