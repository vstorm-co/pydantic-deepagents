# Guardrails & Safety Gates

The guardrails module provides built-in protection against agent failures, runaway loops, cost explosions, and invalid operations. Guardrails act as safety gates that monitor and enforce limits during agent execution.

## Quick Start

```python
from pydantic_deep import create_deep_agent, DeepAgentDeps
from pydantic_deep.guardrails import (
    create_safe_agent_guardrails,
    GuardrailManager,
)
from pydantic_ai_backends import StateBackend

# Create guardrails
guardrails = create_safe_agent_guardrails(
    max_tokens=100000,
    max_cost_usd=5.0,
    max_iterations=20,
)

# Create manager
manager = GuardrailManager(guardrails, mode="strict")

# Use with agent
deps = DeepAgentDeps(
    backend=StateBackend(),
    guardrail_manager=manager,
)

agent = create_deep_agent()
result = await agent.run("Do something", deps=deps)
```

## Built-in Guardrails

### TokenBudgetGuardrail

Prevents token budget overruns by tracking total tokens used.

```python
from pydantic_deep.guardrails import TokenBudgetGuardrail

guardrail = TokenBudgetGuardrail(
    max_tokens=100000,
    warn_at=0.8,  # Warn at 80% usage
    action="raise",  # Action to take on violation
)
```

**Parameters:**
- `max_tokens`: Maximum tokens allowed
- `warn_at`: Fraction at which to emit warning (0.0-1.0), default 0.8
- `action`: Action to take on violation ("raise", "warn", "soft_stop"), default "raise"

**Example:**
```python
# Agent will raise GuardrailViolation when exceeding 50K tokens
guardrail = TokenBudgetGuardrail(max_tokens=50000)
```

### CostLimitGuardrail

Prevents runaway costs by tracking total cost in USD.

```python
from pydantic_deep.guardrails import CostLimitGuardrail

guardrail = CostLimitGuardrail(
    max_cost_usd=10.0,
    warn_at=0.7,  # Warn at 70% of budget
)
```

**Parameters:**
- `max_cost_usd`: Maximum cost in USD allowed
- `warn_at`: Fraction at which to emit warning (0.0-1.0), default 0.7

**Example:**
```python
# Warn at $3.50, fail at $5.00
guardrail = CostLimitGuardrail(max_cost_usd=5.0, warn_at=0.7)
```

### IterationLimitGuardrail

Prevents infinite loops by limiting the number of iterations.

```python
from pydantic_deep.guardrails import IterationLimitGuardrail

guardrail = IterationLimitGuardrail(
    max_iterations=20,
    action="raise",  # or "return_partial"
)
```

**Parameters:**
- `max_iterations`: Maximum iterations allowed, default 20
- `action`: Action to take on violation ("raise", "return_partial"), default "raise"

**Example:**
```python
# Stop after 15 iterations
guardrail = IterationLimitGuardrail(max_iterations=15)
```

### ToolChainValidationGuardrail

Prevents invalid tool call sequences by checking against forbidden patterns.

```python
from pydantic_deep.guardrails import ToolChainValidationGuardrail

guardrail = ToolChainValidationGuardrail(
    forbidden_sequences=[
        ["delete_file", "read_file"],  # Can't read deleted files
        ["drop_table", "insert_rows"],  # Can't insert after drop
    ],
    forbidden_patterns=[
        ("delete_*", "read_*"),  # Can't read anything after delete
    ],
)
```

**Parameters:**
- `forbidden_sequences`: List of forbidden tool sequences (exact matches)
- `forbidden_patterns`: List of (pattern1, pattern2) tuples for wildcard matching

**Example:**
```python
# Prevent destructive sequences
guardrail = ToolChainValidationGuardrail(
    forbidden_sequences=[
        ["delete_file", "read_file"],
        ["write_file", "delete_file", "write_file"],  # Prevent accidental overwrites
    ]
)
```

### OutputValidationGuardrail

Validates agent output before returning, with optional sanitization.

```python
from pydantic_deep.guardrails import OutputValidationGuardrail

def no_secrets(text: str) -> bool:
    return "api_key" not in text.lower()

def sanitize_output(text: str) -> str:
    return text.replace("API_KEY", "***REDACTED***")

guardrail = OutputValidationGuardrail(
    validators=[no_secrets],
    on_fail="sanitize",  # "raise", "sanitize", or "log"
    sanitizer=sanitize_output,
)
```

