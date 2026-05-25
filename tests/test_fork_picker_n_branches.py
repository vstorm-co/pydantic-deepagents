"""Tests for the N-row :class:`ForkPickerModal`.

Verifies that the picker:

- renders ``app.fork_branch_count`` branch rows (instead of a hard-coded 2)
- shows the resolved per-branch model on each row (override or default)
- prefills ``budget_usd`` per branch from ``app.fork_branch_budgets`` and the
  aggregate-budget input from ``app.fork_aggregate_budget_usd``
- validates distinct non-empty labels at N>2, positive budget floats
- on submit returns a :class:`ForkPickerResult` whose ``specs`` length
  matches ``app.fork_branch_count`` and whose ``aggregate_budget_usd`` is
  forwarded
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models.test import TestModel
from pydantic_ai_backends import StateBackend
from textual.widgets import Input, Static

from apps.cli.app import DeepApp
from apps.cli.forking import ForkPickerResult
from apps.cli.modals.fork_picker import ForkPickerModal
from pydantic_deep import DeepAgentDeps, create_deep_agent


def _make_fork_agent() -> Agent[DeepAgentDeps, str]:
    return create_deep_agent(
        model=TestModel(call_tools=[]),
        forking=True,
        include_skills=False,
        include_plan=False,
        include_memory=False,
        include_subagents=False,
        include_teams=False,
        include_todo=False,
        web_search=False,
        web_fetch=False,
        cost_tracking=False,
        context_manager=False,
        stuck_loop_detection=False,
        context_discovery=False,
    )


def _make_app() -> DeepApp:
    agent = _make_fork_agent()
    deps = DeepAgentDeps(backend=StateBackend())
    app = DeepApp(agent=agent, deps=deps, model="test", version="0.3.3")
    app.message_history = [ModelRequest(parts=[UserPromptPart(content="seed turn")])]
    return app


@pytest.fixture
def fork_app() -> DeepApp:
    return _make_app()


def _text_of(static: Static) -> str:
    """Read a Static's current text — Textual >= 5 exposes ``content``."""
    return str(getattr(static, "content", ""))


class TestPickerNRowRendering:
    async def test_renders_count_rows(self, fork_app: DeepApp) -> None:
        async with fork_app.run_test(size=(140, 50)) as pilot:
            await pilot.pause()
            fork_app.fork_branch_count = 4
            modal = ForkPickerModal()
            fork_app.push_screen(modal)
            await pilot.pause()
            inputs = list(modal.query(Input))
            assert len(inputs) == 8
            model_statics = [s for s in modal.query(Static) if "fork-branch-model" in s.classes]
            assert len(model_statics) == 4

    async def test_model_display_reflects_overrides(self, fork_app: DeepApp) -> None:
        async with fork_app.run_test(size=(140, 50)) as pilot:
            await pilot.pause()
            fork_app.fork_branch_count = 4
            fork_app.fork_branch_models = [
                "anthropic:claude-opus-4-6",
                None,
                "openai:gpt-4.1",
                None,
            ]
            fork_app.model_name = "anthropic:claude-sonnet-4-6"
            modal = ForkPickerModal()
            fork_app.push_screen(modal)
            await pilot.pause()
            statistics = [s for s in modal.query(Static) if "fork-branch-model" in s.classes]
            texts = [_text_of(s) for s in statistics]
            assert "anthropic:claude-opus-4-6" in texts[0]
            assert "anthropic:claude-sonnet-4-6" in texts[1]
            assert "openai:gpt-4.1" in texts[2]
            assert "anthropic:claude-sonnet-4-6" in texts[3]

    async def test_per_branch_budgets_propagate_to_specs(self, fork_app: DeepApp) -> None:
        """Each spec's ``budget_usd`` is taken from ``app.fork_branch_budgets[i]``.
        Empty slots → ``None`` (no cap)."""
        captured: dict[str, Any] = {}

        async def _on_dismiss(result: ForkPickerResult | None) -> None:
            captured["result"] = result

        async with fork_app.run_test(size=(140, 50)) as pilot:
            await pilot.pause()
            fork_app.fork_branch_count = 3
            fork_app.fork_branch_budgets = [0.25, None, 1.0]
            modal = ForkPickerModal()
            fork_app.push_screen(modal, _on_dismiss)
            await pilot.pause()
            for i, label in enumerate(("a", "b", "c")):
                modal.query_one(f"#branch-{i}-label", Input).value = label
                modal.query_one(f"#branch-{i}-steer", Input).value = f"steer {i}"
            modal.action_submit()
            await pilot.pause()
            await pilot.pause()
        result_specs = captured["result"].specs
        assert [s.budget_usd for s in result_specs] == [0.25, None, 1.0]

    async def test_aggregate_read_from_app_state(self, fork_app: DeepApp) -> None:
        """Aggregate cap is no longer a picker Input — it's read off
        :attr:`DeepApp.fork_aggregate_budget_usd` at submit time (configured
        via ``/fork-config``). Confirm the picker still propagates it."""
        captured: dict[str, Any] = {}

        async def _on_dismiss(result: ForkPickerResult | None) -> None:
            captured["result"] = result

        async with fork_app.run_test(size=(140, 50)) as pilot:
            await pilot.pause()
            fork_app.fork_branch_count = 1
            fork_app.fork_aggregate_budget_usd = 2.0
            modal = ForkPickerModal()
            fork_app.push_screen(modal, _on_dismiss)
            await pilot.pause()
            modal.query_one("#branch-0-label", Input).value = "a"
            modal.query_one("#branch-0-steer", Input).value = "sa"
            modal.action_submit()
            await pilot.pause()
            await pilot.pause()
        assert captured["result"].aggregate_budget_usd == 2.0

    async def test_padding_when_branch_models_shorter_than_count(self, fork_app: DeepApp) -> None:
        async with fork_app.run_test(size=(140, 50)) as pilot:
            await pilot.pause()
            fork_app.fork_branch_count = 4
            fork_app.fork_branch_models = ["only:one"]
            modal = ForkPickerModal()
            fork_app.push_screen(modal)
            await pilot.pause()
            assert len([s for s in modal.query(Static) if "fork-branch-model" in s.classes]) == 4


