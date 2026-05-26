"""Tests for :class:`JudgeLoadingScreen` — judge progress overlay.

Drives the screen through Textual's :class:`Pilot`, asserting that:

- the success path dismisses with the :class:`ResolveOutcome`;
- exceptions raised inside ``resolve()`` dismiss with the raw exception
  (so the caller can branch on ``isinstance(result, Exception)``);
- :kbd:`Escape` cancels the in-flight judge task and dismisses with
  :class:`JudgeAborted` — the user's escape hatch when a slow LLM call
  stalls.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from apps.cli.widgets.judge_loading import JudgeAborted, JudgeLoadingScreen
from pydantic_deep.types import MergeStrategy


class _ProbeApp(App[None]):
    def compose(self) -> ComposeResult:
        yield Static("anchor")


# ---------------------------------------------------------------------------
# Success path — dismisses with the ResolveOutcome.
# ---------------------------------------------------------------------------


async def test_success_path_dismisses_with_outcome() -> None:
    """``resolve()`` returns a value → the screen dismisses with that value."""
    app = _ProbeApp()
    sentinel = object()
    coordinator = SimpleNamespace(resolve=AsyncMock(return_value=sentinel))
    captured: dict[str, Any] = {}

    async with app.run_test() as pilot:
        screen = JudgeLoadingScreen(coordinator, MergeStrategy(kind="auto"))

        def _on_dismiss(value: Any) -> None:
            captured["value"] = value

        app.push_screen(screen, _on_dismiss)
        # Give the task time to schedule + complete.
        await pilot.pause()
        await pilot.pause()
        assert captured.get("value") is sentinel


# ---------------------------------------------------------------------------
# Exception path — dismisses with the raw Exception so the caller branches on it.
# ---------------------------------------------------------------------------


async def test_exception_path_dismisses_with_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failing ``resolve()`` dismisses with the exception + logs the traceback."""
    app = _ProbeApp()
    boom = RuntimeError("provider 5xx")

    async def _failing(_strategy: Any) -> Any:
        raise boom

    coordinator = SimpleNamespace(resolve=_failing)
    captured: dict[str, Any] = {}

    with caplog.at_level(logging.ERROR, logger="apps.cli.widgets.judge_loading"):
        async with app.run_test() as pilot:
            screen = JudgeLoadingScreen(coordinator, MergeStrategy(kind="auto"))

            def _on_dismiss(value: Any) -> None:
                captured["value"] = value

            app.push_screen(screen, _on_dismiss)
            await pilot.pause()
            await pilot.pause()
            assert captured.get("value") is boom

    # Log line must include the exception class name AND the message so users
    # can grep their logs by type when diagnosing judge failures.
    matching = [r for r in caplog.records if "RuntimeError" in r.getMessage()]
    assert matching, f"Expected a log line containing 'RuntimeError'; got {caplog.text}"
    assert "provider 5xx" in caplog.text


# ---------------------------------------------------------------------------
# Escape — cancels the judge task and dismisses with JudgeAborted.
# ---------------------------------------------------------------------------


async def test_escape_aborts_judge_task() -> None:
    """Pressing Escape mid-call dismisses with :class:`JudgeAborted`."""
    app = _ProbeApp()
    started = asyncio.Event()

    async def _hanging_resolve(_strategy: Any) -> Any:
        started.set()
        await asyncio.Future()  # never resolves
        return None  # pragma: no cover - never reached

    coordinator = SimpleNamespace(resolve=_hanging_resolve)
    captured: dict[str, Any] = {}

    async with app.run_test() as pilot:
        screen = JudgeLoadingScreen(coordinator, MergeStrategy(kind="auto"))

        def _on_dismiss(value: Any) -> None:
            captured["value"] = value

        app.push_screen(screen, _on_dismiss)
        # Wait until the resolve task is actually running so the cancel hits it.
        await asyncio.wait_for(started.wait(), timeout=1.0)
        await pilot.press("escape")
        await pilot.pause()
        await pilot.pause()
        assert isinstance(captured.get("value"), JudgeAborted)


