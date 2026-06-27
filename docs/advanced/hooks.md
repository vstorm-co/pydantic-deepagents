# Hooks

Run your own code on every tool the agent touches — before it runs, after it returns, or when it fails.

A **hook** is a shell command or a Python handler that fires on a tool lifecycle event. That one idea covers a lot: audit-log every call, block writes outside a directory, scrub secrets from output, or wire a tool failure to a pager. Hooks follow Claude Code's conventions, so a script you already wrote for `claude` works here too.

```python hl_lines="1 5 6 7 8 9"
from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend, Hook, HookEvent
from pydantic_deep.features.hooks import HookInput, HookResult


async def block_dangerous(hook_input: HookInput) -> HookResult:
    if "rm -rf" in str(hook_input.tool_input):
        return HookResult(allow=False, reason="Refusing to run a recursive force-delete.")
    return HookResult(allow=True)


agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    hooks=[Hook(event=HookEvent.PRE_TOOL_USE, handler=block_dangerous, matcher="execute")],
)
```

## Run it

```python
import asyncio

async def main():
    deps = DeepAgentDeps(backend=StateBackend())
    result = await agent.run("Delete everything in /tmp with rm -rf.", deps=deps)
    print(result.output)

asyncio.run(main())
```

The `execute` tool never runs your delete. The hook returns `allow=False`, the call is denied, and the model sees your `reason` and adjusts — it'll explain that it can't, or try a safer path. You wrote one function and got a guardrail the model can't talk its way past.

!!! example "Check it"
    Drop the `matcher="execute"` and the hook fires on *every* tool. Change the
    prompt to something harmless and watch it sail through — the hook only denies
    when its rule actually matches.

## Step by step

Let's take the example apart.

### The handler

```python
async def block_dangerous(hook_input: HookInput) -> HookResult:
    if "rm -rf" in str(hook_input.tool_input):
        return HookResult(allow=False, reason="Refusing to run a recursive force-delete.")
    return HookResult(allow=True)
```

A handler is an `async` function: in a [`HookInput`][pydantic_deep.features.hooks.HookInput], out a [`HookResult`][pydantic_deep.features.hooks.HookResult]. `HookInput` carries everything you need to decide — `tool_name`, `tool_input` (the arguments), and on post-events `tool_result` or `tool_error`. The `HookResult` you return is the decision:

- `allow=False` denies the call. Your `reason` surfaces to the model as a `ModelRetry`, so it learns *why* and can recover.
- `modified_args` rewrites the tool's arguments before it runs.
- `modified_result` rewrites the output after it runs.

### Wiring it on

```python hl_lines="2"
agent = create_deep_agent(
    hooks=[Hook(event=HookEvent.PRE_TOOL_USE, handler=block_dangerous, matcher="execute")],
)
```

A [`Hook`][pydantic_deep.features.hooks.Hook] binds your handler to an *event* and an optional *matcher*. Pass a list to `hooks=` and `create_deep_agent()` builds a [`HooksCapability`][pydantic_deep.features.hooks.HooksCapability] for you and registers it. (Want to attach it to a plain Pydantic AI `Agent`? Construct `HooksCapability(hooks=[...])` yourself and pass it in `capabilities=[...]`.)

The **matcher** is a regex tested against the tool name. `matcher="execute"` hits one tool; `matcher="execute|write_file|edit_file"` hits several; `matcher=None` (the default) hits all of them.

### The three tool events

[`HookEvent`][pydantic_deep.features.hooks.HookEvent] picks *when* you fire:

| Event | When | What you can do |
|-------|------|-----------------|
| `PRE_TOOL_USE` | Before a tool runs | Deny the call, or rewrite its args |
| `POST_TOOL_USE` | After it returns | Rewrite the result |
| `POST_TOOL_USE_FAILURE` | After it raises | Observe — log, alert, count |

!!! note "Pre denies, post rewrites"
    `allow=False` only means anything on `PRE_TOOL_USE` — that's the only point
    where the call hasn't happened yet. On post-events you shape the output, not
    whether it ran.

## Reshaping tool I/O

Denying is the blunt option. Often you'd rather *fix* the call instead. Rewrite arguments on the way in:

```python
async def strip_traversal(hook_input: HookInput) -> HookResult:
    args = dict(hook_input.tool_input)
    if "path" in args:
        args["path"] = args["path"].replace("../", "")
    return HookResult(allow=True, modified_args=args)
```

...or redact the result on the way out:

```python
async def redact_secrets(hook_input: HookInput) -> HookResult:
    result = hook_input.tool_result or ""
    return HookResult(modified_result=result.replace("SECRET_KEY=abc123", "SECRET_KEY=***"))

Hook(event=HookEvent.POST_TOOL_USE, handler=redact_secrets, matcher="read_file")
```