**Parameters:**
- `validators`: List of validation functions (return True if valid)
- `on_fail`: Action on validation failure ("raise", "sanitize", "log"), default "raise"
- `sanitizer`: Function to sanitize output if on_fail="sanitize"

**Built-in Validators:**
```python
from pydantic_deep.guardrails import validate_no_secrets, validate_no_pii, redact_secrets

# Use built-in validators
guardrail = OutputValidationGuardrail(
    validators=[validate_no_secrets, validate_no_pii],
    on_fail="sanitize",
    sanitizer=redact_secrets,
)
```

### ToolLoopDetectionGuardrail

Detects when an agent is stuck in a loop by analyzing tool call patterns.

```python
from pydantic_deep.guardrails import ToolLoopDetectionGuardrail

guardrail = ToolLoopDetectionGuardrail(
    window_size=5,
    max_repeats=3,
)
```

**Parameters:**
- `window_size`: Size of the window to check for loops, default 5
- `max_repeats`: Maximum allowed repeats of the same pattern, default 3

**Example:**
```python
# Detect if same tool is called 4+ times in a row
guardrail = ToolLoopDetectionGuardrail(window_size=6, max_repeats=4)
```

## GuardrailManager

The `GuardrailManager` coordinates multiple guardrails and handles violations.

```python
from pydantic_deep.guardrails import GuardrailManager

manager = GuardrailManager(
    guardrails=[
        TokenBudgetGuardrail(max_tokens=50000),
        CostLimitGuardrail(max_cost_usd=5.0),
        IterationLimitGuardrail(max_iterations=20),
    ],
    mode="strict",  # or "permissive"
)
```

**Modes:**
- **`strict`**: Raises `GuardrailViolation` immediately on first violation
- **`permissive`**: Logs violations but continues execution

**Methods:**
- `check_all(context)`: Check all guardrails against current context
- `get_summary()`: Get summary of violations and checks
- `reset()`: Reset violation history

**Example Usage:**
```python
from pydantic_deep.guardrails import GuardrailContext, ToolCall

# Create context from agent state
context = GuardrailContext(
    agent_name="my-agent",
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
    print(f"All checks passed: {all(r.passed for r in results)}")
except GuardrailViolation as e:
    print(f"Guardrail violated: {e}")

# Get summary
summary = manager.get_summary()
print(f"Total violations: {summary['violations']}")
```

## Factory Functions

### create_safe_agent_guardrails

Creates a safe set of default guardrails for development.

```python
from pydantic_deep.guardrails import create_safe_agent_guardrails

guardrails = create_safe_agent_guardrails(
    max_tokens=100000,
    max_cost_usd=10.0,
    max_iterations=20,
)
```

**Includes:**
- `TokenBudgetGuardrail` with 80% warning threshold
- `CostLimitGuardrail` with 70% warning threshold
- `IterationLimitGuardrail`
- `ToolLoopDetectionGuardrail`

### create_production_guardrails

Creates production-grade guardrails with comprehensive safety checks.

```python
from pydantic_deep.guardrails import create_production_guardrails

guardrails = create_production_guardrails(
    max_tokens=200000,
    max_cost_usd=50.0,
    custom_validators=[my_custom_validator],
)
```

**Includes:**
- All guardrails from `create_safe_agent_guardrails`
- `ToolChainValidationGuardrail` with common dangerous sequences
- `OutputValidationGuardrail` with secret/PII detection

## Usage Scenarios

### Scenario 1: Prevent Runaway Costs

```python
from pydantic_deep.guardrails import CostLimitGuardrail, TokenBudgetGuardrail, GuardrailManager

guardrails = [
    CostLimitGuardrail(max_cost_usd=10.0, warn_at=0.7),
    TokenBudgetGuardrail(max_tokens=50000, warn_at=0.8),
]

manager = GuardrailManager(guardrails, mode="strict")
deps = DeepAgentDeps(backend=StateBackend(), guardrail_manager=manager)
```

### Scenario 2: Prevent Infinite Loops

```python
from pydantic_deep.guardrails import IterationLimitGuardrail, ToolLoopDetectionGuardrail

guardrails = [
    IterationLimitGuardrail(max_iterations=15),
    ToolLoopDetectionGuardrail(window_size=5, max_repeats=3),
]

manager = GuardrailManager(guardrails, mode="strict")
```

### Scenario 3: Validate Output Safety

```python
from pydantic_deep.guardrails import OutputValidationGuardrail, validate_no_secrets, redact_secrets

guardrails = [
    OutputValidationGuardrail(
        validators=[validate_no_secrets],
        on_fail="sanitize",
        sanitizer=redact_secrets,
    ),
]

manager = GuardrailManager(guardrails, mode="strict")
```

