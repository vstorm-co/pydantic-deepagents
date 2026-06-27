"""Parse the standard ``mcpServers`` JSON shape into :class:`MCPServerConfig`.

This is the format used by Claude Code, Claude Desktop, Cursor, VS Code and the
MCP spec — ``.mcp.json`` / ``~/.claude.json`` entries look like::

    {"mcpServers": {"github": {"type": "http", "url": "...", "headers": {...}},
                     "db": {"command": "npx", "args": [...], "env": {...}}}}

so importing existing configs (with their tokens in ``env``/``headers``) lets a
server work immediately without re-configuring it.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from pydantic_deep.mcp.config import MCPServerConfig, MCPTransport

__all__ = ["parse_mcp_servers", "expand_env_vars"]

logger = logging.getLogger(__name__)

# ${VAR} and ${VAR:-default}, matching Claude Code's expansion syntax.
_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def expand_env_vars(value: str) -> str:
    """Expand ``${VAR}`` / ``${VAR:-default}`` against the environment.

    An unset variable with no default is left as-is (so it's visibly unresolved
    rather than silently blanked).
    """

    def _repl(match: re.Match[str]) -> str:
        var, default = match.group(1), match.group(2)
        env_val = os.environ.get(var)
        if env_val is not None:
            return env_val
        if default is not None:
            return default
        return match.group(0)

    return _VAR_RE.sub(_repl, value)


def _expand(value: Any) -> str:
    """Expand env vars in a string; coerce any non-string to `str`.

    JSON configs occasionally carry numeric args (``"args": [8080]``); coercing
    here keeps the `list[str]`/`dict[str, str]` contracts intact instead of
    letting an `int` reach the transport and `TypeError` at connect (B13).
    """
    return expand_env_vars(value) if isinstance(value, str) else str(value)


def parse_mcp_servers(
    servers: dict[str, dict[str, Any]], *, enabled: bool = True
) -> list[MCPServerConfig]:
    """Convert a ``mcpServers`` mapping to :class:`MCPServerConfig` list.

    Recognises stdio (``command``), HTTP (``type: http``/``streamable-http`` or a
    bare ``url``) and SSE (``type: sse``). WebSocket (``type: ws``) and malformed
    entries are skipped. ``${VAR}`` references in command/args/env/url/headers are
    expanded. Tokens already present in ``env``/``headers`` are carried over.
    """
    out: list[MCPServerConfig] = []
    for name, entry in servers.items():
        if not isinstance(entry, dict):
            logger.warning("Skipping MCP server %r: entry is not an object", name)
            continue
        transport_type = entry.get("type")
        try:
            if entry.get("command"):
                config = MCPServerConfig(
                    name=name,
                    transport="stdio",
                    command=_expand(entry["command"]),
                    args=[_expand(a) for a in entry.get("args", [])],
                    env={k: _expand(v) for k, v in entry.get("env", {}).items()},
                    enabled=enabled,
                )
            elif entry.get("url") and transport_type != "ws":
                transport: MCPTransport = "sse" if transport_type == "sse" else "http"
                config = MCPServerConfig(
                    name=name,
                    transport=transport,
                    url=_expand(entry["url"]),
                    headers={k: _expand(v) for k, v in entry.get("headers", {}).items()},
                    enabled=enabled,
                )
            else:
                logger.warning(
                    "Skipping MCP server %r: unsupported shape (WebSocket or no command/url)",
                    name,
                )
                continue
        except Exception:
            # Skip a malformed entry rather than abort the whole import, but say
            # which one and why so it isn't silently lost (B13).
            logger.warning("Skipping malformed MCP server %r", name, exc_info=True)
            continue
        out.append(config)
    return out
