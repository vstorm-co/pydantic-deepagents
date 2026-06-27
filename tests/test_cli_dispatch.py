"""Characterization tests for the slash-command dispatcher.

These pin the observable behaviour of `dispatch_command` (notifications, screen
pushes, history mutations) so the table-driven refactor is provably
behaviour-preserving.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from apps.cli.app import DeepApp
from apps.cli.commands import dispatch_command


@pytest.fixture
def app():
    return DeepApp(model="test", version="9.9.9")


def _notify_texts(app: DeepApp) -> list[str]:
    return [str(c.args[0]) for c in app.notify.mock_calls if c.args]  # type: ignore[attr-defined]


class TestSimpleCommands:
    async def test_version_notifies_version(self, app):
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.notify = MagicMock()
            await dispatch_command(app, "/version")
            assert any("9.9.9" in t for t in _notify_texts(app))

    async def test_clear_empties_history_and_notifies(self, app):
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.message_history = ["m1", "m2"]
            app.notify = MagicMock()
            await dispatch_command(app, "/clear")
            assert app.message_history == []
            assert any("cleared" in t.lower() for t in _notify_texts(app))

    async def test_undo_removes_last_turn(self, app):
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.message_history = ["a", "b", "c", "d"]
            app.notify = MagicMock()
            await dispatch_command(app, "/undo")
            assert app.message_history == ["a", "b"]

    async def test_undo_empty_warns(self, app):
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.message_history = []
            app.notify = MagicMock()
            await dispatch_command(app, "/undo")
            assert any("no messages" in t.lower() for t in _notify_texts(app))

    async def test_cost_and_tokens_notify(self, app):
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.notify = MagicMock()
            await dispatch_command(app, "/cost")
            await dispatch_command(app, "/tokens")
            texts = _notify_texts(app)
            assert any("Cost" in t for t in texts)
            assert any("messages" in t for t in texts)

    async def test_save_notifies_autosave(self, app):
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.notify = MagicMock()
            await dispatch_command(app, "/save")
            assert any("auto-saved" in t.lower() for t in _notify_texts(app))

    async def test_unknown_command_warns(self, app):
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.notify = MagicMock()
            await dispatch_command(app, "/definitely-not-a-command")
            assert any("unknown command" in t.lower() for t in _notify_texts(app))


class TestScreenPushingCommands:
    @pytest.mark.parametrize(
        "command",
        ["/help", "/mcp", "/skills", "/settings", "/model", "/compact", "/remind"],
    )
    async def test_pushes_a_screen(self, app, command):
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            before = len(app.screen_stack)
            await dispatch_command(app, command)
            await pilot.pause()
            assert len(app.screen_stack) > before


class TestAliases:
    @pytest.mark.parametrize("command", ["/quit", "/exit", "/q"])
    async def test_quit_aliases_exit(self, app, command):
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.exit = MagicMock()
            await dispatch_command(app, command)
            app.exit.assert_called_once()


class TestShells:
    async def test_no_shells_notifies(self, app, tmp_path):
        from pydantic_ai_backends import LocalBackend

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.deps = type("D", (), {"backend": LocalBackend(root_dir=str(tmp_path))})()
            app.notify = MagicMock()
            await dispatch_command(app, "/shells")
            assert any("no background shells" in t.lower() for t in _notify_texts(app))

    async def test_unsupported_backend_warns(self, app):
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.deps = type("D", (), {"backend": object()})()
            app.notify = MagicMock()
            await dispatch_command(app, "/shells")
            assert any("aren't supported" in t.lower() for t in _notify_texts(app))

    async def test_lists_running_shells(self, app, tmp_path):
        from pydantic_ai_backends import LocalBackend

        backend = LocalBackend(root_dir=str(tmp_path))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.deps = type("D", (), {"backend": backend})()
            backend.execute_background("sleep 30")
            app.notify = MagicMock()
            await dispatch_command(app, "/shells")
            texts = _notify_texts(app)
            assert any("1 running" in t and "sleep 30" in t for t in texts)
            backend.kill_all_background()


class TestUndoSyncsWidgets:
    async def test_undo_removes_visible_turn(self, app):
        from apps.cli.widgets.assistant_message import AssistantMessage
        from apps.cli.widgets.message_list import MessageList
        from apps.cli.widgets.user_message import UserMessage

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            msg_list = app.screen.query_one(MessageList)
            msg_list.append_user_message("first")
            a = msg_list.begin_assistant_message()
            a.append_text("reply")
            await pilot.pause()
            app.message_history = ["req", "resp"]
            assert len(msg_list.query(UserMessage)) == 1
            assert len(msg_list.query(AssistantMessage)) == 1

            await dispatch_command(app, "/undo")
            await pilot.pause()
            # Both history and the on-screen turn are gone.
            assert app.message_history == []
            assert len(msg_list.query(UserMessage)) == 0
            assert len(msg_list.query(AssistantMessage)) == 0


class TestRetry:
    async def test_no_prompt_warns(self, app):
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.last_user_prompt = ""
            app.notify = MagicMock()
            await dispatch_command(app, "/retry")
            assert any("nothing to retry" in t.lower() for t in _notify_texts(app))

    async def test_reruns_last_prompt_and_drops_turn(self, app):
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.last_user_prompt = "do the thing"
            app.message_history = ["a", "b", "c", "d"]
            app.agent_task = None
            app.screen._run_agent = MagicMock()
            app.notify = MagicMock()
            await dispatch_command(app, "/retry")
            # Previous turn dropped, last prompt re-dispatched.
            assert app.message_history == ["a", "b"]
            app.screen._run_agent.assert_called_once_with("do the thing")

    async def test_blocked_while_running(self, app):
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.last_user_prompt = "x"
            running = MagicMock()
            running.done.return_value = False
            app.agent_task = running
            app.screen._run_agent = MagicMock()
            app.notify = MagicMock()
            await dispatch_command(app, "/retry")
            assert any("still running" in t.lower() for t in _notify_texts(app))
            app.screen._run_agent.assert_not_called()


class TestExport:
    async def test_nothing_to_export_warns(self, app):
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.notify = MagicMock()
            await dispatch_command(app, "/export")
            assert any("nothing to export" in t.lower() for t in _notify_texts(app))

    async def test_writes_markdown(self, app, tmp_path):
        from apps.cli.widgets.message_list import MessageList

        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            msg_list = app.screen.query_one(MessageList)
            msg_list.append_user_message("hello there")
            assistant = msg_list.begin_assistant_message()
            assistant.append_text("general kenobi")
            await pilot.pause()
            target = tmp_path / "out" / "convo.md"
            app.notify = MagicMock()
            await dispatch_command(app, f"/export {target}")
            assert target.exists()
            content = target.read_text(encoding="utf-8")
            assert "hello there" in content
            assert "general kenobi" in content
            assert "## You" in content and "## Assistant" in content
            assert any("Exported" in t for t in _notify_texts(app))

    async def test_default_path_in_cwd(self, app, tmp_path, monkeypatch):
        from apps.cli.widgets.message_list import MessageList

        # Run with cwd pointed at tmp so the default conversation-*.md lands there.
        monkeypatch.chdir(tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.screen.query_one(MessageList).append_user_message("hi")
            await pilot.pause()
            app.notify = MagicMock()
            await dispatch_command(app, "/export")
            exports = list(tmp_path.glob("conversation-*.md"))
            assert len(exports) == 1
            assert "hi" in exports[0].read_text(encoding="utf-8")
