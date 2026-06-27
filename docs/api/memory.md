# Memory API

Persistent agent memory gives an agent a long-lived `MEMORY.md` file it can read
and update across runs. Enable it via `include_memory=True` (default) on
[`create_deep_agent`][pydantic_deep.agent.create_deep_agent]. See
[Memory](../learn/memory.md) for the conceptual overview.

## MemoryFile

::: pydantic_deep.features.memory.MemoryFile
    options:
      show_source: false

## AgentMemoryToolset

::: pydantic_deep.features.memory.AgentMemoryToolset
    options:
      show_source: false

## load_memory

::: pydantic_deep.features.memory.load_memory
    options:
      show_source: false

## format_memory_prompt

::: pydantic_deep.features.memory.format_memory_prompt
    options:
      show_source: false

## get_memory_path

::: pydantic_deep.features.memory.get_memory_path
    options:
      show_source: false
