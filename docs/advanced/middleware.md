# Middleware

pydantic-deep integrates with [pydantic-ai-middleware](https://github.com/vstorm-co/pydantic-ai-middleware) for lifecycle hooks, permissions, and cross-cutting concerns. Several features (cost tracking, hooks, checkpointing) use middleware internally.

!!! tip "Installation"
    ```bash
    pip install pydantic-deep[middleware]
    ```

## Quick Start

```python
from pydantic_ai_middleware import AgentMiddleware
from pydantic_deep import create_deep_agent

class LoggingMiddleware(AgentMiddleware):
    async def before_tool_call(self, tool_name, tool_args, deps, ctx=None):
        print(f"Calling {tool_name}({tool_args})")
        return tool_args

    async def after_tool_call(self, tool_name, tool_args, result, deps, ctx=None):
        print(f"{tool_name} returned: {result[:100]}")
        return result

agent = create_deep_agent(
    middleware=[LoggingMiddleware()],
)
```

## Middleware Lifecycle Hooks

| Hook | When | Can Return |
|------|------|------------|
| `before_model_request` | Before LLM call | Modified messages |
| `after_model_response` | After LLM response | Modified response |
| `before_tool_call` | Before tool execution | Modified args or `ToolPermissionResult` |
| `after_tool_call` | After successful tool | Modified result |
| `on_tool_error` | After tool failure | Replacement exception or `None` |

## Permission Handler

For tools that require approval, provide a `permission_handler`:

```python
async def ask_user_permission(tool_name: str, tool_args: dict, reason: str) -> bool:
    response = input(f"Allow {tool_name}? ({reason}) [y/n]: ")
    return response.lower() == "y"

agent = create_deep_agent(
    middleware=[my_middleware],
    permission_handler=ask_user_permission,
)
```

The handler is called when middleware returns `ToolDecision.ASK`.

## Middleware Context

Share state between middleware hooks:

```python
from pydantic_ai_middleware import MiddlewareContext

ctx = MiddlewareContext({"session_id": "abc123"})

agent = create_deep_agent(
    middleware=[my_middleware],
    middleware_context=ctx,
)
```

## Built-in Middleware

pydantic-deep uses these middleware internally:

| Middleware | Enabled By | Purpose |
|-----------|------------|---------|
| `CostTrackingMiddleware` | `cost_tracking=True` (default) | Token/USD cost tracking |
| `HooksMiddleware` | `hooks=[...]` | Claude Code-style lifecycle hooks |
| `CheckpointMiddleware` | `include_checkpoints=True` | Auto-save conversation checkpoints |
| `ContextManagerMiddleware` | `context_manager=True` (default) | Token tracking + auto-compression |

## Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `middleware` | `list[AgentMiddleware]` | `None` | Custom middleware instances |
| `permission_handler` | `Callable` | `None` | Async callback for permission decisions |
| `middleware_context` | `MiddlewareContext` | `None` | Shared state for middleware |

## How It Works

When middleware is provided (or features like cost tracking are enabled), `create_deep_agent()` wraps the base `Agent` in a `MiddlewareAgent`:

```python
from pydantic_ai_middleware import MiddlewareAgent

# This happens automatically inside create_deep_agent():
wrapped = MiddlewareAgent(
    agent=base_agent,
    middleware=[cost_mw, hooks_mw, custom_mw],
    permission_handler=handler,
    context=ctx,
)
```

The `MiddlewareAgent` delegates to the base agent while intercepting lifecycle events.

## Next Steps

- [Cost Tracking](cost-tracking.md) — Token and cost monitoring
- [Hooks](hooks.md) — Claude Code-style tool lifecycle hooks
- [Human-in-the-Loop](human-in-the-loop.md) — Approval workflows
