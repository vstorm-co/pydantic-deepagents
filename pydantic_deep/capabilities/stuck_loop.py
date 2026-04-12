"""Stuck loop detection capability.

Detects repetitive agent behavior and intervenes before the agent wastes
tokens on unproductive loops. Uses ``after_tool_execute`` to track tool
call patterns and raises ``ModelRetry`` or ``StuckLoopError`` when a
pattern is detected.

Three detection patterns:

1. **Repeated identical calls** — same tool + same args N times in a row.
2. **Alternating A-B-A-B** — two tool calls alternating back and forth.
3. **No-op calls** — same tool returning the same result repeatedly.

Example:
    ```python
    from pydantic_deep import create_deep_agent
    from pydantic_deep.capabilities.stuck_loop import StuckLoopDetection

    agent = create_deep_agent(
        capabilities=[StuckLoopDetection(max_repeated=3, action="warn")],
    )
    ```
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.exceptions import ModelRetry
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.tools import ToolDefinition


class StuckLoopError(Exception):
    """Raised when the agent is stuck in a loop and action is ``"error"``.

    Attributes:
        pattern: The detected pattern type (``"repeated"``, ``"alternating"``,
            ``"noop"``).
        message: Human-readable description of the stuck loop.
    """

    def __init__(self, pattern: str, message: str) -> None:
        self.pattern = pattern
        super().__init__(message)


def _hash_args(args: dict[str, Any]) -> str:
    """Create a stable hash of tool arguments for comparison."""
    try:
        serialized = json.dumps(args, sort_keys=True, default=str)
    except (TypeError, ValueError):  # pragma: no cover
        serialized = str(args)
    return hashlib.md5(serialized.encode()).hexdigest()  # noqa: S324


def _hash_result(result: Any) -> str:
    """Create a stable hash of a tool result for comparison."""
    try:
        if isinstance(result, str):
            serialized = result
        else:
            serialized = json.dumps(result, sort_keys=True, default=str)
    except (TypeError, ValueError):  # pragma: no cover
        serialized = str(result)
    return hashlib.md5(serialized.encode()).hexdigest()  # noqa: S324


@dataclass
class StuckLoopDetection(AbstractCapability[Any]):
    """Capability that detects and breaks repetitive agent loops.

    Tracks tool calls via ``after_tool_execute`` and detects three
    patterns of stuck behavior. Per-run state isolation via ``for_run()``
    ensures concurrent runs don't interfere.

    Args:
        max_repeated: Number of repetitions before triggering (default 3).
        action: What to do when stuck — ``"warn"`` raises ``ModelRetry``
            so the model can self-correct, ``"error"`` raises
            ``StuckLoopError`` to abort the run.
        detect_repeated: Enable repeated identical call detection.
        detect_alternating: Enable A-B-A-B pattern detection.
        detect_noop: Enable no-op (same result) detection.
    """

    max_repeated: int = 3
    action: str = "warn"
    detect_repeated: bool = True
    detect_alternating: bool = True
    detect_noop: bool = True

    _call_history: list[tuple[str, str]] = field(default_factory=list, init=False, repr=False)
    """Per-run history of (tool_name, args_hash) tuples."""

    _result_history: list[tuple[str, str]] = field(default_factory=list, init=False, repr=False)
    """Per-run history of (tool_name, result_hash) tuples."""

    def __post_init__(self) -> None:
        if self.max_repeated < 2:
            raise ValueError("max_repeated must be at least 2.")
        if self.action not in ("warn", "error"):
            raise ValueError(f"action must be 'warn' or 'error', got {self.action!r}.")

    async def for_run(self, ctx: RunContext[Any]) -> StuckLoopDetection:
        """Return a fresh instance with isolated per-run state."""
        return replace(self)

    def _react(self, pattern: str, message: str) -> None:
        """Raise the appropriate exception based on configured action."""
        if self.action == "error":
            raise StuckLoopError(pattern, message)
        raise ModelRetry(message)

    def _check_repeated(self) -> str | None:
        """Check for N identical consecutive calls. Returns message or None."""
        history = self._call_history
        n = self.max_repeated
        if len(history) < n:
            return None
        tail = history[-n:]
        if all(entry == tail[0] for entry in tail):
            tool_name = tail[0][0]
            return (
                f"You called `{tool_name}` with identical arguments "
                f"{n} times in a row. Try a different approach."
            )
        return None

    def _check_alternating(self) -> str | None:
        """Check for A-B-A-B alternating pattern. Returns message or None."""
        history = self._call_history
        n = self.max_repeated * 2  # need 2*N entries for N alternations
        if len(history) < n:
            return None
        tail = history[-n:]
        a, b = tail[0], tail[1]
        if a == b:
            return None  # not alternating, it's repeated
        if all(tail[i] == (a if i % 2 == 0 else b) for i in range(n)):
            return (
                f"You're alternating between `{a[0]}` and `{b[0]}` "
                f"in a loop ({n // 2} cycles). "
                f"Step back and try a different strategy."
            )
        return None

    def _check_noop(self) -> str | None:
        """Check for N identical consecutive results. Returns message or None."""
        history = self._result_history
        n = self.max_repeated
        if len(history) < n:
            return None
        tail = history[-n:]
        if all(entry == tail[0] for entry in tail):
            tool_name = tail[0][0]
            return (
                f"`{tool_name}` returned the same result {n} times in a row. "
                f"The operation has no effect — try something different."
            )
        return None

    async def after_tool_execute(
        self,
        ctx: RunContext[Any],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: dict[str, Any],
        result: Any,
    ) -> Any:
        """Track tool calls and detect stuck patterns."""
        call_key = (call.tool_name, _hash_args(args))
        self._call_history.append(call_key)

        result_key = (call.tool_name, _hash_result(result))
        self._result_history.append(result_key)

        if self.detect_repeated:
            msg = self._check_repeated()
            if msg is not None:
                self._react("repeated", msg)

        if self.detect_alternating:
            msg = self._check_alternating()
            if msg is not None:
                self._react("alternating", msg)

        if self.detect_noop:
            msg = self._check_noop()
            if msg is not None:
                self._react("noop", msg)

        return result


__all__ = [
    "StuckLoopDetection",
    "StuckLoopError",
]
