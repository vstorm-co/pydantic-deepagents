# pydantic-deep

> **Looking for a full-stack template?** Check out [fastapi-fullstack](https://github.com/vstorm-co/full-stack-fastapi-nextjs-llm-template) - a production-ready project generator for AI/LLM applications with FastAPI, Next.js, and pydantic-deep integration.

> **Need just the todo toolset?** Check out [pydantic-ai-todo](https://github.com/vstorm-co/pydantic-ai-todo) - standalone task planning toolset that works with any pydantic-ai agent.

> **Need just the backends?** Check out [pydantic-ai-backend](https://github.com/vstorm-co/pydantic-ai-backend) - file storage and sandbox backends that work with any pydantic-ai agent.

[![PyPI version](https://img.shields.io/pypi/v/pydantic-deep.svg)](https://pypi.org/project/pydantic-deep/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Coverage Status](https://coveralls.io/repos/github/vstorm-co/pydantic-deepagents/badge.svg?branch=main)](https://coveralls.io/github/vstorm-co/pydantic-deepagents?branch=main)
[![CI](https://github.com/vstorm-co/pydantic-deep/actions/workflows/ci.yml/badge.svg)](https://github.com/vstorm-co/pydantic-deep/actions/workflows/ci.yml)

Deep agent framework built on [pydantic-ai](https://github.com/pydantic/pydantic-ai) with planning, filesystem, and subagent capabilities.

## Demo

[![Watch Demo](https://img.shields.io/badge/▶_Watch_Demo-Google_Drive-4285F4?style=for-the-badge&logo=googledrive&logoColor=white)](https://drive.google.com/file/d/1hqgXkbAgUrsKOWpfWdF48cqaxRht-8od/view?usp=sharing)

![Demo Screenshot](assets/img.png)

See the [full demo application](https://github.com/vstorm-co/pydantic-deepagents/tree/main/examples/full_app) - a complete example showing how to build a chat interface with file uploads, skills, and streaming responses.

## Features

- **Multiple Backends**: StateBackend (in-memory), FilesystemBackend, DockerSandbox, CompositeBackend - via [pydantic-ai-backend](https://github.com/vstorm-co/pydantic-ai-backend)
- **Rich Toolsets**: TodoToolset (via [pydantic-ai-todo](https://github.com/vstorm-co/pydantic-ai-todo)), FilesystemToolset, SubAgentToolset, SkillsToolset
- **File Uploads**: Upload files for agent processing with `run_with_files()` or `deps.upload_file()`
- **Skills System**: Extensible skill definitions with markdown prompts
- **Structured Output**: Type-safe responses with Pydantic models via `output_type`
- **Context Management**: Automatic conversation summarization for long sessions
- **Human-in-the-Loop**: Built-in support for human confirmation workflows
- **Streaming**: Full streaming support for agent responses

## Modular Architecture

pydantic-deep is built with modular, reusable components:

| Component | Package | Description |
|-----------|---------|-------------|
| **Backends** | [pydantic-ai-backend](https://github.com/vstorm-co/pydantic-ai-backend) | File storage and Docker sandbox |
| **Todo Toolset** | [pydantic-ai-todo](https://github.com/vstorm-co/pydantic-ai-todo) | Task planning and tracking |
| **Summarization** | Built-in | Automatic context management* |

*\*Note: Summarization will be added to pydantic-ai core in late January 2025 ([pydantic-ai#3780](https://github.com/pydantic/pydantic-ai/pull/3780)). We will migrate to use it once available.*

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
from pydantic_ai_backends import StateBackend
from pydantic_deep import create_deep_agent, create_default_deps

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
from pydantic_ai_backends import StateBackend
from pydantic_deep import create_deep_agent, DeepAgentDeps, run_with_files

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

> **Note:** This feature will be added to pydantic-ai core in late January 2025 ([pydantic-ai#3780](https://github.com/pydantic/pydantic-ai/pull/3780)). Once available, we will migrate to use the upstream implementation.

## Documentation

- **[Full Documentation](https://vstorm-co.github.io/pydantic-deepagents/)** - Complete guides and API reference
- **[PyPI Package](https://pypi.org/project/pydantic-deep/)** - Package information and releases
- **[GitHub Repository](https://github.com/vstorm-co/pydantic-deepagents)** - Source code and issues

### Quick Links

- [Installation Guide](https://vstorm-co.github.io/pydantic-deepagents/installation/)
- [Core Concepts](https://vstorm-co.github.io/pydantic-deepagents/concepts/)
- [Examples](https://vstorm-co.github.io/pydantic-deepagents/examples/)
- [API Reference](https://vstorm-co.github.io/pydantic-deepagents/api/)

## Related Projects

- **[pydantic-ai](https://github.com/pydantic/pydantic-ai)** - The foundation: Agent framework by Pydantic
- **[pydantic-ai-backend](https://github.com/vstorm-co/pydantic-ai-backend)** - File storage and sandbox backends (extracted from pydantic-deep)
- **[pydantic-ai-todo](https://github.com/vstorm-co/pydantic-ai-todo)** - Task planning toolset (extracted from pydantic-deep)
- **[fastapi-fullstack](https://github.com/vstorm-co/full-stack-fastapi-nextjs-llm-template)** - Full-stack AI app template with pydantic-deep

## Development

```bash
# Clone the repository
git clone https://github.com/vstorm-co/pydantic-deepagents.git
cd pydantic-deepagents

# Install dependencies
make install

# Run tests
make test

# Run all checks (lint, typecheck, test, coverage)
make all
```

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=vstorm-co/pydantic-deepagents&type=date&legend=top-left)](https://www.star-history.com/#vstorm-co/pydantic-deepagents&type=date&legend=top-left)

## License

MIT License - see [LICENSE](LICENSE) for details.
