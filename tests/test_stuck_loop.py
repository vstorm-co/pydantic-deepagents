"""Tests for StuckLoopDetection capability."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import RunContext, ToolDefinition
from pydantic_ai.usage import RunUsage

from pydantic_deep import (
    StuckLoopDetection,
    StuckLoopError,
    create_deep_agent,
)

TEST_MODEL = TestModel()


def _ctx() -> RunContext[Any]:
    return RunContext(deps=None, model=TEST_MODEL, usage=RunUsage())


def _call(name: str = "grep", call_id: str = "c1") -> ToolCallPart:
    return ToolCallPart(tool_name=name, args={}, tool_call_id=call_id)


def _td(name: str = "grep") -> ToolDefinition:
    return ToolDefinition(name=name, description="")


async def _fire(
    cap: StuckLoopDetection,
    tool_name: str = "grep",
    args: dict[str, Any] | None = None,
    result: Any = "ok",
) -> Any:
    """Helper to call after_tool_execute."""
    return await cap.after_tool_execute(
        _ctx(),
        call=_call(tool_name),
        tool_def=_td(tool_name),
        args=args or {},
        result=result,
    )


class TestValidation:
    """Tests for constructor validation."""

    def test_max_repeated_too_low(self):
        with pytest.raises(ValueError, match="max_repeated must be at least 2"):
            StuckLoopDetection(max_repeated=1)

    def test_invalid_action(self):
        with pytest.raises(ValueError, match="action must be"):
            StuckLoopDetection(action="crash")

    def test_valid_construction(self):
        cap = StuckLoopDetection(max_repeated=5, action="error")
        assert cap.max_repeated == 5
        assert cap.action == "error"


class TestRepeatedDetection:
    """Tests for repeated identical call detection."""

    async def test_no_trigger_below_threshold(self):
        """Calls below threshold pass through."""
        cap = StuckLoopDetection(max_repeated=3)
        await _fire(cap, "grep", {"pattern": "foo"}, "result1")
        result = await _fire(cap, "grep", {"pattern": "foo"}, "result2")
        assert result == "result2"

    async def test_trigger_on_repeated_calls(self):
        """Same tool + same args N times raises ModelRetry."""
        from pydantic_ai.exceptions import ModelRetry

        cap = StuckLoopDetection(max_repeated=3)
        await _fire(cap, "grep", {"pattern": "foo"})
        await _fire(cap, "grep", {"pattern": "foo"})
        with pytest.raises(ModelRetry, match="grep.*identical arguments.*3 times"):
            await _fire(cap, "grep", {"pattern": "foo"})

    async def test_different_args_no_trigger(self):
        """Same tool with different args doesn't trigger."""
        cap = StuckLoopDetection(max_repeated=3, detect_noop=False)
        await _fire(cap, "grep", {"pattern": "foo"})
        await _fire(cap, "grep", {"pattern": "bar"})
        result = await _fire(cap, "grep", {"pattern": "baz"})
        assert result == "ok"

    async def test_different_tools_no_trigger(self):
        """Different tools don't trigger repeated detection."""
        cap = StuckLoopDetection(max_repeated=3)
        await _fire(cap, "grep", {"pattern": "foo"})
        await _fire(cap, "read_file", {"pattern": "foo"})
        result = await _fire(cap, "grep", {"pattern": "foo"})
        assert result == "ok"

    async def test_error_action_raises_stuck_loop_error(self):
        """action='error' raises StuckLoopError instead of ModelRetry."""
        cap = StuckLoopDetection(max_repeated=2, action="error")
        await _fire(cap, "grep", {"pattern": "foo"})
        with pytest.raises(StuckLoopError, match="grep.*identical") as exc_info:
            await _fire(cap, "grep", {"pattern": "foo"})
        assert exc_info.value.pattern == "repeated"

    async def test_disabled_repeated(self):
        """detect_repeated=False skips repeated detection."""
        cap = StuckLoopDetection(max_repeated=2, detect_repeated=False, detect_noop=False)
        await _fire(cap, "grep", {"pattern": "foo"})
        # Would normally trigger, but detection is disabled
        result = await _fire(cap, "grep", {"pattern": "foo"})
        assert result == "ok"


