"""CLI glue for the ``/goal`` command.

Bridges the provider-agnostic engine in :mod:`pydantic_deep.goal` to the
Textual app: sets / clears / reports goal state, drives the status-bar
indicator, and resolves the small evaluator model from CLI config.

The turn-driving loop itself lives on :class:`apps.cli.screens.chat.ChatScreen`
(``_continue_goal``) because it owns ``_run_agent`` and the widget tree.
"""

from __future__ import annotations

import contextlib
import time
from typing import TYPE_CHECKING

from pydantic_deep.goal import (
    GoalEvaluator,
    GoalState,
    format_goal_status,
    parse_goal_command,
)

if TYPE_CHECKING:
    from apps.cli.app import DeepApp


def get_goal_evaluator(app: DeepApp) -> GoalEvaluator:
    """Return the app's goal evaluator, creating it lazily on first use.

    Prefers an explicitly-configured ``goal_model``, then the cheap
    ``reminder_model``, then the engine default (a small Haiku model).
    """
    if app._goal_evaluator is None:
        model: str | None = None
        try:
            from apps.cli.config import load_config

            cfg = load_config()
            model = getattr(cfg, "goal_model", None) or getattr(cfg, "reminder_model", None)
        except Exception:
            model = None
        app._goal_evaluator = GoalEvaluator(model=model) if model else GoalEvaluator()
    return app._goal_evaluator


def set_goal_indicator(app: DeepApp, active: bool) -> None:
    """Toggle the ``◎ goal`` indicator on the status bar (best-effort)."""
    from apps.cli.widgets.status_bar import StatusBar

    with contextlib.suppress(Exception):
        app.screen.query_one(StatusBar).goal_active = active


def clear_goal(app: DeepApp, *, notify: bool = True) -> None:
    """Remove any active goal and hide the indicator."""
    had_goal = app._goal is not None
    app._goal = None
    set_goal_indicator(app, False)
    if notify:
        app.notify("Goal cleared" if had_goal else "No active goal to clear")


def _prompt_for_goal(app: DeepApp) -> None:
    """Open a modal to type a goal condition, then set it on submit.

    Used when ``/goal`` is invoked with no condition and none is active, so the
    user can enter the goal interactively instead of getting a dead-end notice.
    """
    from apps.cli.modals.goal_modal import GoalModal

    async def _on_result(condition: str | None) -> None:
        if condition:
            _set_goal(app, condition)

    app.push_screen(GoalModal(), _on_result)


def _show_status(app: DeepApp) -> None:
    goal = app._goal
    if goal is None:
        _prompt_for_goal(app)
        return
    elapsed = None
    if goal.started_monotonic is not None:
        elapsed = time.monotonic() - goal.started_monotonic
    app.notify(format_goal_status(goal, elapsed), timeout=12)


def _set_goal(app: DeepApp, condition: str) -> None:
    app._goal = GoalState(condition=condition, started_monotonic=time.monotonic())
    set_goal_indicator(app, True)
    app.notify(f"◎ Goal set — {condition}", timeout=6)

    # Setting a goal starts a turn immediately with the condition as the
    # directive, unless a run is already in flight (the goal loop then takes
    # over once that turn finishes).
    if getattr(app, "agent", None) is None:
        return
    task = app.agent_task
    if task is not None and not task.done():
        return
    screen = app.screen
    run = getattr(screen, "_run_agent", None)
    if run is None:
        return
    from apps.cli.widgets.message_list import MessageList

    with contextlib.suppress(Exception):
        screen.query_one(MessageList).append_user_message(condition)
    run(condition)


async def handle_goal_command(app: DeepApp, arg: str) -> None:
    """Handle ``/goal``: set a condition, clear it, or show status."""
    action, condition = parse_goal_command(arg)
    if action == "status":
        _show_status(app)
    elif action == "clear":
        clear_goal(app, notify=True)
    else:  # set
        _set_goal(app, condition)
