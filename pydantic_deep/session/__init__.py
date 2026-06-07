"""UI-agnostic streaming session layer.

This package factors the *agent → UI event* translation — historically
duplicated in the Textual TUI worker (`apps/cli/screens/chat.py`) and the ACP
adapter (`apps/acp/server.py`) — into a single reusable place so every
frontend (Textual, ACP, the WebSocket gateway powering the desktop app) shares
one contract.

The core entry point is :func:`run_session`, which drives ``agent.iter()`` and
emits a typed stream of :class:`SessionEvent` values via an async callback,
returning a :class:`RunOutcome`.
"""

from __future__ import annotations

from pydantic_deep.session.events import (
    RunCancelled,
    RunCompleted,
    RunError,
    RunStarted,
    SessionEvent,
    TextDelta,
    ThinkingDelta,
    ToolCallResult,
    ToolCallStarted,
)
from pydantic_deep.session.mapping import (
    TOOL_KIND_MAP,
    looks_like_tool_error,
    tool_kind,
    tool_title,
)
from pydantic_deep.session.runner import (
    CancelToken,
    EventSink,
    RunOutcome,
    run_session,
)

__all__ = [
    "TOOL_KIND_MAP",
    "CancelToken",
    "EventSink",
    "RunCancelled",
    "RunCompleted",
    "RunError",
    "RunOutcome",
    "RunStarted",
    "SessionEvent",
    "TextDelta",
    "ThinkingDelta",
    "ToolCallResult",
    "ToolCallStarted",
    "looks_like_tool_error",
    "run_session",
    "tool_kind",
    "tool_title",
]