### Scenario 4: Production-Safe Agent

```python
from pydantic_deep.guardrails import create_production_guardrails, GuardrailManager

guardrails = create_production_guardrails(
    max_tokens=200000,
    max_cost_usd=50.0,
)

manager = GuardrailManager(guardrails, mode="strict")
deps = DeepAgentDeps(
    backend=FilesystemBackend(root="/workspace"),
    guardrail_manager=manager,
)
```

## Custom Guardrails

Implement the `GuardrailProtocol` to create custom guardrails:

```python
from pydantic_deep.guardrails import GuardrailProtocol, GuardrailContext, GuardrailResult

class TimeLimitGuardrail:
    """Prevent agent from running too long."""

    def __init__(self, max_seconds: float):
        self.max_seconds = max_seconds

    def check(self, context: GuardrailContext) -> GuardrailResult:
        if context.duration_seconds > self.max_seconds:
            return GuardrailResult(
                passed=False,
                message=f"Time limit exceeded: {context.duration_seconds:.1f}s > {self.max_seconds}s",
            )
        return GuardrailResult(passed=True)

    def on_violation(self, context: GuardrailContext) -> None:
        # Optional: custom handling on violation
        print(f"Time limit violated for agent {context.agent_name}")

# Use custom guardrail
manager = GuardrailManager([TimeLimitGuardrail(max_seconds=60.0)])
```

## Integration with Tracing

Guardrails work seamlessly with the tracing system to provide visibility into safety violations:

```python
from pydantic_deep import create_deep_agent, DeepAgentDeps
from pydantic_deep.guardrails import create_safe_agent_guardrails, GuardrailManager
from pydantic_deep.tracing import TraceContext, ConsoleExporter
from pydantic_ai_backends import StateBackend

# Set up tracing
trace_ctx = TraceContext(exporters=[ConsoleExporter(verbose=True)])

# Set up guardrails
guardrails = create_safe_agent_guardrails()
manager = GuardrailManager(guardrails, mode="permissive")

# Create deps with both
deps = DeepAgentDeps(
    backend=StateBackend(),
    trace_context=trace_ctx,
    guardrail_manager=manager,
)

agent = create_deep_agent()

with trace_ctx.agent_run("my-agent", "Task", "gpt-4o"):
    try:
        result = await agent.run("Do something", deps=deps)
    except GuardrailViolation as e:
        print(f"Guardrail prevented execution: {e}")

# Check for violations
summary = manager.get_summary()
if summary["violations"] > 0:
    print(f"Warning: {summary['violations']} guardrail violations occurred")
    print(f"Violation types: {summary['violation_types']}")
```

## Best Practices

1. **Always use guardrails in production** - Prevents catastrophic failures and cost overruns
2. **Start with safe defaults** - Use `create_safe_agent_guardrails()` for development
3. **Use strict mode for critical systems** - Ensures violations stop execution immediately
4. **Monitor violations in permissive mode** - Collect data on near-violations for tuning
5. **Combine with tracing** - Get full visibility into guardrail checks and violations
6. **Validate output in production** - Always use `OutputValidationGuardrail` to prevent leaking secrets
7. **Test your guardrails** - Ensure they trigger under the expected conditions
8. **Set realistic limits** - Base token/cost limits on actual usage patterns

## Advanced Usage

### Dynamic Guardrail Adjustment

```python
# Adjust guardrails based on task complexity
def create_task_specific_guardrails(task_type: str):
    if task_type == "simple":
        return create_safe_agent_guardrails(
            max_tokens=10000,
            max_cost_usd=1.0,
            max_iterations=10,
        )
    elif task_type == "complex":
        return create_safe_agent_guardrails(
            max_tokens=100000,
            max_cost_usd=10.0,
            max_iterations=50,
        )
    else:
        return create_production_guardrails()
```

### Guardrail Metrics Collection

```python
# Collect metrics on guardrail violations
violations_by_type = {}

class MetricsGuardrailManager(GuardrailManager):
    def check_all(self, context):
        results = super().check_all(context)
        for result in results:
            if not result.passed:
                guardrail_type = type(result).__name__
                violations_by_type[guardrail_type] = violations_by_type.get(guardrail_type, 0) + 1
        return results
```

## API Reference

See the [API documentation](api/guardrails.md) for detailed information on all guardrail classes and functions.
