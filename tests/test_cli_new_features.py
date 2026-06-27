"""Tests for new CLI UX features: turn summary, /paste, /screenshot, approval position."""

from __future__ import annotations

from typing import cast

import pytest

from apps.cli import clipboard_image as ci
from apps.cli.app import DeepApp
from apps.cli.commands import dispatch_command
from apps.cli.screens.chat import ChatScreen, _format_turn_summary


@pytest.fixture
def app() -> DeepApp:
    return DeepApp(model="test", version="0.0.0")


def test_turn_summary_combinations() -> None:
    assert _format_turn_summary({}, 1.0) == ""
    assert _format_turn_summary({"execute": 1}, 2.0) == "✓ 1 command · 2.0s"
    out = _format_turn_summary(
        {"edit_file": 1, "write_file": 1, "execute": 3, "read_file": 1, "grep": 2}, 4.5
    )
    assert "2 edits" in out
    assert "3 commands" in out
    assert "1 read" in out
    assert "2 searches" in out
    assert out.endswith("4.5s")


async def test_screenshot_command(app: DeepApp, monkeypatch: pytest.MonkeyPatch) -> None:
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        msgs: list[str] = []
        monkeypatch.setattr(app, "notify", lambda m, **k: msgs.append(m))
        monkeypatch.setattr(app, "save_screenshot", lambda fn=None: "/tmp/shot.svg")
        await dispatch_command(app, "/screenshot")
        await pilot.pause()
        assert any("Screenshot saved" in m for m in msgs)


async def test_paste_command_delegates(app: DeepApp, monkeypatch: pytest.MonkeyPatch) -> None:
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        monkeypatch.setattr(ci, "grab_clipboard_image", lambda: (b"\x89PNG x", "image/png"))
        await dispatch_command(app, "/paste")
        await pilot.pause()
        assert len(cast(ChatScreen, app.screen)._pending_images) == 1


async def test_approval_modal_position_label() -> None:
    from apps.cli.modals.approval import ApprovalModal

    # No position / single -> no suffix logic crash.
    m1 = ApprovalModal("execute", {"command": "ls"})
    assert m1._position is None

    m2 = ApprovalModal("execute", {"command": "ls"}, position=(1, 3))
    assert m2._position == (1, 3)

    # Render it to ensure the "(1 of 3)" suffix path executes.
    from textual.app import App, ComposeResult

    class _H(App[None]):
        def compose(self) -> ComposeResult:
            yield from ()

    h = _H()
    async with h.run_test() as pilot:
        await h.push_screen(m2)
        await pilot.pause()
        title = m2.query_one("#approval-title")
        rendered = str(title.render())
        assert "1 of 3" in rendered


async def test_context_warning_fires_once_per_crossing(
    app: DeepApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The >=90% context warning must not spam on every update — only on the
    rising edge, re-arming after usage drops below 85% (hysteresis)."""
    from apps.cli.messages import ContextUpdated

    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        screen = cast(ChatScreen, app.screen)
        warnings: list[str] = []
        monkeypatch.setattr(
            app,
            "notify",
            lambda m, **k: warnings.append(m) if "Context at" in str(m) else None,
        )

        # Several high updates in a row → exactly one warning.
        for pct in (0.91, 0.93, 0.95):
            screen.on_context_updated(ContextUpdated(pct, int(pct * 200_000), 200_000))
        assert len(warnings) == 1

        # Drop below the reset threshold (e.g. after /compact) → re-armed.
        screen.on_context_updated(ContextUpdated(0.40, 80_000, 200_000))
        # Climb back over 90% → one more warning.
        screen.on_context_updated(ContextUpdated(0.92, 184_000, 200_000))
        assert len(warnings) == 2


async def test_input_prefill_stages_command(app: DeepApp) -> None:
    """InputArea.prefill stages text in the single-line input for editing."""
    from apps.cli.widgets.input_area import InputArea

    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        input_area = app.screen.query_one(InputArea)
        input_area.prefill("/goal ")
        await pilot.pause()
        prompt = input_area.query("PromptInput").first()
        assert prompt.value == "/goal "  # type: ignore[attr-defined]


async def test_multiline_paste_preserves_structure(app: DeepApp) -> None:
    """A multi-line paste switches the input to multiline mode with the text
    (and any already-typed prefix) intact instead of losing the newlines."""
    from apps.cli.widgets.input_area import InputArea, MultilineInput

    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        input_area = app.screen.query_one(InputArea)
        input_area.enter_multiline_with("def f():\n    return 1\n")
        await pilot.pause()
        assert input_area.is_multiline is True
        ml = input_area.query_one(MultilineInput)
        assert ml.text == "def f():\n    return 1\n"


async def test_on_paste_routes_multiline(app: DeepApp) -> None:
    """PromptInput._on_paste hands multi-line pastes to multiline mode and lets
    a plain single-line paste fall through to the default insert behaviour."""
    from textual.events import Paste

    from apps.cli.widgets.input_area import InputArea

    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        input_area = app.screen.query_one(InputArea)
        prompt = input_area.query("PromptInput").first()
        prompt.value = "pre "  # type: ignore[attr-defined]
        prompt._on_paste(Paste("a\nb"))  # type: ignore[attr-defined]
        await pilot.pause()
        # Routed to multiline with the prefix preserved.
        assert input_area.is_multiline is True
        from apps.cli.widgets.input_area import MultilineInput

        assert input_area.query_one(MultilineInput).text == "pre a\nb"
