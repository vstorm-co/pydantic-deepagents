# Capabilities & the lifecycle

Cost tracking, context compression, stuck-loop detection — they all "just happen" around your agent. **Capabilities** are how. A capability is a small object that hooks into the agent's lifecycle and observes or changes what happens before and after each model request and each tool call. This page shows the hook points, how to register your own, and what's already running for you.

## A custom capability

Here's a capability that logs every tool call. Drop it into any agent.

```python hl_lines="6 20"
import asyncio

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import RunContext, ToolDefinition
from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend


class ToolLogger(AbstractCapability):
    async def after_tool_execute(
        self,
        ctx: RunContext,
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict,
        result,
    ):
        print(f"[tool] {call.tool_name}({args}) -> {str(result)[:60]}")
        return result


async def main():
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        capabilities=[ToolLogger()],
    )
    deps = DeepAgentDeps(backend=StateBackend())
    result = await agent.run("Save 'hi' to note.txt, then read it back.", deps=deps)
    print(result.output)


asyncio.run(main())
```

## Run it

Save it to `main.py` and run:

<div class="termy">

```console
$ python main.py
[tool] write({'file_path': 'note.txt', 'content': 'hi'}) -> Wrote 2 bytes to note.txt
[tool] read({'file_path': 'note.txt'}) -> hi
...
```

</div>

Every tool the agent fired printed a line — before you saw the final answer. You didn't touch `agent.run()` or wrap a single tool. You just dropped one object into `capabilities=[...]`.

!!! example "Check it"
    Add a `before_tool_execute` method too (same signature, minus `result`) and
    return `args` unchanged. Now you'll see each call announced *before* it runs,
    not just after.

## What a capability is

A capability is a reusable unit of cross-cutting behavior built on Pydantic AI's [`AbstractCapability`][pydantic_ai.capabilities.AbstractCapability]. You subclass it, override only the hooks you care about, and pass instances to `create_deep_agent(capabilities=[...])`. The agent dispatches to them natively — there's no wrapper layer.

Let's dissect the example.

### Subclass and override

```python hl_lines="1 2"
class ToolLogger(AbstractCapability):
    async def after_tool_execute(self, ctx, *, call, tool_def, args, result):
        ...
        return result
```

`AbstractCapability` defines every hook as a no-op. You override only the one you need — here, `after_tool_execute`, which runs after a tool finishes successfully. The base class handles the rest, so a capability is as small as the behavior you actually want.

### The hook signature

```python
async def after_tool_execute(
    self, ctx: RunContext, *, call, tool_def, args, result,
):
```

Tool hooks all share the same shape: `ctx` is the run context (reach `ctx.deps` for your backend and config), `call` carries the tool name and call id, `tool_def` is the tool's definition, and `args` is the validated arguments. Hooks that run *after* execution also get `result`. **What you return matters** — returning `result` (or `args`) lets the value flow on; you can return a *modified* one to rewrite it mid-flight.

### Register it

```python hl_lines="3"
agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    capabilities=[ToolLogger()],
)
```

`capabilities=` takes a list of instances. They run in the order you list them, and for tool hooks each capability sees the result of the previous one — a clean chain. Whatever you pass is *added to* the defaults, never replacing them.

## The lifecycle hook points

A run moves through model requests and tool calls. Capabilities can attach at each boundary. The most useful hooks:

| Hook | When it fires | Can change |
|------|---------------|------------|
| `before_model_request(ctx, request_context)` | Before each LLM call | Messages, settings |
| `after_model_request(ctx, *, request_context, response)` | After each LLM response | The response |
| `before_tool_execute(ctx, *, call, tool_def, args)` | Before a tool runs | The args |
| `after_tool_execute(ctx, *, call, tool_def, args, result)` | After a tool succeeds | The result |
| `on_tool_execute_error(ctx, *, call, tool_def, args, error)` | When a tool raises | Recover or re-raise |
| `wrap_run(ctx, *, handler)` | Around the whole run | Everything |

There are more — `get_instructions()` to inject system prompt text, `get_toolset()` to add tools, `prepare_tools()` to filter what the model sees, and validation-stage hooks. The full table lives in the [Capabilities API reference][pydantic_ai.capabilities.AbstractCapability].

!!! tip "Block, don't just observe"
    A `before_tool_execute` hook can refuse a call. Raise
    [`ModelRetry`][pydantic_ai.exceptions.ModelRetry] with a reason and the model
    sees the failure and tries again — that's how a safety gate works:

    ```python
    from pydantic_ai.exceptions import ModelRetry

    async def before_tool_execute(self, ctx, *, call, tool_def, args):
        if call.tool_name == "execute" and "rm -rf" in args.get("command", ""):
            raise ModelRetry("Blocked: destructive command")
        return args
    ```

!!! warning "Isolate per-run state"
    A capability instance is shared across every run of the agent. If yours keeps
    mutable state (a counter, a buffer), override `for_run(ctx)` to return a fresh
    instance per run so state never leaks between calls.

## What's already running

`create_deep_agent()` doesn't hand you a bare model — it wires in a stack of capabilities by default. They're the reason files, costs, and context all behave sensibly out of the box.

| Capability | Default | What it does |
|------------|---------|--------------|
| `ContextManagerCapability` | `context_manager=True` | Tracks tokens, auto-compresses history near the budget |
| `CostTracking` | `cost_tracking=True` | Tallies token usage and USD cost per run and cumulatively |
| `StuckLoopDetection` | `stuck_loop_detection=True` | Catches repeated/alternating/no-op tool calls |
| `PatchToolCallsCapability` | `patch_tool_calls=True` | Repairs orphaned tool calls when resuming a conversation |
| `EvictionCapability` | when `eviction_token_limit` set | Swaps oversized tool output for a preview before it hits history |

Each is a plain feature flag on `create_deep_agent()`. Set `cost_tracking=False` to drop one, or pass your own config — and your `capabilities=[...]` list stacks on top of whatever stays on.

```python
agent = create_deep_agent(
    cost_tracking=True,        # default, shown for clarity
    stuck_loop_detection=False,  # opt out of one
    capabilities=[ToolLogger()], # add your own on top
)
```

!!! note "Built on Pydantic AI, not a fork"
    These all subclass the same `AbstractCapability` you used above. Nothing here
    is special-cased — your custom capability is a first-class citizen alongside
    cost tracking.

## Recap

- A **capability** is a small object that hooks into the agent lifecycle — override only the methods you need on `AbstractCapability`.
- Hooks fire around **model requests** (`before/after_model_request`) and **tool calls** (`before/after_tool_execute`, `on_tool_execute_error`); return the value to pass it on, or a modified one to rewrite it.
- Pass instances via `create_deep_agent(capabilities=[...])`; they run in order and stack on top of the defaults.
- The defaults — context management, cost tracking, stuck-loop detection, tool-call patching, eviction — are themselves capabilities, each toggled by a flag.

Where to go next:

- [Hooks](hooks.md) — Claude Code-style tool lifecycle hooks built on a capability
- [Context management](context-management.md) — how compression, eviction, and summarization fit together
- [Cost tracking & budgets](cost-tracking.md) — spend limits via `CostTracking`
- [Capabilities API reference][pydantic_ai.capabilities.AbstractCapability] — every hook, in full
