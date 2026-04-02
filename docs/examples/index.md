# Examples

This section contains practical examples demonstrating pydantic-deep features.

## Running Examples

All examples are in the `examples/` directory:

```bash
# Set your API key
export OPENAI_API_KEY=your-api-key  # or ANTHROPIC_API_KEY

# Run an example
uv run python examples/<example_name>.py
```

## Example Overview

<div class="feature-grid">

<div class="feature-card">
<h3>:material-rocket-launch: Basic Usage</h3>
<p>Getting started with pydantic-deep. Create agents, use todos, work with files.</p>
<a href="basic-usage/">View Example →</a>
</div>

<div class="feature-card">
<h3>:material-folder: Filesystem</h3>
<p>Real filesystem operations with FilesystemBackend.</p>
<a href="filesystem/">View Example →</a>
</div>

<div class="feature-card">
<h3>:material-layers: Composite Backend</h3>
<p>Combine multiple backends with path-based routing.</p>
<a href="composite-backend/">View Example →</a>
</div>

<div class="feature-card">
<h3>:material-target: Skills</h3>
<p>Modular capability packages with progressive disclosure.</p>
<a href="skills/">View Example →</a>
</div>

<div class="feature-card">
<h3>:material-account-group: Subagents</h3>
<p>Delegate specialized tasks to subagents.</p>
<a href="subagents/">View Example →</a>
</div>

<div class="feature-card">
<h3>:material-wrench: Custom Tools</h3>
<p>Add your own tools alongside built-in toolsets.</p>
<a href="custom-tools/">View Example →</a>
</div>

<div class="feature-card">
<h3>:material-upload: File Uploads</h3>
<p>Upload files for agent processing with run_with_files() or deps.upload_file().</p>
<a href="file-uploads/">View Example →</a>
</div>

<div class="feature-card">
<h3>:material-docker: Docker Sandbox</h3>
<p>Isolated code execution in Docker containers.</p>
<a href="docker-sandbox/">View Example →</a>
</div>

<div class="feature-card">
<h3>:material-cog: Docker Runtimes</h3>
<p>Pre-configured execution environments with RuntimeConfig.</p>
<a href="docker-runtimes/">View Example →</a>
</div>

<div class="feature-card">
<h3>:material-play-speed: Streaming</h3>
<p>Real-time output with agent.iter() for progress tracking.</p>
<a href="streaming/">View Example →</a>
</div>

<div class="feature-card">
<h3>:material-shield-check: Human-in-the-Loop</h3>
<p>Approval workflows for sensitive operations.</p>
<a href="human-in-the-loop/">View Example →</a>
</div>

<div class="feature-card">
<h3>:material-chat: Interactive Chat</h3>
<p>CLI chatbot with streaming and tool visibility.</p>
<a href="interactive-chat/">View Example →</a>
</div>

<div class="feature-card">
<h3>:material-brain: Thinking</h3>
<p>Configure reasoning effort for different complexity levels.</p>
<a href="thinking/">View Example →</a>
</div>

<div class="feature-card">
<h3>:material-web: Web Tools</h3>
<p>Web search, fetch, and custom domain restrictions.</p>
<a href="web-tools/">View Example →</a>
</div>

<div class="feature-card">
<h3>:material-lan-connect: MCP Servers</h3>
<p>Connect to MCP servers for external tool integration.</p>
<a href="mcp/">View Example →</a>
</div>

<div class="feature-card">
<h3>:material-star: Full Application</h3>
<p>Complete FastAPI app with WebSocket streaming, Docker, uploads, and more.</p>
<a href="full-app/">View Example →</a>
</div>

</div>

## Quick Examples

### Hello World

```python
import asyncio
from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend

async def main():
    agent = create_deep_agent()
    deps = DeepAgentDeps(backend=StateBackend())

    result = await agent.run("Say hello!", deps=deps)
    print(result.output)

asyncio.run(main())
```

### Create a File

```python
async def main():
    agent = create_deep_agent()
    deps = DeepAgentDeps(backend=StateBackend())

    result = await agent.run(
        "Create a Python function that calculates factorials and save it to /math/factorial.py",
        deps=deps,
    )

    # Check what was created
    print("Files:", list(deps.backend.files.keys()))
    print("\nContent:")
    print(deps.backend.read("/math/factorial.py"))
```

### Plan a Task

```python
async def main():
    agent = create_deep_agent()
    deps = DeepAgentDeps(backend=StateBackend())

    result = await agent.run(
        """
        Create a simple CLI calculator with the following features:
        1. Add, subtract, multiply, divide
        2. Input validation
        3. Help command

        Plan the task first using todos, then implement.
        """,
        deps=deps,
    )

    # Check the todo list
    print("Todos:")
    for todo in deps.todos:
        status = "✓" if todo.status == "completed" else "○"
        print(f"  {status} {todo.content}")
```

### Delegate to Subagent

```python
from pydantic_deep import SubAgentConfig

async def main():
    subagents = [
        SubAgentConfig(
            name="code-reviewer",
            description="Reviews code for quality",
            instructions="You are a code review expert...",
        ),
    ]

    agent = create_deep_agent(subagents=subagents)
    deps = DeepAgentDeps(backend=StateBackend())

    # Create some code
    deps.backend.write("/src/app.py", "def add(a, b): return a + b")

    result = await agent.run(
        "Delegate a code review of /src/app.py to the code-reviewer",
        deps=deps,
    )

    print(result.output)
```

### Use Skills

```python
async def main():
    agent = create_deep_agent(
        skill_directories=[
            {"path": "./skills", "recursive": True},
        ],
    )
    deps = DeepAgentDeps(backend=StateBackend())

    result = await agent.run(
        """
        1. List available skills
        2. Load the code-review skill
        3. Use it to review /src/app.py
        """,
        deps=deps,
    )

    print(result.output)
```

## Testing Without API

Use `TestModel` for testing without API calls:

```python
from pydantic_ai.models.test import TestModel

async def main():
    agent = create_deep_agent(model=TestModel())
    deps = DeepAgentDeps(backend=StateBackend())

    # TestModel will return predefined responses
    result = await agent.run("Test prompt", deps=deps)
```

## Example Files Reference

| File | Description | Docs Page |
|------|-------------|-----------|
| `basic_usage.py` | Core functionality demonstration | [Basic Usage](basic-usage.md) |
| `filesystem_backend.py` | Real filesystem operations | [Filesystem](filesystem.md) |
| `composite_backend.py` | Mixed storage strategies | [Composite Backend](composite-backend.md) |
| `skills_usage.py` | Skills system | [Skills](skills.md) |
| `subagents.py` | Task delegation | [Subagents](subagents.md) |
| `custom_tools.py` | Adding custom tools | [Custom Tools](custom-tools.md) |
| `file_uploads.py` | File uploads for agent processing | [File Uploads](file-uploads.md) |
| `docker_sandbox.py` | Isolated execution | [Docker Sandbox](docker-sandbox.md) |
| `streaming.py` | Real-time output | [Streaming](streaming.md) |
| `human_in_the_loop.py` | Approval workflows | [Human-in-the-Loop](human-in-the-loop.md) |
| `interactive_chat.py` | CLI chatbot | [Interactive Chat](interactive-chat.md) |
| `full_app/` | Complete FastAPI application | [Full App](full-app.md) |

## Next Steps

- [Basic Usage](basic-usage.md) - Detailed walkthrough
- [Core Concepts](../concepts/index.md) - Understand the fundamentals
- [API Reference](../api/index.md) - Complete API documentation
