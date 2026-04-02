# Capabilities

pydantic-deep uses pydantic-ai's native **Capabilities API** for lifecycle hooks, cross-cutting concerns, and composable agent behaviors. Several features (cost tracking, hooks, checkpointing, context management) are implemented as capabilities.

!!! note "Migration from middleware"
    The previous middleware system (`pydantic-ai-middleware`, `MiddlewareAgent`, `AgentMiddleware`) has been replaced by pydantic-ai's built-in Capabilities API. If you are migrating from the old middleware approach, see the [migration notes](#migrating-from-middleware) below.

## Quick Start

```python
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import RunContext
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import ToolDefinition
from pydantic_deep import create_deep_agent


class LoggingCapability(AbstractCapability):
    async def before_tool_execute(
        self,
        ctx: RunContext,
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict,
    ) -> dict:
        print(f"Calling {call.tool_name}({args})")
        return args

    async def after_tool_execute(
        self,
        ctx: RunContext,
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict,
        result,
    ):
        print(f"{call.tool_name} returned: {str(result)[:100]}")
        return result


agent = create_deep_agent(
    capabilities=[LoggingCapability()],
)
```

## What Is a Capability?

A capability is a reusable, composable unit of agent behavior built on [`AbstractCapability`][pydantic_ai.capabilities.AbstractCapability]. Capabilities are passed to the `Agent` at construction time via the `capabilities` list. They can:

- **Provide tools** via `get_toolset()`
- **Inject instructions** via `get_instructions()`
- **Hook into the tool lifecycle** via `before_tool_execute()`, `after_tool_execute()`, `on_tool_execute_error()`
- **Hook into model requests** via `before_model_request()`, `after_model_request()`, `wrap_model_request()`
- **Wrap the entire run** via `wrap_run()`
- **Filter tool definitions** via `prepare_tools()`
- **Isolate per-run state** via `for_run()`

## AbstractCapability Lifecycle

### Construction-Time Methods

These methods are called once when the agent is created:

| Method | Purpose |
|--------|---------|
| `get_instructions()` | Return instructions to include in the system prompt |
| `get_model_settings()` | Return model settings to merge into the agent defaults |
| `get_toolset()` | Return a toolset to register with the agent |
| `get_builtin_tools()` | Return builtin tools (e.g. web search, code execution) |

### Per-Run Methods

These methods are called during each agent run:

| Method | When | Can Modify |
|--------|------|------------|
| `for_run(ctx)` | Once at the start of each run | Return a fresh capability instance for state isolation |
| `get_wrapper_toolset(toolset)` | During toolset assembly | Wrap the combined toolset |
| `prepare_tools(ctx, tool_defs)` | Before each model request | Filter or modify visible tool definitions |

### Run Lifecycle Hooks

| Hook | When | Can Modify |
|------|------|------------|
| `before_run(ctx)` | Before the agent run starts | Observe only |
| `after_run(ctx, result=...)` | After the run completes | Can modify the result |
| `wrap_run(ctx, handler=...)` | Wraps the entire run | `handler()` executes the run |
| `on_run_error(ctx, error=...)` | When the run fails | Raise or return a recovery result |

### Model Request Hooks

| Hook | When | Can Modify |
|------|------|------------|
| `before_model_request(ctx, request_context)` | Before each LLM call | Messages, settings, parameters |
| `after_model_request(ctx, request_context=..., response=...)` | After each LLM response | Can modify the response |
| `wrap_model_request(ctx, request_context=..., handler=...)` | Wraps the model call | `handler(request_context)` calls the model |
| `on_model_request_error(ctx, request_context=..., error=...)` | When a model call fails | Raise or return a recovery response |

### Tool Lifecycle Hooks

| Hook | When | Can Modify |
|------|------|------------|
| `before_tool_validate(ctx, call=..., tool_def=..., args=...)` | Before argument validation | Raw args |
| `after_tool_validate(ctx, call=..., tool_def=..., args=...)` | After successful validation | Validated args |
| `wrap_tool_validate(ctx, call=..., tool_def=..., args=..., handler=...)` | Wraps validation | `handler(args)` runs validation |
| `on_tool_validate_error(ctx, call=..., tool_def=..., args=..., error=...)` | On validation failure | Raise or return recovery args |
| `before_tool_execute(ctx, call=..., tool_def=..., args=...)` | Before tool execution | Validated args |
| `after_tool_execute(ctx, call=..., tool_def=..., args=..., result=...)` | After successful execution | Result |
| `wrap_tool_execute(ctx, call=..., tool_def=..., args=..., handler=...)` | Wraps execution | `handler(args)` runs the tool |
| `on_tool_execute_error(ctx, call=..., tool_def=..., args=..., error=...)` | On execution failure | Raise or return a recovery result |

## Writing a Custom Capability

Subclass `AbstractCapability` and override only the hooks you need:

