"""Tests for the goal-completion engine (`pydantic_deep.goal`)."""

from __future__ import annotations

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from pydantic_deep.goal import (
    DEFAULT_GOAL_MODEL,
    GoalEvaluation,
    GoalEvaluator,
    GoalState,
    _extract_reason,
    _first_user_text,
    _format_duration,
    _trunc,
    build_goal_transcript,
    format_goal_status,
    goal_continue_directive,
    parse_goal_command,
    parse_verdict,
)


def _reply_model(text: str) -> FunctionModel:
    """A FunctionModel that always replies with the given text."""

    def _fn(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content=text)])

    return FunctionModel(_fn)


def _raising_model() -> FunctionModel:
    def _fn(_messages: list[ModelMessage], _info: AgentInfo) -> ModelResponse:
        raise RuntimeError("boom")

    return FunctionModel(_fn)


class TestParseGoalCommand:
    def test_empty_is_status(self) -> None:
        assert parse_goal_command("") == ("status", "")
        assert parse_goal_command("   ") == ("status", "")

    @pytest.mark.parametrize("word", ["clear", "stop", "off", "reset", "none", "cancel"])
    def test_clear_aliases(self, word: str) -> None:
        assert parse_goal_command(word) == ("clear", "")
        assert parse_goal_command(word.upper()) == ("clear", "")

    def test_set_condition(self) -> None:
        action, condition = parse_goal_command("  all tests pass  ")
        assert action == "set"
        assert condition == "all tests pass"

    def test_set_truncates_to_cap(self) -> None:
        long = "x" * 5000
        action, condition = parse_goal_command(long)
        assert action == "set"
        assert len(condition) == 4000


class TestParseVerdict:
    def test_empty(self) -> None:
        v = parse_verdict("   ")
        assert v.met is False
        assert "no output" in v.reason.lower()

    def test_yes_with_reason(self) -> None:
        v = parse_verdict("YES - all tests pass")
        assert v.met is True
        assert v.reason == "all tests pass"

    def test_no_with_reason(self) -> None:
        v = parse_verdict("NO, the tests have not been run")
        assert v.met is False
        assert v.reason == "the tests have not been run"

    @pytest.mark.parametrize("word", ["met", "done", "true", "complete", "achieved", "satisfied"])
    def test_met_prefixes(self, word: str) -> None:
        assert parse_verdict(f"{word}: looks good").met is True

    @pytest.mark.parametrize("word", ["not", "false", "incomplete", "unmet", "failed"])
    def test_not_met_prefixes(self, word: str) -> None:
        assert parse_verdict(f"{word}: nope").met is False

    def test_yes_bare_default_reason(self) -> None:
        v = parse_verdict("YES")
        assert v.met is True
        assert v.reason == "Condition met."

    def test_no_bare_default_reason(self) -> None:
        v = parse_verdict("NO")
        assert v.met is False
        assert v.reason == "Condition not yet met."

    def test_multiline_reason_falls_back_to_rest(self) -> None:
        v = parse_verdict("YES\nEvery test passed cleanly")
        assert v.met is True
        assert v.reason == "Every test passed cleanly"

    def test_ambiguous_is_not_met(self) -> None:
        v = parse_verdict("Maybe, it depends on the deploy")
        assert v.met is False
        assert v.reason.startswith("Maybe")

    def test_ambiguous_reason_truncated(self) -> None:
        v = parse_verdict("perhaps " * 100)
        assert v.met is False
        assert len(v.reason) <= 200


class TestExtractReason:
    def test_no_verdict_word_returns_head(self) -> None:
        assert _extract_reason("just some text", "rest") == "just some text"

    def test_falls_back_to_rest_when_head_only_verdict(self) -> None:
        assert _extract_reason("YES", "the rest line") == "the rest line"


