# Hooks

Hooks allow executing shell commands or Python handlers on tool lifecycle events, following Claude Code's hook conventions. Use them for audit logging, security gates, content filtering, or custom side effects.

## Quick Start

```python
from pydantic_deep import create_deep_agent, Hook, HookEvent

agent = create_deep_agent(
    hooks=[
        Hook(
            event=HookEvent.PRE_TOOL_USE,
            command="my-security-checker",
            matcher="execute|write_file",
        ),
    ],
)
```

## Hook Events

| Event | When | Can Modify |
|-------|------|------------|
| `PRE_TOOL_USE` | Before tool execution | Deny tool call, modify args |
| `POST_TOOL_USE` | After successful tool call | Modify result |
| `POST_TOOL_USE_FAILURE` | After a tool call fails | Observe only |

## Defining Hooks

### Command Hooks

Command hooks run shell commands via `SandboxProtocol.execute()`. The hook receives `HookInput` as JSON on stdin and uses **exit codes** for decisions:

- **Exit 0** — Allow (optionally return JSON with modifications)
- **Exit 2** — Deny (stdout becomes the denial reason)

```python
Hook(
    event=HookEvent.PRE_TOOL_USE,
    command="python scripts/security_check.py",
    matcher="execute",  # Only match the execute tool
    timeout=30,         # Seconds (default: 30)
)
```

!!! warning "Command hooks require a SandboxProtocol backend"
    Use `LocalBackend` or `DockerSandbox`. `StateBackend` does not support `execute()`.

### Python Handler Hooks

Handler hooks call async Python functions directly:

```python
from pydantic_deep.middleware.hooks import HookInput, HookResult

async def audit_logger(hook_input: HookInput) -> HookResult:
    print(f"[AUDIT] {hook_input.tool_name}({hook_input.tool_input})")
    return HookResult(allow=True)

async def safety_gate(hook_input: HookInput) -> HookResult:
    if "rm -rf" in str(hook_input.tool_input):
        return HookResult(allow=False, reason="Dangerous command blocked")
    return HookResult(allow=True)

agent = create_deep_agent(
    hooks=[
        Hook(event=HookEvent.POST_TOOL_USE, handler=audit_logger),
        Hook(event=HookEvent.PRE_TOOL_USE, handler=safety_gate, matcher="execute"),
    ],
)
```

## Matchers

The `matcher` field is a regex pattern matched against the tool name. `None` matches all tools.

```python
# Match a specific tool
Hook(event=HookEvent.PRE_TOOL_USE, handler=my_handler, matcher="execute")

# Match multiple tools
Hook(event=HookEvent.PRE_TOOL_USE, handler=my_handler, matcher="execute|write_file|edit_file")

# Match all tools (default)
Hook(event=HookEvent.POST_TOOL_USE, handler=audit_logger, matcher=None)
```

## Modifying Tool Behavior

### Pre-tool: Modify Arguments

Command hooks can modify tool arguments by printing JSON to stdout:

```json
{"modified_args": {"path": "/safe/path/file.txt"}}
```

Python handlers return modifications via `HookResult`:

```python
async def normalize_paths(hook_input: HookInput) -> HookResult:
    args = dict(hook_input.tool_input)
    if "path" in args:
        args["path"] = args["path"].replace("../", "")
    return HookResult(allow=True, modified_args=args)
```

### Post-tool: Modify Results

```python
async def redact_secrets(hook_input: HookInput) -> HookResult:
    result = hook_input.tool_result or ""
    redacted = result.replace("SECRET_KEY=abc123", "SECRET_KEY=***")
    return HookResult(modified_result=redacted)

Hook(event=HookEvent.POST_TOOL_USE, handler=redact_secrets, matcher="read_file")
```

## Background Hooks

Background hooks run as fire-and-forget tasks — they don't block tool execution:

```python
Hook(
    event=HookEvent.POST_TOOL_USE,
    handler=send_to_analytics,
    background=True,  # Non-blocking
)
```

## HookInput Structure

Hooks receive this data:

| Field | Type | Description |
|-------|------|-------------|
| `event` | `str` | Event name (`"pre_tool_use"`, `"post_tool_use"`, `"post_tool_use_failure"`) |
| `tool_name` | `str` | Name of the tool being called |
| `tool_input` | `dict` | Tool arguments |
| `tool_result` | `str \| None` | Tool output (only for POST events) |
| `tool_error` | `str \| None` | Error message (only for POST_TOOL_USE_FAILURE) |

## Hook Resolution

For `PRE_TOOL_USE`, hooks run in order and **first deny wins**:

1. All matching hooks execute sequentially
2. If any hook returns `allow=False`, the tool call is denied
3. Argument modifications accumulate across hooks

For `POST_TOOL_USE` and `POST_TOOL_USE_FAILURE`, all matching hooks run:

1. Result modifications from each hook are passed to the next
2. Background hooks run in parallel without blocking

## Components

| Component | Description |
|-----------|-------------|
| [`Hook`][pydantic_deep.middleware.hooks.Hook] | Hook definition (event, command/handler, matcher) |
| [`HookEvent`][pydantic_deep.middleware.hooks.HookEvent] | Enum: `PRE_TOOL_USE`, `POST_TOOL_USE`, `POST_TOOL_USE_FAILURE` |
| [`HookInput`][pydantic_deep.middleware.hooks.HookInput] | Data passed to hooks |
| [`HookResult`][pydantic_deep.middleware.hooks.HookResult] | Result from hook execution |
| [`HooksMiddleware`][pydantic_deep.middleware.hooks.HooksMiddleware] | Middleware that dispatches hooks |
| `EXIT_ALLOW` | Exit code `0` — allow |
| `EXIT_DENY` | Exit code `2` — deny |

## Next Steps

- [Checkpointing](checkpointing.md) — Save and rewind conversation state
- [Memory](memory.md) — Persistent agent memory
- [Human-in-the-Loop](human-in-the-loop.md) — Approval workflows