class TestPickerValidation:
    async def test_distinct_labels_at_n4(self, fork_app: DeepApp) -> None:
        async with fork_app.run_test(size=(140, 50)) as pilot:
            await pilot.pause()
            fork_app.fork_branch_count = 4
            modal = ForkPickerModal()
            fork_app.push_screen(modal)
            await pilot.pause()
            for i in range(4):
                modal.query_one(f"#branch-{i}-label", Input).value = "x"
                modal.query_one(f"#branch-{i}-steer", Input).value = f"steer {i}"
            modal.action_submit()
            await pilot.pause()
            error = modal.query_one("#fork-picker-error", Static)
            assert "distinct" in _text_of(error)
            assert isinstance(fork_app.screen, ForkPickerModal)

    async def test_blank_steer_rejected(self, fork_app: DeepApp) -> None:
        async with fork_app.run_test(size=(140, 50)) as pilot:
            await pilot.pause()
            fork_app.fork_branch_count = 2
            modal = ForkPickerModal()
            fork_app.push_screen(modal)
            await pilot.pause()
            modal.query_one("#branch-0-label", Input).value = "a"
            modal.query_one("#branch-1-label", Input).value = "b"
            modal.query_one("#branch-0-steer", Input).value = "steer A"
            modal.action_submit()
            await pilot.pause()
            error = modal.query_one("#fork-picker-error", Static)
            assert "steer" in _text_of(error).lower()


class TestPickerSubmit:
    async def test_submit_returns_fork_picker_result(self, fork_app: DeepApp) -> None:
        captured: dict[str, Any] = {}

        async def _on_dismiss(result: ForkPickerResult | None) -> None:
            captured["result"] = result

        async with fork_app.run_test(size=(140, 50)) as pilot:
            await pilot.pause()
            fork_app.fork_branch_count = 3
            fork_app.fork_branch_models = [
                "anthropic:claude-opus-4-6",
                None,
                "openai:gpt-4.1",
            ]
            fork_app.fork_branch_budgets = [0.25, 0.25, 0.25]
            fork_app.fork_aggregate_budget_usd = 5.0
            modal = ForkPickerModal()
            fork_app.push_screen(modal, _on_dismiss)
            await pilot.pause()
            for i, label in enumerate(("a", "b", "c")):
                modal.query_one(f"#branch-{i}-label", Input).value = label
                modal.query_one(f"#branch-{i}-steer", Input).value = f"steer {i}"
            modal.action_submit()
            await pilot.pause()
            await pilot.pause()

        result = captured["result"]
        assert isinstance(result, ForkPickerResult)
        assert len(result.specs) == 3
        assert result.aggregate_budget_usd == 5.0
        assert result.specs[0].model == "anthropic:claude-opus-4-6"
        assert result.specs[1].model is None
        assert result.specs[2].model == "openai:gpt-4.1"
        for spec in result.specs:
            assert spec.budget_usd == 0.25

    async def test_cancel_returns_none(self, fork_app: DeepApp) -> None:
        captured: dict[str, Any] = {}

        async def _on_dismiss(result: ForkPickerResult | None) -> None:
            captured["result"] = result

        async with fork_app.run_test(size=(140, 50)) as pilot:
            await pilot.pause()
            modal = ForkPickerModal()
            fork_app.push_screen(modal, _on_dismiss)
            await pilot.pause()
            modal.action_cancel()
            await pilot.pause()
            await pilot.pause()

        assert captured["result"] is None

    async def test_input_submitted_event_triggers_submit(self, fork_app: DeepApp) -> None:
        async with fork_app.run_test(size=(140, 50)) as pilot:
            await pilot.pause()
            fork_app.fork_branch_count = 1
            modal = ForkPickerModal()
            fork_app.push_screen(modal)
            await pilot.pause()
            modal.query_one("#branch-0-label", Input).value = "a"
            modal.query_one("#branch-0-steer", Input).value = "sa"
            input_widget = modal.query_one("#branch-0-steer", Input)
            modal.on_input_submitted(Input.Submitted(input_widget, "sa"))
            await pilot.pause()

    async def test_branch_count_minimum_one(self, fork_app: DeepApp) -> None:
        """``_branch_count`` is clamped to ≥1 so the picker never renders a zero-row form."""
        async with fork_app.run_test(size=(140, 50)) as pilot:
            await pilot.pause()
            fork_app.fork_branch_count = 0
            modal = ForkPickerModal()
            fork_app.push_screen(modal)
            await pilot.pause()
            assert len(list(modal.query(Input))) == 2
