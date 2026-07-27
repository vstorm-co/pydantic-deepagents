# Capabilities API

Capabilities hook into the agent lifecycle via pydantic-ai's native
[`AbstractCapability`](https://ai.pydantic.dev/) API. They are registered through
the `capabilities` parameter of
[`create_deep_agent`][pydantic_deep.agent.create_deep_agent], or enabled through
dedicated feature flags. See [Capabilities](../advanced/capabilities.md) for the
conceptual overview.

## SkillsCapability

::: pydantic_deep.capabilities.SkillsCapability
    options:
      show_source: false

## ContextFilesCapability

::: pydantic_deep.capabilities.ContextFilesCapability
    options:
      show_source: false

## Memory

Persistent memory is provided by the `Memory` capability from the external
**pydantic-ai-harness** package, re-exported as `pydantic_deep.Memory`. It stores
memory in a pluggable `MemoryStore` (independent of `deps.backend`). See the
[Memory API](memory.md) reference for full details.

!!! warning "`MemoryCapability` is deprecated"
    The old `pydantic_deep.capabilities.MemoryCapability` class still imports (as a
    shim that emits `DeprecationWarning`) but is deprecated in favor of the `Memory`
    capability above.

## BrowserCapability

::: pydantic_deep.capabilities.BrowserCapability
    options:
      show_source: false

## StuckLoopDetection

::: pydantic_deep.capabilities.StuckLoopDetection
    options:
      show_source: false

::: pydantic_deep.features.stuck_loop.StuckLoopError
    options:
      show_source: false

## PeriodicReminderCapability

::: pydantic_deep.capabilities.PeriodicReminderCapability
    options:
      show_source: false

## HooksCapability

See the [Hooks API](hooks.md#hookscapability) for `HooksCapability` and the related
hook definitions.

## EvictionCapability

::: pydantic_deep.features.eviction.EvictionCapability
    options:
      show_source: false

## PatchToolCallsCapability

::: pydantic_deep.features.patch.PatchToolCallsCapability
    options:
      show_source: false
