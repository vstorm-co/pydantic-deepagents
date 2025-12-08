# File Uploads

Upload files for agent processing. The agent can analyze, search, and work with uploaded files using built-in file tools.

## Overview

pydantic-deep supports two ways to upload files:

1. **`run_with_files()`** - Helper function that uploads files and runs the agent in one call
2. **`deps.upload_file()`** - Direct upload to dependencies for more control

Uploaded files are:

- Stored in the backend (StateBackend, FilesystemBackend, etc.)
- Visible to the agent in the system prompt
- Accessible via file tools (`read_file`, `grep`, `glob`, `execute`)

## Quick Start

### Using run_with_files()

The simplest way to process files:

```python
import asyncio
from pydantic_deep import create_deep_agent, DeepAgentDeps, run_with_files
from pydantic_deep.backends import StateBackend

async def main():
    agent = create_deep_agent()
    deps = DeepAgentDeps(backend=StateBackend())

    # Upload and process files in one call
    with open("data.csv", "rb") as f:
        result = await run_with_files(
            agent,
            "Analyze this data and find trends",
            deps,
            files=[("data.csv", f.read())],
        )

    print(result)

asyncio.run(main())
```

### Using deps.upload_file()

For more control over the upload process:

```python
async def main():
    agent = create_deep_agent()
    deps = DeepAgentDeps(backend=StateBackend())

    # Upload files separately
    deps.upload_file("config.json", b'{"debug": true}')
    deps.upload_file("data.csv", csv_bytes)

    # Run agent - it sees uploaded files in system prompt
    result = await agent.run("Summarize the config and data", deps=deps)
```

## How It Works

### File Storage

When you upload a file:

1. Content is written to the backend at `/uploads/<filename>`
2. Metadata is tracked in `deps.uploads` dict
3. Agent sees file info in dynamic system prompt

```python
deps.upload_file("sales.csv", csv_bytes)

# File stored at: /uploads/sales.csv
# Metadata tracked:
print(deps.uploads)
# {'/uploads/sales.csv': {'name': 'sales.csv', 'path': '/uploads/sales.csv', 'size': 1024, 'line_count': 50}}
```

### System Prompt

The agent sees uploaded files in its context:

```
## Uploaded Files

Files uploaded by the user:
- `/uploads/sales.csv` (1.0 KB, 50 lines)
- `/uploads/config.json` (128 B, 5 lines)

Use `read_file`, `grep`, `glob` or `execute` to work with these files.
For large files, use `offset` and `limit` in `read_file`.
```

### Agent Tools

The agent can use these tools to work with uploaded files:

| Tool | Usage |
|------|-------|
| `read_file` | Read file content (with offset/limit for large files) |
| `grep` | Search for patterns in files |
| `glob` | Find files by pattern |
| `execute` | Run scripts that process files (with DockerSandbox) |

## Custom Upload Directory

By default, files are uploaded to `/uploads/`. You can customize this:

```python
# run_with_files with custom directory
result = await run_with_files(
    agent,
    "Process configs",
    deps,
    files=[("app.json", config_bytes)],
    upload_dir="/configs",  # Files go to /configs/
)

# Direct upload with custom directory
deps.upload_file("db.json", data, upload_dir="/data")
# Stored at: /data/db.json
```

## Multiple Files

Upload multiple files at once:

```python
files = [
    ("sales_q1.csv", q1_data),
    ("sales_q2.csv", q2_data),
    ("sales_q3.csv", q3_data),
]

result = await run_with_files(
    agent,
    "Compare sales across all quarters",
    deps,
    files=files,
)
```

## Binary Files

Binary files (images, PDFs, etc.) are handled with limited support:

```python
# Binary file upload
deps.upload_file("image.png", png_bytes)

# line_count will be None for binary files
print(deps.uploads["/uploads/image.png"]["line_count"])  # None
```

