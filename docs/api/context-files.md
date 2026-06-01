# Context Files API

Project context files (DEEP.md, AGENTS.md, CLAUDE.md, SOUL.md) are auto-discovered
and injected into the system prompt. Enable discovery via `context_discovery=True`
on [`create_deep_agent`][pydantic_deep.agent.create_deep_agent]. See
[Context Files](../advanced/context-files.md) for the conceptual overview.

## ContextFile

::: pydantic_deep.toolsets.context.ContextFile
    options:
      show_source: false

## ContextToolset

::: pydantic_deep.toolsets.context.ContextToolset
    options:
      show_source: false

## discover_context_files

::: pydantic_deep.toolsets.context.discover_context_files
    options:
      show_source: false

## load_context_files

::: pydantic_deep.toolsets.context.load_context_files
    options:
      show_source: false

## format_context_prompt

::: pydantic_deep.toolsets.context.format_context_prompt
    options:
      show_source: false
