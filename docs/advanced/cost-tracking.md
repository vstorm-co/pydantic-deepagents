# Cost tracking & budgets

An autonomous agent can make a *lot* of model calls in a single run — plan, write, read, summarize, retry. Each one costs money, and a runaway loop can quietly burn through your account. So pydantic-deep keeps a running tally for you, and lets you set a hard ceiling.

You don't wire any of it up. Cost tracking is **on by default**.

```python hl_lines="9 10 11"
import asyncio

from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend


async def main():
    agent = create_deep_agent(model="anthropic:claude-sonnet-4-6")

    result = await agent.run("Summarize what a vector database is.", deps=DeepAgentDeps(backend=StateBackend()))

    info = agent.cost_info
    print(f"This run: ${info.run_cost_usd:.4f}")
    print(f"Tokens: {info.run_request_tokens} in / {info.run_response_tokens} out")


asyncio.run(main())
```

## Run it

Save it to `main.py` and run:

<div class="termy">

```console
$ python main.py
This run: $0.0123
Tokens: 1843 in / 412 out
```

</div>

The agent ran exactly as before — you added nothing to its setup. The token counts and dollar figure were recorded for you automatically, ready to read the moment the run finished.

!!! example "Check it"
    Run the same agent twice in a row, reusing the same `agent`. Print
    `info.total_cost_usd` and `info.run_count` after the second run — the totals
    keep climbing while `run_cost_usd` only reflects the latest run.

## Step by step

### It's already on

```python
agent = create_deep_agent(model="anthropic:claude-sonnet-4-6")
```

Every agent created with [`create_deep_agent()`][pydantic_deep.agent.create_deep_agent] gets a [`CostTracking`](https://github.com/vstorm-co/pydantic-ai-shields) capability attached for free. It's a Pydantic AI capability that hooks into the run lifecycle — no toolset, no callback, no boilerplate.

If you don't want it, turn it off:

```python
agent = create_deep_agent(cost_tracking=False)
```

### Read the cost after a run

```python
info = agent.cost_info
print(f"This run: ${info.run_cost_usd:.4f}")
```

After each run, the capability reads `result.usage()` for the raw token counts and prices them using [`genai-prices`](https://github.com/pydantic/genai-prices) — a model-specific pricing database. The result is a `CostInfo` carrying both **this run** and the **cumulative** totals:

| Field | What it tells you |
|-------|-------------------|
| `run_cost_usd` | USD cost of the latest run (`None` if the model's pricing is unknown) |
| `total_cost_usd` | Cumulative USD across every run on this agent |
| `run_request_tokens` / `run_response_tokens` | Input / output tokens for the latest run |
| `total_request_tokens` / `total_response_tokens` | Input / output tokens across all runs |
| `run_count` | How many runs have completed |

!!! note "`None` is a real answer"
    If `genai-prices` has no entry for your model, the *token* counts are still
    accurate but the *USD* fields come back `None`. Format defensively when you
    display them.

### Set a budget

This is the part that protects you. Pass a cumulative ceiling in dollars:

```python hl_lines="2"
agent = create_deep_agent(
    cost_budget_usd=5.00,
)
```

The capability accumulates cost across every run on this agent. Once the cumulative total crosses `$5.00`, the **next** run raises `BudgetExceededError` instead of calling the model. Catch it where you drive the agent:

```python
from pydantic_ai_shields import BudgetExceededError

try:
    result = await agent.run("Keep researching...", deps=deps)
except BudgetExceededError:
    print("Budget spent — stopping here.")
```

!!! warning "The budget is cumulative, not per-run"
    `cost_budget_usd` caps the *total* spend across the lifetime of the agent
    instance, not any single run. A fresh `create_deep_agent()` starts the meter
    at zero again.

### Watch costs live

Want to react after every run — log it, update a UI, stop early? Pass a callback:

```python hl_lines="6"
from pydantic_ai_shields import CostInfo


def on_cost(info: CostInfo) -> None:
    print(f"Run: ${info.run_cost_usd:.4f}  Total: ${info.total_cost_usd:.4f}")


agent = create_deep_agent(
    on_cost_update=on_cost,
    cost_budget_usd=10.00,
)
```

`on_cost_update` fires once per run with the same `CostInfo` you'd read from `agent.cost_info`.

## Using it standalone

`CostTracking` is just a Pydantic AI capability, so you can attach it to a plain `Agent` too — handy when you're not using the deep-agent factory:

```python
from pydantic_ai import Agent
from pydantic_ai_shields import CostTracking

tracking = CostTracking(
    model_name="anthropic:claude-sonnet-4-6",
    budget_usd=5.0,
)
agent = Agent("anthropic:claude-sonnet-4-6", capabilities=[tracking])

await agent.run("Hello")
print(f"Cost so far: ${tracking.total_cost:.4f}")
```

The same instance accumulates state across runs, so it tracks the full session.

## Recap

- Cost tracking is **on by default** — `create_deep_agent()` attaches `CostTracking` for you. Disable with `cost_tracking=False`.
- Read `agent.cost_info` after a run for a `CostInfo` with per-run *and* cumulative tokens and USD.
- Pricing comes from `genai-prices`; unknown models still report tokens but leave the USD fields `None`.
- `cost_budget_usd=...` sets a hard cumulative ceiling — crossing it raises `BudgetExceededError` before the next model call.
- `on_cost_update=...` gives you a per-run callback to log, display, or stop early.

Where to go next:

- [Capabilities & lifecycle](capabilities.md) — how capabilities like this one hook into a run.
- [Context management](context-management.md) — keep token usage (and cost) down as conversations grow.
- [Stuck-loop detection](stuck-loop-detection.md) — stop the kind of repetition that runs up a bill.
