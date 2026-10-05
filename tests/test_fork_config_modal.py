"""Tests for ForkConfigModal — focused on the unguarded query_one Save crash."""

from __future__ import annotations

import pytest
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models.test import TestModel
from textual.widgets import Input, Static

from apps.cli.app import DeepApp
from apps.cli.modals.fork_config import ForkConfigModal
from pydantic_deep import DeepAgentDeps, create_deep_agent
from tests.workspaces import state_workspace


def _make_app() -> DeepApp:
    agent = create_deep_agent(
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
    deps = DeepAgentDeps()
    agent._cli_workspace = state_workspace()  # type: ignore[attr-defined]
    app = DeepApp(agent=agent, deps=deps, model="test", version="0.3.3")
    app.message_history = [ModelRequest(parts=[UserPromptPart(content="seed")])]
    return app


@pytest.fixture
def config_app() -> DeepApp:
    return _make_app()


async def test_input_or_none_returns_none_for_missing_row(config_app: DeepApp) -> None:
    async with config_app.run_test(size=(140, 50)) as pilot:
        await pilot.pause()
        modal = ForkConfigModal()
        config_app.push_screen(modal)
        await pilot.pause()
        # A real row resolves; a missing id returns None instead of raising NoMatches.
        assert modal._input_or_none("fork-config-budget-0") is not None
        assert modal._input_or_none("fork-config-budget-999") is None


async def test_save_surfaces_error_when_budget_row_not_mounted(config_app: DeepApp) -> None:
    """If a per-branch budget row isn't mounted, Save shows an error, not a traceback."""
    async with config_app.run_test(size=(140, 50)) as pilot:
        await pilot.pause()
        modal = ForkConfigModal()
        config_app.push_screen(modal)
        await pilot.pause()

        count = modal._branch_count
        assert count >= 1
        # Simulate the async mount race: a budget row input is gone at Save time.
        modal.query_one(f"#fork-config-budget-{count - 1}", Input).remove()
        await pilot.pause()

        # Save must not crash; it surfaces a validation error and stays open.
        await modal.action_save()
        await pilot.pause()

        error = modal.query_one("#fork-config-error", Static)
        assert "still loading" in str(getattr(error, "content", "")).lower()
        assert isinstance(config_app.screen, ForkConfigModal)
