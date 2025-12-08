# pydantic-deep

[![PyPI version](https://img.shields.io/pypi/v/pydantic-deep.svg)](https://pypi.org/project/pydantic-deep/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](https://github.com/vstorm-co/pydantic-deep)
[![CI](https://github.com/vstorm-co/pydantic-deep/actions/workflows/ci.yml/badge.svg)](https://github.com/vstorm-co/pydantic-deep/actions/workflows/ci.yml)

Deep agent framework built on [pydantic-ai](https://github.com/pydantic/pydantic-ai) with planning, filesystem, and subagent capabilities.

## Features

- **Multiple Backends**: StateBackend (in-memory), FilesystemBackend, DockerSandbox, CompositeBackend
- **Rich Toolsets**: TodoToolset, FilesystemToolset, SubAgentToolset, SkillsToolset
- **File Uploads**: Upload files for agent processing with `run_with_files()` or `deps.upload_file()`
- **Skills System**: Extensible skill definitions with markdown prompts
- **Structured Output**: Type-safe responses with Pydantic models via `output_type`
- **Context Management**: Automatic conversation summarization for long sessions
- **Human-in-the-Loop**: Built-in support for human confirmation workflows
- **Streaming**: Full streaming support for agent responses

## Installation

```bash
pip install pydantic-deep
```

Or with uv:

```bash
uv add pydantic-deep
```

### Optional dependencies

```bash
# Docker sandbox support
pip install pydantic-deep[sandbox]
```

## Quick Start

```python
import asyncio
from pydantic_deep import create_deep_agent, create_default_deps
from pydantic_deep.backends import StateBackend

async def main():
    # Create a deep agent with state backend
    backend = StateBackend()
    deps = create_default_deps(backend)
    agent = create_deep_agent()

    # Run the agent
    result = await agent.run("Help me organize my tasks", deps=deps)
    print(result.output)

asyncio.run(main())
```

## Structured Output

Get type-safe responses with Pydantic models:

```python
from pydantic import BaseModel
from pydantic_deep import create_deep_agent, create_default_deps

class TaskAnalysis(BaseModel):
    summary: str
    priority: str
    estimated_hours: float

agent = create_deep_agent(output_type=TaskAnalysis)
deps = create_default_deps()

result = await agent.run("Analyze this task: implement user auth", deps=deps)
print(result.output.priority)  # Type-safe access
```

## File Uploads

Process user-uploaded files with the agent:

```python
from pydantic_deep import create_deep_agent, DeepAgentDeps, run_with_files
from pydantic_deep.backends import StateBackend

agent = create_deep_agent()
deps = DeepAgentDeps(backend=StateBackend())

# Upload and process files
with open("sales.csv", "rb") as f:
    result = await run_with_files(
        agent,
        "Analyze this sales data and find top products",
        deps,
        files=[("sales.csv", f.read())],
    )
```

Or upload files directly to deps:

```python
deps.upload_file("config.json", b'{"key": "value"}')
# File is now at /uploads/config.json and agent sees it in system prompt
```

## Context Management

Automatically summarize long conversations to manage token limits:

```python
from pydantic_deep import create_deep_agent
from pydantic_deep.processors import create_summarization_processor

processor = create_summarization_processor(
    trigger=("tokens", 100000),  # Summarize when reaching 100k tokens
    keep=("messages", 20),       # Keep last 20 messages
)

agent = create_deep_agent(history_processors=[processor])
```

## Documentation

- **[Full Documentation](https://vstorm-co.github.io/pydantic-deep/)** - Complete guides and API reference
- **[PyPI Package](https://pypi.org/project/pydantic-deep/)** - Package information and releases
- **[GitHub Repository](https://github.com/vstorm-co/pydantic-deep)** - Source code and issues

### Quick Links

- [Installation Guide](https://vstorm-co.github.io/pydantic-deep/installation/)
- [Core Concepts](https://vstorm-co.github.io/pydantic-deep/concepts/)
- [Examples](https://vstorm-co.github.io/pydantic-deep/examples/)
- [API Reference](https://vstorm-co.github.io/pydantic-deep/api/)

## Development

```bash
# Clone the repository
git clone https://github.com/vstorm-co/pydantic-deep.git
cd pydantic-deep

# Install dependencies
make install

# Run tests
make test

# Run all checks (lint, typecheck, test, coverage)
make all
```

## License

MIT License - see [LICENSE](LICENSE) for details.
