"""Tests for CLI loop detection middleware."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai_middleware import ToolDecision, ToolPermissionResult

from pydantic_deep.cli.middleware.loop_detection import (
    LoopDetectionMiddleware,
    _hash_args,
)


class TestHashArgs:
    """Tests for _hash_args()."""

    def test_same_args_produce_same_hash(self) -> None:
        args = {"command": "python test.py", "timeout": 30}
        assert _hash_args(args) == _hash_args(args)

    def test_different_args_produce_different_hash(self) -> None:
        args1 = {"command": "python test.py"}
        args2 = {"command": "python other.py"}
        assert _hash_args(args1) != _hash_args(args2)

    def test_order_independent(self) -> None:
        args1 = {"a": 1, "b": 2}
        args2 = {"b": 2, "a": 1}
        assert _hash_args(args1) == _hash_args(args2)

    def test_handles_non_serializable(self) -> None:
        """Should fall back to str() for non-JSON-serializable args."""
        args: dict[str, Any] = {"obj": object()}
        result = _hash_args(args)
        assert isinstance(result, str)


class TestLoopDetectionMiddleware:
    """Tests for LoopDetectionMiddleware."""

    @pytest.fixture()
    def middleware(self) -> LoopDetectionMiddleware:
        return LoopDetectionMiddleware(max_repeats=3, window_size=15)

    async def test_allows_first_call(self, middleware: LoopDetectionMiddleware) -> None:
        result = await middleware.before_tool_call(
            "execute", {"command": "python test.py"}
        )
        assert isinstance(result, dict)
        assert result == {"command": "python test.py"}

    async def test_allows_different_calls(
        self, middleware: LoopDetectionMiddleware
    ) -> None:
        for i in range(5):
            result = await middleware.before_tool_call(
                "execute", {"command": f"python test{i}.py"}
            )
            assert isinstance(result, dict)

    async def test_allows_up_to_max_repeats(
        self, middleware: LoopDetectionMiddleware
    ) -> None:
        args = {"command": "python test.py"}

        # First 3 calls should be allowed (max_repeats=3 means 4th is denied)
        for i in range(3):
            result = await middleware.before_tool_call("execute", args)
            assert isinstance(result, dict), f"Call {i+1} should be allowed"

    async def test_denies_after_max_repeats(
        self, middleware: LoopDetectionMiddleware
    ) -> None:
        args = {"command": "python test.py"}

        # First 3 calls allowed
        for _ in range(3):
            await middleware.before_tool_call("execute", args)

        # 4th call should be denied
        result = await middleware.before_tool_call("execute", args)
        assert isinstance(result, ToolPermissionResult)
        assert result.decision == ToolDecision.DENY
        assert "Loop detected" in (result.reason or "")

    async def test_different_tools_tracked_separately(
        self, middleware: LoopDetectionMiddleware
    ) -> None:
        args = {"path": "/test"}

        for _ in range(3):
            await middleware.before_tool_call("read_file", args)

        # Different tool with same args should be allowed
        result = await middleware.before_tool_call("write_file", args)
        assert isinstance(result, dict)

    async def test_same_tool_different_args_tracked_separately(
        self, middleware: LoopDetectionMiddleware
    ) -> None:
        for _ in range(3):
            await middleware.before_tool_call("execute", {"command": "python a.py"})

        # Same tool, different args should be allowed
        result = await middleware.before_tool_call(
            "execute", {"command": "python b.py"}
        )
        assert isinstance(result, dict)

    async def test_window_size_limits_history(self) -> None:
        middleware = LoopDetectionMiddleware(max_repeats=3, window_size=5)

        # Fill window with different calls
        for i in range(10):
            await middleware.before_tool_call("read_file", {"path": f"/file{i}"})

        # Now the same call should be allowed since old entries are outside window
        args = {"command": "python test.py"}
        for _ in range(3):
            result = await middleware.before_tool_call("execute", args)
            assert isinstance(result, dict)

    async def test_custom_max_repeats(self) -> None:
        middleware = LoopDetectionMiddleware(max_repeats=1)
        args = {"command": "test"}

        # First call allowed
        result = await middleware.before_tool_call("execute", args)
        assert isinstance(result, dict)

        # Second call denied (max_repeats=1)
        result = await middleware.before_tool_call("execute", args)
        assert isinstance(result, ToolPermissionResult)
        assert result.decision == ToolDecision.DENY

    async def test_deny_reason_includes_tool_name(
        self, middleware: LoopDetectionMiddleware
    ) -> None:
        args = {"command": "python test.py"}

        for _ in range(3):
            await middleware.before_tool_call("execute", args)

        result = await middleware.before_tool_call("execute", args)
        assert isinstance(result, ToolPermissionResult)
        assert "execute" in (result.reason or "")
        assert "different approach" in (result.reason or "")
