"""Audit and permission middleware for DeepResearch.

- AuditMiddleware: tracks tool usage stats (call count, duration, breakdown)
- PermissionMiddleware: blocks access to sensitive paths
"""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai_middleware import AgentMiddleware, ToolDecision, ToolPermissionResult

from pydantic_deep.deps import DeepAgentDeps

logger = logging.getLogger(__name__)


@dataclass
class ToolUsageStats:
    """Accumulated tool usage statistics."""

    call_count: int = 0
    total_duration_ms: float = 0
    last_tool: str = ""
    tools_used: dict[str, int] = field(default_factory=lambda: defaultdict(int))


class AuditMiddleware(AgentMiddleware[DeepAgentDeps]):
    """Middleware that tracks tool usage for frontend display."""

    def __init__(self) -> None:
        self.stats = ToolUsageStats()
        self._tool_start_times: dict[str, float] = {}

    def get_stats(self) -> ToolUsageStats:
        return self.stats

    def reset_stats(self) -> None:
        self.stats = ToolUsageStats()
        self._tool_start_times.clear()

    async def before_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        deps: DeepAgentDeps | None = None,
        ctx: Any = None,
    ) -> dict[str, Any]:
        self._tool_start_times[tool_name] = time.monotonic()
        return tool_args

    async def after_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        result: Any,
        deps: DeepAgentDeps | None = None,
        ctx: Any = None,
    ) -> Any:
        self.stats.call_count += 1
        self.stats.last_tool = tool_name
        self.stats.tools_used[tool_name] += 1

        start = self._tool_start_times.pop(tool_name, None)
        if start is not None:
            duration = (time.monotonic() - start) * 1000
            self.stats.total_duration_ms += duration

        return result


# Patterns for sensitive paths that should be blocked
BLOCKED_PATH_PATTERNS = [
    r"/etc/passwd",
    r"/etc/shadow",
    r"\.env$",
    r"\.env\.",
    r"/root/",
    r"\.ssh/",
    r"/proc/",
    r"/sys/",
    r"id_rsa",
    r"id_ed25519",
]

# File-related tools whose path arguments should be checked
FILE_TOOLS = {"read_file", "write_file", "edit_file", "glob", "grep"}


class PermissionMiddleware(AgentMiddleware[DeepAgentDeps]):
    """Middleware that blocks access to sensitive paths."""

    async def before_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        deps: DeepAgentDeps | None = None,
        ctx: Any = None,
    ) -> dict[str, Any] | ToolPermissionResult:
        if tool_name not in FILE_TOOLS:
            return tool_args

        path = tool_args.get("path", "") or tool_args.get("pattern", "")

        for pattern in BLOCKED_PATH_PATTERNS:
            if re.search(pattern, str(path)):
                logger.warning(
                    f"PermissionMiddleware BLOCKED: {tool_name}(path={path}) "
                    f"matches pattern '{pattern}'"
                )
                return ToolPermissionResult(
                    decision=ToolDecision.DENY,
                    reason=f"Access denied: path matches blocked pattern '{pattern}'",
                )

        return tool_args
