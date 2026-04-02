# Custom Tools Example

Add your own tools alongside built-in toolsets.

## Source Code

:material-file-code: `examples/custom_tools.py`

## Overview

This example demonstrates:

- Defining custom tool functions
- Accessing dependencies in custom tools
- Combining custom logic with built-in file operations
- Tool return values and documentation

## Full Example

```python
"""Example adding custom tools to the agent."""

import asyncio
from datetime import datetime

from pydantic_ai import RunContext

from pydantic_deep import DeepAgentDeps, StateBackend, create_deep_agent


# Define custom tools as functions
async def get_current_time(ctx: RunContext[DeepAgentDeps]) -> str:
    """Get the current date and time.

    Returns:
        Current timestamp in ISO format.
    """
    return datetime.now().isoformat()


async def log_message(
    ctx: RunContext[DeepAgentDeps],
    message: str,
    level: str = "INFO",
) -> str:
    """Log a message to /logs/agent.log.

    Args:
        message: The message to log.
        level: Log level (INFO, WARNING, ERROR).
    """
    timestamp = datetime.now().isoformat()
    log_entry = f"[{timestamp}] [{level}] {message}\n"

    # Use the backend to append to log file
    backend = ctx.deps.backend

    # Read existing log
    existing = backend.read("/logs/agent.log")
    if "Error:" in existing:
        # File doesn't exist, create it
        content = log_entry
    else:
        # Extract content (remove line numbers)
        lines = []
        for line in existing.split("\n"):
            if "\t" in line:
                lines.append(line.split("\t", 1)[1])
        content = "\n".join(lines) + log_entry

    backend.write("/logs/agent.log", content)

    return f"Logged: {log_entry.strip()}"


async def analyze_code_complexity(
    ctx: RunContext[DeepAgentDeps],
    file_path: str,
) -> str:
    """Analyze the complexity of a Python file.

    Args:
        file_path: Path to the Python file to analyze.

    Returns:
        Complexity analysis report.
    """
    content = ctx.deps.backend.read(file_path)

    if "Error:" in content:
        return content

    # Simple complexity metrics
    lines = content.split("\n")
    total_lines = len(lines)

    # Count various elements (simple heuristics)
    functions = sum(1 for line in lines if "def " in line)
    classes = sum(1 for line in lines if "class " in line)
    imports = sum(1 for line in lines if line.strip().startswith(("import ", "from ")))
    comments = sum(1 for line in lines if "#" in line)

    return f"""Code Complexity Analysis for {file_path}:
- Total lines: {total_lines}
- Functions: {functions}
- Classes: {classes}
- Imports: {imports}
- Comment lines: {comments}
- Code density: {(total_lines - comments) / max(total_lines, 1):.1%}
"""


async def main():
    # Create agent with custom tools
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        instructions="""
        You are a development assistant with custom tools:
        - get_current_time: Get the current timestamp
        - log_message: Log messages to /logs/agent.log
        - analyze_code_complexity: Analyze Python file complexity

        Use these tools along with the built-in filesystem tools.
        Always log important actions.
        """,
        tools=[
            get_current_time,
            log_message,
            analyze_code_complexity,
        ],
    )

    deps = DeepAgentDeps(backend=StateBackend())

    # Run the agent
    result = await agent.run(
        """
        1. Log that we're starting a new task
        2. Create a Python module at /src/calculator.py with add, subtract, multiply functions
        3. Analyze the complexity of the created file
        4. Log the completion with the complexity summary
        5. Get the current time and save a summary to /summary.txt
        """,
        deps=deps,
    )

    print("Agent output:")
    print(result.output)

    # Show the log file
    print("\n" + "=" * 50)
    print("Log file contents:")
    log_content = deps.backend.read("/logs/agent.log")
    print(log_content)


if __name__ == "__main__":
    asyncio.run(main())
```

## Running the Example

