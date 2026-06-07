"""Typed event model for the streaming session layer.

Every signal a frontend needs to render an agent turn is one of these frozen
dataclasses. They form a discriminated union (:data:`SessionEvent`) keyed on the
``type`` literal, so a transport (WebSocket, ACP, in-process callback) can
serialise/dispatch them uniformly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class RunStarted:
    """Emitted once when an agent turn begins."""

    type: Literal["run_started"] = "run_started"


@dataclass(frozen=True)
class TextDelta:
    """An incremental chunk of assistant-visible text."""

    text: str
    type: Literal["text_delta"] = "text_delta"


@dataclass(frozen=True)
class ThinkingDelta:
    """An incremental chunk of extended-thinking / reasoning text."""

    text: str
    type: Literal["thinking_delta"] = "thinking_delta"


@dataclass(frozen=True)
class ToolCallStarted:
    """A tool call has been requested by the model."""

    id: str
    name: str
    args: dict[str, Any] = field(default_factory=dict)
    title: str = ""
    kind: str = "other"
    type: Literal["tool_call_started"] = "tool_call_started"


@dataclass(frozen=True)
class ToolCallResult:
    """A tool call has finished executing."""

    id: str
    content: str
    is_error: bool = False
    status: Literal["completed", "error"] = "completed"
    type: Literal["tool_call_result"] = "tool_call_result"


@dataclass(frozen=True)
class RunCompleted:
    """Emitted once when an agent turn finishes normally.

    ``output`` is the agent's final output — a string for the default text
    agent, or any structured object when an ``output_type`` is configured.
    """

    output: Any = None
    type: Literal["run_completed"] = "run_completed"


@dataclass(frozen=True)
class RunCancelled:
    """Emitted when a turn is cancelled before completion."""

    type: Literal["run_cancelled"] = "run_cancelled"


@dataclass(frozen=True)
class RunError:
    """Emitted when a turn fails with an exception."""

    message: str
    type: Literal["run_error"] = "run_error"


SessionEvent = (
    RunStarted
    | TextDelta
    | ThinkingDelta
    | ToolCallStarted
    | ToolCallResult
    | RunCompleted
    | RunCancelled
    | RunError
)
"""Discriminated union of every event the session runner can emit."""


__all__ = [
    "RunCancelled",
    "RunCompleted",
    "RunError",
    "RunStarted",
    "SessionEvent",
    "TextDelta",
    "ThinkingDelta",
    "ToolCallResult",
    "ToolCallStarted",
]
