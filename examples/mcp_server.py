"""Example demonstrating MCP server integration.

Shows how to connect to MCP servers using pydantic-ai's MCP capability.
MCP tools appear as native tools alongside deep agent's built-in tools.
"""

import asyncio

from pydantic_ai.capabilities import MCP, PrefixTools

from pydantic_deep import DeepAgentDeps, StateBackend, create_deep_agent


async def basic_mcp():
    """Connect to a single MCP server."""
    agent = create_deep_agent(
        capabilities=[
            MCP(url="https://mcp.example.com/api"),
        ],
    )

    deps = DeepAgentDeps(backend=StateBackend())
    result = await agent.run("Use the MCP tools to complete this task", deps=deps)
    print(result.output)


async def multiple_mcp_servers():
    """Connect to multiple MCP servers with namespacing."""
    agent = create_deep_agent(
        capabilities=[
            # Namespace tools to avoid conflicts
            PrefixTools(MCP(url="https://github-mcp.example.com"), prefix="github"),
            PrefixTools(MCP(url="https://slack-mcp.example.com"), prefix="slack"),
        ],
    )

    deps = DeepAgentDeps(backend=StateBackend())
    result = await agent.run(
        "Create a GitHub issue and notify the team on Slack",
        deps=deps,
    )
    print(result.output)


async def local_mcp_server():
    """Connect to a local MCP server via stdio."""
    agent = create_deep_agent(
        capabilities=[
            MCP(
                command="npx",
                args=["-y", "@modelcontextprotocol/server-filesystem", "/workspace"],
            ),
        ],
    )

    deps = DeepAgentDeps(backend=StateBackend())
    result = await agent.run("List files in the workspace", deps=deps)
    print(result.output)


if __name__ == "__main__":
    asyncio.run(basic_mcp())
