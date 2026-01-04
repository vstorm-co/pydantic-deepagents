# Streaming Updates

Real-time streaming updates during agent execution for better UX and monitoring.

## Quick Start

```python
from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend
from pydantic_deep.streaming import run_stream, StreamEventType, stream_text

# Create agent
agent = create_deep_agent(model="openai:gpt-4o")
deps = DeepAgentDeps(backend=StateBackend())

# Stream all events
async for event in run_stream(agent, "Write a story", deps):
    if event.event_type == StreamEventType.LLM_CHUNK:
        print(event.data["text"], end="", flush=True)
    elif event.event_type == StreamEventType.TOOL_START:
        print(f"\n[Calling {event.data['tool_name']}]")
    elif event.event_type == StreamEventType.PROGRESS:
        print(f"\nIteration: {event.data['iteration']}")

# Or just stream text
async for chunk in stream_text(agent, "Hello", deps):
    print(chunk, end="", flush=True)
```

## Overview

The streaming module provides real-time updates during agent execution, enabling:

- **Text streaming**: Token-by-token output for responsive UIs
- **Tool call tracking**: Monitor which tools are being called
- **Progress updates**: Track iterations, tokens, and costs
- **Error handling**: Real-time error notifications
- **Custom monitoring**: Build dashboards and logging systems

## Event Types

All events are represented by [`StreamEvent`][pydantic_deep.streaming.types.StreamEvent] objects with an event type and data payload.

### LLM_CHUNK

Text chunk from the LLM's streaming response.

```python
{
    "event_type": "llm_chunk",
    "data": {"text": "Hello"}
}
```

### TOOL_START

A tool call is starting.

```python
{
    "event_type": "tool_start",
    "data": {
        "tool_name": "read_file",
        "args": {"file_path": "/tmp/test.txt"}
    }
}
```

### TOOL_END

A tool call has completed.

```python
{
    "event_type": "tool_end",
    "data": {
        "tool_name": "read_file",
        "result": "file contents...",
        "duration_seconds": 0.5
    }
}
```

### PROGRESS

Progress update with iteration and token counts.

```python
{
    "event_type": "progress",
    "data": {
        "iteration": 2,
        "total_tokens": 150,
        "total_cost_usd": 0.005
    }
}
```

### ERROR

An error occurred during execution.

```python
{
    "event_type": "error",
    "data": {
        "error": "File not found",
        "exception_type": "FileNotFoundError"
    }
}
```

### AGENT_START / AGENT_END

Agent execution started or completed.

```python
{
    "event_type": "agent_end",
    "data": {
        "agent_name": "assistant",
        "success": True,
        "total_iterations": 3,
        "total_tokens": 250,
        "duration_seconds": 5.2
    }
}
```

## API Reference

### Core Functions

#### run_stream()

Stream all events from agent execution.

```python
from pydantic_deep.streaming import run_stream

async for event in run_stream(agent, prompt, deps):
    print(f"{event.event_type}: {event.data}")
```

**Parameters:**

- `agent`: The agent to run
- `prompt`: User prompt string
- `deps`: Agent dependencies
- `message_history`: Optional message history

**Yields:** [`StreamEvent`][pydantic_deep.streaming.types.StreamEvent] objects

#### stream_text()

Stream only text chunks, ignoring other events.

```python
from pydantic_deep.streaming import stream_text

async for chunk in stream_text(agent, "Write a poem", deps):
    print(chunk, end="", flush=True)
```

**Parameters:**

- `agent`: The agent to run
- `prompt`: User prompt string
- `deps`: Agent dependencies
- `message_history`: Optional message history

**Yields:** Text strings

#### run_stream_with_tools()

Stream with detailed tool call events.

```python
from pydantic_deep.streaming import run_stream_with_tools

async for event in run_stream_with_tools(agent, prompt, deps):
    if event.event_type == StreamEventType.TOOL_START:
        print(f"Calling {event.data['tool_name']}...")
```

**Parameters:**

- `agent`: The agent to run
- `prompt`: User prompt string
- `deps`: Agent dependencies
- `message_history`: Optional message history
- `emit_progress`: Whether to emit progress events (default: True)

