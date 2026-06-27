"""Tests for clipboard image paste flow + subagents panel merge."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from apps.cli import clipboard_image as ci
from apps.cli.app import DeepApp
from apps.cli.messages import UserSubmitted
from apps.cli.screens.chat import ChatScreen

_PNG = b"\x89PNG\r\nfake-bytes"


@pytest.fixture
def app() -> DeepApp:
    return DeepApp(model="test", version="0.0.0")


async def test_attach_clipboard_image_no_image(
    app: DeepApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        monkeypatch.setattr(ci, "grab_clipboard_image", lambda: None)
        screen = cast(ChatScreen, app.screen)
        screen.attach_clipboard_image()
        await pilot.pause()
        assert screen._pending_images == []


def test_dropped_file_path_detection(tmp_path: Path) -> None:
    from apps.cli.widgets.input_area import _dropped_file_path

    f = tmp_path / "report.html"
    f.write_text("<html>")
    assert _dropped_file_path(f"'{f}' ") == str(f)  # quoted + trailing space
    assert _dropped_file_path(str(f)) == str(f)
    assert _dropped_file_path("just some pasted text") is None
    assert _dropped_file_path(f"{f}\nmore") is None  # multiline paste, not a drop
    assert _dropped_file_path(str(tmp_path)) is None  # a directory, not a file


def test_escape_markup_brackets() -> None:
    from apps.cli.widgets.input_area import _escape_markup

    assert _escape_markup("[Image #1]") == r"\[Image #1]"


async def test_clipboard_image_shows_chip(app: DeepApp, monkeypatch: pytest.MonkeyPatch) -> None:
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        await pilot.pause()
        monkeypatch.setattr(ci, "grab_clipboard_image", lambda: (_PNG, "image/png"))
        screen = cast(ChatScreen, app.screen)
        screen.attach_clipboard_image()
        await pilot.pause()
        assert screen._attachment_labels == ["[Image #1]"]
        from textual.widgets import Static

        bar = app.screen.query_one("#attachments-bar", Static)
        assert bar.has_class("visible")
        assert "Image #1" in str(bar.render())


async def test_dropped_image_attaches_as_chip(app: DeepApp, tmp_path: Path) -> None:
    from apps.cli.messages import AttachFileRequested

    img = tmp_path / "shot.png"
    img.write_bytes(_PNG)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        await pilot.pause()
        screen = cast(ChatScreen, app.screen)
        screen.on_attach_file_requested(AttachFileRequested(str(img)))
        await pilot.pause()
        assert len(screen._pending_images) == 1
        assert screen._attachment_labels == ["[shot.png]"]


async def test_dropped_non_image_becomes_at_reference(app: DeepApp, tmp_path: Path) -> None:
    from apps.cli.messages import AttachFileRequested
    from apps.cli.widgets.input_area import PromptInput

    doc = tmp_path / "notes.md"
    doc.write_text("# notes")
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        await pilot.pause()
        screen = cast(ChatScreen, app.screen)
        screen.on_attach_file_requested(AttachFileRequested(str(doc)))
        await pilot.pause()
        assert screen._pending_images == []  # not an image
        assert f"@{doc}" in app.screen.query_one(PromptInput).value


async def test_submit_renders_clean_attachment_subline(
    app: DeepApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The conversation shows attachments as a dim `└ [Image #1]` sub-line, not
    a literal `[dim]…[/dim]` badge."""
    from textual.widgets import Static

    from apps.cli.widgets.message_list import MessageList
    from apps.cli.widgets.user_message import UserMessage

    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        await pilot.pause()
        monkeypatch.setattr(ci, "grab_clipboard_image", lambda: (_PNG, "image/png"))
        screen = cast(ChatScreen, app.screen)
        monkeypatch.setattr(app, "agent", object())
        monkeypatch.setattr(screen, "_run_agent", lambda prompt: None)

        screen.attach_clipboard_image()
        await pilot.pause()
        await screen.on_user_submitted(UserSubmitted("what do you see"))
        await pilot.pause()

        msg = app.screen.query_one(MessageList).query(UserMessage).last()
        rendered = " ".join(str(s.render()) for s in msg.query(Static))
        assert "Image #1" in rendered
        assert "[dim]" not in rendered  # markup applied, not shown literally
        assert "└" in rendered


async def test_clear_attachments(app: DeepApp, monkeypatch: pytest.MonkeyPatch) -> None:
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        await pilot.pause()
        monkeypatch.setattr(ci, "grab_clipboard_image", lambda: (_PNG, "image/png"))
        screen = cast(ChatScreen, app.screen)
        screen.attach_clipboard_image()
        await pilot.pause()
        screen.clear_attachments()
        await pilot.pause()
        assert screen._pending_images == []
        assert screen._attachment_labels == []
        from textual.widgets import Static

        assert not app.screen.query_one("#attachments-bar", Static).has_class("visible")


