# Agent Observability & Tracing

The tracing module provides comprehensive observability for agent executions, allowing you to track tool calls, LLM interactions, token usage, and performance metrics.

## Quick Start

```python
from pydantic_deep import create_deep_agent, DeepAgentDeps
from pydantic_deep.tracing import TraceContext, ConsoleExporter
from pydantic_ai_backends import StateBackend

# Create a trace context with console exporter
trace_ctx = TraceContext(exporters=[ConsoleExporter(verbose=True)])

# Create deps with trace context
deps = DeepAgentDeps(
    backend=StateBackend(),
    trace_context=trace_ctx,
)

# Create and run agent
agent = create_deep_agent(model="openai:gpt-4o")

with trace_ctx.agent_run("my-agent", "Analyze this data", "gpt-4o") as run_id:
    result = await agent.run("Analyze sales data", deps=deps)

# Get summary
summary = trace_ctx.get_summary()
print(f"Total tokens: {summary['total_tokens']}")
print(f"Tool calls: {summary['tool_calls']}")
```

## Exporters

### ConsoleExporter

Prints trace events to the console in a tree-like format:

```python
from pydantic_deep.tracing import ConsoleExporter

exporter = ConsoleExporter(verbose=True)  # Show detailed info
trace_ctx = TraceContext(exporters=[exporter])
```

Output:
```
🤖 Agent run: my-agent
   Model: gpt-4o
   ├─ LLM step [0.8s, 1250 tokens]
   ├─ ✓ Tool: read_todos [0.1s]
   ├─ LLM step [0.6s, 890 tokens]
   ✓ Completed in 3.2s, 2140 tokens
```

### OpenTelemetryExporter

Export traces to OpenTelemetry for distributed tracing:

```python
from pydantic_deep.tracing import OpenTelemetryExporter

exporter = OpenTelemetryExporter(
    endpoint="http://localhost:4318/v1/traces",
    service_name="my-agent-service",
    headers={"Authorization": "Bearer token"},
)
trace_ctx = TraceContext(exporters=[exporter])
```

### StructuredFileExporter

Export traces to a JSONL file for later analysis:

```python
from pydantic_deep.tracing import StructuredFileExporter

with StructuredFileExporter("traces.jsonl") as exporter:
    trace_ctx = TraceContext(exporters=[exporter])
    # Run agent...
    exporter.flush()
```

### InMemoryExporter

Store traces in memory for programmatic analysis:

```python
from pydantic_deep.tracing import InMemoryExporter

exporter = InMemoryExporter()
trace_ctx = TraceContext(exporters=[exporter])

# After running agent
agent_events = exporter.get_events_by_type(AgentRunStartEvent)
tree = exporter.get_tree()  # Get hierarchical view
```

## Event Types

All trace events inherit from `TraceEvent` and include:

- `event_id`: Unique ID for this event
- `parent_id`: ID of parent event (for nesting)
- `timestamp`: When the event occurred
- `event_type`: Type of event
- `metadata`: Additional metadata

### AgentRunStartEvent / AgentRunEndEvent

Tracks agent execution lifecycle:

```python
@dataclass
class AgentRunStartEvent:
    agent_name: str
    prompt: str
    model: str

@dataclass
class AgentRunEndEvent:
    agent_name: str
    output: str | dict
    duration_seconds: float
    total_tokens: int | None
    success: bool
```

### LLMRequestEvent / LLMResponseEvent

Tracks LLM API calls:

```python
@dataclass
class LLMResponseEvent:
    model: str
    duration_seconds: float
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    finish_reason: str | None
```

### ToolCallStartEvent / ToolCallEndEvent

Tracks tool executions:

```python
@dataclass
class ToolCallEndEvent:
    tool_name: str
    duration_seconds: float
    result: Any
    error: str | None
    success: bool
```

### ErrorEvent

Tracks errors during execution:

```python
@dataclass
class ErrorEvent:
    error_type: str
    error_message: str
    traceback: str | None
```

## Manual Tracing

You can manually trace operations:

```python
# Trace tool calls
with trace_ctx.tool_call("my_tool", {"arg": "value"}) as call_id:
    result = my_tool(arg="value")
trace_ctx.tool_call_end("my_tool", start_time, result=result)

# Trace LLM calls
request_id = trace_ctx.llm_request("gpt-4", messages_count=5, tools_count=3)
# ... make LLM call ...
trace_ctx.llm_response(
    "gpt-4",
    start_time,
    input_tokens=100,
    output_tokens=50,
    request_event_id=request_id,
)
```

## Multiple Exporters

Use multiple exporters simultaneously:

```python
trace_ctx = TraceContext(exporters=[
    ConsoleExporter(),
    OpenTelemetryExporter(endpoint="http://localhost:4318/v1/traces"),
    StructuredFileExporter("traces.jsonl"),
])
```

## Performance Considerations

- Tracing adds minimal overhead (~1-2% latency)
- Use `InMemoryExporter` for development/testing
- Use `OpenTelemetryExporter` for production with sampling
- `ConsoleExporter` is best for debugging, not production
- Call `trace_ctx.flush()` to ensure all events are sent before exiting

## Advanced Usage

### Custom Exporters

Implement the `TraceExporterProtocol`:

```python
from pydantic_deep.tracing import TraceExporterProtocol, TraceEvent

class MyCustomExporter:
    def export_event(self, event: TraceEvent) -> None:
        # Handle event
        pass

    def flush(self) -> None:
        # Flush any buffers
        pass
```

### Hierarchical Tracing

Trace contexts maintain parent-child relationships automatically:

```python
with trace_ctx.agent_run("parent", "Task", "gpt-4"):
    # Child events automatically linked to parent
    with trace_ctx.tool_call("read_file", {}):
        pass
```

### Summary Statistics

Get aggregate metrics:

```python
summary = trace_ctx.get_summary()
print(summary)
# {
#     "total_events": 10,
#     "tool_calls": 3,
#     "llm_requests": 2,
#     "total_tokens": 1500,
#     "errors": 0
# }
```
