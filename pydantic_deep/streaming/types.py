"""Types for streaming agent execution.

This module defines the event types and data structures used for
streaming real-time updates during agent execution.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class StreamEventType(str, Enum):
    """Types of events emitted during streaming execution."""

    LLM_CHUNK = "llm_chunk"
    """Text chunk from LLM streaming response."""

    TOOL_START = "tool_start"
    """Tool call is starting."""

    TOOL_END = "tool_end"
    """Tool call has completed."""

    PROGRESS = "progress"
    """Progress update with iteration/token counts."""

    PARTIAL_RESULT = "partial_result"
    """Partial result available before completion."""

    ERROR = "error"
    """Error occurred during execution."""

    AGENT_START = "agent_start"
    """Agent execution started."""

    AGENT_END = "agent_end"
    """Agent execution completed."""


@dataclass
class StreamEvent:
    """Event emitted during streaming execution.

    Each event represents a discrete update during agent execution,
    such as a text chunk, tool call, or progress update.

    Attributes:
        event_type: Type of event
        timestamp: When the event occurred
        data: Event-specific data payload
    """

    event_type: StreamEventType
    timestamp: datetime = field(default_factory=datetime.now)
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate event data based on type."""
        if self.event_type == StreamEventType.LLM_CHUNK:
            if "text" not in self.data:
                raise ValueError("LLM_CHUNK events must include 'text' in data")
        elif self.event_type in (StreamEventType.TOOL_START, StreamEventType.TOOL_END):
            if "tool_name" not in self.data:
                raise ValueError(f"{self.event_type.name} events must include 'tool_name'")
        elif self.event_type == StreamEventType.PROGRESS and "iteration" not in self.data:
            raise ValueError("PROGRESS events must include 'iteration' in data")


# Helper functions for creating events
def llm_chunk_event(text: str, **extra: Any) -> StreamEvent:
    """Create an LLM chunk event.

    Args:
        text: The text chunk from the LLM
        **extra: Additional data to include in the event

    Returns:
        StreamEvent with LLM_CHUNK type
    """
    return StreamEvent(
        event_type=StreamEventType.LLM_CHUNK,
        data={"text": text, **extra},
    )


def tool_start_event(
    tool_name: str, args: dict[str, Any] | None = None, **extra: Any
) -> StreamEvent:
    """Create a tool start event.

    Args:
        tool_name: Name of the tool being called
        args: Arguments passed to the tool
        **extra: Additional data to include in the event

    Returns:
        StreamEvent with TOOL_START type
    """
    data = {"tool_name": tool_name, **extra}
    if args is not None:
        data["args"] = args
    return StreamEvent(event_type=StreamEventType.TOOL_START, data=data)


def tool_end_event(
    tool_name: str,
    result: Any = None,
    error: str | None = None,
    duration_seconds: float | None = None,
    **extra: Any,
) -> StreamEvent:
    """Create a tool end event.

    Args:
        tool_name: Name of the tool that completed
        result: Result returned by the tool
        error: Error message if tool failed
        duration_seconds: How long the tool took to execute
        **extra: Additional data to include in the event

    Returns:
        StreamEvent with TOOL_END type
    """
    data = {"tool_name": tool_name, **extra}
    if result is not None:
        data["result"] = result
    if error is not None:
        data["error"] = error
    if duration_seconds is not None:
        data["duration_seconds"] = duration_seconds
    return StreamEvent(event_type=StreamEventType.TOOL_END, data=data)


def progress_event(
    iteration: int,
    total_tokens: int | None = None,
    total_cost_usd: float | None = None,
    max_iterations: int | None = None,
    **extra: Any,
) -> StreamEvent:
    """Create a progress event.

    Args:
        iteration: Current iteration number
        total_tokens: Total tokens used so far
        total_cost_usd: Total cost in USD so far
        max_iterations: Maximum iterations allowed
        **extra: Additional data to include in the event

    Returns:
        StreamEvent with PROGRESS type
    """
    data = {"iteration": iteration, **extra}
    if total_tokens is not None:
        data["total_tokens"] = total_tokens
    if total_cost_usd is not None:
        data["total_cost_usd"] = total_cost_usd
    if max_iterations is not None:
        data["max_iterations"] = max_iterations
    return StreamEvent(event_type=StreamEventType.PROGRESS, data=data)


def partial_result_event(result: Any, complete: bool = False, **extra: Any) -> StreamEvent:
    """Create a partial result event.

    Args:
        result: The partial result
        complete: Whether this is the final result
        **extra: Additional data to include in the event

    Returns:
        StreamEvent with PARTIAL_RESULT type
    """
    return StreamEvent(
        event_type=StreamEventType.PARTIAL_RESULT,
        data={"result": result, "complete": complete, **extra},
    )


def error_event(error: str, exception_type: str | None = None, **extra: Any) -> StreamEvent:
    """Create an error event.

    Args:
        error: Error message
        exception_type: Type of exception that occurred
        **extra: Additional data to include in the event

    Returns:
        StreamEvent with ERROR type
    """
    data = {"error": error, **extra}
    if exception_type is not None:
        data["exception_type"] = exception_type
    return StreamEvent(event_type=StreamEventType.ERROR, data=data)


def agent_start_event(agent_name: str, prompt: str, **extra: Any) -> StreamEvent:
    """Create an agent start event.

    Args:
        agent_name: Name of the agent
        prompt: User prompt being processed
        **extra: Additional data to include in the event

    Returns:
        StreamEvent with AGENT_START type
    """
    return StreamEvent(
        event_type=StreamEventType.AGENT_START,
        data={"agent_name": agent_name, "prompt": prompt, **extra},
    )


def agent_end_event(
    agent_name: str,
    success: bool = True,
    total_iterations: int | None = None,
    total_tokens: int | None = None,
    total_cost_usd: float | None = None,
    **extra: Any,
) -> StreamEvent:
    """Create an agent end event.

    Args:
        agent_name: Name of the agent
        success: Whether execution completed successfully
        total_iterations: Total iterations performed
        total_tokens: Total tokens used
        total_cost_usd: Total cost in USD
        **extra: Additional data to include in the event

    Returns:
        StreamEvent with AGENT_END type
    """
    data = {"agent_name": agent_name, "success": success, **extra}
    if total_iterations is not None:
        data["total_iterations"] = total_iterations
    if total_tokens is not None:
        data["total_tokens"] = total_tokens
    if total_cost_usd is not None:
        data["total_cost_usd"] = total_cost_usd
    return StreamEvent(event_type=StreamEventType.AGENT_END, data=data)
