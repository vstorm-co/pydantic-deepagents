# Hooks API

Claude Code-style lifecycle hooks run shell commands or Python handlers around tool
execution. Attach them via the `hooks` parameter on
[`create_deep_agent`][pydantic_deep.agent.create_deep_agent]. See
[Hooks](../advanced/hooks.md) for the conceptual overview.

## Hook

::: pydantic_deep.capabilities.hooks.Hook
    options:
      show_source: false

## HookEvent

::: pydantic_deep.capabilities.hooks.HookEvent
    options:
      show_source: false

## HookInput

::: pydantic_deep.capabilities.hooks.HookInput
    options:
      show_source: false

## HookResult

::: pydantic_deep.capabilities.hooks.HookResult
    options:
      show_source: false

## HooksCapability

::: pydantic_deep.capabilities.hooks.HooksCapability
    options:
      show_source: false

## default_security_hook

::: pydantic_deep.capabilities.hooks.default_security_hook
    options:
      show_source: false

## Default Blocklists

::: pydantic_deep.capabilities.hooks.DEFAULT_BLOCKED_COMMANDS
    options:
      show_source: false

::: pydantic_deep.capabilities.hooks.DEFAULT_BLOCKED_READ_PATHS
    options:
      show_source: false

::: pydantic_deep.capabilities.hooks.DEFAULT_BLOCKED_WRITE_PATHS
    options:
      show_source: false

::: pydantic_deep.capabilities.hooks.DEFAULT_SECRET_PATTERNS
    options:
      show_source: false
