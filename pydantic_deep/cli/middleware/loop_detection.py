"""Loop detection middleware — breaks infinite tool call retries."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic_ai_middleware import AgentMiddleware, ToolDecision, ToolPermissionResult

from pydantic_deep.deps import DeepAgentDeps


def _hash_args(args: dict[str, Any]) -> str:
    """Create a stable hash of tool arguments."""
    try:
        serialized = json.dumps(args, sort_keys=True, default=str)
    except (TypeError, ValueError):  # pragma: no cover — default=str handles all types
        serialized = str(args)
    return hashlib.md5(serialized.encode()).hexdigest()


class LoopDetectionMiddleware(AgentMiddleware[DeepAgentDeps]):  # type: ignore[misc]
    """Middleware that detects repeated tool calls with identical arguments.

    When the same tool is called with the same arguments more than
    ``max_repeats`` times within the recent history window, the call
    is denied with a message asking the agent to try a different approach.

    Args:
        max_repeats: Number of identical calls before blocking. Default 3.
        window_size: Number of recent calls to track. Default 15.
    """

    def __init__(self, max_repeats: int = 3, window_size: int = 15) -> None:
        self._max_repeats = max_repeats
        self._window_size = window_size
        self._call_history: list[tuple[str, str]] = []

    async def before_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        deps: DeepAgentDeps | None = None,
        ctx: Any = None,
    ) -> dict[str, Any] | ToolPermissionResult:
        """Check for repeated tool calls and deny if loop detected."""
        key = (tool_name, _hash_args(tool_args))
        recent = self._call_history[-self._window_size :]
        repeat_count = sum(1 for k in recent if k == key)

        if repeat_count >= self._max_repeats:
            return ToolPermissionResult(
                decision=ToolDecision.DENY,
                reason=(
                    f"Loop detected: '{tool_name}' called {repeat_count + 1} times "
                    f"with the same arguments. Stop retrying and try a completely "
                    f"different approach to solve this problem."
                ),
            )

        self._call_history.append(key)
        # Trim history to window size
        if len(self._call_history) > self._window_size * 2:
            self._call_history = self._call_history[-self._window_size :]

        return tool_args


__all__ = ["LoopDetectionMiddleware"]
