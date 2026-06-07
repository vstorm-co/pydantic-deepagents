"""Agent profiles for the desktop app.

An *agent* is a reusable persona: name, avatar (emoji + colour) and an optional
custom prompt layered on top of the framework's default prompt (which already
describes the tools). The built-in ``default`` agent uses the framework prompt
verbatim. User agents persist to ``.pydantic-deep/agents.json``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import uuid4

DEFAULT_AGENT: dict[str, Any] = {
    "id": "default",
    "name": "Assistant",
    "avatar": "",  # empty → UI renders a glyph tile
    "color": "#4493f8",
    "prompt": "",  # empty → use the framework default prompt verbatim
    "builtin": True,
}


def _agents_path() -> Path:
    return Path.cwd() / ".pydantic-deep" / "agents.json"


def _load_user_agents() -> list[dict[str, Any]]:
    path = _agents_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _save_user_agents(agents: list[dict[str, Any]]) -> None:
    path = _agents_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(agents, indent=2))


def list_agents() -> list[dict[str, Any]]:
    """Return all agents — the built-in default first, then user agents."""
    return [DEFAULT_AGENT, *_load_user_agents()]


def get_agent(agent_id: str) -> dict[str, Any] | None:
    """Return one agent by id, or ``None``."""
    return next((a for a in list_agents() if a["id"] == agent_id), None)


def _normalise(data: dict[str, Any]) -> dict[str, Any]:
    avatar = str(data.get("avatar") or "")
    # Keep image data URLs/paths whole; cap only short glyph fallbacks.
    if not (avatar.startswith(("data:", "http", "blob:")) or "/" in avatar):
        avatar = avatar[:8]
    return {
        "name": str(data.get("name") or "Agent").strip()[:60] or "Agent",
        "avatar": avatar,
        "color": str(data.get("color") or "#4493f8")[:16],
        "prompt": str(data.get("prompt") or ""),
    }


def create_agent(data: dict[str, Any]) -> dict[str, Any]:
    """Create and persist a new user agent."""
    agents = _load_user_agents()
    agent = {"id": uuid4().hex[:12], "builtin": False, **_normalise(data)}
    agents.append(agent)
    _save_user_agents(agents)
    return agent


def update_agent(agent_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    """Update a user agent (the built-in default is immutable)."""
    if agent_id == "default":
        return None
    agents = _load_user_agents()
    for i, agent in enumerate(agents):
        if agent["id"] == agent_id:
            agents[i] = {"id": agent_id, "builtin": False, **_normalise(data)}
            _save_user_agents(agents)
            return agents[i]
    return None


def delete_agent(agent_id: str) -> bool:
    """Delete a user agent. The built-in default cannot be removed."""
    if agent_id == "default":
        return False
    agents = _load_user_agents()
    remaining = [a for a in agents if a["id"] != agent_id]
    if len(remaining) == len(agents):
        return False
    _save_user_agents(remaining)
    return True


def default_prompt() -> str:
    """Return the framework's default prompt (with tool descriptions)."""
    from pydantic_deep import BASE_PROMPT

    return BASE_PROMPT


__all__ = [
    "DEFAULT_AGENT",
    "create_agent",
    "default_prompt",
    "delete_agent",
    "get_agent",
    "list_agents",
    "update_agent",
]
