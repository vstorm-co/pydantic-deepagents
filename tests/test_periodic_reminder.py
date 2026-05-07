"""Tests for PeriodicReminderCapability."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from pydantic_ai_backends import StateBackend

from pydantic_deep import create_deep_agent
from pydantic_deep.capabilities.periodic_reminder import (
    LLMReminderGenerator,
    PeriodicReminderCapability,
    PeriodicReminderConfig,
    _default_generate,
    _render,
    _should_fire,
    build_compact_transcript,
    make_config_for_mode,
)
from pydantic_deep.deps import DeepAgentDeps

_MODEL = TestModel()


def _ctx() -> RunContext[Any]:
    return RunContext(
        deps=DeepAgentDeps(backend=StateBackend()),
        model=_MODEL,
        usage=RunUsage(),
    )


def _make_messages(user_text: str = "Fix the login bug") -> list[ModelMessage]:
    return [ModelRequest(parts=[UserPromptPart(content=user_text)])]


class _FakeRequestContext:
    def __init__(self, messages: list[ModelMessage]) -> None:
        self.messages = messages


class TestShouldFire:
    def test_fires_at_every_n_turns_default(self) -> None:
        cfg = PeriodicReminderConfig(every_n_turns=5)
        assert not _should_fire(4, 0, cfg)
        assert _should_fire(5, 0, cfg)

    def test_fires_at_custom_first_after(self) -> None:
        cfg = PeriodicReminderConfig(every_n_turns=10, first_after=3)
        assert not _should_fire(2, 0, cfg)
        assert _should_fire(3, 0, cfg)

    def test_fires_every_n_after_first(self) -> None:
        cfg = PeriodicReminderConfig(every_n_turns=5, first_after=3)
        assert _should_fire(3, 0, cfg)
        assert not _should_fire(4, 1, cfg)
        assert not _should_fire(7, 1, cfg)
        assert _should_fire(8, 1, cfg)
        assert _should_fire(13, 2, cfg)

    def test_does_not_fire_before_first(self) -> None:
        cfg = PeriodicReminderConfig(every_n_turns=10)
        for turn in range(1, 5):
            assert not _should_fire(turn, 0, cfg)
        assert _should_fire(5, 0, cfg)

    def test_respects_max_reminders(self) -> None:
        cfg = PeriodicReminderConfig(every_n_turns=5, max_reminders_per_run=2)
        assert _should_fire(5, 0, cfg)
        assert _should_fire(5, 1, cfg)
        assert not _should_fire(5, 2, cfg)

    def test_max_reminders_zero(self) -> None:
        cfg = PeriodicReminderConfig(every_n_turns=5, max_reminders_per_run=0)
        assert not _should_fire(5, 0, cfg)

    def test_no_max_fires_indefinitely(self) -> None:
        cfg = PeriodicReminderConfig(every_n_turns=1, first_after=1)
        for turn in range(1, 20):
            assert _should_fire(turn, turn - 1, cfg)


class TestRender:
    def test_system_reminder_tag(self) -> None:
        result = _render("system_reminder_tag", "stay focused")
        assert result == "<system-reminder>\nstay focused\n</system-reminder>"

    def test_user_prompt_plain(self) -> None:
        result = _render("user_prompt", "stay focused")
        assert result == "stay focused"

    def test_developer_note(self) -> None:
        result = _render("developer_note", "stay focused")
        assert result == "[Developer note for the assistant: stay focused]"

    def test_unknown_style_returns_plain(self) -> None:
        result = _render("unknown_style", "hello")
        assert result == "hello"


class TestDefaultGenerate:
    def test_extracts_first_user_message(self) -> None:
        msgs = _make_messages("Do the thing")
        result = _default_generate(msgs)
        assert "Do the thing" in result
        assert "original request" in result.lower()

    def test_truncates_at_400_chars(self) -> None:
        long_text = "A" * 500
        msgs = _make_messages(long_text)
        result = _default_generate(msgs)
        assert "A" * 400 in result
        assert "A" * 401 not in result

    def test_fallback_when_no_user_message(self) -> None:
        result = _default_generate([])
        assert result == "Stay on task. Focus on completing your original objective."

    def test_fallback_when_only_non_string_content(self) -> None:
        part = UserPromptPart(content=[{"type": "text", "text": "hi"}])
        msgs: list[ModelMessage] = [ModelRequest(parts=[part])]
        result = _default_generate(msgs)
        assert result == "Stay on task. Focus on completing your original objective."

    def test_skips_non_request_messages(self) -> None:
        msgs: list[ModelMessage] = [
            ModelResponse(parts=[TextPart(content="assistant text")]),
            ModelRequest(parts=[UserPromptPart(content="actual goal")]),
        ]
        result = _default_generate(msgs)
        assert "actual goal" in result


class TestBuildCompactTranscript:
    def test_includes_original_goal(self) -> None:
        msgs = _make_messages("Fix the bug")
        result = build_compact_transcript(msgs, max_recent=5)
        assert "Fix the bug" in result
        assert "[Original goal]" in result

    def test_respects_max_recent(self) -> None:
        msgs = [ModelRequest(parts=[UserPromptPart(content=f"msg{i}")]) for i in range(20)]
        result = build_compact_transcript(msgs, max_recent=3)
        lines = result.splitlines()
        assert len(lines) <= 4

    def test_empty_messages(self) -> None:
        result = build_compact_transcript([], max_recent=5)
        assert result == "(no messages yet)"

    def test_non_request_messages_show_assistant_turn(self) -> None:
        msgs: list[ModelMessage] = [
            ModelRequest(parts=[UserPromptPart(content="goal")]),
            ModelResponse(parts=[TextPart(content="response")]),
        ]
        result = build_compact_transcript(msgs, max_recent=5)
        assert "[Assistant/Tool turn]" in result

    def test_model_request_without_str_user_part(self) -> None:
        msgs: list[ModelMessage] = [
            ModelRequest(parts=[ToolReturnPart(tool_name="t", content="r", tool_call_id="1")]),
        ]
        result = build_compact_transcript(msgs, max_recent=5)
        assert "[User]" not in result

    def test_non_request_before_first_user_message(self) -> None:
        msgs: list[ModelMessage] = [
            ModelResponse(parts=[TextPart(content="assistant preamble")]),
            ModelRequest(parts=[UserPromptPart(content="actual goal")]),
        ]
        result = build_compact_transcript(msgs, max_recent=5)
        assert "actual goal" in result
        assert "[Original goal]" in result

    def test_injected_system_reminder_not_treated_as_original_goal(self) -> None:
        injected = "<system-reminder>\nStay on task.\n</system-reminder>"
        msgs: list[ModelMessage] = [
            ModelRequest(parts=[UserPromptPart(content=injected)]),
            ModelRequest(parts=[UserPromptPart(content="real goal")]),
        ]
        result = build_compact_transcript(msgs, max_recent=5)
        assert "[Original goal] real goal" in result
        assert injected not in result

    def test_injected_reminders_excluded_from_user_entries(self) -> None:
        injected_sr = "<system-reminder>\nReminder.\n</system-reminder>"
        injected_dn = "[Developer note for the assistant: stay focused]"
        msgs: list[ModelMessage] = [
            ModelRequest(parts=[UserPromptPart(content="real goal")]),
            ModelRequest(parts=[UserPromptPart(content=injected_sr)]),
            ModelRequest(parts=[UserPromptPart(content=injected_dn)]),
        ]
        result = build_compact_transcript(msgs, max_recent=10)
        assert "[User] real goal" in result
        assert injected_sr not in result
        assert injected_dn not in result


class TestPeriodicReminderCapability:
    @pytest.mark.anyio
    async def test_for_run_resets_counters(self) -> None:
        cap = PeriodicReminderCapability(config=PeriodicReminderConfig(every_n_turns=3))
        ctx = _ctx()
        rc = _FakeRequestContext(_make_messages())
        await cap.before_model_request(ctx, rc)
        await cap.before_model_request(ctx, rc)
        assert cap._turn_counter == 2

        fresh = await cap.for_run(ctx)
        assert fresh is not cap
        assert fresh._turn_counter == 0
        assert fresh._reminder_count == 0

    @pytest.mark.anyio
    async def test_for_run_preserves_config(self) -> None:
        cfg = PeriodicReminderConfig(every_n_turns=7, first_after=2)
        cap = PeriodicReminderCapability(config=cfg)
        fresh = await cap.for_run(_ctx())
        assert fresh.config.every_n_turns == 7
        assert fresh.config.first_after == 2

    @pytest.mark.anyio
    async def test_concurrent_isolation(self) -> None:
        cap = PeriodicReminderCapability()
        ctx = _ctx()
        run1 = await cap.for_run(ctx)
        run2 = await cap.for_run(ctx)

        rc = _FakeRequestContext(_make_messages())
        await run1.before_model_request(ctx, rc)
        await run1.before_model_request(ctx, rc)
        await run2.before_model_request(ctx, rc)

        assert run1._turn_counter == 2
        assert run2._turn_counter == 1

    @pytest.mark.anyio
    async def test_no_injection_on_non_firing_turn(self) -> None:
        cfg = PeriodicReminderConfig(every_n_turns=10)
        cap = PeriodicReminderCapability(config=cfg)
        messages = _make_messages()
        rc = _FakeRequestContext(messages)
        await cap.before_model_request(_ctx(), rc)
        assert rc.messages is messages

    @pytest.mark.anyio
    async def test_injects_on_firing_turn(self) -> None:
        cfg = PeriodicReminderConfig(every_n_turns=3, first_after=3)
        cap = PeriodicReminderCapability(config=cfg)
        ctx = _ctx()
        messages = _make_messages("original goal")
        rc = _FakeRequestContext(messages)

        for _ in range(3):
            await cap.before_model_request(ctx, rc)

        assert len(rc.messages) == len(messages) + 1
        injected = rc.messages[-1]
        assert isinstance(injected, ModelRequest)
        part = injected.parts[0]
        assert isinstance(part, UserPromptPart)
        assert "<system-reminder>" in str(part.content)

    @pytest.mark.anyio
    async def test_static_string_generator(self) -> None:
        cfg = PeriodicReminderConfig(every_n_turns=1, first_after=1, generator="custom msg")
        cap = PeriodicReminderCapability(config=cfg)
        rc = _FakeRequestContext(_make_messages())
        await cap.before_model_request(_ctx(), rc)

        injected_content = rc.messages[-1].parts[0].content  # type: ignore[union-attr]
        assert "custom msg" in str(injected_content)

    @pytest.mark.anyio
    async def test_async_callable_generator(self) -> None:
        received: list[Any] = []

        async def my_gen(ctx: Any, turn: int, messages: Any) -> str:
            received.append((turn, messages))
            return "callable reminder"

        cfg = PeriodicReminderConfig(every_n_turns=1, first_after=1, generator=my_gen)
        cap = PeriodicReminderCapability(config=cfg)
        messages = _make_messages()
        rc = _FakeRequestContext(messages)
        ctx = _ctx()
        await cap.before_model_request(ctx, rc)

        assert len(received) == 1
        assert received[0][0] == 1
        injected_content = rc.messages[-1].parts[0].content  # type: ignore[union-attr]
        assert "callable reminder" in str(injected_content)

    @pytest.mark.anyio
    async def test_reminder_count_increments(self) -> None:
        cfg = PeriodicReminderConfig(every_n_turns=2, first_after=2)
        cap = PeriodicReminderCapability(config=cfg)
        ctx = _ctx()
        rc = _FakeRequestContext(_make_messages())

        await cap.before_model_request(ctx, rc)
        assert cap._reminder_count == 0
        await cap.before_model_request(ctx, rc)
        assert cap._reminder_count == 1
        await cap.before_model_request(ctx, rc)
        assert cap._reminder_count == 1
        await cap.before_model_request(ctx, rc)
        assert cap._reminder_count == 2

    @pytest.mark.anyio
    async def test_render_style_user_prompt(self) -> None:
        cfg = PeriodicReminderConfig(every_n_turns=1, first_after=1, render_style="user_prompt")
        cap = PeriodicReminderCapability(config=cfg)
        rc = _FakeRequestContext(_make_messages())
        await cap.before_model_request(_ctx(), rc)
        injected_content = rc.messages[-1].parts[0].content  # type: ignore[union-attr]
        assert "<system-reminder>" not in str(injected_content)
        assert "[Developer note for the assistant:" not in str(injected_content)

    @pytest.mark.anyio
    async def test_render_style_developer_note(self) -> None:
        cfg = PeriodicReminderConfig(every_n_turns=1, first_after=1, render_style="developer_note")
        cap = PeriodicReminderCapability(config=cfg)
        rc = _FakeRequestContext(_make_messages())
        await cap.before_model_request(_ctx(), rc)
        injected_content = rc.messages[-1].parts[0].content  # type: ignore[union-attr]
        assert "[Developer note for the assistant:" in str(injected_content)

    @pytest.mark.anyio
    async def test_messages_not_mutated_in_place(self) -> None:
        cfg = PeriodicReminderConfig(every_n_turns=1, first_after=1)
        cap = PeriodicReminderCapability(config=cfg)
        original = _make_messages()
        rc = _FakeRequestContext(original)
        await cap.before_model_request(_ctx(), rc)
        assert len(original) == 1
        assert len(rc.messages) == 2

    @pytest.mark.anyio
    async def test_on_reminder_callback_called_on_fire(self) -> None:
        calls: list[tuple[int, str]] = []

        def _cb(turn: int, text: str) -> None:
            calls.append((turn, text))

        cfg = PeriodicReminderConfig(
            every_n_turns=1, first_after=1, generator="ping", on_reminder=_cb
        )
        cap = PeriodicReminderCapability(config=cfg)
        rc = _FakeRequestContext(_make_messages())
        await cap.before_model_request(_ctx(), rc)

        assert len(calls) == 1
        assert calls[0][0] == 1
        assert "ping" in calls[0][1]

    @pytest.mark.anyio
    async def test_on_reminder_callback_not_called_when_not_firing(self) -> None:
        calls: list[tuple[int, str]] = []

        cfg = PeriodicReminderConfig(
            every_n_turns=10, on_reminder=lambda t, s: calls.append((t, s))
        )
        cap = PeriodicReminderCapability(config=cfg)
        rc = _FakeRequestContext(_make_messages())
        await cap.before_model_request(_ctx(), rc)

        assert calls == []


class TestLLMReminderGenerator:
    @pytest.mark.anyio
    async def test_calls_agent_and_returns_output(self) -> None:
        gen = LLMReminderGenerator(model="anthropic:claude-haiku-4-5-20251001")
        messages = _make_messages("Build a rocket")

        mock_result = MagicMock()
        mock_result.output = "Focus on building the rocket."

        with patch("pydantic_deep.capabilities.periodic_reminder.Agent") as MockAgent:
            mock_agent_instance = MagicMock()
            mock_agent_instance.run = AsyncMock(return_value=mock_result)
            MockAgent.return_value = mock_agent_instance

            result = await gen(_ctx(), turn=5, messages=messages)

        assert result == "Focus on building the rocket."
        MockAgent.assert_called_once_with(model="anthropic:claude-haiku-4-5-20251001")
        mock_agent_instance.run.assert_called_once()
        prompt_arg = mock_agent_instance.run.call_args[0][0]
        assert "Build a rocket" in prompt_arg
        assert "5" in prompt_arg

    @pytest.mark.anyio
    async def test_compact_transcript_in_prompt(self) -> None:
        gen = LLMReminderGenerator(max_context_messages=3)
        messages = [ModelRequest(parts=[UserPromptPart(content=f"message {i}")]) for i in range(10)]

        mock_result = MagicMock()
        mock_result.output = "reminder text"

        with patch("pydantic_deep.capabilities.periodic_reminder.Agent") as MockAgent:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(return_value=mock_result)
            MockAgent.return_value = mock_instance

            await gen(_ctx(), turn=10, messages=messages)

        prompt_arg = mock_instance.run.call_args[0][0]
        assert "message 0" in prompt_arg

    @pytest.mark.anyio
    async def test_reuses_agent_across_calls(self) -> None:
        gen = LLMReminderGenerator(model="anthropic:claude-haiku-4-5-20251001")
        mock_result = MagicMock()
        mock_result.output = "reminder"

        with patch("pydantic_deep.capabilities.periodic_reminder.Agent") as MockAgent:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(return_value=mock_result)
            MockAgent.return_value = mock_instance

            await gen(_ctx(), 1, _make_messages("goal"))
            await gen(_ctx(), 2, _make_messages("goal"))

        assert MockAgent.call_count == 1

    @pytest.mark.anyio
    async def test_exception_fallback_to_default_generate(self) -> None:
        gen = LLMReminderGenerator(model="anthropic:claude-haiku-4-5-20251001")
        msgs = _make_messages("Do the thing")

        with patch("pydantic_deep.capabilities.periodic_reminder.Agent") as MockAgent:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(side_effect=RuntimeError("network fail"))
            MockAgent.return_value = mock_instance

            result = await gen(_ctx(), 1, msgs)

        assert "Do the thing" in result


class TestMakeConfigForMode:
    def test_llm_mode_returns_llm_generator(self) -> None:
        cfg = make_config_for_mode("llm")
        assert isinstance(cfg.generator, LLMReminderGenerator)
        assert cfg.every_n_turns == 15
        assert cfg.max_reminders_per_run == 3

    def test_first_mode_returns_none_generator(self) -> None:
        cfg = make_config_for_mode("first")
        assert cfg.generator is None
        assert cfg.every_n_turns == 10
        assert cfg.max_reminders_per_run is None

    def test_context_mode_returns_callable_generator(self) -> None:
        cfg = make_config_for_mode("context")
        assert callable(cfg.generator)
        assert cfg.every_n_turns == 10

    @pytest.mark.anyio
    async def test_context_mode_generator_builds_transcript(self) -> None:
        cfg = make_config_for_mode("context")
        msgs = _make_messages("my goal")
        assert cfg.generator is not None
        result = await cfg.generator(_ctx(), 1, msgs)  # type: ignore[operator]
        assert "my goal" in result

    def test_unknown_mode_falls_back_to_llm(self) -> None:
        cfg = make_config_for_mode("unknown")
        assert isinstance(cfg.generator, LLMReminderGenerator)


class TestAgentIntegration:
    def test_create_with_periodic_reminder_true(self) -> None:
        agent = create_deep_agent(model=_MODEL, periodic_reminder=True)
        assert agent is not None

    def test_create_with_periodic_reminder_config(self) -> None:
        cfg = PeriodicReminderConfig(every_n_turns=5, first_after=2)
        agent = create_deep_agent(model=_MODEL, periodic_reminder=cfg)
        assert agent is not None

    def test_create_with_periodic_reminder_false(self) -> None:
        agent = create_deep_agent(model=_MODEL, periodic_reminder=False)
        assert agent is not None

    def test_create_with_periodic_reminder_none(self) -> None:
        agent = create_deep_agent(model=_MODEL, periodic_reminder=None)
        assert agent is not None
