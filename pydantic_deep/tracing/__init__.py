"""Agent observability and tracing for pydantic-deep.

This module provides comprehensive tracing and observability for agent
executions, including:

- Trace events for agent runs, LLM calls, and tool executions
- Multiple exporters (console, OpenTelemetry, in-memory, file)
- Token usage and latency tracking
- Hierarchical event structure

Example:
    ```python
    from pydantic_deep import create_deep_agent, DeepAgentDeps
    from pydantic_deep.tracing import ConsoleExporter, TraceContext

    # Create agent with tracing
    trace_ctx = TraceContext(exporters=[ConsoleExporter()])
    agent = create_deep_agent(model="openai:gpt-4o")

    # Wrap execution in trace context
    with trace_ctx.agent_run("my-agent", "Analyze data", "gpt-4o"):
        result = await agent.run("Analyze this data", deps=deps)

    # View summary
    summary = trace_ctx.get_summary()
    print(f"Total tokens: {summary['total_tokens']}")
    ```
"""

from pydantic_deep.tracing.context import TraceContext as TraceContext
from pydantic_deep.tracing.exporters import (
    ConsoleExporter as ConsoleExporter,
)
from pydantic_deep.tracing.exporters import (
    InMemoryExporter as InMemoryExporter,
)
from pydantic_deep.tracing.exporters import (
    OpenTelemetryExporter as OpenTelemetryExporter,
)
from pydantic_deep.tracing.exporters import (
    StructuredFileExporter as StructuredFileExporter,
)
from pydantic_deep.tracing.types import (
    AgentRunEndEvent as AgentRunEndEvent,
)
from pydantic_deep.tracing.types import (
    AgentRunStartEvent as AgentRunStartEvent,
)
from pydantic_deep.tracing.types import (
    ErrorEvent as ErrorEvent,
)
from pydantic_deep.tracing.types import (
    EventType as EventType,
)
from pydantic_deep.tracing.types import (
    LLMRequestEvent as LLMRequestEvent,
)
from pydantic_deep.tracing.types import (
    LLMResponseEvent as LLMResponseEvent,
)
from pydantic_deep.tracing.types import (
    ToolCallEndEvent as ToolCallEndEvent,
)
from pydantic_deep.tracing.types import (
    ToolCallStartEvent as ToolCallStartEvent,
)
from pydantic_deep.tracing.types import (
    TraceEvent as TraceEvent,
)
from pydantic_deep.tracing.types import (
    TraceExporterProtocol as TraceExporterProtocol,
)

__all__ = [
    "TraceContext",
    "ConsoleExporter",
    "InMemoryExporter",
    "OpenTelemetryExporter",
    "StructuredFileExporter",
    "TraceEvent",
    "EventType",
    "AgentRunStartEvent",
    "AgentRunEndEvent",
    "LLMRequestEvent",
    "LLMResponseEvent",
    "ToolCallStartEvent",
    "ToolCallEndEvent",
    "ErrorEvent",
    "TraceExporterProtocol",
]
