# Message Queue

The **Message Queue** lets external code push messages into a running agent loop without cancelling and restarting it — preserving in-flight tool results and the prompt cache.

Two delivery semantics are supported:

| Semantic | When delivered | Use case |
|---|---|---|
| **Steering** | Before the next LLM request, after the current tool batch | "Stop that approach, try X instead" |
| **Follow-up** | When the agent would otherwise stop | "When you're done, also do Y" |

## Quick start

```python
from pydantic_deep import create_deep_agent
from pydantic_deep.capabilities.message_queue import MessageQueue, run_with_queue
from pydantic_deep.deps import DeepAgentDeps

queue = MessageQueue()
agent = create_deep_agent(model="anthropic:claude-sonnet-4-6", message_queue=queue)
deps = DeepAgentDeps(message_queue=queue)

# In another coroutine / task while the agent is running:
await queue.steer("stop digging deeper, summarise what you have")
await queue.follow_up("when done, write a test for the result")

# Run with follow-up support
result = await run_with_queue(agent, "investigate the bug", deps=deps, queue=queue)
```

## Delivery modes

Each message can be queued with one of two `delivery_mode` values:

- **`"one_at_a_time"`** (default) — each `drain_*` call pops exactly one message
- **`"all"`** — the first `drain_*` call empties the entire queue at once (mode is read from the head message)

```python
await queue.steer("first hint")
await queue.steer("second hint")
# drain_steering() returns only "first hint" (one_at_a_time)

await queue.steer("batch A", delivery_mode="all")
await queue.steer("batch B")
# drain_steering() returns both (mode from head message)
```

## Subagent sharing

By default, `DeepAgentDeps.clone_for_subagent()` passes the same `MessageQueue` reference to subagents. A subagent can therefore steer the parent:

```python
# Inside a tool or subagent:
await ctx.deps.message_queue.steer("parent, change your approach")
```

Pass a fresh `MessageQueue()` to `clone_for_subagent()` override on the cloned deps if isolation is needed.

## Delivery sequence

```
External caller          MessageQueue          Agent loop (pydantic-ai)
     |                       |                         |
     |-- await steer("X") -->|                         |
     |                       |  [steering deque: X]    |
     |                       |                         |
     |                       |<-- before_model_request-|
     |                       |  drain_steering()       |
     |                       |-- inject UserPromptPart->|
     |                       |                         |-- LLM sees "[steering] X"
     |                       |                         |
     |-- await follow_up("Y")|                         |
     |                       |  [follow_up deque: Y]   |
     |                       |                         |
     |                       |                    agent stops
     |                       |                         |
     |             run_with_queue() drain_follow_up()  |
     |                       |-- "Y" as next prompt -->|
     |                       |                         |-- new run with Y
```
