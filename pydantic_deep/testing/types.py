"""Types for deterministic testing infrastructure."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


@dataclass
class RecordedRequest:
    """A recorded LLM request."""

    # Request metadata
    timestamp: str
    model: str
    messages_count: int
    tools_count: int

    # Full request data
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    tool_choice: Any | None = None
    temperature: float | None = None
    max_tokens: int | None = None

    # For matching during replay
    request_hash: str = ""  # Hash of messages + tools for matching


@dataclass
class RecordedResponse:
    """A recorded LLM response."""

    # Response metadata
    timestamp: str
    model: str
    finish_reason: str

    # Token usage
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    # Response content
    content: str | None = None
    tool_calls: list[dict[str, Any]] | None = None

    # Full response data
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass
class RecordedInteraction:
    """A single request-response interaction."""

    request: RecordedRequest
    response: RecordedResponse

    # Metadata
    interaction_id: int
    duration_seconds: float


@dataclass
class FixtureFile:
    """A fixture file containing recorded interactions."""

    # Metadata
    version: str = "1.0"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    model: str = ""
    description: str = ""

    # Recorded interactions
    interactions: list[RecordedInteraction] = field(default_factory=list)

    # Statistics
    total_interactions: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0


class FixtureValidationError(Exception):
    """Raised when fixture validation fails."""

    pass


class ReplayMismatchError(Exception):
    """Raised when replay request doesn't match recorded request."""

    pass


RecordMode = Literal["record", "replay", "passthrough"]
