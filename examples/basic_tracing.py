"""Basic example of agent observability and tracing.

This example demonstrates how to use the tracing system to monitor
agent execution, track tool calls, and collect metrics.
"""

import asyncio

from pydantic_ai.models import TestModel
from pydantic_ai_backends import StateBackend

from pydantic_deep import DeepAgentDeps, create_deep_agent
from pydantic_deep.tracing import ConsoleExporter, InMemoryExporter, TraceContext


async def basic_tracing_example():
    """Basic tracing with console output."""
    print("=== Basic Tracing Example ===\n")

    # Create trace context with console exporter for visual feedback
    trace_ctx = TraceContext(exporters=[ConsoleExporter(verbose=True)])

    # Create agent with tracing
    agent = create_deep_agent(
        model=TestModel(),
        instructions="You are a helpful assistant that writes files.",
    )

    # Create deps with trace context
    deps = DeepAgentDeps(
        backend=StateBackend(),
        trace_context=trace_ctx,
    )

    # Run agent with tracing
    with trace_ctx.agent_run("file-writer", "Write a hello.txt file", "test-model"):
        result = await agent.run(
            "Create a file called hello.txt with the text 'Hello, World!'",
            deps=deps,
        )

    print(f"\nResult: {result.output}")

    # Get summary statistics
    summary = trace_ctx.get_summary()
    print(f"\n=== Trace Summary ===")
    print(f"Total events: {summary['total_events']}")
    print(f"Tool calls: {summary['tool_calls']}")
    print(f"LLM requests: {summary['llm_requests']}")
    print(f"Total tokens: {summary['total_tokens']}")
    print(f"Errors: {summary['errors']}")


async def multi_exporter_example():
    """Example using multiple exporters simultaneously."""
    print("\n\n=== Multi-Exporter Example ===\n")

    # Create trace context with both console and in-memory exporters
    memory_exporter = InMemoryExporter()
    trace_ctx = TraceContext(
        exporters=[
            ConsoleExporter(verbose=False),  # Less verbose for cleaner output
            memory_exporter,
        ]
    )

    agent = create_deep_agent(
        model=TestModel(),
        instructions="You are a helpful assistant.",
    )

    deps = DeepAgentDeps(
        backend=StateBackend(),
        trace_context=trace_ctx,
    )

    with trace_ctx.agent_run("data-processor", "Process data", "test-model"):
        result = await agent.run("Read and analyze data.txt", deps=deps)

    # Get hierarchical tree view from memory exporter
    tree = memory_exporter.get_tree()
    print("\n=== Event Tree ===")
    print(f"Root events: {len(tree['roots'])}")

    # Filter events by type
    from pydantic_deep.tracing import LLMResponseEvent

    llm_events = memory_exporter.get_events_by_type(LLMResponseEvent)
    print(f"\n=== LLM Events ===")
    for event in llm_events:
        print(
            f"  - Model: {event.model}, Duration: {event.duration_seconds:.2f}s, "
            f"Tokens: {event.total_tokens or 'N/A'}"
        )


async def manual_tracing_example():
    """Example of manual tracing for custom operations."""
    print("\n\n=== Manual Tracing Example ===\n")

    trace_ctx = TraceContext(exporters=[ConsoleExporter(verbose=True)])

    # Manually trace custom operations
    with trace_ctx.agent_run("custom-agent", "Custom task", "test-model") as run_id:
        print(f"Agent run ID: {run_id}")

        # Manually trace a tool call
        with trace_ctx.tool_call("custom_tool", {"arg1": "value1"}) as call_id:
            # Simulate tool execution
            await asyncio.sleep(0.1)
            result = {"status": "success", "data": "processed"}

        # Record tool completion
        from datetime import datetime

        trace_ctx.tool_call_end("custom_tool", datetime.now(), result=result)

        # Manually trace LLM request
        request_id = trace_ctx.llm_request("gpt-4", messages_count=3, tools_count=2)

        # Simulate LLM call
        await asyncio.sleep(0.2)

        # Record LLM response
        trace_ctx.llm_response(
            "gpt-4",
            datetime.now(),
            input_tokens=100,
            output_tokens=50,
            finish_reason="stop",
            request_event_id=request_id,
        )

    # Flush to ensure all events are exported
    trace_ctx.flush()

    print("\n=== Summary ===")
    summary = trace_ctx.get_summary()
    print(f"Total events: {summary['total_events']}")


if __name__ == "__main__":
    asyncio.run(basic_tracing_example())
    asyncio.run(multi_exporter_example())
    asyncio.run(manual_tracing_example())
