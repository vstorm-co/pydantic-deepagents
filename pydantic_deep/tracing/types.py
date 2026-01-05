"""Tracing types and data structures for agent observability."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Protocol, TypedDict

from typing_extensions import NotRequired


class EventType(str, Enum):
    """Types of trace events."""

    AGENT_RUN_START = "agent_run_start"
    AGENT_RUN_END = "agent_run_end"
    LLM_REQUEST = "llm_request"
    LLM_RESPONSE = "llm_response"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_END = "tool_call_end"
    ERROR = "error"


@dataclass
class TraceEvent:
    """Base class for all trace events."""

    event_id: str  # Unique ID for this event
    parent_id: str | None
    timestamp: datetime
    event_type: EventType
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentRunStartEvent(TraceEvent):
    """Event emitted when agent run starts."""

    agent_name: str = ""
    prompt: str = ""
    model: str = ""

    def __post_init__(self) -> None:
        """Set event type."""
        object.__setattr__(self, "event_type", EventType.AGENT_RUN_START)


@dataclass
class AgentRunEndEvent(TraceEvent):
    """Event emitted when agent run ends."""

    agent_name: str = ""
    output: str | dict[str, Any] = ""
    duration_seconds: float = 0.0
    total_tokens: int | None = None
    success: bool = True

    def __post_init__(self) -> None:
        """Set event type."""
        object.__setattr__(self, "event_type", EventType.AGENT_RUN_END)


@dataclass
class LLMRequestEvent(TraceEvent):
    """Event emitted when LLM request is made."""

    model: str = ""
    messages_count: int = 0
    tools_count: int = 0

    def __post_init__(self) -> None:
        """Set event type."""
        object.__setattr__(self, "event_type", EventType.LLM_REQUEST)


@dataclass
class LLMResponseEvent(TraceEvent):
    """Event emitted when LLM responds."""

    model: str = ""
    duration_seconds: float = 0.0
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    finish_reason: str | None = None

    def __post_init__(self) -> None:
        """Set event type."""
        object.__setattr__(self, "event_type", EventType.LLM_RESPONSE)


@dataclass
class ToolCallStartEvent(TraceEvent):
    """Event emitted when tool call starts."""

    tool_name: str = ""
    args: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Set event type."""
        object.__setattr__(self, "event_type", EventType.TOOL_CALL_START)


@dataclass
class ToolCallEndEvent(TraceEvent):
    """Event emitted when tool call ends."""

    tool_name: str = ""
    duration_seconds: float = 0.0
    result: Any = None
    error: str | None = None
    success: bool = True

    def __post_init__(self) -> None:
        """Set event type."""
        object.__setattr__(self, "event_type", EventType.TOOL_CALL_END)


@dataclass
class ErrorEvent(TraceEvent):
    """Event emitted when an error occurs."""

    error_type: str = ""
    error_message: str = ""
    traceback: str | None = None

    def __post_init__(self) -> None:
        """Set event type."""
        object.__setattr__(self, "event_type", EventType.ERROR)


class TraceExporterProtocol(Protocol):
    """Protocol for trace exporters.

    Exporters receive trace events and send them to various backends
    (OpenTelemetry, console, file, etc.).
    """

    def export_event(self, event: TraceEvent) -> None:
        """Export a single trace event.

        Args:
            event: The trace event to export.
        """
        ...

    def flush(self) -> None:
        """Flush any buffered events.

        This is called at the end of an agent run to ensure all
        events are sent to the backend.
        """
        ...


class TraceSpan(TypedDict):
    """A traced operation with timing and metadata."""

    name: str
    type: str  # "llm", "tool", "agent"
    start_time: datetime
    end_time: NotRequired[datetime]
    duration_seconds: NotRequired[float]
    tokens: NotRequired[int]
    metadata: NotRequired[dict[str, Any]]
    children: NotRequired[list[TraceSpan]]