class TestAlternatingDetection:
    """Tests for A-B-A-B alternating pattern detection."""

    async def test_trigger_on_alternating(self):
        """A-B-A-B pattern triggers after max_repeated*2 calls."""
        from pydantic_ai.exceptions import ModelRetry

        cap = StuckLoopDetection(max_repeated=2)
        # Need 2*2=4 calls: A-B-A-B
        await _fire(cap, "grep", {"p": "x"})
        await _fire(cap, "read_file", {"path": "/a"})
        await _fire(cap, "grep", {"p": "x"})
        with pytest.raises(ModelRetry, match="alternating.*grep.*read_file"):
            await _fire(cap, "read_file", {"path": "/a"})

    async def test_no_trigger_three_different_tools(self):
        """Three different tools in rotation don't trigger A-B detection."""
        cap = StuckLoopDetection(max_repeated=2)
        await _fire(cap, "grep")
        await _fire(cap, "read_file")
        await _fire(cap, "write_file")
        result = await _fire(cap, "grep")
        assert result == "ok"

    async def test_no_trigger_when_first_two_tail_entries_equal(self):
        """When tail[0] == tail[1], it's not alternating — no trigger."""
        # With max_repeated=2, need 4 calls. Make history: A-A-B-B
        # tail = [A, A, B, B]: tail[0]==tail[1] so early return None (line 144)
        cap = StuckLoopDetection(max_repeated=2, detect_repeated=False, detect_noop=False)
        await _fire(cap, "grep", {"p": "a"})
        await _fire(cap, "grep", {"p": "a"})
        await _fire(cap, "read_file", {"path": "/a"})
        result = await _fire(cap, "read_file", {"path": "/a"})
        assert result == "ok"

    async def test_disabled_alternating(self):
        """detect_alternating=False skips alternating detection."""
        cap = StuckLoopDetection(max_repeated=2, detect_alternating=False)
        await _fire(cap, "grep", {"p": "x"})
        await _fire(cap, "read_file", {"path": "/a"})
        await _fire(cap, "grep", {"p": "x"})
        result = await _fire(cap, "read_file", {"path": "/a"})
        assert result == "ok"


class TestNoopDetection:
    """Tests for no-op (same result) detection."""

    async def test_trigger_on_same_result(self):
        """Same tool returning same result N times triggers (different args each time)."""
        from pydantic_ai.exceptions import ModelRetry

        cap = StuckLoopDetection(max_repeated=3, detect_repeated=False)
        await _fire(cap, "list_files", {"path": "/a"}, ["a.py", "b.py"])
        await _fire(cap, "list_files", {"path": "/b"}, ["a.py", "b.py"])
        with pytest.raises(ModelRetry, match="list_files.*same result.*3 times"):
            await _fire(cap, "list_files", {"path": "/c"}, ["a.py", "b.py"])

    async def test_different_results_no_trigger(self):
        """Same tool with different results doesn't trigger."""
        cap = StuckLoopDetection(max_repeated=3, detect_repeated=False)
        await _fire(cap, "grep", {"p": "a"}, "match 1")
        await _fire(cap, "grep", {"p": "b"}, "match 2")
        result = await _fire(cap, "grep", {"p": "c"}, "match 3")
        assert result == "match 3"

    async def test_disabled_noop(self):
        """detect_noop=False skips no-op detection."""
        cap = StuckLoopDetection(max_repeated=2, detect_noop=False, detect_repeated=False)
        await _fire(cap, "list_files", {}, ["a.py"])
        result = await _fire(cap, "list_files", {}, ["a.py"])
        assert result == ["a.py"]


