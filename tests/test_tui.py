"""Tests for the Textual TUI."""

from __future__ import annotations

import pytest

from apps.cli.app import DeepApp


@pytest.fixture
def app():
    return DeepApp(model="test", version="0.3.3")


class TestTUIWidgets:
    async def test_app_starts(self, app):
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            assert app.screen.__class__.__name__ == "ChatScreen"

    async def test_welcome_shown(self, app):
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.pause()
            from apps.cli.widgets.message_list import MessageList

            msg_list = app.screen.query_one(MessageList)
            assert len(msg_list.children) >= 1

    async def test_user_message(self, app):
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.pause()
            from apps.cli.widgets.message_list import MessageList

            msg_list = app.screen.query_one(MessageList)
            msg_list.append_user_message("test")
            await pilot.pause()
            assert len(msg_list.children) >= 2

    async def test_shell_command(self, app):
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.pause()
            app.run_shell_command("echo hello")
            await pilot.pause()
            from apps.cli.widgets.message_list import MessageList

            msg_list = app.screen.query_one(MessageList)
            # welcome + user "!echo hello" + assistant result = 3+
            assert len(msg_list.children) >= 3

    async def test_header_state(self, app):
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.pause()
            from apps.cli.widgets.header import DeepHeader

            header = app.screen.query_one(DeepHeader)
            assert header.version == "0.3.3"
            assert header.model_name == "test"

    async def test_status_bar(self, app):
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.pause()
            from apps.cli.widgets.status_bar import StatusBar

            status = app.screen.query_one(StatusBar)
            assert status.model_name == "test"

    async def test_commands_dispatch(self, app):
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.pause()
            from apps.cli.commands import dispatch_command

            await dispatch_command(app, "/version")
            await dispatch_command(app, "/cost")
            await dispatch_command(app, "/tokens")
            await pilot.pause()


class TestSearchModal:
    async def test_search_modal_opens(self, app):
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.pause()
            # Add some messages to search through
            from apps.cli.widgets.message_list import MessageList

            msg_list = app.screen.query_one(MessageList)
            msg_list.append_user_message("hello world")
            assistant = msg_list.begin_assistant_message()
            assistant.append_text("I can help you")
            assistant.finalize_text()
            msg_list.end_assistant_message()
            await pilot.pause()

            # Open search modal via Ctrl+R
            await pilot.press("ctrl+r")
            await pilot.pause()

            from apps.cli.modals.search import SearchModal

            # Check that search modal is showing
            assert any(isinstance(s, SearchModal) for s in app.screen_stack)


class TestToolCallWidget:
    async def test_tool_call_expand_collapse(self, app):
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.pause()
            from apps.cli.widgets.message_list import MessageList

            msg_list = app.screen.query_one(MessageList)
            assistant = msg_list.begin_assistant_message()
            tool = assistant.add_tool_call("read_file", {"file_path": "test.py"}, "c1")
            tool.complete("line1\nline2\nline3\nline4\nline5", 0.5)
            await pilot.pause()

            # Initially not expanded
            assert tool.expanded is False
            assert tool.can_focus is True

            # Toggle expand
            tool.action_toggle_expand()
            assert tool.expanded is True

            # Toggle collapse
            tool.action_toggle_expand()
            assert tool.expanded is False

            msg_list.end_assistant_message()


class TestThemes:
    def test_available_themes(self):
        from apps.cli.styles.themes import available_themes

        themes = available_themes()
        assert "default" in themes
        assert "ocean" in themes
        assert "rose" in themes
        assert "minimal" in themes

    def test_theme_colors(self):
        from apps.cli.styles.themes import THEMES

        assert THEMES["ocean"]["primary"] == "#3b82f6"
        assert THEMES["rose"]["primary"] == "#f43f5e"
        assert THEMES["minimal"]["primary"] == "#a0a0a0"

    async def test_register_themes(self, app):
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            # Themes should have been registered in __init__
            # Verify by trying to apply one
            from apps.cli.styles.themes import apply_theme

            apply_theme(app, "ocean")
            # May or may not succeed depending on Textual version
            # but should not raise
            await pilot.pause()

    async def test_theme_command(self, app):
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.pause()
            from apps.cli.commands import dispatch_command

            await dispatch_command(app, "/theme")
            await pilot.pause()
            # Unknown theme
            await dispatch_command(app, "/theme badname")
            await pilot.pause()


