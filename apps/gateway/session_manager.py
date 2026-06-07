"""In-process session lifecycle for the gateway.

Owns one agent + deps + history per session, drives turns through the shared
`pydantic_deep.session.run_session`, and supports cancellation. Agent
construction is injectable so tests can supply a deterministic model.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from pydantic_ai.messages import ModelMessage

from pydantic_deep.session import (
    CancelToken,
    EventSink,
    RunError,
    RunOutcome,
    RunStarted,
    run_session,
)

# Stat callbacks bound to a session and passed into agent construction.
CostCallback = Callable[[Any], None]
ContextCallback = Callable[[float, int, int], None]

# A factory returns (agent, deps) for a session. Injectable for testing.
AgentFactory = Callable[
    [str | None, str | None, str, CostCallback, ContextCallback, dict[str, Any]],
    tuple[Any, Any],
]


def _default_factory(
    model: str | None,
    cwd: str | None,
    session_id: str,
    on_cost: CostCallback,
    on_context: ContextCallback,
    controls: dict[str, Any],
) -> tuple[Any, Any]:
    """Build a fully-configured CLI agent (lazy import to keep startup light).

    ``controls`` carries live per-session overrides (e.g. thinking effort,
    temperature) applied on top of the configured defaults.
    """
    from apps.cli.agent import create_cli_agent

    # The desktop app works on the real local filesystem by default (not Docker).
    kwargs: dict[str, Any] = {"sandbox": controls.get("sandbox", "local")}
    thinking = controls.get("thinking")
    if thinking is not None:
        kwargs["thinking"] = False if thinking == "off" else thinking
    if controls.get("temperature") is not None:
        kwargs["temperature"] = controls["temperature"]
    if controls.get("extra_instructions"):
        kwargs["extra_instructions"] = controls["extra_instructions"]

    return create_cli_agent(
        model=model,
        working_dir=cwd,
        non_interactive=True,
        session_id=session_id,
        on_cost_update=on_cost,
        on_context_update=on_context,
        **kwargs,
    )


@dataclass
class GatewaySession:
    """Runtime state for one gateway session."""

    id: str
    model: str
    cwd: str
    agent: Any = None
    deps: Any = None
    name: str | None = None
    name_custom: bool = False  # True once the user renames it manually
    agent_id: str = "default"
    agent_name: str = "Assistant"
    agent_avatar: str = "◆"
    agent_color: str = "#4493f8"
    created_at: float = field(default_factory=time.time)
    history: list[ModelMessage] = field(default_factory=list)
    cancel_token: CancelToken | None = None
    # Deferred agent builder — the agent is constructed lazily on first run so
    # the UI loads even before a provider/API key is configured.
    builder: Callable[[], tuple[Any, Any]] | None = None
    build_error: str | None = None
    # Live per-session overrides (thinking, temperature, …) applied at build.
    controls: dict[str, Any] = field(default_factory=dict)
    # Latest cost / context stats, updated by agent callbacks.
    cost: dict[str, float] = field(default_factory=dict)
    context: dict[str, float] = field(default_factory=dict)

    @property
    def message_count(self) -> int:
        return len(self.history)

    def stats(self) -> dict[str, Any]:
        """Snapshot of session stats for the `session_stats` event."""
        return {
            "type": "session_stats",
            "cost": self.cost,
            "context": self.context,
            "message_count": self.message_count,
        }


class SessionManager:
    """Creates, tracks, runs, and tears down gateway sessions."""

    def __init__(
        self,
        *,
        default_model: str = "anthropic:claude-sonnet-4-6",
        agent_factory: AgentFactory | None = None,
    ) -> None:
        self._default_model = default_model
        self._factory: AgentFactory = agent_factory or _default_factory
        self._sessions: dict[str, GatewaySession] = {}

    def create(
        self,
        *,
        cwd: str | None = None,
        model: str | None = None,
        name: str | None = None,
        agent_id: str | None = None,
    ) -> GatewaySession:
        """Create and register a new session."""
        session_id = uuid4().hex[:12]
        session = GatewaySession(
            id=session_id,
            model=model or self._default_model,
            cwd=cwd or ".",
            name=name,
        )
        self._apply_agent(session, agent_id or "default")

        def on_cost(info: Any) -> None:
            session.cost = {
                "run_usd": float(getattr(info, "run_cost_usd", 0) or 0),
                "total_usd": float(getattr(info, "total_cost_usd", 0) or 0),
                "input": float(getattr(info, "total_request_tokens", 0) or 0),
                "output": float(getattr(info, "total_response_tokens", 0) or 0),
            }

        def on_context(pct: float, current: int, maximum: int) -> None:
            session.context = {"pct": float(pct), "current": float(current), "max": float(maximum)}

        # Defer the (potentially expensive / key-requiring) agent build to the
        # first turn so creating a session never fails. The builder reads
        # `session.model` / `session.controls` at call time so a model or
        # control switch just resets the agent.
        session.builder = lambda: self._factory(
            session.model, session.cwd, session_id, on_cost, on_context, session.controls
        )
        self._sessions[session_id] = session
        return session

    def _apply_agent(self, session: GatewaySession, agent_id: str) -> bool:
        """Apply an agent profile (name/avatar/prompt) to a session."""
        from apps.gateway.agents import get_agent

        profile = get_agent(agent_id) or get_agent("default")
        assert profile is not None  # the default agent always exists
        session.agent_id = profile["id"]
        session.agent_name = profile["name"]
        session.agent_avatar = profile["avatar"]
        session.agent_color = profile["color"]
        if profile["prompt"]:
            session.controls = {**session.controls, "extra_instructions": profile["prompt"]}
        else:
            session.controls = {
                k: v for k, v in session.controls.items() if k != "extra_instructions"
            }
        return True

    def set_agent(self, session_id: str, agent_id: str) -> bool:
        """Switch a session's agent profile; the underlying agent rebuilds lazily."""
        session = self.get(session_id)
        if session is None:
            return False
        self._apply_agent(session, agent_id)
        session.agent = None  # rebuild with the new prompt
        session.build_error = None
        return True

    def _ensure_agent(self, session: GatewaySession) -> str | None:
        """Build the session's agent on first use. Returns an error message or None."""
        if session.agent is not None:
            return None
        if session.builder is None:  # pragma: no cover - always set by create()
            return "Session has no agent builder."
        try:
            agent, deps = session.builder()
        except Exception as exc:
            session.build_error = _friendly_build_error(exc)
            return session.build_error
        session.agent = agent
        session.deps = deps
        session.build_error = None
        return None

    def get(self, session_id: str) -> GatewaySession | None:
        """Return a session by id, or ``None`` if unknown."""
        return self._sessions.get(session_id)

    def list(self) -> list[GatewaySession]:
        """Return all live sessions, newest first."""
        return sorted(self._sessions.values(), key=lambda s: s.created_at, reverse=True)

    def delete(self, session_id: str) -> bool:
        """Remove a session; cancels an in-flight run first. Returns success."""
        session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        if session.cancel_token is not None:
            session.cancel_token.cancel()
        return True

    def rename(self, session_id: str, name: str) -> bool:
        """Set a session's display name (marks it as user-chosen)."""
        session = self.get(session_id)
        if session is None:
            return False
        session.name = name
        session.name_custom = True
        return True

    def set_cwd(self, session_id: str, cwd: str) -> bool:
        """Switch a session's working directory; the agent rebuilds lazily."""
        session = self.get(session_id)
        if session is None:
            return False
        session.cwd = cwd
        session.agent = None  # rebuild rooted at the new directory
        session.build_error = None
        return True

    def set_model(self, session_id: str, model: str) -> bool:
        """Switch a session's model; the agent rebuilds lazily on the next turn."""
        session = self.get(session_id)
        if session is None:
            return False
        session.model = model
        session.agent = None  # force a rebuild with the new model (history kept)
        session.build_error = None
        return True

    def reset_all_agents(self) -> None:
        """Force every session to rebuild its agent (e.g. after a key change)."""
        for session in self._sessions.values():
            session.agent = None
            session.build_error = None

    def set_controls(self, session_id: str, controls: dict[str, Any]) -> bool:
        """Merge live control overrides (thinking, temperature); rebuild lazily."""
        session = self.get(session_id)
        if session is None:
            return False
        session.controls = {**session.controls, **controls}
        session.agent = None  # rebuild with new controls (history kept)
        session.build_error = None
        return True

    def cancel(self, session_id: str) -> bool:
        """Request cancellation of a session's in-flight run."""
        session = self.get(session_id)
        if session is None or session.cancel_token is None:
            return False
        session.cancel_token.cancel()
        return True

    async def run(self, session_id: str, text: str, on_event: EventSink) -> RunOutcome:
        """Run one turn for a session, streaming events and updating history."""
        session = self.get(session_id)
        if session is None:
            raise KeyError(session_id)

        # Auto-name the session from the user's message unless renamed manually.
        if not session.name_custom:
            session.name = _session_name(text)

        build_error = self._ensure_agent(session)
        if build_error is not None:
            await on_event(RunStarted())
            await on_event(RunError(build_error))
            return RunOutcome(error=build_error)

        token = CancelToken()
        session.cancel_token = token
        try:
            outcome = await run_session(
                session.agent,
                text,
                deps=session.deps,
                message_history=session.history,
                on_event=on_event,
                cancel=token,
            )
        finally:
            session.cancel_token = None
        session.history = outcome.messages
        return outcome


def _session_name(text: str, *, limit: int = 60) -> str:
    """Derive a short session title from the user's message.

    Strips any attachment preamble, collapses whitespace, and truncates so the
    sidebar stays compact regardless of message length.
    """
    body = text
    marker = "Attached files in the workspace:"
    if body.startswith(marker) and "\n\n" in body:
        body = body.split("\n\n", 1)[1]
    # First non-empty line, whitespace-collapsed.
    line = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
    line = " ".join(line.split())
    if not line:
        return "New chat"
    return line if len(line) <= limit else line[:limit].rstrip() + "…"


def _friendly_build_error(exc: Exception) -> str:
    """Turn an agent-construction exception into a user-facing hint."""
    text = str(exc)
    if "API_KEY" in text or "api_key" in text:
        return (
            "No API key configured. Set your provider's key (e.g. "
            "ANTHROPIC_API_KEY) in the environment, then start a new session. "
            f"Details: {text}"
        )
    return f"Failed to start the agent: {text}"


__all__ = ["AgentFactory", "GatewaySession", "SessionManager"]
