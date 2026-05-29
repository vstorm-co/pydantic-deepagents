# Hooks

Hooks allow executing shell commands or Python handlers on tool lifecycle events, following Claude Code's hook conventions. Use them for audit logging, security gates, content filtering, or custom side effects. Hooks are implemented via `HooksCapability`, a pydantic-ai capability.

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

### Tool Events

| Event | When | Can Modify |
|-------|------|------------|
| `PRE_TOOL_USE` | Before tool execution | Deny tool call, modify args |
| `POST_TOOL_USE` | After successful tool call | Modify result |
| `POST_TOOL_USE_FAILURE` | After a tool call fails | Observe only |

### Run Events

| Event | When | Use Case |
|-------|------|----------|
| `BEFORE_RUN` | Start of `agent.run()` | Setup, session tracking |
| `AFTER_RUN` | End of `agent.run()` | Cleanup, audit logging |
| `RUN_ERROR` | `agent.run()` fails | Error tracking, alerts |

### Model Request Events

| Event | When | Use Case |
|-------|------|----------|
| `BEFORE_MODEL_REQUEST` | Before each LLM call | Rate limiting, request logging |
| `AFTER_MODEL_REQUEST` | After each LLM response | Token tracking, response logging |

## Defining Hooks

### Command Hooks

Command hooks run shell commands via `SandboxProtocol.execute()`. The hook receives `HookInput` as JSON on stdin and uses **exit codes** for decisions:

- **Exit 0** -- Allow (optionally return JSON with modifications)
- **Exit 2** -- Deny (stdout becomes the denial reason)

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
from pydantic_deep.capabilities.hooks import HookInput, HookResult

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

Background hooks run as fire-and-forget tasks -- they don't block tool execution:

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
| `event` | `str` | Event name (e.g. `"pre_tool_use"`, `"before_run"`, `"after_model_request"`) |
| `tool_name` | `str` | Name of the tool being called |
| `tool_input` | `dict` | Tool arguments |
| `tool_result` | `str \| None` | Tool output (only for POST events) |
| `tool_error` | `str \| None` | Error message (only for POST_TOOL_USE_FAILURE) |

## Hook Resolution

For `PRE_TOOL_USE`, hooks run in order and **first deny wins**:

1. All matching hooks execute sequentially
2. If any hook returns `allow=False`, the tool call is denied (raises `ModelRetry`)
3. Argument modifications accumulate across hooks

For `POST_TOOL_USE` and `POST_TOOL_USE_FAILURE`, all matching hooks run:

1. Result modifications from each hook are passed to the next
2. Background hooks run in parallel without blocking

## HooksCapability

`HooksCapability` is the `AbstractCapability` that dispatches hooks. It maps hook events to pydantic-ai capability methods:

| Hook Event | Capability Method |
|------------|------------------|
| `PRE_TOOL_USE` | `before_tool_execute()` |
| `POST_TOOL_USE` | `after_tool_execute()` |
| `POST_TOOL_USE_FAILURE` | `on_tool_execute_error()` |
| `BEFORE_RUN` | `before_run()` |
| `AFTER_RUN` | `after_run()` |
| `RUN_ERROR` | `on_run_error()` |
| `BEFORE_MODEL_REQUEST` | `before_model_request()` |
| `AFTER_MODEL_REQUEST` | `after_model_request()` |

When you pass `hooks=[...]` to `create_deep_agent()`, a `HooksCapability` is automatically created and added to the agent's capabilities list. You can also create it directly:

```python
from pydantic_ai import Agent
from pydantic_deep.capabilities.hooks import HooksCapability, Hook, HookEvent

hooks_cap = HooksCapability(hooks=[
    Hook(event=HookEvent.PRE_TOOL_USE, handler=my_handler),
])

agent = Agent("anthropic:claude-sonnet-4-6", capabilities=[hooks_cap])
```

## Run and Model Hooks

### Session Tracking

```python
async def on_start(hook_input: HookInput) -> HookResult:
    print(f"Agent run started at {time.time()}")
    return HookResult()

async def on_end(hook_input: HookInput) -> HookResult:
    print(f"Agent run finished. Output: {hook_input.tool_result}")
    return HookResult()

agent = create_deep_agent(
    hooks=[
        Hook(event=HookEvent.BEFORE_RUN, handler=on_start),
        Hook(event=HookEvent.AFTER_RUN, handler=on_end),
    ],
)
```

### LLM Call Logging

```python
request_count = 0

async def count_requests(hook_input: HookInput) -> HookResult:
    global request_count
    request_count += 1
    return HookResult()

agent = create_deep_agent(
    hooks=[
        Hook(event=HookEvent.BEFORE_MODEL_REQUEST, handler=count_requests),
    ],
)
```

### Error Alerts

```python
Hook(
    event=HookEvent.RUN_ERROR,
    command="curl -X POST https://alerts.example.com/webhook -d @-",
    background=True,
)
```

!!! note "Matcher is ignored for non-tool events"
    Run and model request hooks don't have a tool name to match against.
    The `matcher` field is ignored — these hooks always fire.

## Built-in Security Preset

[`default_security_hook()`][pydantic_deep.capabilities.hooks.default_security_hook] is a batteries-included bundle that blocks common tool-misuse patterns and redacts obvious secrets from tool output — so you don't have to hand-roll a safety gate for every deployment.

```python
from pydantic_deep import create_deep_agent, default_security_hook

agent = create_deep_agent(hooks=default_security_hook())
```

The preset returns a `list[Hook]`, and `create_deep_agent`'s `hooks=` parameter takes a list — pass it through directly.

### What gets blocked

The defaults are opt-out, not opt-in: turn things off explicitly when you need to.

