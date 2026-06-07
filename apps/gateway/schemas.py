"""Wire schemas for the gateway REST + WebSocket API."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from pydantic import BaseModel

from pydantic_deep.session import SessionEvent


def event_to_dict(event: SessionEvent) -> dict[str, Any]:
    """Serialise a :class:`SessionEvent` dataclass to a JSON-ready dict.

    Every event carries a ``type`` discriminator, so the client can dispatch on
    it without ambiguity.
    """
    return asdict(event)


class CreateSessionRequest(BaseModel):
    """Body for ``POST /sessions``."""

    cwd: str | None = None
    model: str | None = None
    name: str | None = None
    agent_id: str | None = None


class SessionInfo(BaseModel):
    """Summary of a session returned by the REST API."""

    id: str
    model: str
    cwd: str
    name: str | None = None
    created_at: float
    message_count: int
    thinking: str | None = None
    temperature: float | None = None
    agent_id: str = "default"
    agent_name: str = "Assistant"
    agent_avatar: str = "◆"
    agent_color: str = "#4493f8"


class PromptRequest(BaseModel):
    """Body for the non-streaming ``POST /sessions/{id}/prompt`` helper."""

    text: str


class ConfigUpdate(BaseModel):
    """Body for ``PUT /config`` — a single key/value pair."""

    key: str
    value: Any


class RenameRequest(BaseModel):
    """Body for ``PUT /sessions/{id}/name``."""

    name: str


class ModelUpdate(BaseModel):
    """Body for ``PUT /sessions/{id}/model``."""

    model: str


class ControlsUpdate(BaseModel):
    """Body for ``PUT /sessions/{id}/settings`` — live per-session overrides."""

    thinking: str | None = None
    temperature: float | None = None


class KeyUpdate(BaseModel):
    """Body for ``PUT /keys`` — set a provider API key."""

    provider: str
    key: str


class AgentBody(BaseModel):
    """Body for creating / updating an agent profile."""

    name: str
    avatar: str = "🤖"
    color: str = "#4493f8"
    prompt: str = ""


class AgentSelect(BaseModel):
    """Body for ``PUT /sessions/{id}/agent``."""

    agent_id: str


class CwdUpdate(BaseModel):
    """Body for ``PUT /sessions/{id}/cwd``."""

    path: str


class SkillBody(BaseModel):
    """Body for ``POST /skills`` — create a project skill."""

    name: str
    description: str = ""
    content: str = ""


__all__ = [
    "AgentBody",
    "AgentSelect",
    "ConfigUpdate",
    "ControlsUpdate",
    "CreateSessionRequest",
    "CwdUpdate",
    "KeyUpdate",
    "ModelUpdate",
    "PromptRequest",
    "RenameRequest",
    "SessionInfo",
    "SkillBody",
    "event_to_dict",
]
