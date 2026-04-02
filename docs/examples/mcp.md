# MCP Server Example

This example demonstrates connecting to MCP servers for external tool integration.

## Source Code

:material-file-code: `examples/mcp_server.py`

## Overview

[MCP (Model Context Protocol)](https://modelcontextprotocol.io/) servers provide external tools that the agent can use. pydantic-deep supports MCP through pydantic-ai's native `MCP` capability.

## Examples

### Single MCP Server

```python
from pydantic_ai.capabilities import MCP
from pydantic_deep import create_deep_agent

agent = create_deep_agent(
    capabilities=[
        MCP(url="https://mcp.example.com/api"),
    ],
)
```

### Multiple Servers with Namespacing

```python
from pydantic_ai.capabilities import MCP, PrefixTools

agent = create_deep_agent(
    capabilities=[
        PrefixTools(MCP(url="https://github-mcp.example.com"), prefix="github"),
        PrefixTools(MCP(url="https://slack-mcp.example.com"), prefix="slack"),
    ],
)
```

### Local MCP Server (stdio)

```python
from pydantic_ai.capabilities import MCP

agent = create_deep_agent(
    capabilities=[
        MCP(
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem", "/workspace"],
        ),
    ],
)
```

### MCP with Subagents

```python
from pydantic_ai.capabilities import MCP

mcp = MCP(url="https://mcp.example.com/api")

agent = create_deep_agent(
    capabilities=[mcp],
    subagent_extra_toolsets=[mcp.get_toolset()],
)
```

## How It Works

MCP tools appear as native tools alongside the agent's built-in tools (filesystem, web, memory). The agent doesn't need to know the tools come from MCP -- it just uses them.

The `MCP` capability handles:
- Connection management (HTTP, WebSocket, stdio)
- Tool discovery and schema mapping
- Provider adaptation (builtin MCP when supported, local fallback)
- Authentication (token-based, OAuth)

## Learn More

- [MCP Guide](../advanced/mcp.md) -- Full MCP documentation
- [pydantic-ai MCP docs](https://ai.pydantic.dev/mcp/) -- Upstream reference
- [modelcontextprotocol.io](https://modelcontextprotocol.io/) -- MCP specification