class TestTranscript:
    def test_first_user_text_none(self) -> None:
        assert _first_user_text([]) is None
        # ModelResponse only — no user prompt
        assert _first_user_text([ModelResponse(parts=[TextPart(content="hi")])]) is None

    def test_first_user_text_skips_non_str(self) -> None:
        msgs: list[ModelMessage] = [
            ModelRequest(parts=[UserPromptPart(content=["image-ish", "parts"])]),
            ModelRequest(parts=[UserPromptPart(content="real goal")]),
        ]
        assert _first_user_text(msgs) == "real goal"

    def test_empty_transcript(self) -> None:
        assert build_goal_transcript([]) == "(no conversation yet)"

    def test_full_transcript_render(self) -> None:
        msgs: list[ModelMessage] = [
            ModelRequest(parts=[UserPromptPart(content="Fix the auth bug")]),
            ModelResponse(
                parts=[
                    TextPart(content="Running the tests now"),
                    ToolCallPart(tool_name="execute", args={"cmd": "pytest"}),
                ]
            ),
            ModelRequest(
                parts=[ToolReturnPart(tool_name="execute", content="3 passed", tool_call_id="1")]
            ),
            ModelResponse(parts=[TextPart(content="   ")]),  # blank assistant text skipped
        ]
        out = build_goal_transcript(msgs)
        assert "[Original request] Fix the auth bug" in out
        assert "[Assistant] Running the tests now" in out
        assert "[Tool call: execute]" in out
        assert "[Tool result: execute] 3 passed" in out
        # Blank assistant text produced no extra [Assistant] line
        assert out.count("[Assistant]") == 1

    def test_request_part_neither_user_nor_tool_return(self) -> None:
        from pydantic_ai.messages import SystemPromptPart

        msgs: list[ModelMessage] = [
            ModelRequest(
                parts=[
                    SystemPromptPart(content="system context"),
                    UserPromptPart(content=["non-str", "content"]),
                ]
            ),
        ]
        # Neither part renders a line; transcript collapses to the placeholder.
        assert build_goal_transcript(msgs) == "(no conversation yet)"

    def test_recent_window_limits_messages(self) -> None:
        msgs: list[ModelMessage] = [
            ModelRequest(parts=[UserPromptPart(content="original")]),
        ]
        for i in range(20):
            msgs.append(ModelResponse(parts=[TextPart(content=f"turn {i}")]))
        out = build_goal_transcript(msgs, max_recent=3)
        # Original request always anchored
        assert "[Original request] original" in out
        # Only the last 3 messages rendered in detail
        assert "turn 19" in out
        assert "turn 0" not in out

    def test_trunc(self) -> None:
        assert _trunc("short", 100) == "short"
        long = _trunc("a" * 50, 10)
        assert long.startswith("a" * 10)
        assert "truncated" in long


class TestFormatDuration:
    def test_seconds(self) -> None:
        assert _format_duration(5) == "5s"

    def test_minutes(self) -> None:
        assert _format_duration(125) == "2m5s"

    def test_hours(self) -> None:
        assert _format_duration(3725) == "1h2m"


class TestGoalState:
    def test_is_active(self) -> None:
        state = GoalState(condition="x")
        assert state.is_active is True
        state.achieved = True
        assert state.is_active is False

    def test_record_not_met(self) -> None:
        state = GoalState(condition="x")
        state.record(GoalEvaluation(met=False, reason="nope", input_tokens=3, output_tokens=2))
        assert state.turns == 1
        assert state.achieved is False
        assert state.last_reason == "nope"
        assert state.input_tokens == 3
        assert state.output_tokens == 2

    def test_record_met(self) -> None:
        state = GoalState(condition="x")
        state.record(GoalEvaluation(met=True, reason="done"))
        assert state.achieved is True

    def test_exhausted(self) -> None:
        state = GoalState(condition="x", max_turns=2)
        assert state.exhausted is False
        state.record(GoalEvaluation(met=False, reason="a"))
        state.record(GoalEvaluation(met=False, reason="b"))
        assert state.exhausted is True

    def test_exhausted_false_when_achieved(self) -> None:
        state = GoalState(condition="x", max_turns=1)
        state.record(GoalEvaluation(met=True, reason="done"))
        assert state.exhausted is False


class TestFormatGoalStatus:
    def test_active_minimal(self) -> None:
        state = GoalState(condition="ship it")
        out = format_goal_status(state)
        assert "Goal (active): ship it" in out
        assert "Turns evaluated: 0" in out
        assert "Running for" not in out
        assert "Evaluator tokens" not in out
        assert "Latest" not in out

    def test_achieved_full(self) -> None:
        state = GoalState(
            condition="ship it",
            turns=4,
            achieved=True,
            last_reason="all green",
            input_tokens=10,
            output_tokens=5,
        )
        out = format_goal_status(state, elapsed_seconds=65)
        assert "Goal (achieved): ship it" in out
        assert "Running for 1m5s" in out
        assert "Turns evaluated: 4" in out
        assert "Evaluator tokens: 15" in out
        assert "Latest: all green" in out


def test_goal_continue_directive() -> None:
    out = goal_continue_directive("all tests pass", "tests not run yet")
    assert "all tests pass" in out
    assert "tests not run yet" in out
    assert "concrete evidence" in out


class TestGoalEvaluator:
    async def test_evaluate_met(self) -> None:
        evaluator = GoalEvaluator(model=_reply_model("YES - everything passes"))
        msgs: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart(content="pass tests")])]
        result = await evaluator.evaluate("tests pass", msgs)
        assert result.met is True
        assert result.reason == "everything passes"
        assert result.output_tokens > 0

    async def test_evaluate_not_met(self) -> None:
        evaluator = GoalEvaluator(model=_reply_model("NO - still failing"))
        result = await evaluator.evaluate("tests pass", [])
        assert result.met is False
        assert result.reason == "still failing"

    async def test_evaluate_handles_exception(self) -> None:
        evaluator = GoalEvaluator(model=_raising_model())
        result = await evaluator.evaluate("tests pass", [])
        assert result.met is False
        assert "Evaluator error" in result.reason

    async def test_agent_is_cached(self) -> None:
        evaluator = GoalEvaluator(model=_reply_model("YES"))
        first = evaluator._get_agent()
        second = evaluator._get_agent()
        assert first is second

    def test_default_model_constant(self) -> None:
        assert isinstance(DEFAULT_GOAL_MODEL, str)
        assert GoalEvaluator().model == DEFAULT_GOAL_MODEL
