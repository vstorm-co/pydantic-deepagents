"""Tests for the UI-agnostic streaming session layer (`pydantic_deep.session`)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.models.test import TestModel

from pydantic_deep.session import (
    CancelToken,
    RunOutcome,
    SessionEvent,
    looks_like_tool_error,
    run_session,
    tool_kind,
    tool_title,
)


class _Collector:
    """Async event sink that records every emitted event."""

    def __init__(self) -> None:
        self.events: list[SessionEvent] = []

    async def __call__(self, event: SessionEvent) -> None:
        self.events.append(event)

    def types(self) -> list[str]:
        return [e.type for e in self.events]

    def of(self, type_: str) -> list[Any]:
        return [e for e in self.events if e.type == type_]


def _agent_with_tool(return_value: str) -> Agent[None, str]:
    agent: Agent[None, str] = Agent(model=TestModel())

    @agent.tool_plain
    def do_thing(x: str) -> str:  # pragma: no cover - body exercised via the agent
        return return_value

    return agent


# --- mapping helpers -------------------------------------------------------


class TestMapping:
    def test_tool_kind_known_and_unknown(self) -> None:
        assert tool_kind("read_file") == "read"
        assert tool_kind("execute") == "execute"
        assert tool_kind("mystery") == "other"

    @pytest.mark.parametrize(
        ("args", "expected"),
        [
            ({"path": "/a/b.py"}, "t: /a/b.py"),
            ({"pattern": "foo"}, "t: foo"),
            ({"command": "ls -la"}, "t: ls -la"),
            ({"description": "do it"}, "t: do it"),
            ({}, "t"),
            ("not-a-dict", "t"),
        ],
    )
    def test_tool_title(self, args: Any, expected: str) -> None:
        assert tool_title("t", args) == expected

    def test_tool_title_truncates(self) -> None:
        title = tool_title("t", {"command": "x" * 100}, max_len=10)
        assert title == "t: " + "x" * 10

    def test_looks_like_tool_error(self) -> None:
        assert looks_like_tool_error("") is False
        assert looks_like_tool_error("all good") is False
        assert looks_like_tool_error("Error: boom") is True
        assert looks_like_tool_error("Traceback (most recent call last)") is True


# --- CancelToken -----------------------------------------------------------


def test_cancel_token() -> None:
    token = CancelToken()
    assert token.cancelled is False
    token.cancel()
    assert token.cancelled is True


# --- runner ----------------------------------------------------------------


class TestRunSession:
    async def test_plain_text_run(self) -> None:
        agent: Agent[None, str] = Agent(model=TestModel())
        col = _Collector()
        outcome = await run_session(agent, "hello", deps=None, on_event=col)
        types = col.types()
        assert types[0] == "run_started"
        assert "text_delta" in types
        assert types[-1] == "run_completed"
        assert outcome.error is None
        assert outcome.cancelled is False
        assert outcome.messages
        assert isinstance(outcome.output, str)

    async def test_tool_call_and_result(self) -> None:
        agent = _agent_with_tool("ok")
        col = _Collector()
        await run_session(agent, "go", deps=None, on_event=col)
        started = col.of("tool_call_started")
        results = col.of("tool_call_result")
        assert started and started[0].name == "do_thing"
        assert started[0].kind == "other"
        assert results and results[0].content == "ok"
        assert results[0].is_error is False
        assert results[0].status == "completed"

    async def test_tool_error_result(self) -> None:
        agent = _agent_with_tool("Error: it broke")
        col = _Collector()
        await run_session(agent, "go", deps=None, on_event=col)
        result = col.of("tool_call_result")[0]
        assert result.is_error is True
        assert result.status == "error"

    async def test_tool_empty_result(self) -> None:
        agent = _agent_with_tool("")
        col = _Collector()
        await run_session(agent, "go", deps=None, on_event=col)
        result = col.of("tool_call_result")[0]
        assert result.content == ""
        assert result.is_error is False

    async def test_thinking_delta_streamed(self) -> None:
        from pydantic_ai.models.function import DeltaThinkingCalls, DeltaThinkingPart

        async def _stream(_messages: list[ModelMessage], _info: AgentInfo) -> Any:
            # First chunk → PartStartEvent(ThinkingPart); second → ThinkingPartDelta.
            yield DeltaThinkingCalls({0: DeltaThinkingPart(content="first")})
            yield DeltaThinkingCalls({0: DeltaThinkingPart(content="second")})
            yield "the answer"

        agent: Agent[None, str] = Agent(model=FunctionModel(stream_function=_stream))
        col = _Collector()
        await run_session(agent, "go", deps=None, on_event=col)
        thinking = [e.text for e in col.of("thinking_delta")]
        assert thinking == ["first", "second"]
        assert "text_delta" in col.types()

    async def test_cancel_before_run(self) -> None:
        agent: Agent[None, str] = Agent(model=TestModel())
        col = _Collector()
        token = CancelToken()
        token.cancel()
        outcome = await run_session(agent, "hi", deps=None, on_event=col, cancel=token)
        assert outcome.cancelled is True
        assert "run_cancelled" in col.types()
        assert "run_completed" not in col.types()

    async def test_error_is_captured(self) -> None:
        # A model that cannot stream raises inside agent.iter; the runner must
        # catch it, emit RunError, and report it on the outcome (never raise).
        def _fn(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
            return ModelResponse(parts=[TextPart(content="plain")])

        agent: Agent[None, str] = Agent(model=FunctionModel(_fn))
        col = _Collector()
        outcome = await run_session(agent, "hi", deps=None, message_history=[], on_event=col)
        assert isinstance(outcome, RunOutcome)
        assert outcome.error is not None
        assert "run_error" in col.types()
        assert "run_completed" not in col.types()
