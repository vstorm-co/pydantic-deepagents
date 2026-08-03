# Capabilities API

Capabilities hook into the agent lifecycle via pydantic-ai's native
[`AbstractCapability`](https://ai.pydantic.dev/) API. They are registered through
the `capabilities` parameter of
[`create_deep_agent`][pydantic_deep.agent.create_deep_agent], or enabled through
dedicated feature flags. See [Capabilities](../advanced/capabilities.md) for the
conceptual overview.

## SkillsCapability

::: pydantic_deep.features.skills.SkillsCapability
    options:
      show_source: false

## ContextFilesCapability

::: pydantic_deep.features.context.ContextFilesCapability
    options:
      show_source: false

## MemoryCapability

::: pydantic_deep.features.memory.MemoryCapability
    options:
      show_source: false

## BrowserCapability

::: pydantic_deep.features.browser.BrowserCapability
    options:
      show_source: false

## StuckLoopDetection

::: pydantic_deep.features.stuck_loop.StuckLoopDetection
    options:
      show_source: false

::: pydantic_deep.features.stuck_loop.StuckLoopError
    options:
      show_source: false

## PeriodicReminderCapability

::: pydantic_deep.features.periodic_reminder.PeriodicReminderCapability
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
