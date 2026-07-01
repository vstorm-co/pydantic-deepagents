# Fallback models

When a provider hiccups — a rate limit, a 5xx, a timeout — you don't want the whole run to die. Give your agent a backup model, and it keeps going on the next one in line.

## Add a backup model

Here's the smallest version: one primary, one fallback.

```python hl_lines="5"
from pydantic_deep import create_deep_agent

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    fallback_model="anthropic:claude-haiku-4-5-20251001",
)
```

That's it. Run the agent the way you always do. If `claude-sonnet-4-6` raises a transient API error mid-run, the agent retries the same step on `claude-haiku-4-5-20251001` instead of raising — and the conversation continues, it doesn't restart.

!!! info "What's happening under the hood"
    `fallback_model=` wraps your primary in Pydantic AI's
    [`FallbackModel`][pydantic_ai.models.fallback.FallbackModel]. Without it, a
    transient error from the provider propagates straight out of `agent.run()`
    and the run ends. With it, the error becomes a cue to try the next model.

## Build a chain

One backup is good. An ordered chain is better — pass a list and the agent walks it top to bottom until one model answers.

```python hl_lines="5 6 7 8"
agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    fallback_model=[
        "anthropic:claude-haiku-4-5-20251001",
        "openai:gpt-4o-mini",
    ],
)
```

Sonnet is tried first. If it fails, Haiku. If Haiku fails too, GPT-4o-mini. Only when every model in the chain has failed does the run raise. `fallback_model=` accepts a model string, a `Model` instance, or a list mixing both — so you can span providers freely.

!!! tip "Pin model versions in production"
    The examples use date-suffixed IDs like `claude-haiku-4-5-20251001`. Pin them
    explicitly in production so a provider silently re-tagging an unversioned alias
    can't quietly change how your chain behaves.

## What triggers a fallback — and what doesn't

This is the important part, so let's be precise. A fallback fires only when the error is a [`ModelAPIError`][pydantic_ai.exceptions.ModelAPIError] **and** its message looks transient. Concretely, that covers:

- Rate limits (HTTP 429)
- Server errors (HTTP 5xx)
- Provider outages and timeouts surfaced as `ModelAPIError`

It deliberately does **not** fire on:

- **Auth and permission errors** — anything whose message contains `401`, `403`, `unauthorized`, or `forbidden` (case-insensitive). These are permanent: a bad key fails on every model in the chain, so retrying is pointless. The original exception is re-raised untouched.
- **`ModelRetry`** — tool-driven retries are Pydantic AI's job and are handled long before the fallback layer sees them.
- **`BudgetExceededError`** from [cost tracking](cost-tracking.md) — not a `ModelAPIError`, so it propagates as-is.
- **Validation errors** and any other non-`ModelAPIError` exception.

!!! warning "Auth detection is substring-based"
    The auth filter matches `401` / `403` / `unauthorized` / `forbidden` in the
    exception message. A provider that phrases auth failures differently could slip
    through and trigger a needless fallback. If you hit that, open an issue with the
    exact message.

## Know when it happened

A silent fallback is a fallback you'll forget about until the bill arrives. Wire up the `MODEL_FALLBACK_TRIGGERED` [hook event](hooks.md) to log or alert every time the agent switches models.

```python hl_lines="11"
from pydantic_deep import create_deep_agent
from pydantic_deep.features.hooks import Hook, HookEvent, HookInput, HookResult


async def on_fallback(inp: HookInput) -> HookResult:
    primary = inp.tool_input["primary"]
    fallback = inp.tool_input["fallback"]
    print(f"Model fallback: {primary} → {fallback} (error: {inp.tool_error})")
    return HookResult()


agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    fallback_model="anthropic:claude-haiku-4-5-20251001",
    hooks=[Hook(event=HookEvent.MODEL_FALLBACK_TRIGGERED, handler=on_fallback)],
)
```

The `HookInput` you receive carries:

| Field | Value |
|-------|-------|
| `tool_input["primary"]` | Name of the primary model |
| `tool_input["fallback"]` | Name of the **first** fallback in the chain |
| `tool_error` | The stringified error message (`str(exc)`), not the exception object |

!!! note "The `fallback` field names the chain, not the hop"
    For a chain `[A, B, C]`, the hook always reports `fallback=A`, no matter which
    hop is actually in flight (A→B, B→C, …). It tells you *that* a fallback
    happened and which chain owns it — for per-hop detail, lean on `tool_error`
    and your provider's own telemetry.

## In the CLI

Using the terminal assistant? Run `/model` to pick a primary. A second prompt then offers an optional fallback (or "No fallback"). Both choices are saved to `.pydantic-deep/config.toml` and applied automatically on every later run.

## A couple of things to keep in mind

**Costs accumulate across the chain.** Every model you fall through to bills separately. The [`CostTracking`](cost-tracking.md) capability sums tokens and USD across all of them, and `cost_budget_usd` is enforced against that cumulative total — fallbacks don't get their own budget.

**`agent.model` reports the wrapper.** Once you set a fallback, `agent.model` is the `FallbackModel`, not whichever underlying model actually answered. To learn which model handled a given response, use the `MODEL_FALLBACK_TRIGGERED` hook or provider-level telemetry.

## Recap

- `fallback_model=` keeps a run alive by retrying transient provider failures on a backup model instead of raising.
- Pass a single model for one backup, or a list for an ordered chain across providers — string or `Model`, mixed freely.
- Only transient `ModelAPIError`s trigger a fallback; auth errors (401/403/unauthorized/forbidden), `ModelRetry`, budget errors, and validation errors all propagate untouched.
- Message history carries across the hop — the backup continues the conversation, it doesn't restart it.
- The `MODEL_FALLBACK_TRIGGERED` hook event lets you log and alert on every switch.

Next, see how to react to model and tool events more broadly:

- [Hooks →](hooks.md)
- [Cost tracking & budgets →](cost-tracking.md)
