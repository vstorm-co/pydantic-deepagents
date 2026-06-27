# Tool Search API

Tool search defers situational toolsets so the model discovers them on demand,
keeping the active tool list small. Enabled via `tool_search=True` on
[`create_deep_agent`][pydantic_deep.agent.create_deep_agent] (off by default in
the library, on in the CLI).

## ToolSearch

`ToolSearch` is re-exported from Pydantic AI
([`pydantic_ai.capabilities.ToolSearch`](https://ai.pydantic.dev/)). Pass it via
`capabilities=[...]`, or simply set `tool_search=True` on
[`create_deep_agent`][pydantic_deep.agent.create_deep_agent] to wire it together
with the helper below.

## defer_situational_toolsets

::: pydantic_deep.features.tool_search.defer_situational_toolsets
    options:
      show_source: false