async def test_escape_before_task_started_is_safe() -> None:
    """``action_abort`` is a no-op when the task hasn't been created yet.

    Guards against an Escape between ``__init__`` and ``on_mount`` (rare but
    possible if a parent screen pre-empts mount).
    """
    app = _ProbeApp()
    coordinator = SimpleNamespace(resolve=AsyncMock(return_value="ok"))
    async with app.run_test() as pilot:
        screen = JudgeLoadingScreen(coordinator, MergeStrategy(kind="auto"))
        # Don't push it — call action_abort before mount.
        screen.action_abort()  # should not raise
        # Now exercise the normal flow to make sure the screen is still usable.
        captured: dict[str, Any] = {}
        app.push_screen(screen, lambda v: captured.__setitem__("value", v))
        await pilot.pause()
        await pilot.pause()
        assert captured["value"] == "ok"


# ---------------------------------------------------------------------------
# Spinner label updates while task is in-flight.
# ---------------------------------------------------------------------------


async def test_spinner_label_includes_abort_hint() -> None:
    """The label shows the elapsed counter and the ``(esc to abort)`` hint."""
    app = _ProbeApp()
    started = asyncio.Event()

    async def _hanging(_s: Any) -> Any:
        started.set()
        await asyncio.Future()

    coordinator = SimpleNamespace(resolve=_hanging)
    async with app.run_test() as pilot:
        screen = JudgeLoadingScreen(coordinator, MergeStrategy(kind="auto"))
        app.push_screen(screen)
        await asyncio.wait_for(started.wait(), timeout=1.0)
        await pilot.pause()
        label = screen.query_one("#judge-label", Static)
        text = str(label.render())
        assert "Judge evaluating" in text
        assert "esc to abort" in text
        # Tidy up so the test loop terminates cleanly.
        screen.action_abort()
        await pilot.pause()


# ---------------------------------------------------------------------------
# Passive mode — no task spawned, dismissed externally, escape safe.
# ---------------------------------------------------------------------------


async def test_passive_mode_does_not_start_task() -> None:
    """``passive=True`` shows the spinner but never calls ``resolve()``."""
    app = _ProbeApp()
    resolve_called = False

    async def _resolve(_s: Any) -> Any:
        nonlocal resolve_called
        resolve_called = True  # pragma: no cover - must NOT be called
        return None

    coordinator = SimpleNamespace(resolve=_resolve)
    async with app.run_test() as pilot:
        screen = JudgeLoadingScreen(coordinator, MergeStrategy(kind="auto"), passive=True)
        app.push_screen(screen)
        await pilot.pause()
        # No judge task should have been created.
        assert screen._judge_task is None
        assert not resolve_called
        # External dismiss (simulates FunctionToolResultEvent handler).
        screen.dismiss(None)
        await pilot.pause()


async def test_passive_mode_label_differs_from_active() -> None:
    """Passive label says 'Agent evaluating' instead of 'Judge evaluating'."""
    app = _ProbeApp()
    coordinator = SimpleNamespace(resolve=AsyncMock(return_value=None))
    async with app.run_test() as pilot:
        screen = JudgeLoadingScreen(coordinator, MergeStrategy(kind="auto"), passive=True)
        app.push_screen(screen)
        await pilot.pause()
        label = screen.query_one("#judge-label", Static)
        text = str(label.render())
        assert "Agent evaluating" in text
        assert "esc to abort" not in text
        screen.dismiss(None)
        await pilot.pause()


async def test_passive_mode_escape_dismisses_with_judgeaborted() -> None:
    """Pressing Escape in passive mode dismisses (no task to cancel)."""
    app = _ProbeApp()
    coordinator = SimpleNamespace(resolve=AsyncMock(return_value=None))
    captured: dict[str, Any] = {}

    async with app.run_test() as pilot:
        screen = JudgeLoadingScreen(coordinator, MergeStrategy(kind="auto"), passive=True)
        app.push_screen(screen, lambda v: captured.__setitem__("value", v))
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(captured.get("value"), JudgeAborted)
