# Subagents Example

Delegate specialized tasks to dedicated subagents for better results.

## Source Code

:material-file-code: `examples/subagents.py`

## Overview

This example demonstrates:

- Configuring custom subagents with specialized instructions
- Delegating tasks to appropriate subagents
- Coordinating work between the main agent and subagents
- Context sharing via the backend

## When to Use Subagents

Subagents are useful when:

- Tasks require specialized expertise (code review, documentation, testing)
- You want to separate concerns and keep instructions focused
- Different parts of a task need different prompts or models
- You want to parallelize work across multiple specialists

## Full Example

```python
"""Example using subagents for task delegation."""

import asyncio

from pydantic_deep import DeepAgentDeps, StateBackend, create_deep_agent
from pydantic_deep.types import SubAgentConfig


async def main():
    # Define specialized subagents
    subagents = [
        SubAgentConfig(
            name="code-reviewer",
            description="Reviews code for bugs, style issues, and best practices",
            instructions="""
            You are an expert code reviewer.
            When reviewing code:
            1. Check for bugs and logical errors
            2. Verify proper error handling
            3. Look for security issues
            4. Suggest improvements
            Provide a structured review with severity levels.
            """,
        ),
        SubAgentConfig(
            name="documentation-writer",
            description="Writes clear, comprehensive documentation",
            instructions="""
            You are a technical documentation specialist.
            Write clear, well-structured documentation including:
            - Overview and purpose
            - Usage examples
            - API reference
            - Best practices
            """,
        ),
        SubAgentConfig(
            name="test-generator",
            description="Generates comprehensive unit tests",
            instructions="""
            You are a test engineering expert.
            Generate thorough unit tests including:
            - Happy path tests
            - Edge cases
            - Error handling tests
            - Use pytest style
            """,
        ),
    ]

    # Create the main agent with subagents
    agent = create_deep_agent(
        model="openai:gpt-4.1",
        instructions="""
        You are a senior software engineer.
        Delegate specialized tasks to the appropriate subagents:
        - code-reviewer for code reviews
        - documentation-writer for docs
        - test-generator for tests

        Coordinate the work and synthesize results.
        """,
        subagents=subagents,
        include_general_purpose_subagent=False,  # Only use our custom subagents
    )

    deps = DeepAgentDeps(backend=StateBackend())

    # First, create some code to work with
    deps.backend.write(
        "/calculator.py",
        '''"""Simple calculator module."""

def add(a, b):
    return a + b

def divide(a, b):
    return a / b

def multiply(a, b):
    return a * b
''',
    )

    # Ask the agent to review, document, and test the code
    result = await agent.run(
        """I have a calculator module at /calculator.py.
        Please:
        1. Review the code for issues
        2. Write documentation for it
        3. Generate unit tests

        Save the documentation to /docs/calculator.md and tests to /tests/test_calculator.py
        """,
        deps=deps,
    )

    print("Agent output:")
    print(result.output)

    print("\nFiles created:")
    for path in sorted(deps.files.keys()):
        print(f"  {path}")


if __name__ == "__main__":
    asyncio.run(main())
```

## Running the Example

```bash
export OPENAI_API_KEY=your-api-key
uv run python examples/subagents.py
```

## Expected Output

```
Agent output:
I've analyzed your calculator module and delegated to specialists:

**Code Review** (from code-reviewer):
- ISSUE: divide() has no zero division handling (HIGH severity)
- SUGGESTION: Add type hints for better maintainability
- SUGGESTION: Consider adding subtract function for completeness

**Documentation** saved to /docs/calculator.md

**Tests** saved to /tests/test_calculator.py with:
- test_add_positive_numbers
- test_divide_by_non_zero
- test_divide_by_zero (catches expected exception)
- test_multiply_basics

Files created:
  /calculator.py
  /docs/calculator.md
  /tests/test_calculator.py
```

## Key Concepts

### SubAgentConfig

```python
SubAgentConfig(
    name="code-reviewer",           # Unique identifier
    description="...",              # Shown to main agent for delegation
    instructions="...",             # System prompt for the subagent
    model="openai:gpt-4.1",         # Optional: override model
    toolsets=[my_toolset],          # Optional: custom toolsets
    agent_kwargs={"builtin_tools": [...]},  # Optional: additional Agent kwargs
)
```

### How Delegation Works

1. Main agent knows available subagents from system prompt
2. Main agent calls `task(description, subagent_type)` to delegate
3. Subagent runs with its own instructions but shares the backend
4. Subagent can read/write files that main agent created
5. Main agent receives subagent's response and synthesizes results

### Context Sharing

Subagents share the same backend as the main agent:

```python
# Main agent creates a file
deps.backend.write("/src/app.py", "...")

# Subagent can read it
# (inside subagent's execution)
content = deps.backend.read("/src/app.py")
```

## Variations

### With General-Purpose Subagent

```python
agent = create_deep_agent(
    subagents=subagents,
    include_general_purpose_subagent=True,  # Default
)
```

The general-purpose subagent can handle tasks that don't fit specialized subagents.

### Different Models per Subagent

```python
subagents = [
    SubAgentConfig(
        name="quick-helper",
        description="Fast responses for simple tasks",
        instructions="...",
        model="openai:gpt-4o-mini",  # Faster, cheaper
    ),
    SubAgentConfig(
        name="deep-analyst",
        description="Complex analysis requiring careful reasoning",
        instructions="...",
        model="anthropic:claude-sonnet-4-20250514",  # More capable
    ),
]
```

### Output Types for Subagents

```python
from pydantic import BaseModel

class CodeReview(BaseModel):
    issues: list[str]
    suggestions: list[str]
    score: int

SubAgentConfig(
    name="code-reviewer",
    description="...",
    instructions="...",
    output_type=CodeReview,  # Structured output
)
```

## Best Practices

1. **Clear descriptions** - Help the main agent choose the right subagent
2. **Focused instructions** - Each subagent should excel at one thing
3. **Shared context** - Use the backend to pass data between agents
4. **Appropriate models** - Use cheaper models for simpler subagent tasks

## Next Steps

- [Skills Example](skills.md) - Another way to extend capabilities
- [Concepts: Subagents](../advanced/subagents.md) - Deep dive
- [Custom Tools](custom-tools.md) - Add your own tools
