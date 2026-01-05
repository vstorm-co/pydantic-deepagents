"""Basic example of guardrails and safety gates.

This example demonstrates how to use guardrails to protect against
runaway costs, infinite loops, and invalid operations.
"""

import asyncio

from pydantic_ai.models.test import TestModel
from pydantic_ai_backends import StateBackend

from pydantic_deep import DeepAgentDeps, create_deep_agent
from pydantic_deep.guardrails import (
    CostLimitGuardrail,
    GuardrailContext,
    GuardrailManager,
    GuardrailViolation,
    IterationLimitGuardrail,
    TokenBudgetGuardrail,
    ToolLoopDetectionGuardrail,
    create_safe_agent_guardrails,
)


async def basic_guardrails_example():
    """Basic example using safe agent guardrails."""
    print("=== Basic Guardrails Example ===\n")

    # Create safe guardrails with sensible defaults
    guardrails = create_safe_agent_guardrails(
        max_tokens=100000,
        max_cost_usd=5.0,
        max_iterations=20,
    )

    # Create manager in strict mode (raises on violation)
    manager = GuardrailManager(guardrails, mode="strict")

    # Create agent
    create_deep_agent(
        model=TestModel(),
        instructions="You are a helpful assistant.",
    )

    # Create deps with guardrails
    DeepAgentDeps(
        backend=StateBackend(),
        guardrail_manager=manager,
    )

    # Simulate guardrail check
    context = GuardrailContext(
        agent_name="test-agent",
        run_id="run-123",
        iteration_count=5,
        total_tokens=10000,
        total_cost_usd=0.50,
        duration_seconds=5.0,
        tool_calls=[],
        last_n_tools=["read_file", "write_file", "execute"],
    )

    # Check all guardrails
    try:
        results = manager.check_all(context)
        print(f"✓ All {len(results)} guardrail checks passed")
        for _i, result in enumerate(results):
            status = "✓ PASS" if result.passed else "✗ FAIL"
            print(f"  {status}: {result.message or 'No issues'}")
    except GuardrailViolation as e:
        print(f"✗ Guardrail violation: {e}")

    # Get summary
    summary = manager.get_summary()
    print("\n=== Guardrail Summary ===")
    print(f"Total checks: {summary['total_checks']}")
    print(f"Violations: {summary['violations']}")


async def individual_guardrails_example():
    """Example using individual guardrails."""
    print("\n\n=== Individual Guardrails Example ===\n")

    # Token budget guardrail
    print("--- Token Budget Guardrail ---")
    token_guardrail = TokenBudgetGuardrail(max_tokens=50000, warn_at=0.8)

    # Within budget
    ctx = GuardrailContext(
        agent_name="test",
        run_id="1",
        iteration_count=1,
        total_tokens=30000,
        total_cost_usd=0.0,
        duration_seconds=1.0,
        tool_calls=[],
        last_n_tools=[],
    )
    result = token_guardrail.check(ctx)
    print(f"30K tokens: {result.passed} - {result.message or 'OK'}")

    # Warning threshold
    ctx.total_tokens = 45000
    result = token_guardrail.check(ctx)
    print(f"45K tokens: {result.passed} - {result.message or 'OK'}")

    # Exceeded
    ctx.total_tokens = 60000
    result = token_guardrail.check(ctx)
    print(f"60K tokens: {result.passed} - {result.message or 'OK'}")

    # Cost limit guardrail
    print("\n--- Cost Limit Guardrail ---")
    cost_guardrail = CostLimitGuardrail(max_cost_usd=10.0, warn_at=0.7)

    ctx.total_cost_usd = 5.0
    result = cost_guardrail.check(ctx)
    print(f"$5.00: {result.passed} - {result.message or 'OK'}")

    ctx.total_cost_usd = 8.0
    result = cost_guardrail.check(ctx)
    print(f"$8.00: {result.passed} - {result.message or 'OK'}")

    ctx.total_cost_usd = 15.0
    result = cost_guardrail.check(ctx)
    print(f"$15.00: {result.passed} - {result.message or 'OK'}")

    # Iteration limit guardrail
    print("\n--- Iteration Limit Guardrail ---")
    iteration_guardrail = IterationLimitGuardrail(max_iterations=10)

    ctx.iteration_count = 5
    result = iteration_guardrail.check(ctx)
    print(f"5 iterations: {result.passed} - {result.message or 'OK'}")

    ctx.iteration_count = 15
    result = iteration_guardrail.check(ctx)
    print(f"15 iterations: {result.passed} - {result.message or 'OK'}")

    # Tool loop detection
    print("\n--- Tool Loop Detection Guardrail ---")
    loop_guardrail = ToolLoopDetectionGuardrail(window_size=5, max_repeats=3)

    # Normal sequence
    ctx.last_n_tools = ["read_file", "write_file", "execute", "grep"]
    result = loop_guardrail.check(ctx)
    print(f"Normal sequence: {result.passed} - {result.message or 'OK'}")

    # Repeating pattern
    ctx.last_n_tools = [
        "read_file",
        "write_file",
        "read_file",
        "write_file",
        "read_file",
        "write_file",
    ]
    result = loop_guardrail.check(ctx)
    print(f"Repeating pattern: {result.passed} - {result.message or 'OK'}")

    # Stuck in loop
    ctx.last_n_tools = ["read_file"] * 5
    result = loop_guardrail.check(ctx)
    print(f"Stuck in loop: {result.passed} - {result.message or 'OK'}")