**Yields:** [`StreamEvent`][pydantic_deep.streaming.types.StreamEvent] objects

#### stream_tool_calls()

Stream only tool calls.

```python
from pydantic_deep.streaming import stream_tool_calls

async for tool_name, args, result in stream_tool_calls(agent, prompt, deps):
    if result is None:
        print(f"Calling {tool_name}({args})...")
    else:
        print(f"  -> {result}")
```

**Parameters:**

- `agent`: The agent to run
- `prompt`: User prompt string
- `deps`: Agent dependencies
- `message_history`: Optional message history

**Yields:** Tuples of `(tool_name, args, result)`

#### collect_stream_result()

Collect all events into a list with optional callback.

```python
from pydantic_deep.streaming import collect_stream_result

def on_event(event):
    print(f"Event: {event.event_type}")

result, events = await collect_stream_result(
    agent, prompt, deps, on_event=on_event
)
```

**Parameters:**

- `agent`: The agent to run
- `prompt`: User prompt string
- `deps`: Agent dependencies
- `message_history`: Optional message history
- `on_event`: Optional callback function

**Returns:** Tuple of `(result, events)`

### Event Factory Functions

Helper functions for creating events:

```python
from pydantic_deep.streaming import (
    llm_chunk_event,
    tool_start_event,
    tool_end_event,
    progress_event,
    error_event,
    agent_start_event,
    agent_end_event,
)

# Create events
event = llm_chunk_event(text="Hello")
event = tool_start_event(tool_name="read_file", args={"path": "/tmp/test.txt"})
event = tool_end_event(tool_name="read_file", result="contents", duration_seconds=0.5)
event = progress_event(iteration=2, total_tokens=150)
event = error_event(error="Something went wrong", exception_type="ValueError")
```

## Usage Patterns

### Simple Text Streaming

For basic text-only applications:

```python
from pydantic_deep.streaming import stream_text

async def chat(agent, prompt):
    """Simple chat with text streaming."""
    print("Assistant: ", end="", flush=True)
    async for chunk in stream_text(agent, prompt, deps):
        print(chunk, end="", flush=True)
    print()  # Newline at end
```

### Progress Monitoring

Track progress and costs in real-time:

```python
from pydantic_deep.streaming import run_stream, StreamEventType

async def run_with_progress(agent, prompt):
    """Run agent with progress bar."""
    total_tokens = 0
    total_cost = 0.0

    async for event in run_stream(agent, prompt, deps):
        if event.event_type == StreamEventType.LLM_CHUNK:
            print(event.data["text"], end="", flush=True)

        elif event.event_type == StreamEventType.PROGRESS:
            total_tokens = event.data.get("total_tokens", 0)
            total_cost = event.data.get("total_cost_usd", 0.0)
            print(f"\n[Progress: {total_tokens} tokens, ${total_cost:.4f}]")

        elif event.event_type == StreamEventType.AGENT_END:
            print(f"\n[Completed in {event.data['duration_seconds']:.1f}s]")
```

### Tool Call Monitoring

Monitor tool executions:

```python
from pydantic_deep.streaming import stream_tool_calls

async def run_with_tool_monitoring(agent, prompt):
    """Run agent with tool call monitoring."""
    async for tool_name, args, result in stream_tool_calls(agent, prompt, deps):
        if result is None:
            # Tool starting
            print(f"⚙️  Calling {tool_name}...")
            if args:
                print(f"   Args: {args}")
        else:
            # Tool completed
            print(f"✓  {tool_name} completed")
            print(f"   Result: {result}")
```

### Error Handling

Handle errors gracefully:

```python
from pydantic_deep.streaming import run_stream, StreamEventType

async def run_with_error_handling(agent, prompt):
    """Run agent with error handling."""
    try:
        async for event in run_stream(agent, prompt, deps):
            if event.event_type == StreamEventType.ERROR:
                print(f"❌ Error: {event.data['error']}")
                print(f"   Type: {event.data['exception_type']}")

            elif event.event_type == StreamEventType.LLM_CHUNK:
                print(event.data["text"], end="", flush=True)

    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
```

### Building a Dashboard