```python
from dataclasses import dataclass
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.tools import RunContext
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import ToolDefinition


@dataclass
class SafetyGate(AbstractCapability):
    """Block dangerous shell commands."""

    blocked_patterns: list[str]

    async def before_tool_execute(
        self,
        ctx: RunContext,
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict,
    ) -> dict:
        if call.tool_name == "execute":
            command = args.get("command", "")
            for pattern in self.blocked_patterns:
                if pattern in command:
                    from pydantic_ai.exceptions import ModelRetry

                    raise ModelRetry(f"Blocked: command contains '{pattern}'")
        return args


agent = create_deep_agent(
    capabilities=[SafetyGate(blocked_patterns=["rm -rf", "mkfs"])],
)
```

### Per-Run State Isolation

Override `for_run()` to create a fresh capability instance for each run, preventing state leakage:

```python
@dataclass
class RequestCounter(AbstractCapability):
    count: int = 0

    async def for_run(self, ctx: RunContext) -> "RequestCounter":
        return RequestCounter(count=0)  # Fresh instance per run

    async def before_model_request(self, ctx, request_context):
        self.count += 1
        print(f"Model request #{self.count}")
        return request_context
```

## Built-in Capabilities

pydantic-deep uses these capabilities internally:

| Capability | Enabled By | Purpose |
|------------|------------|---------|
| `CostTracking` | `cost_tracking=True` (default) | Token/USD cost tracking from `pydantic_ai_shields` |
| `HooksCapability` | `hooks=[...]` | Claude Code-style lifecycle hooks |
| `CheckpointMiddleware` | `include_checkpoints=True` | Auto-save conversation checkpoints (now `AbstractCapability`) |
| `ContextManagerCapability` | `context_manager=True` (default) | Token tracking + auto-compression |
| `WebSearch` | `web_search=True, web_fetch=True` | Built-in web search capability |
| `WebFetch` | `web_search=True, web_fetch=True` | Built-in URL fetching capability |

## Configuration

Pass capabilities to `create_deep_agent()`:

```python
from pydantic_ai_shields import CostTracking
from pydantic_deep.capabilities.hooks import HooksCapability, Hook, HookEvent

agent = create_deep_agent(
    capabilities=[
        CostTracking(budget_usd=10.0),
        HooksCapability(hooks=[
            Hook(event=HookEvent.PRE_TOOL_USE, handler=my_handler),
        ]),
        MyCustomCapability(),
    ],
)
```

Additional capabilities provided by feature flags (e.g. `cost_tracking=True`, `hooks=[...]`, `web_search=True, web_fetch=True`) are appended automatically.

## How It Works

Capabilities are passed directly to pydantic-ai's `Agent` via the `capabilities` parameter. There is no wrapping layer -- the agent natively understands and dispatches to capabilities:

```python
from pydantic_ai import Agent
from pydantic_ai.capabilities import AbstractCapability

# This is what create_deep_agent() does internally:
agent = Agent(
    "anthropic:claude-sonnet-4-6",
    capabilities=[cost_cap, hooks_cap, context_cap, ...],
)
```

When multiple capabilities are registered, hooks execute in the order the capabilities were added. For tool hooks, each capability processes the result of the previous one (chain pattern).

## Migrating from Middleware

If you previously used `pydantic-ai-middleware`:

| Old (Middleware) | New (Capabilities) |
|-----------------|-------------------|
| `AgentMiddleware` | `AbstractCapability` |
| `MiddlewareAgent` | Not needed -- capabilities are native to `Agent` |
| `before_tool_call(tool_name, tool_args, ...)` | `before_tool_execute(ctx, *, call, tool_def, args)` |
| `after_tool_call(tool_name, tool_args, result, ...)` | `after_tool_execute(ctx, *, call, tool_def, args, result)` |
| `on_tool_error(...)` | `on_tool_execute_error(ctx, *, call, tool_def, args, error)` |
| `before_model_request(messages)` | `before_model_request(ctx, request_context)` |
| `after_model_response(response)` | `after_model_request(ctx, *, request_context, response)` |
| `middleware=[...]` param | `capabilities=[...]` param |
| `permission_handler` | Use `before_tool_execute` + `ModelRetry` or pydantic-ai approval toolsets |
| `MiddlewareContext` | Use capability instance fields or `ctx.deps` |
| `CostTrackingMiddleware` | `CostTracking` from `pydantic_ai_shields` |
| `HooksMiddleware` | `HooksCapability` from `pydantic_deep.capabilities.hooks` |
| `CheckpointMiddleware` | `CheckpointMiddleware` (now subclasses `AbstractCapability`) |
| `ContextManagerMiddleware` | `ContextManagerCapability` from `pydantic_ai_summarization` |

## Next Steps

- [Cost Tracking](cost-tracking.md) -- Token and cost monitoring
- [Hooks](hooks.md) -- Claude Code-style tool lifecycle hooks
- [Human-in-the-Loop](human-in-the-loop.md) -- Approval workflows
