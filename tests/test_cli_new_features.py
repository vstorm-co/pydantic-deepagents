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
