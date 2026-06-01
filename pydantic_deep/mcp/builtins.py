"""Curated, ready-to-use MCP server definitions.

These are templates users can enable out of the box (some need a token via the
CLI ``/mcp`` login flow). :func:`builtin_mcp_servers` returns fresh copies so
callers can mutate (enable/disable) without affecting the shared definitions.
"""

from __future__ import annotations

from pydantic_deep.mcp.config import MCPAuth, MCPServerConfig

__all__ = ["builtin_mcp_servers", "BUILTIN_MCP_NAMES"]

BUILTIN_MCP_NAMES = ("github", "figma", "figma-local", "context7", "deepwiki")


def builtin_mcp_servers() -> list[MCPServerConfig]:
    """Return fresh :class:`MCPServerConfig` instances for the built-in servers.

    All are disabled by default — the user opts in via ``/mcp``.
    """
    return [
        MCPServerConfig(
            name="github",
            transport="http",
            url="https://api.githubcopilot.com/mcp/",
            description="GitHub's hosted MCP server — repos, issues, PRs, code search.",
            enabled=False,
            builtin=True,
            auth=MCPAuth(
                secret_key="GITHUB_MCP_PAT",
                kind="bearer",
                instructions=(
                    "Create a GitHub Personal Access Token at "
                    "https://github.com/settings/tokens (fine-grained or classic)."
                ),
            ),
        ),
        MCPServerConfig(
            name="figma",
            transport="http",
            url="https://mcp.figma.com/mcp",
            description=(
                "Figma's hosted MCP server (OAuth). NOTE: during Figma's beta this "
                "endpoint allowlists OAuth clients, so generic clients get a 403 at "
                "sign-in. If that happens, use 'figma-local' (Dev Mode desktop app) "
                "instead, which needs no OAuth."
            ),
            enabled=False,
            builtin=True,
            auth=MCPAuth(
                kind="oauth",
                instructions="Sign in to Figma in the browser window that opens.",
            ),
        ),
        MCPServerConfig(
            name="figma-local",
            transport="http",
            url="http://127.0.0.1:3845/mcp",
            description=(
                "Figma Dev Mode MCP (local). Requires the Figma desktop app with "
                "Dev Mode MCP server enabled (Preferences → Enable Dev Mode MCP)."
            ),
            enabled=False,
            builtin=True,
        ),
        MCPServerConfig(
            name="context7",
            transport="http",
            url="https://mcp.context7.com/mcp",
            description="Context7 — up-to-date library/framework documentation lookup.",
            enabled=False,
            builtin=True,
        ),
        MCPServerConfig(
            name="deepwiki",
            transport="http",
            url="https://mcp.deepwiki.com/mcp",
            description="DeepWiki — ask questions about any public GitHub repository.",
            enabled=False,
            builtin=True,
        ),
    ]