Collect events for dashboard visualization:

```python
from pydantic_deep.streaming import collect_stream_result

async def run_with_dashboard(agent, prompt):
    """Run agent and update dashboard."""
    events_by_type = {
        "llm_chunks": [],
        "tool_calls": [],
        "progress": [],
        "errors": [],
    }

    def update_dashboard(event):
        """Update dashboard with new event."""
        if event.event_type == StreamEventType.LLM_CHUNK:
            events_by_type["llm_chunks"].append(event.data["text"])

        elif event.event_type == StreamEventType.TOOL_START:
            events_by_type["tool_calls"].append({
                "name": event.data["tool_name"],
                "status": "running"
            })

        elif event.event_type == StreamEventType.PROGRESS:
            events_by_type["progress"].append(event.data)

        # Update UI/dashboard here...

    result, events = await collect_stream_result(
        agent, prompt, deps, on_event=update_dashboard
    )

    return result, events_by_type
```

## Integration with Tracing

Combine streaming with tracing for comprehensive monitoring:

```python
from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend
from pydantic_deep.streaming import run_stream, StreamEventType
from pydantic_deep.tracing import TraceContext, ConsoleExporter

# Create trace context
trace_context = TraceContext(exporters=[ConsoleExporter(verbose=True)])

# Add to deps
deps = DeepAgentDeps(
    backend=StateBackend(),
    trace_context=trace_context,
)

# Both streaming AND tracing will be active
async for event in run_stream(agent, "Task", deps):
    # Handle streaming events
    if event.event_type == StreamEventType.LLM_CHUNK:
        print(event.data["text"], end="", flush=True)

# Trace events are also being exported to console
```

## Best Practices

### 1. Choose the Right Function

- **`stream_text()`**: For simple text-only UIs
- **`run_stream()`**: For general-purpose streaming with all event types
- **`stream_tool_calls()`**: When you only care about tool executions
- **`run_stream_with_tools()`**: For detailed tool monitoring
- **`collect_stream_result()`**: When you need all events in a list

### 2. Handle Backpressure

When streaming to slow clients (like WebSockets), implement backpressure:

```python
import asyncio

async def stream_with_backpressure(agent, prompt, queue_size=10):
    """Stream events with backpressure handling."""
    queue = asyncio.Queue(maxsize=queue_size)

    async def producer():
        async for event in run_stream(agent, prompt, deps):
            await queue.put(event)  # Blocks if queue is full
        await queue.put(None)  # Signal completion

    async def consumer():
        while True:
            event = await queue.get()
            if event is None:
                break
            # Process event (send to client, etc.)
            await process_event(event)

    await asyncio.gather(producer(), consumer())
```

### 3. Implement Timeouts

Add timeouts for long-running operations:

```python
import asyncio

async def stream_with_timeout(agent, prompt, timeout_seconds=30):
    """Stream events with timeout."""
    try:
        async with asyncio.timeout(timeout_seconds):
            async for event in run_stream(agent, prompt, deps):
                # Handle event
                pass
    except asyncio.TimeoutError:
        print(f"Operation timed out after {timeout_seconds}s")
```

### 4. Log All Events

Keep a record of all events for debugging:

```python
import json
from pathlib import Path

async def stream_with_logging(agent, prompt, log_file="events.jsonl"):
    """Stream events and log them to file."""
    log_path = Path(log_file)

    with log_path.open("a") as f:
        async for event in run_stream(agent, prompt, deps):
            # Log event
            log_entry = {
                "event_type": event.event_type,
                "timestamp": event.timestamp.isoformat(),
                "data": event.data,
            }
            f.write(json.dumps(log_entry) + "\n")
            f.flush()

            # Handle event normally
            if event.event_type == StreamEventType.LLM_CHUNK:
                print(event.data["text"], end="", flush=True)
```

### 5. Build Reusable Event Handlers

Create reusable event handler functions:

