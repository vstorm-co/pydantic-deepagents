"""Tests for CLI interactive chat mode."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.messages import ModelMessage

from pydantic_deep.cli.interactive import (
    _handle_command,
    _print_header,
    _print_todos,
    _truncate,
    run_interactive,
)
from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.types import Todo


class TestTruncateInteractive:
    """Tests for _truncate() in interactive module."""

    def test_short_text_unchanged(self) -> None:
        assert _truncate("hello", 120) == "hello"

    def test_long_text_truncated(self) -> None:
        text = "x" * 200
        result = _truncate(text, 120)
        assert len(result) == 120
        assert result.endswith("...")


class TestPrintHeader:
    """Tests for _print_header()."""

    @patch("pydantic_deep.cli.interactive.console")
    def test_prints_header(self, mock_console: MagicMock) -> None:
        _print_header()
        assert mock_console.print.call_count >= 3


class TestPrintTodos:
    """Tests for _print_todos()."""

    @patch("pydantic_deep.cli.interactive.console")
    def test_empty_todos(self, mock_console: MagicMock) -> None:
        deps = MagicMock()
        deps.todos = []
        _print_todos(deps)
        mock_console.print.assert_called_once_with("[dim]No TODOs[/dim]")

    @patch("pydantic_deep.cli.interactive.console")
    def test_completed_todo(self, mock_console: MagicMock) -> None:
        deps = MagicMock()
        deps.todos = [Todo(content="done task", status="completed", active_form="Completing")]
        _print_todos(deps)
        # Should print: empty line, todo item, empty line
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("\u2713" in c for c in calls)

    @patch("pydantic_deep.cli.interactive.console")
    def test_in_progress_todo(self, mock_console: MagicMock) -> None:
        deps = MagicMock()
        deps.todos = [Todo(content="working", status="in_progress", active_form="Working")]
        _print_todos(deps)
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("\u25cf" in c for c in calls)

    @patch("pydantic_deep.cli.interactive.console")
    def test_pending_todo(self, mock_console: MagicMock) -> None:
        deps = MagicMock()
        deps.todos = [Todo(content="pending task", status="pending", active_form="Pending")]
        _print_todos(deps)
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("\u25cb" in c for c in calls)


class TestHandleCommand:
    """Tests for _handle_command()."""

    @patch("pydantic_deep.cli.interactive.console")
    def test_quit_command(self, _mock_console: MagicMock) -> None:
        deps = MagicMock()
        should_break, _ = _handle_command("/quit", deps, [])
        assert should_break is True

    @patch("pydantic_deep.cli.interactive.console")
    def test_exit_command(self, _mock_console: MagicMock) -> None:
        deps = MagicMock()
        should_break, _ = _handle_command("/exit", deps, [])
        assert should_break is True

    @patch("pydantic_deep.cli.interactive.console")
    def test_clear_command(self, _mock_console: MagicMock) -> None:
        deps = MagicMock()
        deps.todos = [Todo(content="test", status="pending", active_form="Testing")]
        history: list[ModelMessage] = [MagicMock()]

        should_break, new_history = _handle_command("/clear", deps, history)
        assert should_break is False
        assert new_history == []
        assert deps.todos == []

    @patch("pydantic_deep.cli.interactive._print_todos")
    @patch("pydantic_deep.cli.interactive.console")
    def test_todos_command(
        self, _mock_console: MagicMock, mock_print_todos: MagicMock
    ) -> None:
        deps = MagicMock()
        should_break, _ = _handle_command("/todos", deps, [])
        assert should_break is False
        mock_print_todos.assert_called_once_with(deps)

    @patch("pydantic_deep.cli.interactive.console")
    def test_unknown_command(self, _mock_console: MagicMock) -> None:
        deps = MagicMock()
        should_break, _ = _handle_command("/unknown", deps, [])
        assert should_break is False

    @patch("pydantic_deep.cli.interactive.console")
    def test_case_insensitive(self, _mock_console: MagicMock) -> None:
        deps = MagicMock()
        should_break, _ = _handle_command("/QUIT", deps, [])
        assert should_break is True


class TestProcessStream:
    """Tests for _process_stream()."""

    @patch("pydantic_deep.cli.interactive.console")
    async def test_process_stream_basic(self, _mock_console: MagicMock) -> None:
        from pydantic_deep.cli.interactive import _process_stream

        # Mock agent that yields no events
        mock_agent = MagicMock()

        async def empty_stream(*args: Any, **kwargs: Any) -> Any:
            return
            yield  # Make it an async generator  # noqa: RUF028

        mock_agent.run_stream_events = empty_stream
        deps = MagicMock()

        result = await _process_stream(mock_agent, "test", deps, [])
        assert isinstance(result, list)

    @patch("pydantic_deep.cli.interactive.console")
    async def test_process_stream_with_text_delta(self, _mock_console: MagicMock) -> None:
        from pydantic_deep.cli.interactive import _process_stream

        mock_agent = MagicMock()

        # Create mock events
        mock_delta = MagicMock()
        mock_delta.delta.content_delta = "Hello"
        mock_delta.__class__ = type("PartDeltaEvent", (), {})

        # Create PartDeltaEvent mock
        part_event = MagicMock(spec=[])
        part_event.delta = MagicMock()
        part_event.delta.content_delta = "Hello"

        result_event = MagicMock(spec=[])
        result_event.result = MagicMock()
        result_event.result.all_messages.return_value = []

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            from pydantic_ai import AgentRunResultEvent, PartDeltaEvent

            # Create proper mock events
            pe = MagicMock(spec=PartDeltaEvent)
            pe.delta = MagicMock()
            pe.delta.content_delta = "Hello world"

            re = MagicMock(spec=AgentRunResultEvent)
            re.result = MagicMock()
            re.result.all_messages.return_value = []

            yield pe
            yield re

        mock_agent.run_stream_events = mock_stream
        deps = MagicMock()

        result = await _process_stream(mock_agent, "test", deps, [])
        assert isinstance(result, list)

    @patch("pydantic_deep.cli.interactive.console")
    async def test_process_stream_with_tool_call(self, _mock_console: MagicMock) -> None:
        from pydantic_ai import FunctionToolCallEvent, FunctionToolResultEvent

        from pydantic_deep.cli.interactive import _process_stream

        mock_agent = MagicMock()

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            # Tool call event
            tc = MagicMock(spec=FunctionToolCallEvent)
            tc.part = MagicMock()
            tc.part.tool_name = "read_file"
            tc.part.args = {"path": "/test.py"}

            # Tool result event
            tr = MagicMock(spec=FunctionToolResultEvent)
            tr.result = MagicMock()
            tr.result.content = "file content here"

            yield tc
            yield tr

        mock_agent.run_stream_events = mock_stream
        deps = MagicMock()

        result = await _process_stream(mock_agent, "test", deps, [])
        assert isinstance(result, list)

    @patch("pydantic_deep.cli.interactive.console")
    async def test_process_stream_text_followed_by_tool(
        self, _mock_console: MagicMock
    ) -> None:
        """Text then tool call should insert newline and needs_prefix flag."""
        from pydantic_ai import (
            AgentRunResultEvent,
            FunctionToolCallEvent,
            PartDeltaEvent,
        )

        from pydantic_deep.cli.interactive import _process_stream

        mock_agent = MagicMock()

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            pe = MagicMock(spec=PartDeltaEvent)
            pe.delta = MagicMock()
            pe.delta.content_delta = "Thinking..."

            tc = MagicMock(spec=FunctionToolCallEvent)
            tc.part = MagicMock()
            tc.part.tool_name = "execute"
            tc.part.args = {"command": "ls"}

            # More text after tool
            pe2 = MagicMock(spec=PartDeltaEvent)
            pe2.delta = MagicMock()
            pe2.delta.content_delta = "Done!"

            re = MagicMock(spec=AgentRunResultEvent)
            re.result = MagicMock()
            re.result.all_messages.return_value = ["msg1"]

            yield pe
            yield tc
            yield pe2
            yield re

        mock_agent.run_stream_events = mock_stream
        deps = MagicMock()

        result = await _process_stream(mock_agent, "test", deps, [])
        assert result == ["msg1"]

    @patch("pydantic_deep.cli.interactive.console")
    async def test_process_stream_null_content_delta(
        self, _mock_console: MagicMock
    ) -> None:
        """content_delta can be None — should not crash."""
        from pydantic_ai import AgentRunResultEvent, PartDeltaEvent

        from pydantic_deep.cli.interactive import _process_stream

        mock_agent = MagicMock()

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            pe = MagicMock(spec=PartDeltaEvent)
            pe.delta = MagicMock()
            pe.delta.content_delta = None

            re = MagicMock(spec=AgentRunResultEvent)
            re.result = MagicMock()
            re.result.all_messages.return_value = []

            yield pe
            yield re

        mock_agent.run_stream_events = mock_stream
        deps = MagicMock()

        result = await _process_stream(mock_agent, "test", deps, [])
        assert isinstance(result, list)


class TestRunInteractive:
    """Tests for run_interactive()."""

    @patch("pydantic_deep.cli.interactive._process_stream")
    @patch("pydantic_deep.cli.interactive.create_cli_agent")
    @patch("pydantic_deep.cli.interactive._print_header")
    @patch("pydantic_deep.cli.interactive.console")
    @patch("builtins.input")
    async def test_quit_exits_loop(
        self,
        mock_input: MagicMock,
        _mock_console: MagicMock,
        _mock_header: MagicMock,
        mock_create: MagicMock,
        _mock_stream: MagicMock,
    ) -> None:
        mock_agent = MagicMock()
        mock_deps = MagicMock()
        mock_deps.todos = []
        mock_create.return_value = (mock_agent, mock_deps)

        mock_input.return_value = "/quit"
        await run_interactive()

    @patch("pydantic_deep.cli.interactive._process_stream")
    @patch("pydantic_deep.cli.interactive.create_cli_agent")
    @patch("pydantic_deep.cli.interactive._print_header")
    @patch("pydantic_deep.cli.interactive.console")
    @patch("builtins.input")
    async def test_empty_input_continues(
        self,
        mock_input: MagicMock,
        _mock_console: MagicMock,
        _mock_header: MagicMock,
        mock_create: MagicMock,
        _mock_stream: MagicMock,
    ) -> None:
        mock_agent = MagicMock()
        mock_deps = MagicMock()
        mock_deps.todos = []
        mock_create.return_value = (mock_agent, mock_deps)

        mock_input.side_effect = ["", "/quit"]
        await run_interactive()

    @patch("pydantic_deep.cli.interactive._process_stream")
    @patch("pydantic_deep.cli.interactive.create_cli_agent")
    @patch("pydantic_deep.cli.interactive._print_header")
    @patch("pydantic_deep.cli.interactive.console")
    @patch("builtins.input")
    async def test_message_calls_process_stream(
        self,
        mock_input: MagicMock,
        _mock_console: MagicMock,
        _mock_header: MagicMock,
        mock_create: MagicMock,
        mock_stream: MagicMock,
    ) -> None:
        mock_agent = MagicMock()
        mock_deps = MagicMock()
        mock_deps.todos = []
        mock_create.return_value = (mock_agent, mock_deps)

        mock_stream.return_value = []
        mock_input.side_effect = ["hello", "/quit"]
        await run_interactive()
        mock_stream.assert_called_once()

    @patch("pydantic_deep.cli.interactive._process_stream")
    @patch("pydantic_deep.cli.interactive.create_cli_agent")
    @patch("pydantic_deep.cli.interactive._print_header")
    @patch("pydantic_deep.cli.interactive.console")
    @patch("builtins.input")
    async def test_shows_todos_after_message(
        self,
        mock_input: MagicMock,
        _mock_console: MagicMock,
        _mock_header: MagicMock,
        mock_create: MagicMock,
        mock_stream: MagicMock,
    ) -> None:
        mock_agent = MagicMock()
        mock_deps = MagicMock()
        mock_deps.todos = [Todo(content="test task", status="pending", active_form="Testing")]
        mock_create.return_value = (mock_agent, mock_deps)

        mock_stream.return_value = []
        mock_input.side_effect = ["hello", "/quit"]

        with patch("pydantic_deep.cli.interactive._print_todos") as mock_pt:
            await run_interactive()
            mock_pt.assert_called()

    @patch("pydantic_deep.cli.interactive.create_cli_agent")
    @patch("pydantic_deep.cli.interactive._print_header")
    @patch("pydantic_deep.cli.interactive.console")
    @patch("builtins.input")
    async def test_keyboard_interrupt_continues(
        self,
        mock_input: MagicMock,
        mock_console: MagicMock,
        _mock_header: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        mock_agent = MagicMock()
        mock_deps = MagicMock()
        mock_deps.todos = []
        mock_create.return_value = (mock_agent, mock_deps)

        mock_input.side_effect = [KeyboardInterrupt(), "/quit"]
        await run_interactive()
        # Should print interrupted message
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("Interrupted" in c for c in calls)

    @patch("pydantic_deep.cli.interactive.create_cli_agent")
    @patch("pydantic_deep.cli.interactive._print_header")
    @patch("pydantic_deep.cli.interactive.console")
    @patch("builtins.input")
    async def test_eof_error_exits(
        self,
        mock_input: MagicMock,
        mock_console: MagicMock,
        _mock_header: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        mock_agent = MagicMock()
        mock_deps = MagicMock()
        mock_deps.todos = []
        mock_create.return_value = (mock_agent, mock_deps)

        mock_input.side_effect = EOFError()
        await run_interactive()
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("Goodbye" in c for c in calls)

    @patch("pydantic_deep.cli.interactive._process_stream")
    @patch("pydantic_deep.cli.interactive.create_cli_agent")
    @patch("pydantic_deep.cli.interactive._print_header")
    @patch("pydantic_deep.cli.interactive.console")
    @patch("builtins.input")
    async def test_exception_shows_error(
        self,
        mock_input: MagicMock,
        mock_console: MagicMock,
        _mock_header: MagicMock,
        mock_create: MagicMock,
        mock_stream: MagicMock,
    ) -> None:
        mock_agent = MagicMock()
        mock_deps = MagicMock()
        mock_deps.todos = []
        mock_create.return_value = (mock_agent, mock_deps)

        mock_stream.side_effect = [RuntimeError("test error"), []]
        mock_input.side_effect = ["hello", "/quit"]
        await run_interactive()
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("Error" in c for c in calls)

    @patch("pydantic_deep.cli.interactive.create_cli_agent")
    @patch("pydantic_deep.cli.interactive._print_header")
    @patch("pydantic_deep.cli.interactive.console")
    @patch("builtins.input")
    async def test_cost_callback(
        self,
        mock_input: MagicMock,
        _mock_console: MagicMock,
        _mock_header: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        """Verify create_cli_agent is called with on_cost_update."""
        mock_agent = MagicMock()
        mock_deps = MagicMock()
        mock_deps.todos = []
        mock_create.return_value = (mock_agent, mock_deps)

        mock_input.return_value = "/quit"
        await run_interactive()

        # Verify on_cost_update was passed
        call_kwargs = mock_create.call_args[1]
        assert "on_cost_update" in call_kwargs
        callback = call_kwargs["on_cost_update"]

        # Test the callback with cost info
        cost_info = MagicMock()
        cost_info.run_cost_usd = 0.0123
        cost_info.cumulative_cost_usd = 0.0456
        callback(cost_info)  # Should not raise

    @patch("pydantic_deep.cli.interactive.create_cli_agent")
    @patch("pydantic_deep.cli.interactive._print_header")
    @patch("pydantic_deep.cli.interactive.console")
    @patch("builtins.input")
    async def test_cost_callback_no_run_cost(
        self,
        mock_input: MagicMock,
        _mock_console: MagicMock,
        _mock_header: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        """Cost callback handles missing run_cost_usd."""
        mock_agent = MagicMock()
        mock_deps = MagicMock()
        mock_deps.todos = []
        mock_create.return_value = (mock_agent, mock_deps)

        mock_input.return_value = "/quit"
        await run_interactive()

        callback = mock_create.call_args[1]["on_cost_update"]

        # Object without run_cost_usd attribute
        cost_info = object()
        callback(cost_info)  # Should not raise

    @patch("pydantic_deep.cli.interactive._process_stream")
    @patch("pydantic_deep.cli.interactive.create_cli_agent")
    @patch("pydantic_deep.cli.interactive._print_header")
    @patch("pydantic_deep.cli.interactive.console")
    @patch("builtins.input")
    async def test_non_breaking_command_continues_loop(
        self,
        mock_input: MagicMock,
        _mock_console: MagicMock,
        _mock_header: MagicMock,
        mock_create: MagicMock,
        _mock_stream: MagicMock,
    ) -> None:
        """Non-breaking slash commands (e.g. /clear) should continue the loop."""
        mock_agent = MagicMock()
        mock_deps = MagicMock()
        mock_deps.todos = []
        mock_create.return_value = (mock_agent, mock_deps)

        # /clear is non-breaking, then /quit exits
        mock_input.side_effect = ["/clear", "/quit"]
        await run_interactive()


class TestProcessStreamBranches:
    """Tests for branch coverage in _process_stream()."""

    @patch("pydantic_deep.cli.interactive.console")
    async def test_delta_without_content_delta_attr(
        self, _mock_console: MagicMock
    ) -> None:
        """PartDeltaEvent where delta has no content_delta attribute."""
        from pydantic_ai import PartDeltaEvent

        from pydantic_deep.cli.interactive import _process_stream

        mock_agent = MagicMock()

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            pe = MagicMock(spec=PartDeltaEvent)
            pe.delta = MagicMock(spec=[])  # No content_delta attribute
            yield pe

        mock_agent.run_stream_events = mock_stream
        deps = MagicMock()

        result = await _process_stream(mock_agent, "test", deps, [])
        assert isinstance(result, list)

    @patch("pydantic_deep.cli.interactive.console")
    async def test_multiple_tool_calls_showed_tools_flag(
        self, _mock_console: MagicMock
    ) -> None:
        """Second tool call should not print extra newline (showed_tools=True)."""
        from pydantic_ai import FunctionToolCallEvent

        from pydantic_deep.cli.interactive import _process_stream

        mock_agent = MagicMock()

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            tc1 = MagicMock(spec=FunctionToolCallEvent)
            tc1.part = MagicMock()
            tc1.part.tool_name = "read_file"
            tc1.part.args = {"path": "/a.py"}

            tc2 = MagicMock(spec=FunctionToolCallEvent)
            tc2.part = MagicMock()
            tc2.part.tool_name = "write_file"
            tc2.part.args = {"path": "/b.py"}

            yield tc1
            yield tc2

        mock_agent.run_stream_events = mock_stream
        deps = MagicMock()

        result = await _process_stream(mock_agent, "test", deps, [])
        assert isinstance(result, list)

    @patch("pydantic_deep.cli.interactive.console")
    async def test_stream_ends_without_result_event(
        self, _mock_console: MagicMock
    ) -> None:
        """Stream that ends without AgentRunResultEvent returns message_history."""
        from pydantic_deep.cli.interactive import _process_stream

        mock_agent = MagicMock()

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            return
            yield  # noqa: RUF028

        mock_agent.run_stream_events = mock_stream
        deps = MagicMock()

        original_history: list[Any] = [MagicMock()]
        result = await _process_stream(mock_agent, "test", deps, original_history)
        assert result is original_history
