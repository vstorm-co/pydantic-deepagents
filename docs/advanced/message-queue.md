# Message queue (steering)

Talk to an agent *while* it's still working. No cancel, no restart — you push a message into the running loop and the agent picks it up at the next natural moment.

This is what powers "stop, try something else" and "when you're done, also do X" — without throwing away in-flight tool results or busting the prompt cache.

## The two moments you can speak

There are exactly two points where it's safe to slip a message in, and you choose which one:

| You want to… | Use | Delivered |
|---|---|---|
| Redirect the agent mid-task | **steering** | before the next model call, after the current tool batch finishes |
| Add work for when it's wrapping up | **follow-up** | when the agent would otherwise stop |

Steering is an interrupt: *"actually, do it this way instead."* Follow-up is a queue: *"once that's done, here's the next thing."*

## Show it

```python hl_lines="2 7 8 11"
import asyncio
from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend
from pydantic_deep.features.message_queue import MessageQueue, run_with_queue


async def main():
    queue = MessageQueue()
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        message_queue=queue,
    )
    deps = DeepAgentDeps(backend=StateBackend(), message_queue=queue)

    async def supervisor():
        # Some other coroutine, watching the run unfold.
        await asyncio.sleep(2)
        await queue.steer("stop digging deeper — summarise what you have so far")
        await queue.follow_up("when you're done, write one test for the result")

    _, result = await asyncio.gather(
        supervisor(),
        run_with_queue(agent, "investigate the failing test", deps=deps, queue=queue),
    )
    print(result.output)


asyncio.run(main())
```

## Run it

The agent starts investigating. Two seconds in, `supervisor()` drops a steering message and a follow-up. At the next model call the agent sees `[steering] stop digging deeper…` and changes course. When it finishes that work, `run_with_queue` notices the pending follow-up and re-enters the loop with *"when you're done, write one test…"* as the next prompt.

You steered a running agent from outside it — and queued a continuation it'll reach on its own.

!!! example "Check it"
    Comment out the `queue.steer(...)` line and run again. Without the nudge the
    agent keeps investigating on its own terms. The queue is the only thing that
    changed its mind.

## Step by step

### Step 1: one queue, shared two ways

```python hl_lines="2 6"
queue = MessageQueue()
agent = create_deep_agent(model="anthropic:claude-sonnet-4-6", message_queue=queue)
deps = DeepAgentDeps(backend=StateBackend(), message_queue=queue)
```

The same `MessageQueue` goes to *both* the agent and the deps. Passing it to `create_deep_agent(message_queue=…)` installs the capability that injects steering before each model request. Putting it on `DeepAgentDeps` makes it reachable from inside tools and subagents (more on that below).

### Step 2: speak from anywhere

```python
await queue.steer("change your approach")
await queue.follow_up("then summarise")
```

Both are `async` and asyncio-safe — call them from any coroutine, task, or HTTP handler that holds the queue. `steer()` is the interrupt; `follow_up()` is the continuation. Each takes a plain string.

### Step 3: run with `run_with_queue`

```python
result = await run_with_queue(agent, "investigate the bug", deps=deps, queue=queue)
```

Steering works on a plain `await agent.run(...)` too — the capability injects it before each model request automatically. But follow-ups need someone to re-enter the loop once a run ends. That's [`run_with_queue`][pydantic_deep.features.message_queue.run_with_queue]: after each completed run it drains any follow-ups and starts a fresh turn with them as the prompt, repeating until the queue is empty.

!!! note "Use the wrapper for follow-ups"
    Steering only? Plain `agent.run(..., deps=deps)` is enough. The moment you
    want follow-ups, reach for `run_with_queue` — it's the part that loops.

## One message or the whole batch

Every message carries a `delivery_mode`. The default, `"one_at_a_time"`, hands the agent exactly one queued message per drain — drip-fed, in order. Mark a message `"all"` and the queue empties the contiguous run of `"all"` messages at once.

```python hl_lines="3"
await queue.steer("first hint")
await queue.steer("second hint")
# the agent sees "first hint" now; "second hint" waits for the next model call

await queue.steer("context line 1", delivery_mode="all")
await queue.steer("context line 2", delivery_mode="all")
# both arrive together in one steering injection
```

The mode is read from the *head* message, and an `"all"` head never swallows a later message that asked to be delivered on its own — so you can mix the two freely.

## Subagents can steer the parent

Because the queue lives on `DeepAgentDeps`, anything with `ctx.deps` can use it — including a subagent. By default `clone_for_subagent()` hands subagents the *same* queue, so a child can talk back to the parent:

```python
# Inside a tool or subagent:
await ctx.deps.message_queue.steer("parent — this path is a dead end, pivot")
```

Want isolation instead? Give the cloned deps a fresh `MessageQueue()` and the channels stay separate.

!!! tip "It's a back-channel, not a megaphone"
    Steering injects a single user-turn part before the next request. Keep each
    message short and directive — the agent reads it like a teammate leaning over
    your shoulder, not a new system prompt.

## Recap

- A `MessageQueue` lets external code — or a subagent — inject messages into a *running* agent without cancel/restart.
- **Steering** redirects mid-task (before the next model call); **follow-up** adds work for when the agent would stop.
- Share one queue with both `create_deep_agent(message_queue=…)` and `DeepAgentDeps(message_queue=…)`.
- Steering works on plain `agent.run`; follow-ups need [`run_with_queue`][pydantic_deep.features.message_queue.run_with_queue] to re-enter the loop.
- `delivery_mode="all"` batches messages; the default drip-feeds one at a time.

Where to go next:

- [Live Run Forking →](forking.md) — branch a run instead of steering it.
- [Agent teams →](teams.md) — many agents coordinating through shared channels.
- [Monitor (watch & react) →](monitor.md) — react to a run from the outside.
