# Memory API

Persistent agent memory gives an agent long-lived notes it can read and update
across runs. Enable it via `include_memory=True` (default) on
[`create_deep_agent`][pydantic_deep.agent.create_deep_agent]. Memory is backed by
the `Memory` capability from
[pydantic-ai-harness](https://github.com/vstorm-co/pydantic-ai-harness), which
stores memory in a pluggable `MemoryStore` (independent of the agent's backend),
injects `MEMORY.md` as user-role context, and provides `read_memory` /
`write_memory` / `delete_memory` / `search_memory` tools. See
[Memory](../learn/memory.md) for the conceptual overview.

## Memory

The persistent-memory capability. Re-exported as `pydantic_deep.Memory`.

::: pydantic_deep.features.memory.Memory
    options:
      show_source: false

## build_memory_store

::: pydantic_deep.features.memory.build_memory_store
    options:
      show_source: false

## Stores

`InMemoryStore` (ephemeral default), `FileStore` (on-disk), and
`SqliteMemoryStore` are re-exported from `pydantic_deep`;
`PostgresMemoryStore` is available from `pydantic_ai_harness.memory`.

::: pydantic_deep.features.memory.FileStore
    options:
      show_source: false

::: pydantic_deep.features.memory.SqliteMemoryStore
    options:
      show_source: false

## Deprecated (backend-backed) API

The original backend-backed memory implementation remains importable for
backward compatibility and emits a `DeprecationWarning`. Prefer the `Memory`
capability above.

::: pydantic_deep.features.memory.MemoryCapability
    options:
      show_source: false

::: pydantic_deep.features.memory.AgentMemoryToolset
    options:
      show_source: false
