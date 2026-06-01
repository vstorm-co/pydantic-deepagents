"""Persistence + wiring for MCP servers in the CLI.

User-defined servers and per-builtin enabled-state live in
``.pydantic-deep/mcp.json``; auth tokens live in the keystore (``keys.toml``,
git-ignored). This module merges the built-in catalogue with user config into a
single :class:`~pydantic_deep.mcp.MCPRegistry`, backed by a keystore + env
secret resolver.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from apps.cli.config import get_project_dir
from apps.cli.keystore import get_stored_keys, remove_key, save_key
from pydantic_deep.mcp import (
    MCPNotInstalledError,
    MCPRegistry,
    MCPServerConfig,
    SecretResolver,
    builtin_mcp_servers,
    parse_mcp_servers,
)

__all__ = [
    "mcp_config_path",
    "mcp_secret_resolver",
    "mcp_oauth_storage",
    "load_mcp_registry",
    "save_mcp_registry",
    "mcp_login",
    "mcp_logout",
    "build_mcp_servers_for_agent",
    "claude_code_config_paths",
    "import_claude_code_servers",
]


def mcp_config_path() -> Path:
    """Path to the per-project MCP config file."""
    return get_project_dir() / "mcp.json"


def mcp_secret_resolver() -> SecretResolver:
    """Resolve secrets from the live environment, falling back to the keystore."""

    def _resolve(key: str) -> str | None:
        return os.environ.get(key) or get_stored_keys().get(key)

    return _resolve


def mcp_oauth_storage() -> object | None:
    """Persistent, user-level OAuth token store for hosted MCP servers.

    Tokens (e.g. for the hosted Figma server) are cached on disk under
    ``~/.pydantic-deep/mcp-oauth`` and keyed by server URL, so authorizing once
    (via ``/mcp`` test) works for the agent too and survives restarts. Returns
    ``None`` if the disk store backend isn't installed (falls back to in-memory).
    """
    try:
        from key_value.aio.stores.disk import DiskStore
    except Exception:
        return None
    path = Path.home() / ".pydantic-deep" / "mcp-oauth"
    try:
        path.mkdir(parents=True, exist_ok=True)
        return DiskStore(directory=str(path))
    except Exception:
        return None


def _read_config() -> dict:
    path = mcp_config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def load_mcp_registry(resolver: SecretResolver | None = None) -> MCPRegistry:
    """Build a registry merging built-in servers with user config + overrides."""
    data = _read_config()
    builtin_state: dict[str, dict] = data.get("builtin_state", {})
    user_servers: list[dict] = data.get("user_servers", [])

    configs: list[MCPServerConfig] = []
    for builtin in builtin_mcp_servers():
        override = builtin_state.get(builtin.name)
        if override is not None and "enabled" in override:
            builtin.enabled = bool(override["enabled"])
        configs.append(builtin)

    for raw in user_servers:
        try:
            configs.append(MCPServerConfig.from_dict(raw))
        except Exception:
            continue  # skip malformed user entries rather than crash startup

    return MCPRegistry(
        configs,
        resolver=resolver or mcp_secret_resolver(),
        oauth_token_storage=mcp_oauth_storage(),
    )


def save_mcp_registry(registry: MCPRegistry) -> None:
    """Persist user servers + per-builtin enabled-state to ``mcp.json``."""
    builtin_state: dict[str, dict] = {}
    user_servers: list[dict] = []
    for config in registry.list_servers():
        if config.builtin:
            builtin_state[config.name] = {"enabled": config.enabled}
        else:
            user_servers.append(config.to_dict())

    path = mcp_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"builtin_state": builtin_state, "user_servers": user_servers}
    path.write_text(json.dumps(payload, indent=2) + "\n")


def mcp_login(secret_key: str, token: str) -> None:
    """Store an MCP auth token in the keystore (and current environment)."""
    save_key(secret_key, token)


def mcp_logout(secret_key: str) -> None:
    """Revoke a stored MCP token: remove from keystore and the live environment."""
    remove_key(secret_key)
    os.environ.pop(secret_key, None)


def claude_code_config_paths(project_dir: Path | None = None) -> list[Path]:
    """Claude Code MCP config files: project ``.mcp.json`` + ``~/.claude.json``."""
    root = project_dir or Path.cwd()
    return [root / ".mcp.json", Path.home() / ".claude.json"]


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def import_claude_code_servers(project_dir: Path | None = None) -> list[MCPServerConfig]:
    """Read MCP servers already configured in Claude Code.

    Merges Claude Code's three scopes with its precedence (local > project >
    user): user-scope ``~/.claude.json`` ``mcpServers``, project ``.mcp.json``,
    then this project's local-scope entry in ``~/.claude.json``. Tokens in
    ``env``/``headers`` carry over, so imported servers work immediately.
    """
    root = (project_dir or Path.cwd()).resolve()
    merged: dict[str, dict] = {}

    home = _read_json(Path.home() / ".claude.json")
    # user scope (lowest precedence)
    user_servers = home.get("mcpServers")
    if isinstance(user_servers, dict):
        merged.update(user_servers)
    # project scope
    project = _read_json(root / ".mcp.json")
    project_servers = project.get("mcpServers")
    if isinstance(project_servers, dict):
        merged.update(project_servers)
    # local scope (highest precedence) — this project's entry in ~/.claude.json
    projects = home.get("projects")
    if isinstance(projects, dict):
        entry = projects.get(str(root))
        if isinstance(entry, dict) and isinstance(entry.get("mcpServers"), dict):
            merged.update(entry["mcpServers"])

    return parse_mcp_servers(merged, enabled=True)


def build_mcp_servers_for_agent(on_degraded: object | None = None) -> list:
    """Build all ready (enabled + authenticated) MCP server toolsets.

    ``on_degraded(name, reason)`` is forwarded to each server's resilient
    wrapper and fires once if the server turns out unreachable at runtime.
    Returns an empty list if the optional ``mcp`` dependency is missing, so the
    agent still starts without MCP support.
    """
    registry = load_mcp_registry()
    try:
        return registry.build_active(on_degraded=on_degraded)  # type: ignore[arg-type]
    except MCPNotInstalledError:
        return []
