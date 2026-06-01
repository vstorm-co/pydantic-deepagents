"""Tests for the Textual TUI."""

from __future__ import annotations

from typing import cast

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

    async def test_cost_uses_authoritative_total_cost(self, app):
        """/cost reports the tracked CostTracking total (any model) when available,
        not the hardcoded Sonnet-rate heuristic."""
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.pause()
            from apps.cli.commands import dispatch_command

            messages: list[str] = []
            app.notify = lambda msg, **kw: messages.append(msg)
            app.total_cost = 0.1234

            await dispatch_command(app, "/cost")
            await pilot.pause()

        assert messages
        # Exact tracked value, no "~" estimate prefix.
        assert "$0.1234" in messages[-1]
        assert "~$" not in messages[-1]

    async def test_cost_falls_back_to_heuristic_without_tracked_cost(self, app):
        """When no tracked cost is available, /cost shows the rough estimate marked
        with a "~" prefix."""
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.pause()
            from apps.cli.commands import dispatch_command

            messages: list[str] = []
            app.notify = lambda msg, **kw: messages.append(msg)
            app.total_cost = 0.0

            await dispatch_command(app, "/cost")
            await pilot.pause()

        assert messages
        assert "~$" in messages[-1]


class TestReconfigureAgent:
    async def test_reconfigure_preserves_callbacks(self, monkeypatch):
        """After /model, reconfigure_agent must re-pass the status-bar/reminder
        callbacks so cost/token/context updates and reminders keep working."""
        sentinel_cost = object()
        sentinel_ctx = object()
        sentinel_rem = object()

        app = DeepApp(
            model="test",
            version="0.0.0",
            on_cost_update=sentinel_cost,
            on_context_update=sentinel_ctx,
            on_reminder=sentinel_rem,
        )

        captured: dict[str, object] = {}

        def fake_create(**kwargs):
            captured.update(kwargs)
            return ("AGENT", "DEPS")

        import apps.cli.agent as agent_mod
        import apps.cli.config as config_mod

        monkeypatch.setattr(agent_mod, "create_cli_agent", fake_create)
        monkeypatch.setattr(config_mod, "set_config_value", lambda *a, **k: None)

        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            # Explicit model skips key-based model picking; deterministic.
            app.reconfigure_agent(model="anthropic:claude-sonnet-4-6")
            await pilot.pause()

        assert captured["on_cost_update"] is sentinel_cost
        assert captured["on_context_update"] is sentinel_ctx
        assert captured["on_reminder"] is sentinel_rem
        assert cast(object, app.agent) == "AGENT"
        assert cast(object, app.deps) == "DEPS"


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

    async def test_search_modal_escapes_markup_in_snippet(self, app):
        """Messages with literal Rich markup must not corrupt the option label."""
        async with app.run_test(size=(120, 35)) as pilot:
            await pilot.pause()
            await pilot.pause()
            from apps.cli.widgets.message_list import MessageList

            msg_list = app.screen.query_one(MessageList)
            # Message containing literal Rich markup that would otherwise be parsed
            msg_list.append_user_message("the [red]danger[/] keyword is special")
            await pilot.pause()

            await pilot.press("ctrl+r")
            await pilot.pause()

            from textual.widgets import Input, OptionList

            from apps.cli.modals.search import SearchModal

            modal = next(s for s in app.screen_stack if isinstance(s, SearchModal))
            search_input = modal.query_one("#search-input", Input)
            search_input.value = "danger"
            modal.on_input_changed(Input.Changed(search_input, "danger"))
            await pilot.pause()

            option_list = modal.query_one("#search-results", OptionList)
            # The matching snippet should have produced exactly one option without
            # raising a Rich MarkupError; the raw markup is preserved escaped.
            assert option_list.option_count == 1
            assert modal._matches[0][1] == "the [red]danger[/] keyword is special"


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
            app.agent_task = task

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
            app.agent_task = task

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
