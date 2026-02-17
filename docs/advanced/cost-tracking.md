# Cost Tracking

pydantic-deep tracks token usage and USD costs automatically using `CostTrackingMiddleware` from [pydantic-ai-middleware](https://github.com/vstorm-co/pydantic-ai-middleware). Cost tracking is **enabled by default**.

!!! tip "Requires middleware"
    Cost tracking uses `pydantic-ai-middleware` with `genai-prices` for pricing data. Install with:
    ```bash
    pip install pydantic-deep[middleware]
    ```

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
from pydantic_ai_middleware import CostInfo

def on_cost(info: CostInfo):
    print(f"Run cost: ${info.run_cost_usd:.4f}")
    print(f"Total: ${info.cumulative_cost_usd:.4f}")
    print(f"Tokens: {info.run_input_tokens} in / {info.run_output_tokens} out")

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
| `run_input_tokens` | `int` | Input tokens for this run |
| `run_output_tokens` | `int` | Output tokens for this run |
| `run_cost_usd` | `float` | USD cost for this run |
| `cumulative_input_tokens` | `int` | Total input tokens across all runs |
| `cumulative_output_tokens` | `int` | Total output tokens across all runs |
| `cumulative_cost_usd` | `float` | Total USD cost across all runs |

## How It Works

1. `CostTrackingMiddleware` wraps the agent via `MiddlewareAgent`
2. After each run, it reads `result.usage()` for token counts
3. Token costs are calculated using `genai-prices` (model-specific pricing)
4. `CostInfo` is passed to the `on_cost_update` callback
5. If `cumulative_cost_usd` exceeds `cost_budget_usd`, subsequent runs raise `BudgetExceededError`

## Next Steps

- [Middleware](middleware.md) — Middleware system and permissions
- [Context Manager](processors.md) — Token tracking and auto-compression
- [Agents](../concepts/agents.md) — Full agent configuration
