# Streaming Example

Real-time output with `agent.iter()` for progress tracking.

## Source Code

:material-file-code: `examples/streaming.py`

## Overview

This example demonstrates:

- Using `agent.iter()` for streaming execution
- Processing nodes as they execute
- Tracking tool calls in real-time
- Monitoring agent progress

## When to Use Streaming

Streaming is useful when:

- You want to show progress during long-running tasks
- Users need real-time feedback
- You're building interactive UIs
- Debugging agent behavior

## Full Example

```python
"""Example using streaming for real-time output."""

import asyncio

from pydantic_ai._agent_graph import CallToolsNode, End, ModelRequestNode, UserPromptNode

from pydantic_deep import DeepAgentDeps, StateBackend, create_deep_agent


async def main():
    # Create the agent
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        instructions="You are a helpful assistant.",
    )

    deps = DeepAgentDeps(backend=StateBackend())

    print("Starting agent with streaming...\n")

    # Use iter() for streaming execution
    async with agent.iter(
        "Create a simple Python module with 3 utility functions and save it to /utils.py",
        deps=deps,
    ) as run:
        step = 0
        async for node in run:
            step += 1
            node_type = type(node).__name__

            if isinstance(node, UserPromptNode):
                print(f"[Step {step}] Processing user prompt...")

            elif isinstance(node, ModelRequestNode):
                print(f"[Step {step}] Calling model...")

            elif isinstance(node, CallToolsNode):
                # Extract tool calls from the model response
                tool_calls = []
                for part in node.model_response.parts:
                    if hasattr(part, "tool_name"):
                        tool_calls.append(part.tool_name)

                if tool_calls:
                    print(f"[Step {step}] Executing tools: {', '.join(tool_calls)}")
                else:
                    print(f"[Step {step}] Processing response...")

            elif isinstance(node, End):
                print(f"[Step {step}] Completed!")

            else:
                print(f"[Step {step}] {node_type}")

        # Get the final result
        result = run.result

    print(f"\n{'=' * 50}")
    print("Final output:")
    print(result.output)

    # Show usage statistics
    print("\nUsage:")
    print(f"  Input tokens: {result.usage().input_tokens}")
    print(f"  Output tokens: {result.usage().output_tokens}")
    print(f"  Total requests: {result.usage().requests}")

    # Show created files
    print("\nFiles created:")
    for path in sorted(deps.files.keys()):
        print(f"  {path}")


if __name__ == "__main__":
    asyncio.run(main())
```

## Running the Example

```bash
export OPENAI_API_KEY=your-api-key
uv run python examples/streaming.py
```

## Expected Output

```
Starting agent with streaming...

[Step 1] Processing user prompt...
[Step 2] Calling model...
[Step 3] Executing tools: write_todos
[Step 4] Calling model...
[Step 5] Executing tools: write_file
[Step 6] Calling model...
[Step 7] Completed!

==================================================
Final output:
I've created a Python utility module at /utils.py with three functions:

1. `format_date(dt)` - Formats a datetime object
2. `slugify(text)` - Converts text to URL-friendly slug
3. `truncate(text, max_len)` - Truncates text with ellipsis

Usage:
  Input tokens: 1234
  Output tokens: 567
  Total requests: 3

Files created:
  /utils.py
```

## Key Concepts

### The iter() Context Manager

```python
async with agent.iter(prompt, deps=deps) as run:
    async for node in run:
        # Process each node
        pass

    # Access final result
    result = run.result
```

### Node Types

| Node Type | Description |
|-----------|-------------|
| `UserPromptNode` | Processing user input |
| `ModelRequestNode` | Sending request to LLM |
| `CallToolsNode` | Executing tool calls |
| `End` | Agent completed |

### Extracting Tool Calls

```python
if isinstance(node, CallToolsNode):
    for part in node.model_response.parts:
        if hasattr(part, "tool_name"):
            print(f"Tool: {part.tool_name}")
            print(f"Args: {part.args}")
```

## Variations

### Streaming with Events

For more granular control, use `run_stream_events`:

```python
from pydantic_ai import (
    PartDeltaEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    AgentRunResultEvent,
)

async for event in agent.run_stream_events(prompt, deps=deps):
    if isinstance(event, PartDeltaEvent):
        # Streaming text chunks
        if hasattr(event.delta, "content_delta"):
            print(event.delta.content_delta, end="", flush=True)

    elif isinstance(event, FunctionToolCallEvent):
        # Tool call started
        print(f"\n[Tool] {event.part.tool_name}")

    elif isinstance(event, FunctionToolResultEvent):
        # Tool returned result
        print(f"  -> {event.result.content[:50]}...")

    elif isinstance(event, AgentRunResultEvent):
        # Agent finished
        result = event.result
```

### Progress Bar

```python
from tqdm import tqdm

async with agent.iter(prompt, deps=deps) as run:
    with tqdm(desc="Agent progress") as pbar:
        async for node in run:
            pbar.update(1)
            pbar.set_postfix(step=type(node).__name__)
```

### WebSocket Streaming

```python
async def stream_to_websocket(websocket, prompt, deps):
    async with agent.iter(prompt, deps=deps) as run:
        async for node in run:
            await websocket.send_json({
                "type": "node",
                "node_type": type(node).__name__,
            })

        await websocket.send_json({
            "type": "complete",
            "output": run.result.output,
        })
```

### Streaming Text Deltas

```python
async for event in agent.run_stream_events(prompt, deps=deps):
    if isinstance(event, PartDeltaEvent):
        if hasattr(event.delta, "content_delta"):
            # Print text as it arrives
            print(event.delta.content_delta, end="", flush=True)
```

## Interactive Chat Example

See the [Interactive Chat](interactive-chat.md) example for a complete implementation with:

- Real-time text streaming
- Tool call visualization
- TODO list display
- Color-coded output

## Best Practices

1. **Use context manager** - Ensures proper cleanup
2. **Handle all node types** - Don't assume execution order
3. **Access result after iteration** - `run.result` is only available after completion
4. **Consider buffering** - For UI updates, buffer small deltas

## Next Steps

- [Interactive Chat](interactive-chat.md) - Full CLI chatbot with streaming
- [Advanced: Streaming](../advanced/streaming.md) - Deep dive
- [Full App](full-app.md) - WebSocket streaming in FastAPI