When several hooks match one event they run in order. On `PRE_TOOL_USE`, **first deny wins** and argument edits accumulate down the chain; on `POST_TOOL_USE`, each hook's result is handed to the next. Mark a hook `background=True` to fire it as a non-blocking, fire-and-forget task — perfect for analytics or audit shipping you don't want in the critical path.

## Shell-command hooks

A handler is Python; a hook can also be a shell command, which is how Claude Code hooks work. The command gets the `HookInput` as JSON on stdin and signals its decision through the **exit code**:

```python
Hook(
    event=HookEvent.PRE_TOOL_USE,
    command="python scripts/security_check.py",
    matcher="execute",
    timeout=30,  # seconds, default 30
)
```

- **Exit `0`** (`EXIT_ALLOW`) — allow. Print JSON to stdout to return `modified_args`, `modified_result`, or a `reason`.
- **Exit `2`** (`EXIT_DENY`) — deny. Whatever it printed to stdout becomes the denial reason.

!!! warning "Command hooks need a real shell"
    They run via the backend's `SandboxProtocol.execute()`, so use `LocalBackend`
    or `DockerSandbox`. `StateBackend` is in-memory and has no shell — handlers
    work there, commands don't.

## The batteries-included security preset

You don't have to hand-roll a safety gate for every project. [`default_security_hook()`][pydantic_deep.features.hooks.default_security_hook] returns a ready-made `list[Hook]` that blocks common tool-misuse and redacts obvious secrets. Because `hooks=` already takes a list, you pass it straight through:

```python
from pydantic_deep import create_deep_agent, default_security_hook

agent = create_deep_agent(hooks=default_security_hook())
```

Out of the box it blocks `rm -rf /` and friends, fork bombs, `mkfs`, `dd …of=/dev/…`, and `curl`/`wget` piped into a shell on `execute`; refuses `..` path traversal and writes/reads of sensitive files (`~/.ssh/`, `/etc/passwd`, `.env`, `~/.aws/credentials`, …); and on every tool's output redacts AWS keys, OpenAI keys, GitHub PATs, and JWT-shaped tokens. The pre-tool rules emit `HookResult(allow=False, reason=…)`, so the model sees the denial and can course-correct.

It's built to be tuned:

```python
from pydantic_deep.features.hooks import DEFAULT_BLOCKED_COMMANDS

# Require every write to land inside an allowed root (absolute paths only).
hooks = default_security_hook(allowed_write_roots=["/workspace", "/tmp/agent"])

# Extend, don't replace — lists you pass override the defaults, so spread them.
hooks = default_security_hook(
    blocked_commands=[*DEFAULT_BLOCKED_COMMANDS, r"\bsudo\b"],
)

# Turn a category off, or drop secret-scrubbing entirely.
hooks = default_security_hook(blocked_read_paths=[], redact_secrets=False)

# Shadow mode: allow everything, log what *would* have been denied.
hooks = default_security_hook(mode="warn")
```

The same "lists replace, so concatenate the constants" rule applies to `blocked_write_paths`, `blocked_read_paths`, and `secret_patterns`. And since it's just a list, stack your own hooks on top:

```python
agent = create_deep_agent(
    hooks=[
        *default_security_hook(),
        Hook(event=HookEvent.PRE_TOOL_USE, handler=block_dangerous),
    ],
)
```

!!! warning "Defense in depth, not a sandbox"
    The preset matches *common* misuse shapes. It won't catch obfuscation
    (`base64 -d | sh`), indirect access (`ln -s /etc/shadow /tmp/x`), or novel
    secret formats. For real isolation run against a `DockerSandbox` backend and
    use this preset *on top of* it, not instead of it.

## Recap

You now have a hook into every tool the agent runs:

- A `Hook` binds a handler (Python) or `command` (shell) to a `HookEvent` and an optional regex `matcher`.
- The three tool events are `PRE_TOOL_USE` (deny / rewrite args), `POST_TOOL_USE` (rewrite result), and `POST_TOOL_USE_FAILURE` (observe).
- Handlers return a `HookResult`: `allow=False` denies and feeds `reason` back to the model; `modified_args` / `modified_result` reshape I/O. Command hooks decide via exit code — `0` allow, `2` deny.
- `default_security_hook()` is a tunable, batteries-included safety bundle — and it's just a list, so spread it and add your own.

Where to go next:

- [Capabilities & lifecycle](capabilities.md) — the system hooks plug into.
- [Cost tracking & budgets](cost-tracking.md) — another lifecycle guardrail.
- [Human-in-the-loop](../learn/human-in-the-loop.md) — approval workflows for risky tools.
