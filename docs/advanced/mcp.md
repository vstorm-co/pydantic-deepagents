# MCP Servers

pydantic-deep supports [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) servers through pydantic-ai's built-in `MCP` capability. MCP tools appear as native tools alongside filesystem, web, and other deep agent tools.

## Quick Start

```python
from pydantic_ai.capabilities import MCP
from pydantic_deep import create_deep_agent

agent = create_deep_agent(
    capabilities=[
        MCP(url="https://mcp.example.com/api"),
    ],
)
```

## Multiple MCP Servers

Use `PrefixTools` to namespace tools from different servers:

```python
from pydantic_ai.capabilities import MCP, PrefixTools

agent = create_deep_agent(
    capabilities=[
        PrefixTools(MCP(url="https://github-mcp.example.com"), prefix="github"),
        PrefixTools(MCP(url="https://slack-mcp.example.com"), prefix="slack"),
    ],
)
```

## Local MCP Servers (stdio)

Connect to local MCP servers via stdio transport:

```python
from pydantic_ai.capabilities import MCP

agent = create_deep_agent(
    capabilities=[
        MCP(command="npx", args=["-y", "@modelcontextprotocol/server-filesystem", "/workspace"]),
    ],
)
```

## MCP with Subagents

Pass MCP capabilities to subagents via `subagent_extra_toolsets`:

```python
from pydantic_ai.capabilities import MCP

mcp = MCP(url="https://mcp.example.com/api")

agent = create_deep_agent(
    capabilities=[mcp],
    # Subagents also get access to the MCP server
    subagent_extra_toolsets=[mcp.get_toolset()],
)
```

## How It Works

The `MCP` capability from pydantic-ai handles:

- **Connection management** — connects to MCP server, discovers tools
- **Tool wrapping** — MCP tools appear as native agent tools with proper schemas
- **Provider adaptation** — uses builtin MCP support when the model supports it (e.g., Anthropic), falls back to local transport otherwise
- **Authentication** — supports token-based and OAuth auth

pydantic-deep adds no MCP-specific code — it's all pydantic-ai native. Any pydantic-ai capability works with `create_deep_agent(capabilities=[...])`.

## Learn More

- [pydantic-ai MCP docs](https://ai.pydantic.dev/mcp/) — Full MCP reference
- [pydantic-ai Capabilities](https://ai.pydantic.dev/capabilities/) — All built-in capabilities
- [modelcontextprotocol.io](https://modelcontextprotocol.io/) — MCP specification
