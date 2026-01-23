# Agents

The `create_deep_agent()` function is the main entry point for creating deep agents.

## Basic Usage

```python
from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend

# Create agent with defaults
agent = create_deep_agent()

# Run with dependencies
deps = DeepAgentDeps(backend=StateBackend())
result = await agent.run("Hello!", deps=deps)
```

## Configuration Options

### Model Selection

```python
# Anthropic (default)
agent = create_deep_agent(model="openai:gpt-4.1")

# OpenAI
agent = create_deep_agent(model="openai:gpt-4")

# For testing (no API calls)
from pydantic_ai.models.test import TestModel
agent = create_deep_agent(model=TestModel())
```

### Custom Instructions

```python
agent = create_deep_agent(
    instructions="""
    You are a Python expert specializing in data science.

    When writing code:
    - Use type hints
    - Include docstrings
    - Prefer pandas for data manipulation
    """
)
```

### Enabling/Disabling Features

```python
agent = create_deep_agent(
    include_todo=True,        # Planning tools (default: True)
    include_filesystem=True,  # File operations (default: True)
    include_subagents=True,   # Task delegation (default: True)
    include_skills=True,      # Skill packages (default: True)
)
```

### Human-in-the-Loop

Require approval for sensitive operations:

```python
agent = create_deep_agent(
    interrupt_on={
        "execute": True,      # Require approval for command execution
        "write_file": True,   # Require approval for file writes
        "edit_file": True,    # Require approval for file edits
    }
)
```

### Structured Output

Get type-safe responses with Pydantic models:

```python
from pydantic import BaseModel

class TaskAnalysis(BaseModel):
    summary: str
    priority: str
    estimated_hours: float

agent = create_deep_agent(output_type=TaskAnalysis)

result = await agent.run("Analyze this task: implement auth", deps=deps)
print(result.output.priority)  # Type-safe access
```

See [Structured Output](../advanced/structured-output.md) for more details.

### Context Management

Automatically summarize long conversations:

```python
from pydantic_deep.processors import create_summarization_processor

processor = create_summarization_processor(
    trigger=("tokens", 100000),
    keep=("messages", 20),
)

agent = create_deep_agent(history_processors=[processor])
```

See [History Processors](../advanced/processors.md) for more details.

### Advanced Agent Configuration