async def test_attach_and_submit_builds_multimodal_prompt(
    app: DeepApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        await pilot.pause()
        monkeypatch.setattr(ci, "grab_clipboard_image", lambda: (_PNG, "image/png"))
        screen = cast(ChatScreen, app.screen)
        monkeypatch.setattr(app, "agent", object())  # truthy: pass the guard

        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            screen, "_run_agent", lambda prompt: captured.__setitem__("prompt", prompt)
        )

        screen.attach_clipboard_image()
        await pilot.pause()
        assert len(screen._pending_images) == 1

        await screen.on_user_submitted(UserSubmitted("describe this"))
        await pilot.pause()

        prompt = captured["prompt"]
        assert isinstance(prompt, list)
        assert prompt[0] == "describe this"
        # Second element is a pydantic-ai BinaryContent with our bytes.
        from pydantic_ai.messages import BinaryContent

        assert isinstance(prompt[1], BinaryContent)
        assert prompt[1].data == _PNG
        # Pending images cleared after submit.
        assert screen._pending_images == []


async def test_at_reference_image_attaches_as_multimodal(
    app: DeepApp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    img = tmp_path / "shot.png"
    img.write_bytes(_PNG)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        screen = cast(ChatScreen, app.screen)
        monkeypatch.setattr(app, "working_dir", str(tmp_path), raising=False)
        expanded = screen._expand_file_refs("look at @shot.png please")
        assert "[image: shot.png]" in expanded
        assert len(screen._pending_images) == 1
        assert screen._pending_images[0][1] == "image/png"


async def test_at_reference_text_passes_path_not_contents(
    app: DeepApp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    f = tmp_path / "note.txt"
    f.write_text("hello world")
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        screen = cast(ChatScreen, app.screen)
        monkeypatch.setattr(app, "working_dir", str(tmp_path), raising=False)
        expanded = screen._expand_file_refs("see @note.txt")
        # The path is handed to the agent; its contents are NOT inlined.
        assert "`note.txt`" in expanded
        assert "hello world" not in expanded
        assert screen._pending_images == []


async def test_at_reference_image_with_spaces_quoted(
    app: DeepApp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A quoted @-ref with spaces (e.g. a screenshot) attaches as an image."""
    img = tmp_path / "Screenshot 2026-06-27 at 10.34.39.png"
    img.write_bytes(_PNG)
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        screen = cast(ChatScreen, app.screen)
        monkeypatch.setattr(app, "working_dir", str(tmp_path), raising=False)
        expanded = screen._expand_file_refs(
            'what you see here @"Screenshot 2026-06-27 at 10.34.39.png"'
        )
        assert "[image: Screenshot 2026-06-27 at 10.34.39.png]" in expanded
        assert len(screen._pending_images) == 1
        assert screen._pending_images[0][1] == "image/png"


async def test_at_reference_text_with_spaces_quoted(
    app: DeepApp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    f = tmp_path / "my notes.md"
    f.write_text("# notes")
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        screen = cast(ChatScreen, app.screen)
        monkeypatch.setattr(app, "working_dir", str(tmp_path), raising=False)
        expanded = screen._expand_file_refs('read @"my notes.md" now')
        assert "`my notes.md`" in expanded
        assert "# notes" not in expanded


async def test_at_reference_unquoted_still_works(
    app: DeepApp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Bare (unquoted) refs without spaces keep working alongside quoted ones."""
    img = tmp_path / "a.png"
    img.write_bytes(_PNG)
    (tmp_path / "x.txt").write_text("data")
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        screen = cast(ChatScreen, app.screen)
        monkeypatch.setattr(app, "working_dir", str(tmp_path), raising=False)
        expanded = screen._expand_file_refs("see @a.png and @x.txt")
        assert "[image: a.png]" in expanded
        assert "`x.txt`" in expanded
        assert len(screen._pending_images) == 1


async def test_submit_without_agent_keeps_images(
    app: DeepApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        monkeypatch.setattr(ci, "grab_clipboard_image", lambda: (_PNG, "image/png"))
        screen = cast(ChatScreen, app.screen)
        monkeypatch.setattr(app, "agent", None)  # no agent configured
        ran: dict[str, Any] = {}
        monkeypatch.setattr(screen, "_run_agent", lambda p: ran.__setitem__("ran", True))

        screen.attach_clipboard_image()
        await pilot.pause()
        await screen.on_user_submitted(UserSubmitted("hi"))
        await pilot.pause()
        # Image preserved, agent not run.
        assert len(screen._pending_images) == 1
        assert "ran" not in ran


async def test_capture_old_content_skips_large_and_sentinel(app: DeepApp) -> None:
    from apps.cli.screens.chat import ChatScreen

    class _Backend:
        data = b""

        def exists(self, path: str) -> bool:
            return True

        def read_bytes(self, path: str) -> bytes:
            return self.data

    backend = _Backend()

    class _Deps:
        backend: Any

    deps = _Deps()
    deps.backend = backend

    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        screen = cast(ChatScreen, app.screen)
        app.deps = deps

        backend.data = b"old text"
        args: dict[str, Any] = {"file_path": "/x", "content": "new"}
        screen._capture_old_content("write_file", args)
        assert args["_old_content"] == "old text"

        backend.data = b"x" * (ChatScreen._MAX_DIFF_READ_BYTES + 1)
        big: dict[str, Any] = {"file_path": "/x", "content": "new"}
        screen._capture_old_content("write_file", big)
        assert "_old_content" not in big

        backend.data = b"[Error: not found]"
        err: dict[str, Any] = {"file_path": "/x", "content": "new"}
        screen._capture_old_content("write_file", err)
        assert "_old_content" not in err


async def test_paste_action_delegates_to_screen(
    app: DeepApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        called: dict[str, bool] = {}
        monkeypatch.setattr(
            app.screen, "attach_clipboard_image", lambda: called.__setitem__("hit", True)
        )
        app.action_paste_image()
        assert called.get("hit") is True


async def test_subagents_panel_keeps_idle_agents(app: DeepApp) -> None:
    from apps.cli.widgets.subagents_panel import SubagentsWidget

    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        screen = cast(ChatScreen, app.screen)
        # Default baseline (no agent configured) is planner + research.
        known = screen._known_subagents
        assert "planner" in known and "research" in known

        # One task running for 'planner'; 'research' must stay tracked as idle.
        screen._update_subagents_panel(
            {"call-1": {"name": "planner", "status": "running", "description": "plan it"}}
        )
        await pilot.pause()
        widget = app.screen.query_one(SubagentsWidget)
        names = [a["name"] for a in widget.agents]
        assert "planner" in names
        assert "research" in names  # idle one not dropped
        planner = next(a for a in widget.agents if a["name"] == "planner")
        assert planner["status"] == "running"
        research = next(a for a in widget.agents if a["name"] == "research")
        assert research["status"] == "idle"


async def test_capture_old_content_for_write_file(app: DeepApp) -> None:
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        screen = cast(ChatScreen, app.screen)

        class _FakeBackend:
            def exists(self, path: str) -> bool:
                return True

            def read_bytes(self, path: str) -> bytes:
                return b"old content here"

        class _Deps:
            backend = _FakeBackend()

        app.deps = _Deps()
        args = {"file_path": "/x.md", "content": "new"}
        screen._capture_old_content("write_file", args)
        assert args["_old_content"] == "old content here"

        # Non-write tools are untouched.
        other = {"command": "ls"}
        screen._capture_old_content("execute", other)
        assert "_old_content" not in other


async def test_capture_old_content_missing_file(app: DeepApp) -> None:
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        screen = cast(ChatScreen, app.screen)

        class _FakeBackend:
            def exists(self, path: str) -> bool:
                return False

            def read_bytes(self, path: str) -> bytes:  # pragma: no cover
                raise AssertionError("should not read")

        class _Deps:
            backend = _FakeBackend()

        app.deps = _Deps()
        args = {"file_path": "/missing.md", "content": "new"}
        screen._capture_old_content("write_file", args)
        assert "_old_content" not in args


async def test_ctrl_v_triggers_paste(app: DeepApp, monkeypatch: pytest.MonkeyPatch) -> None:
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        await pilot.pause()
        called: dict[str, bool] = {}
        monkeypatch.setattr(
            app.screen, "attach_clipboard_image", lambda: called.__setitem__("hit", True)
        )
        from apps.cli.widgets.input_area import InputArea

        app.screen.query_one(InputArea).focus_input()
        await pilot.pause()
        await pilot.press("ctrl+v")
        await pilot.pause()
        assert called.get("hit") is True


async def test_signal_cancelling_marks_tool_calls(app: DeepApp) -> None:
    from apps.cli.widgets.message_list import MessageList

    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        msg_list = app.screen.query_one(MessageList)
        assistant = msg_list.begin_assistant_message()
        widget = assistant.add_tool_call("execute", {"command": "sleep 9"}, "c1")
        await pilot.pause()
        app._signal_cancelling()
        await pilot.pause()
        assert widget._cancelling is True