!!! note
    Binary files are stored but text-based analysis is limited. For full binary processing, consider using DockerSandbox with appropriate tools.

## Large Files

For large files, the agent should use pagination:

```python
deps.upload_file("large_log.txt", log_bytes)  # 100,000 lines

# Agent will see:
# - `/uploads/large_log.txt` (5.2 MB, 100000 lines)

# Agent can then:
# 1. read_file("/uploads/large_log.txt", limit=100)  # First 100 lines
# 2. read_file("/uploads/large_log.txt", offset=100, limit=100)  # Next 100
# 3. grep("ERROR", "/uploads/large_log.txt")  # Search for patterns
```

## Subagent Access

Uploaded files are shared with subagents:

```python
deps.upload_file("data.csv", csv_bytes)

# Main agent can delegate to subagent
# Subagent will have access to /uploads/data.csv
result = await agent.run(
    "Delegate data analysis to the data-analyst subagent",
    deps=deps,
)
```

## Complete Example

```python
"""Full file uploads workflow example."""

import asyncio
from pydantic import BaseModel
from pydantic_deep import (
    create_deep_agent,
    DeepAgentDeps,
    StateBackend,
    run_with_files,
)


class AnalysisResult(BaseModel):
    """Structured analysis result."""
    summary: str
    total_records: int
    insights: list[str]


async def main():
    # Create agent with structured output
    agent = create_deep_agent(
        model="openai:gpt-4.1",
        output_type=AnalysisResult,
        instructions="""
        You are a data analyst. When analyzing files:
        1. Read the file to understand structure
        2. Perform analysis
        3. Return structured insights
        """,
    )

    deps = DeepAgentDeps(backend=StateBackend())

    # Sample data
    sales_data = b"""date,product,quantity,revenue
2024-01-15,Widget A,50,2500
2024-01-16,Widget B,30,1800
2024-01-17,Widget A,75,3750
2024-01-18,Widget C,20,1600
2024-01-19,Widget B,45,2700
"""

    # Run with file upload
    result = await run_with_files(
        agent,
        "Analyze the sales data: identify top product, total revenue, and trends",
        deps,
        files=[("sales.csv", sales_data)],
    )

    # Type-safe access to structured result
    print(f"Summary: {result.summary}")
    print(f"Total records: {result.total_records}")
    print("Insights:")
    for insight in result.insights:
        print(f"  - {insight}")


if __name__ == "__main__":
    asyncio.run(main())
```

## API Reference

### run_with_files()

```python
async def run_with_files(
    agent: Agent[DeepAgentDeps, OutputT],
    query: str,
    deps: DeepAgentDeps,
    files: list[tuple[str, bytes]] | None = None,
    *,
    upload_dir: str = "/uploads",
) -> OutputT:
    """Run agent with file uploads.

    Args:
        agent: The agent to run.
        query: The user query/prompt.
        deps: Agent dependencies.
        files: List of (filename, content) tuples to upload.
        upload_dir: Directory to store uploads.

    Returns:
        Agent output (type depends on agent's output_type).
    """
```

### deps.upload_file()

```python
def upload_file(
    self,
    name: str,
    content: bytes,
    *,
    upload_dir: str = "/uploads",
) -> str:
    """Upload a file to the backend and track it.

    Args:
        name: Original filename (e.g., "sales.csv")
        content: File content as bytes
        upload_dir: Directory to store uploads

    Returns:
        The path where the file was stored.
    """
```

### UploadedFile

```python
class UploadedFile(TypedDict):
    """Metadata for an uploaded file."""
    name: str        # Original filename
    path: str        # Path in backend (e.g., /uploads/sales.csv)
    size: int        # Size in bytes
    line_count: int | None  # Number of lines (None for binary)
```

## Next Steps

- [Basic Usage](basic-usage.md) - Core functionality
- [Docker Sandbox](docker-sandbox.md) - Execute code on uploaded files
- [Structured Output](../advanced/structured-output.md) - Type-safe results
