"""Tests for the CLI `/goal` command glue and the goal-continuation loop."""

from __future__ import annotations

from typing import Any

import pytest

from apps.cli.app import DeepApp
from apps.cli.commands import dispatch_command
from apps.cli.screens.chat import ChatScreen
from apps.cli.widgets.status_bar import StatusBar
from pydantic_deep.goal import GoalEvaluation, GoalState


@pytest.fixture
def app() -> DeepApp:
    return DeepApp(model="test", version="0.0.0")


class _FakeEvaluator:
    def __init__(self, evaluation: GoalEvaluation) -> None:
        self.evaluation = evaluation
        self.calls = 0

    async def evaluate(self, _condition: str, _messages: list[Any]) -> GoalEvaluation:
        self.calls += 1
        return self.evaluation


async def test_set_clear_status(app: DeepApp, monkeypatch: pytest.MonkeyPatch) -> None:
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        msgs: list[str] = []
        monkeypatch.setattr(app, "notify", lambda m, **k: msgs.append(m))

        # Set a goal — indicator lights up, first turn is kicked (no real agent).
        await dispatch_command(app, "/goal all tests pass")
        await pilot.pause()
        assert app._goal is not None
        assert app._goal.condition == "all tests pass"
        assert app.screen.query_one(StatusBar).goal_active is True
        assert msgs[-1].startswith("◎ Goal set")

        # Status with an active goal.
        await dispatch_command(app, "/goal")
        await pilot.pause()
        assert "Goal (active): all tests pass" in msgs[-1]

        # Clear via an alias drops the goal and the indicator.
        await dispatch_command(app, "/goal stop")
        await pilot.pause()
        assert app._goal is None
        assert app.screen.query_one(StatusBar).goal_active is False
        assert msgs[-1] == "Goal cleared"


async def test_goal_no_arg_opens_modal_then_sets(
    app: DeepApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`/goal` with no condition and no active goal opens the input modal;
    submitting a condition sets the goal."""
    from apps.cli.modals.goal_modal import GoalModal

    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()

        captured: dict[str, Any] = {}

        def fake_push(screen: Any, callback: Any = None) -> None:
            captured["screen"] = screen
            captured["callback"] = callback

        monkeypatch.setattr(app, "push_screen", fake_push)

        await dispatch_command(app, "/goal")
        await pilot.pause()

        # No dead-end notice — an input modal is offered instead.
        assert isinstance(captured["screen"], GoalModal)
        assert app._goal is None

        # The user types a condition and submits it.
        await captured["callback"]("all tests pass")
        await pilot.pause()
        assert app._goal is not None
        assert app._goal.condition == "all tests pass"
        assert app.screen.query_one(StatusBar).goal_active is True


async def test_goal_modal_cancel_leaves_no_goal(
    app: DeepApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dismissing the goal modal without a condition sets nothing."""
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()

        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            app, "push_screen", lambda screen, callback=None: captured.update(callback=callback)
        )

        await dispatch_command(app, "/goal")
        await pilot.pause()
        await captured["callback"](None)
        await pilot.pause()
        assert app._goal is None


async def test_clear_via_slash_clear(app: DeepApp) -> None:
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        await dispatch_command(app, "/goal ship it")
        await pilot.pause()
        assert app._goal is not None
        await dispatch_command(app, "/clear")
        await pilot.pause()
        assert app._goal is None


async def test_continue_goal_achieved(app: DeepApp, monkeypatch: pytest.MonkeyPatch) -> None:
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        msgs: list[str] = []
        monkeypatch.setattr(app, "notify", lambda m, **k: msgs.append(m))
        screen = app.screen
        assert isinstance(screen, ChatScreen)

        app._goal = GoalState(condition="done?")
        app._goal_evaluator = _FakeEvaluator(GoalEvaluation(met=True, reason="all green"))  # type: ignore[assignment]

        ran: list[str] = []
        monkeypatch.setattr(screen, "_run_agent", lambda text: ran.append(text))

        await screen._continue_goal()
        assert app._goal is None  # cleared on success
        assert ran == []  # no further turn
        assert any("Goal achieved" in m for m in msgs)


async def test_continue_goal_not_met_runs_again(
    app: DeepApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        monkeypatch.setattr(app, "notify", lambda m, **k: None)
        screen = app.screen
        assert isinstance(screen, ChatScreen)

        app._goal = GoalState(condition="keep going")
        app._goal_evaluator = _FakeEvaluator(GoalEvaluation(met=False, reason="not yet"))  # type: ignore[assignment]

        ran: list[str] = []
        monkeypatch.setattr(screen, "_run_agent", lambda text: ran.append(text))

        await screen._continue_goal()
        assert app._goal is not None
        assert app._goal.turns == 1
        assert app._goal.last_reason == "not yet"
        assert len(ran) == 1
        assert "keep going" in ran[0]


async def test_continue_goal_exhausted(app: DeepApp, monkeypatch: pytest.MonkeyPatch) -> None:
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        msgs: list[str] = []
        monkeypatch.setattr(app, "notify", lambda m, **k: msgs.append(m))
        screen = app.screen
        assert isinstance(screen, ChatScreen)

        # One turn away from the cap; the next evaluation hits it.
        app._goal = GoalState(condition="forever", max_turns=1)
        app._goal_evaluator = _FakeEvaluator(GoalEvaluation(met=False, reason="still no"))  # type: ignore[assignment]

        ran: list[str] = []
        monkeypatch.setattr(screen, "_run_agent", lambda text: ran.append(text))

        await screen._continue_goal()
        assert app._goal is None  # stopped at the cap
        assert ran == []  # no further turn
        assert any("Goal stopped after" in m for m in msgs)


async def test_continue_goal_no_active_goal(app: DeepApp) -> None:
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, ChatScreen)
        app._goal = None
        # No goal → no-op, no error.
        await screen._continue_goal()
