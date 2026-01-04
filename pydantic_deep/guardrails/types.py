"""Guardrail types and protocols for agent safety."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class GuardrailViolation(Exception):
    """Raised when a guardrail is violated."""

    pass


@dataclass
class GuardrailResult:
    """Result of a guardrail check."""

    passed: bool
    message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolCall:
    """Represents a tool call in the agent's history."""

    tool_name: str
    args: dict[str, Any]
    result: Any = None
    error: str | None = None
    timestamp: float = 0.0


@dataclass
class GuardrailContext:
    """Context passed to guardrails during checks."""

    # Agent state
    agent_name: str
    run_id: str
    iteration_count: int

    # Resource usage
    total_tokens: int
    total_cost_usd: float
    duration_seconds: float

    # Tool history
    tool_calls: list[ToolCall]
    last_n_tools: list[str]  # For detecting loops

    # Custom metadata
    metadata: dict[str, Any] = field(default_factory=dict)


class GuardrailProtocol(Protocol):
    """Protocol for all guardrails."""

    def check(self, context: GuardrailContext) -> GuardrailResult:
        """Check if the guardrail passes.

        Args:
            context: Current guardrail context.

        Returns:
            Result indicating if the check passed.
        """
        ...

    def on_violation(self, context: GuardrailContext) -> None:
        """Called when guardrail is violated.

        Args:
            context: Current guardrail context.
        """
        ...