class TestForRun:
    """Tests for per-run state isolation."""

    async def test_for_run_resets_state(self):
        """for_run returns fresh instance with empty history."""
        cap = StuckLoopDetection(max_repeated=3)
        await _fire(cap, "grep", {"pattern": "foo"})
        await _fire(cap, "grep", {"pattern": "foo"})
        assert len(cap._call_history) == 2

        fresh = await cap.for_run(_ctx())
        assert fresh is not cap
        assert fresh._call_history == []
        assert fresh._result_history == []
        assert fresh.max_repeated == 3
        assert fresh.action == "warn"

    async def test_concurrent_isolation(self):
        """Concurrent runs don't share state."""
        cap = StuckLoopDetection(max_repeated=3)
        run1 = await cap.for_run(_ctx())
        run2 = await cap.for_run(_ctx())

        await _fire(run1, "grep", {"pattern": "foo"})
        await _fire(run1, "grep", {"pattern": "foo"})
        assert len(run1._call_history) == 2
        assert len(run2._call_history) == 0


class TestEdgeCases:
    """Tests for edge cases."""

    async def test_non_serializable_args(self):
        """Non-JSON-serializable args don't crash."""
        cap = StuckLoopDetection(max_repeated=3)
        obj = object()
        result = await _fire(cap, "tool", {"obj": obj})
        assert result == "ok"

    async def test_non_serializable_result(self):
        """Non-JSON-serializable result doesn't crash."""
        cap = StuckLoopDetection(max_repeated=3)
        result = await _fire(cap, "tool", {}, result=object())
        assert result is not None

    async def test_max_repeated_2(self):
        """Minimum threshold of 2 works."""
        from pydantic_ai.exceptions import ModelRetry

        cap = StuckLoopDetection(max_repeated=2)
        await _fire(cap, "grep", {"p": "x"})
        with pytest.raises(ModelRetry):
            await _fire(cap, "grep", {"p": "x"})

    async def test_repeated_detected_before_noop(self):
        """Repeated detection fires before noop (same args + same result)."""
        from pydantic_ai.exceptions import ModelRetry

        cap = StuckLoopDetection(max_repeated=2)
        await _fire(cap, "grep", {"p": "x"}, "same")
        with pytest.raises(ModelRetry, match="identical arguments"):
            await _fire(cap, "grep", {"p": "x"}, "same")


class TestStuckLoopError:
    """Tests for StuckLoopError exception."""

    def test_attributes(self):
        err = StuckLoopError("repeated", "test message")
        assert err.pattern == "repeated"
        assert str(err) == "test message"

    def test_is_exception(self):
        assert issubclass(StuckLoopError, Exception)


class TestAgentIntegration:
    """Tests for create_deep_agent integration."""

    def _has_stuck_loop(self, agent: object) -> bool:
        root = getattr(agent, "_root_capability", None)
        if root is None:
            return False  # pragma: no cover
        for cap in getattr(root, "capabilities", []):
            if isinstance(cap, StuckLoopDetection):
                return True
        return False

    def test_enabled_by_default(self):
        agent = create_deep_agent(
            model=TEST_MODEL,
            include_subagents=False,
            include_skills=False,
            cost_tracking=False,
        )
        assert self._has_stuck_loop(agent)

    def test_disabled(self):
        agent = create_deep_agent(
            model=TEST_MODEL,
            include_subagents=False,
            include_skills=False,
            cost_tracking=False,
            stuck_loop_detection=False,
        )
        assert not self._has_stuck_loop(agent)


class TestExports:
    """Tests for package exports."""

    def test_stuck_loop_detection_importable(self):
        from pydantic_deep import StuckLoopDetection as Imported

        assert Imported is StuckLoopDetection

    def test_stuck_loop_error_importable(self):
        from pydantic_deep import StuckLoopError as Imported

        assert Imported is StuckLoopError
