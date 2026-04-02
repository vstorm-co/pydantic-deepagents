# Cost Tracking

pydantic-deep tracks token usage and USD costs automatically using `CostTracking` from [pydantic-ai-shields](https://github.com/vstorm-co/pydantic-ai-shields). Cost tracking is **enabled by default** and is implemented as a pydantic-ai capability.

## Quick Start

```python
from pydantic_deep import create_deep_agent

# Cost tracking is ON by default
agent = create_deep_agent()

# Disable cost tracking
agent = create_deep_agent(cost_tracking=False)
```

## Budget Limits

Set a maximum cumulative cost. When exceeded, the next run raises `BudgetExceededError`:

```python
agent = create_deep_agent(
    cost_budget_usd=5.00,  # $5 budget
)
```

## Cost Update Callback

Monitor costs in real-time:

```python
from pydantic_ai_shields import CostInfo

def on_cost(info: CostInfo):
    print(f"Run cost: ${info.run_cost_usd:.4f}")
    print(f"Total: ${info.total_cost_usd:.4f}")
    print(f"Tokens: {info.run_request_tokens} in / {info.run_response_tokens} out")

agent = create_deep_agent(
    on_cost_update=on_cost,
    cost_budget_usd=10.00,
)
```

## Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `cost_tracking` | `bool` | `True` | Enable automatic cost tracking |
| `cost_budget_usd` | `float \| None` | `None` | Maximum cumulative cost in USD |
| `on_cost_update` | `Callable \| None` | `None` | Callback after each run with `CostInfo` |

## CostInfo Fields

The `CostInfo` dataclass provides both per-run and cumulative metrics:

| Field | Type | Description |
|-------|------|-------------|
| `run_cost_usd` | `float \| None` | USD cost for this run (None if model pricing unknown) |
| `total_cost_usd` | `float \| None` | Cumulative USD cost across all runs (None if model pricing unknown) |
| `run_request_tokens` | `int` | Input tokens for this run |
| `run_response_tokens` | `int` | Output tokens for this run |
| `total_request_tokens` | `int` | Total input tokens across all runs |
| `total_response_tokens` | `int` | Total output tokens across all runs |
| `run_count` | `int` | Number of completed runs so far |

## Standalone Usage

You can use `CostTracking` directly as a capability with any pydantic-ai agent:

```python
from pydantic_ai import Agent
from pydantic_ai_shields import CostTracking

tracking = CostTracking(
    model_name="anthropic:claude-sonnet-4-6",
    budget_usd=5.0,
)

agent = Agent("anthropic:claude-sonnet-4-6", capabilities=[tracking])

result = await agent.run("Hello")
print(f"Cost so far: ${tracking.total_cost:.4f}")
print(f"Total tokens: {tracking.total_request_tokens} in / {tracking.total_response_tokens} out")
```

### CostTracking Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model_name` | `str \| None` | `None` | Model name for cost lookup (e.g. `"anthropic:claude-sonnet-4-6"`). Auto-detected if None. |
| `budget_usd` | `float \| None` | `None` | Maximum allowed cumulative cost. None = unlimited. |
| `on_cost_update` | `CostCallback` | `None` | Callback invoked after each run with `CostInfo`. |

## How It Works

1. `CostTracking` is an `AbstractCapability` that hooks into the agent run lifecycle
2. On the first run, it resolves per-token pricing from `genai-prices` (model-specific pricing database)
3. After each run, it reads `result.usage()` for token counts and calculates costs
4. `CostInfo` is passed to the `on_cost_update` callback
5. If cumulative cost exceeds `budget_usd`, subsequent runs raise `BudgetExceededError`

The capability accumulates state across runs via internal fields (`_total_request_tokens`, `_total_response_tokens`, `_total_cost_usd`), so the same `CostTracking` instance tracks the full session.

## Next Steps

- [Capabilities](middleware.md) -- Capabilities system overview
- [Context Manager](processors.md) -- Token tracking and auto-compression
- [Agents](../concepts/agents.md) -- Full agent configuration