async def permissive_mode_example():
    """Example using permissive mode to collect violations without failing."""
    print("\n\n=== Permissive Mode Example ===\n")

    # Create guardrails that will be violated
    guardrails = [
        TokenBudgetGuardrail(max_tokens=10000),  # Will be violated
        CostLimitGuardrail(max_cost_usd=1.0),  # Will be violated
        IterationLimitGuardrail(max_iterations=5),  # Will be violated
    ]

    # Use permissive mode to log violations without raising
    manager = GuardrailManager(guardrails, mode="permissive")

    # Create context that violates multiple guardrails
    context = GuardrailContext(
        agent_name="test-agent",
        run_id="run-456",
        iteration_count=10,  # Exceeds limit
        total_tokens=20000,  # Exceeds limit
        total_cost_usd=2.0,  # Exceeds limit
        duration_seconds=10.0,
        tool_calls=[],
        last_n_tools=[],
    )

    # Check all guardrails (won't raise in permissive mode)
    results = manager.check_all(context)

    print("Guardrail results:")
    for _i, result in enumerate(results):
        status = "✓ PASS" if result.passed else "✗ FAIL"
        print(f"  {status}: {result.message or 'No message'}")

    # Get summary of violations
    summary = manager.get_summary()
    print("\n=== Violation Summary ===")
    print(f"Total checks: {summary['total_checks']}")
    print(f"Violations: {summary['violations']}")
    print("Violation types:")
    for violation_msg in summary["violation_types"]:
        print(f"  - {violation_msg}")

    # Reset for next run
    manager.reset()
    print(f"\nAfter reset: {manager.get_summary()['violations']} violations")


async def output_validation_example():
    """Example using output validation to prevent secrets leaking."""
    print("\n\n=== Output Validation Example ===\n")

    from pydantic_deep.guardrails import (
        OutputValidationGuardrail,
        redact_secrets,
        validate_no_secrets,
    )

    # Create output validation guardrail
    guardrail = OutputValidationGuardrail(
        validators=[validate_no_secrets],
        on_fail="sanitize",
        sanitizer=redact_secrets,
    )

    # Test with clean output
    ctx = GuardrailContext(
        agent_name="test",
        run_id="1",
        iteration_count=1,
        total_tokens=0,
        total_cost_usd=0.0,
        duration_seconds=0.0,
        tool_calls=[],
        last_n_tools=[],
        metadata={"output": "This is a clean response with no secrets."},
    )

    result = guardrail.check(ctx)
    print(f"Clean output: {result.passed}")
    print(f"  Output: {ctx.metadata['output']}")

    # Test with secrets
    ctx.metadata["output"] = "Your api_key=sk-1234567890abcdefghij is ready!"

    result = guardrail.check(ctx)
    print(f"\nOutput with secrets: {result.passed}")
    print("  Original: Your api_key=sk-1234567890abcdefghij is ready!")

    # Sanitize the output
    guardrail.on_violation(ctx)
    print(f"  Sanitized: {ctx.metadata['output']}")


if __name__ == "__main__":
    asyncio.run(basic_guardrails_example())
    asyncio.run(individual_guardrails_example())
    asyncio.run(permissive_mode_example())
    asyncio.run(output_validation_example())
