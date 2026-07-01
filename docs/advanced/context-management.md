# Context management

Long runs fill up. An agent that greps a huge file, reads a dozen sources, and plans a multi-step task will happily blow past the model's context window — and then the run fails. pydantic-deep keeps that from happening for you, automatically, from the first line.

## It's already on

You don't have to do anything to get this:

```python
from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend

agent = create_deep_agent(model="anthropic:claude-sonnet-4-6")

deps = DeepAgentDeps(backend=StateBackend())
result = await agent.run("Research the FastAPI request lifecycle and summarize it.", deps=deps)
print(result.output)
```

That agent can run for dozens of turns without overflowing. Behind the scenes, three layers are working together — and every one of them is a default.

!!! tip "The short version"
    `context_manager=True` and `eviction_token_limit=20_000` are both on by
    default. For most apps, that's the whole story — you can stop reading here
    and come back when you want to tune it.

## How it works

Think of it as a stack of three guards, each catching a different kind of bloat before it reaches the model.

**1. The context manager — watches the whole conversation.**
The `ContextManagerCapability` counts tokens before every model request, reports usage through a callback, and when the conversation crosses a threshold (default 90% of the token budget) it summarizes older messages with a lightweight LLM call. Recent turns stay verbatim; the early history collapses into a summary. This is the smart, high-level layer — it answers *"are we running out of room?"*

**2. Eviction — catches one oversized tool result.**
A single `grep` or `read_file` can return 50,000 characters in one shot. The [`EvictionCapability`][pydantic_deep.features.eviction.EvictionCapability] intercepts any tool output over the threshold (default 20,000 tokens) *before* it enters the history, writes the full output to a file in your backend, and leaves a head/tail preview plus the file path in its place. The agent can `read_file` with `offset`/`limit` to pull back exactly the part it needs. The giant blob never sits in memory. See [Eviction](context-management.md) for the full walkthrough.

**3. History processors — transform the message list.**
These are low-level passes applied to the messages right before each model request. They don't decide anything — they just reshape the list. Two run by default (eviction and tool-call patching), and you can add your own: a **summarization processor** for intelligent compression, or a **sliding-window processor** for zero-cost trimming.

!!! info "Complementary, not competing"
    The context manager and history processors run *together*. The context
    manager handles the big "are we out of space?" question; processors handle
    "clean up the data before it goes out." You can rely on the defaults, add
    processors, or both.

## Watch it happen

The context manager reports usage on every request. Hook into it to drive a progress bar, log, or status line:

```python hl_lines="4"
agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    context_manager_max_tokens=128_000,
    on_context_update=lambda pct, current, maximum: print(f"Context: {pct:.0%} ({current}/{maximum})"),
)
```

`on_context_update` fires with `(percentage, current_tokens, max_tokens)` before each model call. When `percentage` climbs past the compression threshold, summarization kicks in automatically — you'll see the token count drop on the next callback.

!!! example "Check it"
    Run a long task with the callback above and watch the numbers. You'll see
    the percentage rise, then fall after a compaction — the agent kept going,
    you never touched it.

## Tuning it

The defaults are good, but you can dial in every layer.

### Add a summarization processor

For explicit control over *when* and *how much* to compress, attach a `create_summarization_processor`:

```python
from pydantic_deep import create_deep_agent, create_summarization_processor

processor = create_summarization_processor(
    trigger=("tokens", 100_000),  # summarize when history hits 100k tokens
    keep=("messages", 20),        # keep the last 20 messages verbatim
)

agent = create_deep_agent(history_processors=[processor])
```

Triggers can be `("tokens", N)`, `("messages", N)`, or `("fraction", 0.8)` (needs `max_input_tokens`). Pass a list of triggers and *any* of them fires. The processor always finds a safe cutoff that never splits a tool call from its response.

### Or trim for free with a sliding window

When you don't need to remember earlier turns, `create_sliding_window_processor` drops old messages with no LLM call — instant and costless:

```python
from pydantic_deep import create_sliding_window_processor

processor = create_sliding_window_processor(
    trigger=("messages", 100),  # once the history hits 100 messages
    keep=("messages", 50),      # keep the most recent 50
)

agent = create_deep_agent(history_processors=[processor])
```

Reach for summarization when earlier decisions matter; reach for the sliding window when only recent context counts (high-volume chat, throwaway sessions).

### Tune eviction

Raise the bar before tool outputs get evicted to files, or turn it off entirely:

```python
agent = create_deep_agent(eviction_token_limit=50_000)  # evict only above 50k tokens
agent = create_deep_agent(eviction_token_limit=None)     # disable eviction
```

### Tune (or disable) the context manager

```python
agent = create_deep_agent(
    context_manager=True,
    context_manager_max_tokens=128_000,  # default: auto-detected from the model
)

agent = create_deep_agent(context_manager=False)  # off
```

!!! warning "One context manager at a time"
    If you build a `ContextManagerCapability` yourself and pass it via
    `capabilities=[...]`, also set `context_manager=False` so you don't run two
    of them. Same idea applies anywhere you take manual control of a default layer.

## Recap

- **It's on by default.** `context_manager=True` and `eviction_token_limit=20_000` keep long runs from overflowing with zero configuration.
- **Three layers, three jobs.** The context manager summarizes the conversation near the budget; eviction parks oversized tool outputs in files; history processors reshape the message list before each request.
- **Watch it live.** `on_context_update(pct, current, max)` fires before every model call — wire it to a status display.
- **Tune what you need.** Add `create_summarization_processor` for smart compression, `create_sliding_window_processor` for free trimming, or adjust `eviction_token_limit` and `context_manager_max_tokens`.

Where to go next:

- [Eviction →](context-management.md) — the deep dive on oversized tool outputs
- [History processors →](context-management.md) — every processor option and how they chain
- [Cost tracking & budgets →](cost-tracking.md) — keep tokens and dollars in check
- [Capabilities & lifecycle →](capabilities.md) — how these layers plug into the agent
