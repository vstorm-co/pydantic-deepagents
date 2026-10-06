# Memory API

Persistent agent memory is the `pydantic-ai-harness` [`Memory`](https://pydantic.dev/docs/ai/harness/)
capability over a `FileStore` in the run's workspace. Enable it via
`include_memory=True` (default) on
[`create_deep_agent`][pydantic_deep.agent.create_deep_agent], which builds it with
[`build_memory_capability`][pydantic_deep.features.memory.store.build_memory_capability].
See [Memory](../learn/memory.md) for the conceptual overview.

pydantic-deep's own memory API - `AgentMemoryToolset`, `MemoryCapability`,
`MemoryFile`, `load_memory`, `format_memory_prompt` - is deprecated: it still
imports, with a `DeprecationWarning`, and nothing uses it.

## build_memory_capability

::: pydantic_deep.features.memory.store.build_memory_capability
    options:
      show_source: false

## MemoryNamespace

::: pydantic_deep.features.memory.store.MemoryNamespace
    options:
      show_source: false

## get_memory_path

::: pydantic_deep.features.memory.service.get_memory_path
    options:
      show_source: false
