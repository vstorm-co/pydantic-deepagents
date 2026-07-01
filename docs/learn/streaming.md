# Streaming

A real agent run takes a while — it plans, calls tools, thinks, writes. Awaiting one `agent.run()` gives you the answer, but the screen sits frozen until it lands. Streaming lets you watch the work happen instead: tokens as they're generated, tool calls as they fire, thinking as it unfolds.

You stream by iterating over **events** as the run progresses, rather than awaiting one final result.

```python
import asyncio

from pydantic_ai import (
    AgentRunResultEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
)

from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend


async def main():
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        instructions="You are a helpful coding assistant.",
    )

    deps = DeepAgentDeps(backend=StateBackend())

    async for event in agent.run_stream_events(
        "Write a Python function that returns the nth Fibonacci number, "
        "save it to fib.py, then read it back to me.",
        deps=deps,
    ):
        if isinstance(event, PartDeltaEvent):
            if hasattr(event.delta, "content_delta"):
                print(event.delta.content_delta, end="", flush=True)

        elif isinstance(event, FunctionToolCallEvent):
            print(f"\n[tool] {event.part.tool_name}", flush=True)

        elif isinstance(event, AgentRunResultEvent):
            print(f"\n\nDone. Files: {sorted(event.result.deps.files)}")


asyncio.run(main())
```

## Run it

Save it to `main.py` and run:

<div class="termy">

```console
$ python main.py
```

</div>

Instead of one silent pause, you'll see the answer typing itself out, with the agent's tool calls interleaved as they happen:

```
[tool] write_todos
[tool] write_file
[tool] read_file
Done! I wrote fib.py with a function that returns the nth Fibonacci number,
then read it back. Here's what it contains:

def fib(n): ...
[tool] (none)

Done. Files: ['fib.py']
```

Same agent, same prompt as [Your first agent](first-agent.md) — you just watched it work instead of waiting for it to finish.

## Step by step

Let's look at the streaming loop one piece at a time.

### Step 1: ask for events instead of a result

```python hl_lines="1"
async for event in agent.run_stream_events(prompt, deps=deps):
    ...
```

`run_stream_events()` returns an async iterator. Where `agent.run()` hands back a single `AgentRunResult` at the end, this yields a typed `event` for every small thing that happens along the way — and you `async for` over them.

### Step 2: print text as it's generated

```python hl_lines="2 3"
if isinstance(event, PartDeltaEvent):
    if hasattr(event.delta, "content_delta"):
        print(event.delta.content_delta, end="", flush=True)
```

A `PartDeltaEvent` carries a *delta* — one more chunk of a part the model is building. For text, `event.delta.content_delta` is the next snippet of the answer. Print it with `end=""` and `flush=True` and the reply appears token by token, exactly like a chat UI.

### Step 3: see tool calls as they fire

```python hl_lines="1 2"
elif isinstance(event, FunctionToolCallEvent):
    print(f"\n[tool] {event.part.tool_name}")
```

When the agent decides to act — write a file, update its todos, search the web — you get a `FunctionToolCallEvent` *before* the tool runs. `event.part.tool_name` tells you which one, and `event.part.args` holds the arguments. There's a matching `FunctionToolResultEvent` once the tool returns, with `event.result.content`.

### Step 4: grab the final result

```python hl_lines="1 2"
elif isinstance(event, AgentRunResultEvent):
    print(event.result.output)
```

The very last event is an `AgentRunResultEvent`. Its `event.result` is the same `AgentRunResult` you'd get from `agent.run()` — so `event.result.output`, `event.result.usage()`, and `event.result.deps` are all there when the stream ends.

## Watching the agent think

Reasoning models emit their thinking as its own kind of part. It arrives as `PartDeltaEvent`s too — just with a *thinking* delta instead of a content delta:

```python hl_lines="3 4"
if isinstance(event, PartDeltaEvent):
    if hasattr(event.delta, "content_delta"):
        print(event.delta.content_delta, end="", flush=True)
    elif hasattr(event.delta, "thinking_delta"):
        print(f"\033[2m{event.delta.thinking_delta}\033[0m", end="", flush=True)
```

Now the model's reasoning streams in dim text and its actual answer streams in normal text — the same split you see in a polished assistant UI.

!!! tip "Nodes vs. events"
    There are two granularities. `agent.run_stream_events()` (used here) gives
    fine-grained **events** — text deltas, thinking, individual tool calls —
    ideal for a live UI. `agent.iter()` gives coarser **nodes**, one per step of
    the run, which is handy for a simple progress indicator. Reach for events
    when you want the typing-it-out feel.

!!! note "The result is only there at the end"
    `run.result` (with `iter()`) and `AgentRunResultEvent` (with events) are only
    available once the stream finishes. Don't try to read the output mid-stream —
    collect deltas as they arrive, or wait for the final event.

!!! warning "Handle every event type"
    Don't assume an order. A run interleaves thinking, text, and many tool
    calls, and new event types can appear. Match the ones you care about and let
    the rest fall through — never index into `event` assuming it's the kind you
    expect.

## Recap

You turned a silent wait into a live view of the agent at work:

- `agent.run_stream_events(prompt, deps=deps)` yields typed events as the run unfolds — `async for` over them instead of awaiting one result.
- `PartDeltaEvent` carries incremental output: `content_delta` for the answer, `thinking_delta` for reasoning. Print with `flush=True` for the typing effect.
- `FunctionToolCallEvent` and `FunctionToolResultEvent` surface tool calls as they fire and return.
- `AgentRunResultEvent` is the last event; `event.result` is the same `AgentRunResult` you'd get from `agent.run()`.
- Want coarse, per-step progress instead? `agent.iter()` yields one node per step.

Next, let's let the agent pause and check with you before it does something risky.

- [Human-in-the-loop →](human-in-the-loop.md)
