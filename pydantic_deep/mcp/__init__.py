"""MCP (Model Context Protocol) client support for pydantic-deep.

Declarative server configs (:class:`MCPServerConfig` / :class:`MCPAuth`), a
secret-aware :class:`MCPRegistry` that builds connected pydantic-ai toolsets,
curated built-in servers, and a connection probe. The optional ``mcp`` extra
provides the underlying transport (``pip install 'pydantic-deep[mcp]'``).
"""

from __future__ import annotations

from pydantic_deep.mcp.builtins import BUILTIN_MCP_NAMES, builtin_mcp_servers
from pydantic_deep.mcp.config import (
    MCPAuth,
    MCPAuthKind,
    MCPConfigError,
    MCPServerConfig,
    MCPTransport,
)
from pydantic_deep.mcp.loader import expand_env_vars, parse_mcp_servers
from pydantic_deep.mcp.registry import (
    MCP_INSTALL_HINT,
    MCPNotInstalledError,
    MCPProbeResult,
    MCPRegistry,
    SecretResolver,
    auth_satisfied,
    build_mcp_server,
    make_resilient,
    probe_mcp_server,
)

__all__ = [
    "MCPAuth",
    "MCPAuthKind",
    "MCPConfigError",
    "MCPServerConfig",
    "MCPTransport",
    "MCPRegistry",
    "MCPProbeResult",
    "MCPNotInstalledError",
    "MCP_INSTALL_HINT",
    "SecretResolver",
    "auth_satisfied",
    "build_mcp_server",
    "make_resilient",
    "probe_mcp_server",
    "builtin_mcp_servers",
    "BUILTIN_MCP_NAMES",
    "parse_mcp_servers",
    "expand_env_vars",
]
