# pydantic-deep Examples

This directory contains example scripts demonstrating the features of pydantic-deep.

## Observability & Tracing Examples

### `basic_tracing.py`

Demonstrates the agent observability and tracing system:

- Basic tracing with console output
- Using multiple exporters simultaneously
- Manual tracing for custom operations
- Getting trace summaries and statistics

**Run:**
```bash
python examples/basic_tracing.py
```

**Key Features:**
- `TraceContext` for collecting trace events
- `ConsoleExporter` for visual feedback
- `InMemoryExporter` for programmatic analysis
- Event filtering and hierarchical tree views

## Guardrails & Safety Examples

### `basic_guardrails.py`

Demonstrates the guardrails and safety gates system:

- Using safe agent guardrails
- Individual guardrail examples (token budget, cost limit, iteration limit, loop detection)
- Permissive vs strict mode
- Output validation and secret sanitization

**Run:**
```bash
python examples/basic_guardrails.py
```

**Key Features:**
- `GuardrailManager` for coordinating multiple guardrails
- Built-in guardrails (token budget, cost limit, iteration limit, etc.)
- Strict mode (raises on violation) vs permissive mode (logs violations)
- Output validation with automatic sanitization

## Combined Examples

### `combined_tracing_guardrails.py`

Demonstrates using tracing and guardrails together:

- Combined observability and safety
- Capturing guardrail violations in traces
- Production-ready agent configuration
- Writing traces to structured files

**Run:**
```bash
python examples/combined_tracing_guardrails.py
```

**Key Features:**
- Using both `TraceContext` and `GuardrailManager` together
- Monitoring agent execution with full safety
- Production-grade configuration
- File-based trace persistence

## Common Patterns

### Setting Up Tracing

```python
from pydantic_deep.tracing import TraceContext, ConsoleExporter

trace_ctx = TraceContext(exporters=[ConsoleExporter(verbose=True)])

deps = DeepAgentDeps(
    backend=StateBackend(),
    trace_context=trace_ctx,
)

with trace_ctx.agent_run("my-agent", "Task description", "model-name"):
    result = await agent.run("Do something", deps=deps)

summary = trace_ctx.get_summary()
```

### Setting Up Guardrails

```python
from pydantic_deep.guardrails import (
    create_safe_agent_guardrails,
    GuardrailManager,
)

guardrails = create_safe_agent_guardrails(
    max_tokens=100000,
    max_cost_usd=10.0,
    max_iterations=20,
)

manager = GuardrailManager(guardrails, mode="strict")

deps = DeepAgentDeps(
    backend=StateBackend(),
    guardrail_manager=manager,
)
```

### Combined Setup

```python
from pydantic_deep import DeepAgentDeps, create_deep_agent
from pydantic_deep.guardrails import create_safe_agent_guardrails, GuardrailManager
from pydantic_deep.tracing import TraceContext, ConsoleExporter

# Set up tracing
trace_ctx = TraceContext(exporters=[ConsoleExporter()])

# Set up guardrails
guardrails = create_safe_agent_guardrails()
manager = GuardrailManager(guardrails, mode="strict")

# Create deps with both
deps = DeepAgentDeps(
    backend=StateBackend(),
    trace_context=trace_ctx,
    guardrail_manager=manager,
)

# Run agent with full monitoring and safety
agent = create_deep_agent()
with trace_ctx.agent_run("my-agent", "Task", "model"):
    result = await agent.run("Do something", deps=deps)
```

## Production Recommendations

For production use:

1. **Use `create_production_guardrails()`** - Comprehensive safety with secret detection
2. **Enable tracing with `StructuredFileExporter`** - Persistent trace storage
3. **Use strict mode for guardrails** - Fail fast on violations
4. **Monitor trace summaries** - Track token usage and performance
5. **Set realistic limits** - Base on actual usage patterns

Example production configuration:

```python
from pydantic_deep.guardrails import create_production_guardrails
from pydantic_deep.tracing import TraceContext, StructuredFileExporter

# Production tracing
trace_ctx = TraceContext(exporters=[
    StructuredFileExporter("logs/traces.jsonl"),
])

# Production guardrails
guardrails = create_production_guardrails(
    max_tokens=200000,
    max_cost_usd=50.0,
)
manager = GuardrailManager(guardrails, mode="strict")

# Create production deps
deps = DeepAgentDeps(
    backend=FilesystemBackend(root="/workspace"),
    trace_context=trace_ctx,
    guardrail_manager=manager,
)
```

## Additional Resources

- [Tracing Documentation](../docs/tracing.md)
- [Guardrails Documentation](../docs/guardrails.md)
- [API Reference](../docs/api/)