```python
def create_text_handler():
    """Create a text streaming handler."""
    def handler(event):
        if event.event_type == StreamEventType.LLM_CHUNK:
            print(event.data["text"], end="", flush=True)
    return handler

def create_progress_handler():
    """Create a progress monitoring handler."""
    def handler(event):
        if event.event_type == StreamEventType.PROGRESS:
            tokens = event.data.get("total_tokens", 0)
            print(f"\n[{tokens} tokens]")
    return handler

# Combine handlers
async def run_with_handlers(agent, prompt, *handlers):
    """Run agent with multiple event handlers."""
    async for event in run_stream(agent, prompt, deps):
        for handler in handlers:
            handler(event)

# Usage
await run_with_handlers(
    agent,
    prompt,
    create_text_handler(),
    create_progress_handler(),
)
```

## Performance Considerations

### Latency

Streaming adds minimal latency:

- **Text streaming**: Adds ~1-5ms per chunk
- **Tool event tracking**: Adds ~0.1-0.5ms per tool call
- **Progress events**: Adds ~0.1ms per iteration

The overhead is negligible compared to LLM latency (100-1000ms+).

### Memory

Streaming is memory-efficient:

- Events are yielded one at a time (streaming)
- No buffering of full responses
- Use `collect_stream_result()` only when you need all events

### Concurrency

All streaming functions are async and can handle concurrent requests:

```python
async def stream_multiple_requests(prompts):
    """Stream multiple agent requests concurrently."""
    tasks = [
        run_stream(agent, prompt, deps)
        for prompt in prompts
    ]

    for task in asyncio.as_completed(tasks):
        async for event in await task:
            # Handle event
            pass
```

## Real-World Examples

### Web Application with Server-Sent Events (SSE)

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI()

@app.get("/chat")
async def chat_stream(prompt: str):
    """Stream chat responses via SSE."""
    async def event_stream():
        async for event in run_stream(agent, prompt, deps):
            if event.event_type == StreamEventType.LLM_CHUNK:
                yield f"data: {event.data['text']}\n\n"

            elif event.event_type == StreamEventType.AGENT_END:
                yield f"event: done\ndata: {{\"success\": true}}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream"
    )
```

### CLI with Rich Progress Bar

```python
from rich.console import Console
from rich.live import Live
from rich.progress import Progress

console = Console()

async def cli_with_progress(agent, prompt):
    """CLI with rich progress bar."""
    with Live(console=console, refresh_per_second=4) as live:
        progress = Progress()
        task_id = progress.add_task("[cyan]Processing...", total=None)

        async for event in run_stream(agent, prompt, deps):
            if event.event_type == StreamEventType.LLM_CHUNK:
                console.print(event.data["text"], end="")

            elif event.event_type == StreamEventType.PROGRESS:
                iteration = event.data["iteration"]
                tokens = event.data.get("total_tokens", 0)
                progress.update(
                    task_id,
                    description=f"[cyan]Iteration {iteration} ({tokens} tokens)"
                )

            live.update(progress)
```

## Troubleshooting

### Events Not Streaming

If events aren't streaming as expected:

1. **Check async iteration**: Ensure you're using `async for`
2. **Verify model supports streaming**: TestModel supports streaming
3. **Check buffering**: Disable output buffering with `flush=True`

```python
# Wrong - missing await
for event in run_stream(agent, prompt, deps):  # ❌
    pass

# Correct
async for event in run_stream(agent, prompt, deps):  # ✓
    pass
```

### Missing Events

If you're missing tool call or progress events:

- Use `run_stream_with_tools()` for detailed tool events
- Ensure `emit_progress=True` (default)
- Check that your agent actually calls tools

### Performance Issues

If streaming is slow:

- Don't perform heavy computation in event handlers
- Use background tasks for slow operations
- Consider batching events for network transmission

## See Also

- [Tracing Documentation](./tracing.md) - For distributed tracing
- [Guardrails Documentation](./guardrails.md) - For safety monitoring
- [Testing Documentation](./testing.md) - For deterministic testing

## API Documentation

For complete API documentation, see:

- [`run_stream`][pydantic_deep.streaming.run_stream]
- [`stream_text`][pydantic_deep.streaming.stream_text]
- [`StreamEvent`][pydantic_deep.streaming.types.StreamEvent]
- [`StreamEventType`][pydantic_deep.streaming.types.StreamEventType]
