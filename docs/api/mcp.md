# MCP API

Model Context Protocol (MCP) client support. Build MCP server toolsets and attach
them to an agent via the `mcp_servers` parameter of
[`create_deep_agent`][pydantic_deep.agent.create_deep_agent]. See
[MCP servers](../learn/web-and-mcp.md) for the conceptual overview.

## build_mcp_server

::: pydantic_deep.mcp.build_mcp_server
    options:
      show_source: false

## probe_mcp_server

::: pydantic_deep.mcp.probe_mcp_server
    options:
      show_source: false

## create_mcp_resources_toolset

Most MCP servers are used for their tools, but a server can also publish
*resources* — docs, templates, or FastMCP `skill://.../SKILL.md` skills. pydantic-ai
surfaces only the tools to the model, so set `include_resources=True` (or
`include_skills=True` for skills specifically) on an
[`MCPServerConfig`][pydantic_deep.mcp.MCPServerConfig] and build with
[`MCPRegistry.build_active`][pydantic_deep.mcp.MCPRegistry] to attach a second
toolset that lets the model discover and read them:

```python
from pydantic_deep.mcp import MCPRegistry, MCPServerConfig

registry = MCPRegistry([
    MCPServerConfig(
        name="service",
        transport="http",
        url="https://example.com/mcp/",
        include_skills=True,  # exposes list_mcp_skills / load_mcp_skill
    ),
])
mcp_servers = registry.build_active()  # tools toolset + resources toolset
```

The resources toolset adds `list_mcp_resources` / `read_mcp_resource`, plus
`list_mcp_skills` / `load_mcp_skill` when `include_skills` is set. It binds to the
same underlying `MCPToolset`, so tools and resources share one connection. Use
`create_mcp_resources_toolset` directly to wrap a server you built yourself.

::: pydantic_deep.mcp.create_mcp_resources_toolset
    options:
      show_source: false

## builtin_mcp_servers

::: pydantic_deep.mcp.builtin_mcp_servers
    options:
      show_source: false

## auth_satisfied

::: pydantic_deep.mcp.auth_satisfied
    options:
      show_source: false

## parse_mcp_servers

::: pydantic_deep.mcp.parse_mcp_servers
    options:
      show_source: false

## MCPServerConfig

::: pydantic_deep.mcp.MCPServerConfig
    options:
      show_source: false

## MCPAuth

::: pydantic_deep.mcp.MCPAuth
    options:
      show_source: false

## MCPRegistry

::: pydantic_deep.mcp.MCPRegistry
    options:
      show_source: false

## MCPProbeResult

::: pydantic_deep.mcp.MCPProbeResult
    options:
      show_source: false

## MCPNotInstalledError

::: pydantic_deep.mcp.MCPNotInstalledError
    options:
      show_source: false