```bash
export OPENAI_API_KEY=your-api-key
uv run python examples/custom_tools.py
```

## Expected Output

```
Agent output:
I've completed all the tasks:

1. Logged the start of the task
2. Created /src/calculator.py with add, subtract, and multiply functions
3. Analyzed the code complexity:
   - 15 total lines
   - 3 functions
   - Good code density
4. Logged the completion
5. Saved summary to /summary.txt with current timestamp

==================================================
Log file contents:
     1	[2024-01-15T10:30:00] [INFO] Starting new task: create calculator module
     2	[2024-01-15T10:30:05] [INFO] Task completed. Code complexity: 3 functions, 15 lines
```

## Key Concepts

### Tool Function Signature

```python
async def my_tool(
    ctx: RunContext[DeepAgentDeps],  # Required: access to dependencies
    param1: str,                      # Required parameter
    param2: int = 10,                 # Optional parameter with default
) -> str:                             # Return type
    """Tool description shown to the agent.

    Args:
        param1: Description of param1.
        param2: Description of param2.

    Returns:
        Description of what the tool returns.
    """
    # Access dependencies
    backend = ctx.deps.backend
    todos = ctx.deps.todos

    # Your logic here
    return "result"
```

### Accessing Dependencies

```python
async def my_tool(ctx: RunContext[DeepAgentDeps]) -> str:
    # Access the backend for file operations
    content = ctx.deps.backend.read("/some/file.txt")
    ctx.deps.backend.write("/output.txt", "result")

    # Access todos
    for todo in ctx.deps.todos:
        print(todo.content)

    # Access uploaded files metadata
    for path, info in ctx.deps.uploads.items():
        print(f"{path}: {info['size']} bytes")

    return "done"
```

### Registering Tools

```python
agent = create_deep_agent(
    tools=[
        my_tool,           # Function reference
        another_tool,
        yet_another_tool,
    ],
)
```

## Variations

### Sync Tools

Tools can be synchronous if they don't need async operations:

```python
def get_version(ctx: RunContext[DeepAgentDeps]) -> str:
    """Get the application version."""
    return "1.0.0"
```

### Tools with Complex Return Types

```python
from pydantic import BaseModel

class AnalysisResult(BaseModel):
    file_path: str
    lines: int
    complexity_score: float
    issues: list[str]

async def analyze_file(
    ctx: RunContext[DeepAgentDeps],
    path: str,
) -> AnalysisResult:
    """Analyze a file and return structured results."""
    content = ctx.deps.backend.read(path)
    # ... analysis logic ...
    return AnalysisResult(
        file_path=path,
        lines=100,
        complexity_score=0.7,
        issues=["TODO found on line 42"],
    )
```

### Tools with External APIs

```python
import httpx

async def fetch_weather(
    ctx: RunContext[DeepAgentDeps],
    city: str,
) -> str:
    """Get current weather for a city."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.weather.com/v1/current?city={city}"
        )
        data = response.json()
        return f"Weather in {city}: {data['temp']}°C, {data['condition']}"
```

### Combining with Toolsets

```python
from pydantic_ai.toolsets import FunctionToolset

# Create a toolset from multiple functions
my_toolset = FunctionToolset([
    get_current_time,
    log_message,
    analyze_code_complexity,
])

agent = create_deep_agent(
    toolsets=[my_toolset],  # Add as a toolset
)
```

## Best Practices

1. **Clear docstrings** - The agent uses docstrings to understand what tools do
2. **Type hints** - Help the agent understand parameter types
3. **Descriptive names** - `analyze_code_complexity` vs `analyze`
4. **Error handling** - Return helpful error messages, don't raise exceptions
5. **Stateless** - Tools should not maintain state between calls

## Next Steps

- [Subagents](subagents.md) - Delegate to specialized agents
- [Skills](skills.md) - Package capabilities as skills
- [API: Toolsets](../api/toolsets.md) - Toolset reference