The `create_deep_agent()` function accepts `**agent_kwargs` which are passed directly to the underlying [Pydantic AI Agent](https://ai.pydantic.dev/). This allows you to configure advanced options:

```python
agent = create_deep_agent(
    model="openai:gpt-4.1",
    # Advanced pydantic-ai options via **agent_kwargs
    retries=3,                    # Number of retries on failure
    result_retries=2,             # Retries for result validation
    end_strategy="early",         # Stop strategy: "early" or "exhaustive"
    defer_model_check=True,       # Defer model validation
    name="my-agent",              # Agent name for logging
)
```

Common `**agent_kwargs` options:

| Parameter | Type | Description |
|-----------|------|-------------|
| `retries` | `int` | Number of retries on LLM errors (default: 1) |
| `result_retries` | `int` | Retries for result validation failures |
| `end_strategy` | `str` | `"early"` stops at first valid result, `"exhaustive"` tries all |
| `defer_model_check` | `bool` | Defer model availability check until first use |
| `name` | `str` | Agent name for logging and debugging |

See [Pydantic AI documentation](https://ai.pydantic.dev/) for all available options.

### Dynamic System Prompts

Pydantic Deep Agents uses a dynamic system prompt mechanism that automatically composes context from multiple sources. The system prompt is generated at runtime based on current state and enabled features.

**Prompt composition order:**

1. **Uploaded Files Summary** - Files uploaded via `deps.upload_file()` are listed first
2. **Todo Prompt** - Current task list and progress from the todo toolset
3. **Console Prompt** - File operation instructions from the filesystem toolset
4. **Subagent Prompt** - Available subagents and delegation instructions
5. **Skills Prompt** - Available skills that can be loaded

```python
# The agent automatically includes relevant prompts based on enabled features
agent = create_deep_agent(
    instructions="You are a Python expert.",  # Your base instructions
    include_todo=True,        # Adds todo prompt
    include_filesystem=True,  # Adds console prompt
    include_subagents=True,   # Adds subagent prompt
    include_skills=True,      # Adds skills prompt
)

# At runtime, the agent sees:
# 1. Your instructions: "You are a Python expert."
# 2. Uploaded files: "## Uploaded Files\n- /uploads/data.csv (1024 bytes, 50 lines)"
# 3. Todo prompt: "## Current Todos\n- [ ] Analyze data..."
# 4. Console prompt: "## File Operations\nYou can use ls, read_file, write_file..."
# 5. Subagent prompt: "## Available Subagents\n- code-reviewer: Reviews code..."
# 6. Skills prompt: "## Available Skills\n- git: Git operations..."
```

Each prompt generator can be used standalone:

```python
from pydantic_deep import (
    get_console_system_prompt,
    get_skills_system_prompt,
)
from pydantic_ai_todo import get_todo_system_prompt
from subagents_pydantic_ai import get_subagent_system_prompt

# Generate individual prompts
console_prompt = get_console_system_prompt()
todo_prompt = get_todo_system_prompt(deps)
skills_prompt = get_skills_system_prompt(deps, skills)
```

## Dependencies

The `DeepAgentDeps` class holds all runtime state:

```python
from dataclasses import dataclass
from pydantic_deep import BackendProtocol, Todo, UploadedFile

@dataclass
class DeepAgentDeps:
    backend: BackendProtocol  # File storage
    files: dict[str, FileData]  # File cache
    todos: list[Todo]  # Task list
    subagents: dict[str, Any]  # Preconfigured agents
    uploads: dict[str, UploadedFile]  # Uploaded files metadata
```

### Creating Dependencies

```python
# Simple - in-memory storage
deps = DeepAgentDeps(backend=StateBackend())

# With filesystem storage
from pydantic_ai_backends import LocalBackend
deps = DeepAgentDeps(backend=LocalBackend("/workspace"))

# With initial todos
from pydantic_deep import Todo
deps = DeepAgentDeps(
    backend=StateBackend(),
    todos=[
        Todo(content="Review code", status="pending", active_form="Reviewing code"),
    ]
)
```

### Uploading Files

Upload files for agent processing:

```python
# Upload a file
deps.upload_file("data.csv", csv_bytes)
# File stored at /uploads/data.csv

# Custom upload directory
deps.upload_file("config.json", config_bytes, upload_dir="/configs")
# File stored at /configs/config.json

# Check uploads
for path, info in deps.uploads.items():
    print(f"{path}: {info['size']} bytes, {info['line_count']} lines")
```

Or use the `run_with_files()` helper:

```python
from pydantic_deep import run_with_files

result = await run_with_files(
    agent,
    "Analyze this data",
    deps,
    files=[("data.csv", csv_bytes)],
)
```

See [File Uploads](../examples/file-uploads.md) for more details.

## Running Agents

### Basic Run

```python
result = await agent.run("Create a calculator module", deps=deps)
print(result.output)  # Agent's text response
```

### Streaming

```python
from pydantic_ai._agent_graph import CallToolsNode

async with agent.iter("Create a calculator", deps=deps) as run:
    async for node in run:
        if isinstance(node, CallToolsNode):
            # Get tool calls from the response
            for part in node.model_response.parts:
                if hasattr(part, 'tool_name'):
                    print(f"Calling: {part.tool_name}")

    result = run.result
```

### Continuing Conversations

```python
# First interaction
result1 = await agent.run("Create a file", deps=deps)

# Continue with history
result2 = await agent.run(
    "Now modify it",
    deps=deps,
    message_history=result1.all_messages(),
)
```

## Adding Custom Tools

### Function Tools

```python
from pydantic_ai import RunContext

async def get_weather(
    ctx: RunContext[DeepAgentDeps],
    city: str,
) -> str:
    """Get current weather for a city.

    Args:
        city: Name of the city.

    Returns:
        Weather description.
    """
    return f"Weather in {city}: Sunny, 22°C"

agent = create_deep_agent(tools=[get_weather])
```

### Accessing Dependencies in Tools

```python
async def save_report(
    ctx: RunContext[DeepAgentDeps],
    content: str,
) -> str:
    """Save a report to the filesystem."""
    # Access the backend through dependencies
    result = ctx.deps.backend.write("/reports/latest.md", content)
    return f"Saved to {result.path}"
```

## Subagent Configuration

Pre-configure specialized subagents:

```python
from pydantic_deep import SubAgentConfig

subagents = [
    SubAgentConfig(
        name="code-reviewer",
        description="Reviews code for quality and security issues",
        instructions="""
        You are an expert code reviewer. Focus on:
        - Security vulnerabilities
        - Performance issues
        - Code style
        """,
    ),
    SubAgentConfig(
        name="test-writer",
        description="Generates pytest test cases",
        instructions="Generate comprehensive pytest tests...",
    ),
]

agent = create_deep_agent(subagents=subagents)
```

The main agent can then delegate:

```python
# Agent can call: task(description="Review the calculator module", subagent_type="code-reviewer")
```

## Skills Configuration

Load skills from directories:

```python
agent = create_deep_agent(
    skill_directories=[
        {"path": "~/.pydantic-deep/skills", "recursive": True},
        {"path": "./project-skills", "recursive": False},
    ]
)
```

Or provide skills directly:

```python
skills = [
    {
        "name": "code-review",
        "description": "Review code for quality",
        "path": "/path/to/skill",
        "tags": ["code", "review"],
        "version": "1.0.0",
        "author": "",
        "frontmatter_loaded": True,
    }
]

agent = create_deep_agent(skills=skills)
```

## Usage Statistics

```python
result = await agent.run("Create a module", deps=deps)

usage = result.usage()
print(f"Input tokens: {usage.input_tokens}")
print(f"Output tokens: {usage.output_tokens}")
print(f"Total requests: {usage.requests}")
```

## Error Handling

### Basic Error Handling

```python
try:
    result = await agent.run(prompt, deps=deps)
except Exception as e:
    print(f"Agent error: {e}")
```

### Common Exceptions

| Exception | Source | Cause |
|-----------|--------|-------|
| `ModelRetry` | pydantic-ai | Model requested retry (validation failed) |
| `UnexpectedModelBehavior` | pydantic-ai | Model produced unexpected output |
| `UserError` | pydantic-ai | Invalid user input or configuration |
| `FileNotFoundError` | Backend | File doesn't exist |
| `PermissionError` | Backend | Access denied |
| `TimeoutError` | Execution | Command exceeded timeout |
| `docker.errors.DockerException` | DockerSandbox | Docker operation failed |

### Handling Tool Errors

Tools should return informative error strings rather than raising exceptions:

```python
async def my_tool(ctx: RunContext[DeepAgentDeps], path: str) -> str:
    try:
        content = ctx.deps.backend.read(path)
        return content
    except FileNotFoundError:
        return f"Error: File '{path}' not found"
    except PermissionError:
        return f"Error: Permission denied for '{path}'"
```

### Retry Configuration

Configure retries for transient failures:

```python
agent = create_deep_agent(
    retries=3,          # Retry LLM calls up to 3 times
    result_retries=2,   # Retry validation failures
)
```

### Graceful Degradation

```python
async def run_with_fallback(agent, prompt, deps):
    try:
        return await agent.run(prompt, deps=deps)
    except Exception as e:
        # Log error, notify user, or try simpler approach
        logger.error(f"Agent failed: {e}")
        return f"I encountered an error: {e}. Please try again."
```

## Next Steps

- [Backends](backends.md) - Storage options
- [Toolsets](toolsets.md) - Available tools
- [Skills](skills.md) - Modular capabilities
