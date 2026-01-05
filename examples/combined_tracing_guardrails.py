"""Combined example using both tracing and guardrails.

This example demonstrates how to use tracing and guardrails together
for comprehensive observability and safety.
"""

import asyncio

from pydantic_ai.models.test import TestModel
from pydantic_ai_backends import StateBackend

from pydantic_deep import DeepAgentDeps, create_deep_agent
from pydantic_deep.guardrails import (
    GuardrailManager,
    GuardrailViolation,
    create_safe_agent_guardrails,
)
from pydantic_deep.tracing import ConsoleExporter, InMemoryExporter, TraceContext


async def combined_example():
    """Example using both tracing and guardrails."""
    print("=== Combined Tracing & Guardrails Example ===\n")

    # Set up tracing
    memory_exporter = InMemoryExporter()
    trace_ctx = TraceContext(
        exporters=[
            ConsoleExporter(verbose=True),
            memory_exporter,
        ]
    )

    # Set up guardrails
    guardrails = create_safe_agent_guardrails(
        max_tokens=50000,
        max_cost_usd=5.0,
        max_iterations=15,
    )
    guardrail_manager = GuardrailManager(guardrails, mode="strict")

    # Create agent
    agent = create_deep_agent(
        model=TestModel(),
        instructions="You are a helpful file management assistant.",
    )

    # Create deps with both tracing and guardrails
    deps = DeepAgentDeps(
        backend=StateBackend(),
        trace_context=trace_ctx,
        guardrail_manager=guardrail_manager,
    )

    # Run agent with monitoring
    print("Running agent with tracing and guardrails enabled...\n")

    with trace_ctx.agent_run("safe-agent", "Manage files safely", "test-model"):
        try:
            result = await agent.run(
                "Create a file hello.txt and write 'Hello, World!' to it",
                deps=deps,
            )
            print(f"\n✓ Agent completed successfully")
            print(f"Result: {result.output}")
        except GuardrailViolation as e:
            print(f"\n✗ Guardrail violation prevented execution: {e}")

    # Show trace summary
    print("\n=== Trace Summary ===")
    trace_summary = trace_ctx.get_summary()
    print(f"Total events: {trace_summary['total_events']}")
    print(f"Tool calls: {trace_summary['tool_calls']}")
    print(f"LLM requests: {trace_summary['llm_requests']}")
    print(f"Total tokens: {trace_summary['total_tokens']}")
    print(f"Errors: {trace_summary['errors']}")

    # Show guardrail summary
    print("\n=== Guardrail Summary ===")
    guardrail_summary = guardrail_manager.get_summary()
    print(f"Total checks: {guardrail_summary['total_checks']}")
    print(f"Violations: {guardrail_summary['violations']}")

    # Get detailed event analysis from memory exporter
    print("\n=== Detailed Event Analysis ===")
    from pydantic_deep.tracing import LLMResponseEvent, ToolCallEndEvent

    llm_events = memory_exporter.get_events_by_type(LLMResponseEvent)
    tool_events = memory_exporter.get_events_by_type(ToolCallEndEvent)

    print(f"LLM calls: {len(llm_events)}")
    for event in llm_events:
        print(f"  - Duration: {event.duration_seconds:.2f}s, Tokens: {event.total_tokens or 'N/A'}")

    print(f"\nTool calls: {len(tool_events)}")
    for event in tool_events:
        status = "✓" if event.success else "✗"
        print(f"  {status} {event.tool_name}: {event.duration_seconds:.2f}s")


async def guardrail_violation_with_tracing():
    """Example showing how violations are captured in traces."""
    print("\n\n=== Guardrail Violation with Tracing ===\n")

    # Set up tracing
    trace_ctx = TraceContext(exporters=[ConsoleExporter(verbose=True)])

    # Set up very restrictive guardrails (will likely violate)
    from pydantic_deep.guardrails import (
        GuardrailContext,
        IterationLimitGuardrail,
        TokenBudgetGuardrail,
    )

    guardrails = [
        TokenBudgetGuardrail(max_tokens=1000),  # Very low limit
        IterationLimitGuardrail(max_iterations=3),  # Very low limit
    ]
    guardrail_manager = GuardrailManager(guardrails, mode="permissive")

    # Simulate agent state that violates guardrails
    context = GuardrailContext(
        agent_name="restricted-agent",
        run_id="run-789",
        iteration_count=5,  # Exceeds iteration limit
        total_tokens=2000,  # Exceeds token limit
        total_cost_usd=0.10,
        duration_seconds=2.0,
        tool_calls=[],
        last_n_tools=["read_file", "write_file"],
    )

    print("Checking guardrails with permissive mode...\n")

    with trace_ctx.agent_run("restricted-agent", "Task with restrictions", "test-model"):
        # Check guardrails (won't raise in permissive mode)
        results = guardrail_manager.check_all(context)

        # Log results
        print("\nGuardrail check results:")
        for result in results:
            if result.passed:
                print(f"  ✓ PASS: {result.message or 'No issues'}")
            else:
                print(f"  ✗ FAIL: {result.message}")

    # Show violations collected
    summary = guardrail_manager.get_summary()
    print(f"\n=== Violations Collected ===")
    print(f"Total violations: {summary['violations']}")
    for violation_msg in summary["violation_types"]:
        print(f"  - {violation_msg}")

    # Trace summary
    print(f"\n=== Trace Summary ===")
    trace_summary = trace_ctx.get_summary()
    print(f"Total events captured: {trace_summary['total_events']}")


async def production_ready_agent():
    """Example of a production-ready agent with full monitoring and safety."""
    print("\n\n=== Production-Ready Agent Example ===\n")

    from pydantic_deep.guardrails import create_production_guardrails
    from pydantic_deep.tracing import StructuredFileExporter

    # Set up comprehensive tracing
    file_exporter = StructuredFileExporter("/tmp/agent-traces.jsonl")
    trace_ctx = TraceContext(
        exporters=[
            ConsoleExporter(verbose=False),  # Less verbose for production
            file_exporter,
        ]
    )

    # Set up production guardrails
    guardrails = create_production_guardrails(
        max_tokens=200000,
        max_cost_usd=50.0,
    )
    guardrail_manager = GuardrailManager(guardrails, mode="strict")

    # Create production agent
    agent = create_deep_agent(
        model=TestModel(),
        instructions="You are a production agent with full safety and monitoring.",
    )

    # Create deps
    deps = DeepAgentDeps(
        backend=StateBackend(),
        trace_context=trace_ctx,
        guardrail_manager=guardrail_manager,
    )

    print("Running production agent with full monitoring and safety...\n")

    with trace_ctx.agent_run("prod-agent", "Production task", "test-model"):
        try:
            result = await agent.run(
                "Perform a safe file operation",
                deps=deps,
            )
            print(f"\n✓ Production agent completed successfully")
        except GuardrailViolation as e:
            print(f"\n✗ Safety guardrail prevented unsafe operation: {e}")

    # Flush traces to file
    file_exporter.flush()
    file_exporter.close()

    print(f"\n✓ Trace data written to /tmp/agent-traces.jsonl")
    print(f"✓ Guardrail checks: {guardrail_manager.get_summary()['total_checks']}")
    print(f"✓ Events captured: {trace_ctx.get_summary()['total_events']}")


if __name__ == "__main__":
    asyncio.run(combined_example())
    asyncio.run(guardrail_violation_with_tracing())
    asyncio.run(production_ready_agent())