| Tool | Rule |
|------|------|
| `execute` | `rm -rf /`, `rm -rf /*`, `rm --recursive --force /`, `rm -rf ~`, fork bombs (`:(){:|:&};:`), `mkfs`, `dd …of=/dev/…`, `curl`/`wget` piped into a shell |
| `write_file`, `edit_file` | Paths containing `..` traversal segments; `~/.ssh/`, `/etc/passwd|shadow|sudoers`, `/etc/cron*`, `~/.aws/credentials`, `.env` files, shell startup files; optionally, anything outside `allowed_write_roots` |
| `read_file` | `/etc/shadow`, `~/.ssh/*`, `.env*`, `~/.aws/credentials`, GCP `application_default_credentials.json` |
| All tools (POST) | Redacts AWS access keys (`AKIA…`), OpenAI keys (legacy `sk-…` and current `sk-proj-…`, `sk-svcacct-…`, `sk-admin-…`), GitHub PATs (`ghp_…`, `github_pat_…`), JWT-shaped tokens |

The pre-tool rules emit `HookResult(allow=False, reason=…)`, which surfaces to the model as a `ModelRetry` — the agent sees the denial reason and can adjust.

### Customizing

**Tighten the write boundary.** By default, `..` traversal and a sensitive-path denylist (`~/.ssh/`, `/etc/passwd`, etc.) are blocked. Pass `allowed_write_roots` to additionally require every write to resolve inside one of those directories. Roots must be **absolute** paths — `~`-prefixed and relative paths are rejected at construction time, because `~` expands against the controller's HOME which may differ from the agent backend's namespace (e.g. DockerSandbox):

```python
hooks = default_security_hook(allowed_write_roots=["/workspace", "/tmp/agent"])
```

**Extend the command blocklist.** Lists you pass *replace* the defaults — concatenate with the constants to keep them:

```python
from pydantic_deep.capabilities.hooks import DEFAULT_BLOCKED_COMMANDS

hooks = default_security_hook(
    blocked_commands=[*DEFAULT_BLOCKED_COMMANDS, r"\bsudo\b", r"\bdocker\s+rm\b"],
)
```

The same pattern works for `blocked_write_paths`, `blocked_read_paths`, and `secret_patterns`.

**Disable a category.** Pass an empty list, or `redact_secrets=False` to drop the POST hook entirely:

```python
hooks = default_security_hook(
    blocked_read_paths=[],   # don't gate read_file
    redact_secrets=False,    # don't scrub tool output
)
```

**Shadow mode.** Roll out in non-blocking mode first to see what *would* be denied:

```python
hooks = default_security_hook(mode="warn")
```

Every match is allowed through but logged at `WARNING` level on the `pydantic_deep.capabilities.hooks` logger. Once the noise looks acceptable, flip back to the default `mode="deny"`.

**Combine with custom hooks.** Spread the list and append your own:

```python
from pydantic_deep import Hook, HookEvent, create_deep_agent, default_security_hook

agent = create_deep_agent(
    hooks=[
        *default_security_hook(),
        Hook(event=HookEvent.PRE_TOOL_USE, handler=my_audit_logger),
    ],
)
```

### Limits

This is defense in depth, not a sandbox. The regexes catch *common* misuse shapes — they don't catch:

- Obfuscated commands (`echo cm0gLXJmIC8= | base64 -d | sh`)
- Indirect file access (`ln -s /etc/shadow /tmp/x; cat /tmp/x`)
- Novel secret formats not in the pattern list
- Misuse via shell features that aren't in the literal command string (env vars, `eval`, etc.)

For hard isolation, run the agent against a `DockerSandbox` backend. Use this preset on top of that, not instead of it.

## Components

| Component | Description |
|-----------|-------------|
| [`Hook`][pydantic_deep.capabilities.hooks.Hook] | Hook definition (event, command/handler, matcher) |
| [`HookEvent`][pydantic_deep.capabilities.hooks.HookEvent] | Enum: 8 events (tool, run, model request) |
| [`HookInput`][pydantic_deep.capabilities.hooks.HookInput] | Data passed to hooks |
| [`HookResult`][pydantic_deep.capabilities.hooks.HookResult] | Result from hook execution |
| [`HooksCapability`][pydantic_deep.capabilities.hooks.HooksCapability] | Capability that dispatches hooks on tool events |
| [`default_security_hook`][pydantic_deep.capabilities.hooks.default_security_hook] | Built-in safety preset (returns `list[Hook]`) |
| [`DEFAULT_BLOCKED_COMMANDS`][pydantic_deep.capabilities.hooks.DEFAULT_BLOCKED_COMMANDS] | Default destructive-command regex tuple |
| [`DEFAULT_BLOCKED_READ_PATHS`][pydantic_deep.capabilities.hooks.DEFAULT_BLOCKED_READ_PATHS] | Default sensitive read-path regex tuple |
| [`DEFAULT_BLOCKED_WRITE_PATHS`][pydantic_deep.capabilities.hooks.DEFAULT_BLOCKED_WRITE_PATHS] | Default sensitive write-path regex tuple |
| [`DEFAULT_SECRET_PATTERNS`][pydantic_deep.capabilities.hooks.DEFAULT_SECRET_PATTERNS] | Default secret-token regex tuple |
| `EXIT_ALLOW` | Exit code `0` -- allow |
| `EXIT_DENY` | Exit code `2` -- deny |

## Next Steps

- [Capabilities](middleware.md) -- Capabilities system overview
- [Checkpointing](checkpointing.md) -- Save and rewind conversation state
- [Memory](memory.md) -- Persistent agent memory
- [Human-in-the-Loop](human-in-the-loop.md) -- Approval workflows