class TestFileRefs:
    async def test_expand_file_refs_existing(self, app):
        """Test that @file refs expand for existing files."""
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.pause()
            from apps.cli.screens.chat import ChatScreen

            chat = app.screen
            assert isinstance(chat, ChatScreen)
            # pyproject.toml should exist in the working dir
            result = chat._expand_file_refs("look at @pyproject.toml please")
            # If pyproject.toml exists in cwd, it should be expanded
            import os

            if os.path.isfile(os.path.join(app.working_dir, "pyproject.toml")):
                assert '<file path="pyproject.toml">' in result
            else:
                # If not, it should be left as-is
                assert "@pyproject.toml" in result

    async def test_expand_file_refs_nonexistent(self, app):
        """Non-existent files should be left as-is."""
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.pause()
            from apps.cli.screens.chat import ChatScreen

            chat = app.screen
            assert isinstance(chat, ChatScreen)
            result = chat._expand_file_refs("look at @nonexistent_file_xyz.txt")
            assert "@nonexistent_file_xyz.txt" in result

    async def test_expand_multiple_refs(self, app):
        """Multiple @file references should all be processed."""
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.pause()
            from apps.cli.screens.chat import ChatScreen

            chat = app.screen
            assert isinstance(chat, ChatScreen)
            result = chat._expand_file_refs("@nofile1.txt and @nofile2.txt")
            assert "@nofile1.txt" in result
            assert "@nofile2.txt" in result


class TestMessageQueueIntegration:
    async def test_steer_queued_when_agent_running(self, app):
        """Submitting >>text while agent is running routes to queue.steer()."""
        import asyncio

        from apps.cli.messages import UserSubmitted
        from apps.cli.screens.chat import ChatScreen
        from pydantic_deep.capabilities.message_queue import MessageQueue

        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.pause()

            chat = app.screen
            assert isinstance(chat, ChatScreen)

            # Ensure there is a queue (may be None if agent not yet configured)
            if app.queue is None:
                app.queue = MessageQueue()

            # Simulate a long-running agent task
            barrier = asyncio.Event()

            async def _fake_agent() -> None:
                await barrier.wait()

            task = asyncio.create_task(_fake_agent())
            app._agent_task = task

            # Submit steering input while agent is "running"
            chat.post_message(UserSubmitted(">>stop and summarise"))
            await pilot.pause()
            await pilot.pause()

            steering, _ = app.queue.pending_count()
            assert steering == 1
            drained = await app.queue.drain_steering()
            assert drained[0].content == "stop and summarise"
            assert drained[0].priority == "steering"

            # Cleanup
            barrier.set()
            await task

    async def test_follow_up_queued_when_agent_running(self, app):
        """Submitting plain text while agent is running routes to queue.follow_up()."""
        import asyncio

        from apps.cli.messages import UserSubmitted
        from apps.cli.screens.chat import ChatScreen
        from pydantic_deep.capabilities.message_queue import MessageQueue

        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.pause()

            chat = app.screen
            assert isinstance(chat, ChatScreen)

            if app.queue is None:
                app.queue = MessageQueue()

            barrier = asyncio.Event()

            async def _fake_agent() -> None:
                await barrier.wait()

            task = asyncio.create_task(_fake_agent())
            app._agent_task = task

            chat.post_message(UserSubmitted("when done, write a test"))
            await pilot.pause()
            await pilot.pause()

            _, follow_up = app.queue.pending_count()
            assert follow_up == 1
            drained = await app.queue.drain_follow_up()
            assert drained[0].content == "when done, write a test"
            assert drained[0].priority == "follow_up"

            barrier.set()
            await task
