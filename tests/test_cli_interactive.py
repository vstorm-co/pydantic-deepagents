"""Tests for CLI interactive chat mode."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.messages import ModelMessage

from cli.interactive import (
    _handle_command,
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
        assert len(result) <= 120
        # Ends with glyph ellipsis (Unicode "…" or ASCII "...")
        assert result.endswith("\u2026") or result.endswith("...")


class TestPrintWelcomeBanner:
    """Tests for print_welcome_banner()."""

    @patch("cli.display._get_git_branch", return_value="main")
    @patch("cli.display.__version__", "0.0.0", create=True)
    def test_prints_banner(self, _mock_branch: MagicMock) -> None:
        from cli.display import print_welcome_banner

        mock_console = MagicMock()
        with patch("cli.display.__version__", "0.0.0", create=True):
            print_welcome_banner(mock_console, model="test-model", working_dir="/tmp")
        assert mock_console.print.call_count >= 2


class TestPrintTodos:
    """Tests for _print_todos()."""

    @patch("cli.interactive.console")
    def test_empty_todos(self, mock_console: MagicMock) -> None:
        deps = MagicMock()
        deps.todos = []
        _print_todos(deps)
        # Empty list should not print anything
        mock_console.print.assert_not_called()

    @patch("cli.interactive.console")
    def test_completed_todo(self, mock_console: MagicMock) -> None:
        deps = MagicMock()
        deps.todos = [Todo(content="done task", status="completed", active_form="Completing")]
        _print_todos(deps)
        # Should print: empty line, todo item, empty line
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("\u2713" in c for c in calls)

    @patch("cli.interactive.console")
    def test_in_progress_todo(self, mock_console: MagicMock) -> None:
        deps = MagicMock()
        deps.todos = [Todo(content="working", status="in_progress", active_form="Working")]
        _print_todos(deps)
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("\u25cf" in c for c in calls)

    @patch("cli.interactive.console")
    def test_pending_todo(self, mock_console: MagicMock) -> None:
        deps = MagicMock()
        deps.todos = [Todo(content="pending task", status="pending", active_form="Pending")]
        _print_todos(deps)
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("\u25cb" in c for c in calls)


class TestHandleCommand:
    """Tests for _handle_command()."""

    @patch("cli.interactive.console")
    async def test_quit_command(self, _mock_console: MagicMock) -> None:
        deps = MagicMock()
        should_break, _ = await _handle_command("/quit", deps, [])
        assert should_break is True

    @patch("cli.interactive.console")
    async def test_exit_command(self, _mock_console: MagicMock) -> None:
        deps = MagicMock()
        should_break, _ = await _handle_command("/exit", deps, [])
        assert should_break is True

    @patch("cli.interactive.console")
    async def test_clear_command(self, _mock_console: MagicMock) -> None:
        deps = MagicMock()
        deps.todos = [Todo(content="test", status="pending", active_form="Testing")]
        history: list[ModelMessage] = [MagicMock()]

        should_break, new_history = await _handle_command("/clear", deps, history)
        assert should_break is False
        assert new_history == []
        assert deps.todos == []

    @patch("cli.interactive._print_todos")
    @patch("cli.interactive.console")
    async def test_todos_command(self, _mock_console: MagicMock, mock_print_todos: MagicMock) -> None:
        deps = MagicMock()
        should_break, _ = await _handle_command("/todos", deps, [])
        assert should_break is False
        mock_print_todos.assert_called_once_with(deps)

    @patch("cli.interactive.console")
    async def test_unknown_command(self, _mock_console: MagicMock) -> None:
        deps = MagicMock()
        should_break, _ = await _handle_command("/unknown", deps, [])
        assert should_break is False

    @patch("cli.interactive.console")
    async def test_case_insensitive(self, _mock_console: MagicMock) -> None:
        deps = MagicMock()
        should_break, _ = await _handle_command("/QUIT", deps, [])
        assert should_break is True

    @patch("cli.interactive.console")
    async def test_cost_command_no_data(self, mock_console: MagicMock) -> None:
        deps = MagicMock()
        should_break, _ = await _handle_command("/cost", deps, [])
        assert should_break is False
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("No cost data" in c for c in calls)

    @patch("cli.interactive.console")
    async def test_cost_command_with_data(self, mock_console: MagicMock) -> None:
        deps = MagicMock()
        should_break, _ = await _handle_command("/cost", deps, [], cumulative_cost=0.0456)
        assert should_break is False
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("0.0456" in c for c in calls)

    @patch("cli.interactive.console")
    async def test_help_shows_cost_command(self, mock_console: MagicMock) -> None:
        deps = MagicMock()
        await _handle_command("/help", deps, [])
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("/cost" in c for c in calls)


class TestPrintModelError:
    """Tests for _print_model_error()."""

    @patch("cli.interactive.print_error")
    @patch("cli.interactive.console")
    def test_api_key_error(self, _mock_console: MagicMock, mock_print_error: MagicMock) -> None:
        from cli.interactive import _print_model_error

        _print_model_error(ValueError("Missing api_key for provider"))
        mock_print_error.assert_called_once()
        call_kwargs = mock_print_error.call_args
        assert "hint" in call_kwargs[1]

    @patch("cli.interactive.print_error")
    @patch("cli.interactive.console")
    def test_non_api_key_error(self, _mock_console: MagicMock, mock_print_error: MagicMock) -> None:
        from cli.interactive import _print_model_error

        _print_model_error(RuntimeError("Connection timeout"))
        mock_print_error.assert_called_once()
        call_args = mock_print_error.call_args[0]
        assert "Connection timeout" in str(call_args)


class TestCreateSandboxBackend:
    """Tests for _create_sandbox_backend()."""

    @patch("cli.interactive.print_error")
    @patch("cli.interactive.console")
    def test_import_error(self, _mock_console: MagicMock, mock_print_error: MagicMock) -> None:
        from cli.interactive import _create_sandbox_backend

        with patch.dict("sys.modules", {"pydantic_ai_backends": None}):
            import builtins

            original_import = builtins.__import__

            def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
                if name == "pydantic_ai_backends":
                    raise ImportError("No module")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=fake_import):
                result = _create_sandbox_backend("python-minimal")
        assert result is None
        mock_print_error.assert_called_once()


class TestStopSandbox:
    """Tests for _stop_sandbox()."""

    @patch("cli.interactive.print_warning")
    @patch("cli.interactive.console")
    def test_cleanup_failure(self, _mock_console: MagicMock, mock_warning: MagicMock) -> None:
        from cli.interactive import _stop_sandbox

        mock_sandbox = MagicMock()
        mock_sandbox.stop.side_effect = RuntimeError("cleanup failed")
        _stop_sandbox(mock_sandbox)
        mock_warning.assert_called_once()

    @patch("cli.interactive.console")
    def test_cleanup_success(self, _mock_console: MagicMock) -> None:
        from cli.interactive import _stop_sandbox

        mock_sandbox = MagicMock()
        _stop_sandbox(mock_sandbox)
        mock_sandbox.stop.assert_called_once()


class TestStreamToolCalls:
    """Tests for _stream_tool_calls()."""

    @patch("cli.interactive.console")
    async def test_tool_call_event(self, mock_console: MagicMock) -> None:
        from pydantic_ai.messages import FunctionToolCallEvent

        from cli.interactive import _stream_tool_calls

        tc = MagicMock(spec=FunctionToolCallEvent)
        tc.part = MagicMock()
        tc.part.tool_name = "read_file"
        tc.part.args = {"path": "/test.py"}

        async def fake_stream():
            yield tc

        node = MagicMock()
        ctx = MagicMock()

        class FakeHandle:
            async def __aenter__(self):
                return fake_stream()

            async def __aexit__(self, *args: Any):
                pass

        node.stream.return_value = FakeHandle()

        await _stream_tool_calls(node, ctx)
        mock_console.print.assert_called()

    @patch("cli.interactive.console")
    async def test_tool_result_event(self, mock_console: MagicMock) -> None:
        from pydantic_ai.messages import FunctionToolResultEvent

        from cli.interactive import _stream_tool_calls

        tr = MagicMock(spec=FunctionToolResultEvent)
        tr.result = MagicMock()
        tr.result.tool_name = "read_file"
        tr.result.content = "file content here"

        async def fake_stream():
            yield tr

        node = MagicMock()
        ctx = MagicMock()

        class FakeHandle:
            async def __aenter__(self):
                return fake_stream()

            async def __aexit__(self, *args: Any):
                pass

        node.stream.return_value = FakeHandle()

        await _stream_tool_calls(node, ctx)
        mock_console.print.assert_called()

    @patch("cli.interactive.console")
    async def test_non_dict_args(self, mock_console: MagicMock) -> None:
        from pydantic_ai.messages import FunctionToolCallEvent

        from cli.interactive import _stream_tool_calls

        tc = MagicMock(spec=FunctionToolCallEvent)
        tc.part = MagicMock()
        tc.part.tool_name = "execute"
        tc.part.args = "string args"  # Not a dict

        async def fake_stream():
            yield tc

        node = MagicMock()
        ctx = MagicMock()

        class FakeHandle:
            async def __aenter__(self):
                return fake_stream()

            async def __aexit__(self, *args: Any):
                pass

        node.stream.return_value = FakeHandle()

        await _stream_tool_calls(node, ctx)
        mock_console.print.assert_called()


class _FakeIterRun:
    """Fake async context manager + async iterator for agent.iter() in tests."""

    def __init__(self, nodes: list[Any], result_messages: list[Any] | None = None) -> None:
        self._nodes = nodes
        self._result = MagicMock()
        self._result.all_messages.return_value = result_messages or []
        self.ctx = MagicMock()

    @property
    def result(self) -> Any:
        return self._result

    async def __aenter__(self) -> _FakeIterRun:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass

    def __aiter__(self) -> _FakeIterRun:
        self._index = 0
        return self

    async def __anext__(self) -> Any:
        if self._index >= len(self._nodes):
            raise StopAsyncIteration
        node = self._nodes[self._index]
        self._index += 1
        return node


class TestProcessStream:
    """Tests for _process_stream() — uses agent.iter() internally."""

    @patch("cli.interactive.console")
    async def test_process_stream_empty(self, _mock_console: MagicMock) -> None:
        from cli.interactive import _process_stream

        mock_agent = MagicMock()
        mock_agent.iter.return_value = _FakeIterRun([], result_messages=["msg"])

        deps = MagicMock()
        result = await _process_stream(mock_agent, "test", deps, [])
        assert result == ["msg"]

    @patch("cli.interactive.console")
    async def test_process_stream_with_end_node(self, _mock_console: MagicMock) -> None:
        from pydantic_ai._agent_graph import End

        from cli.interactive import _process_stream

        mock_agent = MagicMock()
        end_node = MagicMock(spec=End)
        mock_agent.iter.return_value = _FakeIterRun([end_node], result_messages=[])
        # Agent.is_model_request_node and is_call_tools_node return False for End
        mock_agent.is_model_request_node.return_value = False
        mock_agent.is_call_tools_node.return_value = False

        deps = MagicMock()
        result = await _process_stream(mock_agent, "test", deps, [])
        assert isinstance(result, list)


class TestRunInteractive:
    """Tests for run_interactive()."""

    @patch("cli.interactive._process_stream")
    @patch("cli.interactive.create_cli_agent")
    @patch("cli.interactive.print_welcome_banner")
    @patch("cli.interactive.console")
    @patch("builtins.input")
    async def test_quit_exits_loop(
        self,
        mock_input: MagicMock,
        _mock_console: MagicMock,
        _mock_banner: MagicMock,
        mock_create: MagicMock,
        _mock_stream: MagicMock,
    ) -> None:
        mock_agent = MagicMock()
        mock_deps = MagicMock()
        mock_deps.todos = []
        mock_deps.checkpoint_store = None
        mock_create.return_value = (mock_agent, mock_deps)

        mock_input.return_value = "/quit"
        await run_interactive()

    @patch("cli.interactive._process_stream")
    @patch("cli.interactive.create_cli_agent")
    @patch("cli.interactive.print_welcome_banner")
    @patch("cli.interactive.console")
    @patch("builtins.input")
    async def test_empty_input_continues(
        self,
        mock_input: MagicMock,
        _mock_console: MagicMock,
        _mock_banner: MagicMock,
        mock_create: MagicMock,
        _mock_stream: MagicMock,
    ) -> None:
        mock_agent = MagicMock()
        mock_deps = MagicMock()
        mock_deps.todos = []
        mock_deps.checkpoint_store = None
        mock_create.return_value = (mock_agent, mock_deps)

        mock_input.side_effect = ["", "/quit"]
        await run_interactive()

    @patch("cli.interactive._process_stream")
    @patch("cli.interactive.create_cli_agent")
    @patch("cli.interactive.print_welcome_banner")
    @patch("cli.interactive.console")
    @patch("builtins.input")
    async def test_message_calls_process_stream(
        self,
        mock_input: MagicMock,
        _mock_console: MagicMock,
        _mock_banner: MagicMock,
        mock_create: MagicMock,
        mock_stream: MagicMock,
    ) -> None:
        mock_agent = MagicMock()
        mock_deps = MagicMock()
        mock_deps.todos = []
        mock_deps.checkpoint_store = None
        mock_create.return_value = (mock_agent, mock_deps)

        mock_stream.return_value = []
        mock_input.side_effect = ["hello", "/quit"]
        await run_interactive()
        mock_stream.assert_called_once()

    @patch("cli.interactive._process_stream")
    @patch("cli.interactive.create_cli_agent")
    @patch("cli.interactive.print_welcome_banner")
    @patch("cli.interactive.console")
    @patch("builtins.input")
    async def test_shows_todos_after_message(
        self,
        mock_input: MagicMock,
        _mock_console: MagicMock,
        _mock_banner: MagicMock,
        mock_create: MagicMock,
        mock_stream: MagicMock,
    ) -> None:
        mock_agent = MagicMock()
        mock_deps = MagicMock()
        mock_deps.todos = [Todo(content="test task", status="pending", active_form="Testing")]
        mock_deps.checkpoint_store = None
        mock_create.return_value = (mock_agent, mock_deps)

        mock_stream.return_value = []
        mock_input.side_effect = ["hello", "/quit"]

        with patch("cli.interactive._print_todos") as mock_pt:
            await run_interactive()
            mock_pt.assert_called()

    @patch("cli.interactive.create_cli_agent")
    @patch("cli.interactive.print_welcome_banner")
    @patch("cli.interactive.console")
    @patch("builtins.input")
    async def test_keyboard_interrupt_continues(
        self,
        mock_input: MagicMock,
        mock_console: MagicMock,
        _mock_banner: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        mock_agent = MagicMock()
        mock_deps = MagicMock()
        mock_deps.todos = []
        mock_deps.checkpoint_store = None
        mock_create.return_value = (mock_agent, mock_deps)

        mock_input.side_effect = [KeyboardInterrupt(), "/quit"]
        await run_interactive()
        # Should print interrupted message
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("Ctrl+C" in c for c in calls)

    @patch("cli.interactive.create_cli_agent")
    @patch("cli.interactive.print_welcome_banner")
    @patch("cli.interactive.console")
    @patch("builtins.input")
    async def test_eof_error_exits(
        self,
        mock_input: MagicMock,
        mock_console: MagicMock,
        _mock_banner: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        mock_agent = MagicMock()
        mock_deps = MagicMock()
        mock_deps.todos = []
        mock_deps.checkpoint_store = None
        mock_create.return_value = (mock_agent, mock_deps)

        mock_input.side_effect = EOFError()
        await run_interactive()
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("Goodbye" in c for c in calls)

    @patch("cli.interactive._process_stream")
    @patch("cli.interactive.create_cli_agent")
    @patch("cli.interactive.print_welcome_banner")
    @patch("cli.interactive.console")
    @patch("builtins.input")
    async def test_exception_shows_error(
        self,
        mock_input: MagicMock,
        mock_console: MagicMock,
        _mock_banner: MagicMock,
        mock_create: MagicMock,
        mock_stream: MagicMock,
    ) -> None:
        mock_agent = MagicMock()
        mock_deps = MagicMock()
        mock_deps.todos = []
        mock_deps.checkpoint_store = None
        mock_create.return_value = (mock_agent, mock_deps)

        mock_stream.side_effect = [RuntimeError("test error"), []]
        mock_input.side_effect = ["hello", "/quit"]
        await run_interactive()
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert any("Error" in c for c in calls)

    @patch("cli.interactive.create_cli_agent")
    @patch("cli.interactive.print_welcome_banner")
    @patch("cli.interactive.console")
    @patch("builtins.input")
    async def test_cost_callback(
        self,
        mock_input: MagicMock,
        _mock_console: MagicMock,
        _mock_banner: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        """Verify create_cli_agent is called with on_cost_update."""
        mock_agent = MagicMock()
        mock_deps = MagicMock()
        mock_deps.todos = []
        mock_deps.checkpoint_store = None
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
        cost_info.total_cost_usd = 0.0456
        callback(cost_info)  # Should not raise

    @patch("cli.interactive.create_cli_agent")
    @patch("cli.interactive.print_welcome_banner")
    @patch("cli.interactive.console")
    @patch("builtins.input")
    async def test_cost_callback_no_run_cost(
        self,
        mock_input: MagicMock,
        _mock_console: MagicMock,
        _mock_banner: MagicMock,
        mock_create: MagicMock,
    ) -> None:
        """Cost callback handles missing run_cost_usd."""
        mock_agent = MagicMock()
        mock_deps = MagicMock()
        mock_deps.todos = []
        mock_deps.checkpoint_store = None
        mock_create.return_value = (mock_agent, mock_deps)

        mock_input.return_value = "/quit"
        await run_interactive()

        callback = mock_create.call_args[1]["on_cost_update"]

        # Object without run_cost_usd attribute
        cost_info = object()
        callback(cost_info)  # Should not raise

    @patch("cli.interactive._process_stream")
    @patch("cli.interactive.create_cli_agent")
    @patch("cli.interactive.print_welcome_banner")
    @patch("cli.interactive.console")
    @patch("builtins.input")
    async def test_non_breaking_command_continues_loop(
        self,
        mock_input: MagicMock,
        _mock_console: MagicMock,
        _mock_banner: MagicMock,
        mock_create: MagicMock,
        _mock_stream: MagicMock,
    ) -> None:
        """Non-breaking slash commands (e.g. /clear) should continue the loop."""
        mock_agent = MagicMock()
        mock_deps = MagicMock()
        mock_deps.todos = []
        mock_deps.checkpoint_store = None
        mock_create.return_value = (mock_agent, mock_deps)

        # /clear is non-breaking, then /quit exits
        mock_input.side_effect = ["/clear", "/quit"]
        await run_interactive()


class TestStreamModelRequest:
    """Tests for _stream_model_request()."""

    @patch("cli.interactive._is_tty", return_value=False)
    @patch("cli.interactive.console")
    async def test_tool_name_in_part_start(
        self, mock_console: MagicMock, _mock_tty: MagicMock
    ) -> None:
        """Tool PartStartEvent stops spinner but does not print (handled by _stream_tool_calls)."""
        from cli.interactive import _stream_model_request

        from pydantic_ai import PartStartEvent

        part_start = MagicMock(spec=PartStartEvent)
        part_start.part = MagicMock()
        part_start.part.tool_name = "grep"

        async def fake_events():
            yield part_start

        class FakeStream:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args: Any):
                pass

            def __aiter__(self):
                return fake_events().__aiter__()

        node = MagicMock()
        node.stream.return_value = FakeStream()
        ctx = MagicMock()

        result = await _stream_model_request(node, ctx)
        assert result == ""
        # Tool calls are rendered by _stream_tool_calls, not here
        # PartStartEvent with tool_name just stops the spinner
        calls = [str(c) for c in mock_console.print.call_args_list]
        assert not any("grep" in c for c in calls)


class TestRunInteractiveSandbox:
    """Tests for sandbox-related paths in run_interactive()."""

    @patch("cli.interactive._create_sandbox_backend", return_value=None)
    @patch("cli.interactive.console")
    async def test_sandbox_creation_fails(
        self, _mock_console: MagicMock, _mock_sandbox: MagicMock
    ) -> None:
        await run_interactive(sandbox=True)

    @patch("cli.interactive._stop_sandbox")
    @patch("cli.interactive.create_cli_agent")
    @patch("cli.interactive._create_sandbox_backend")
    @patch("cli.interactive.print_welcome_banner")
    @patch("cli.interactive.console")
    @patch("builtins.input")
    async def test_sandbox_cleanup_on_exit(
        self,
        mock_input: MagicMock,
        _mock_console: MagicMock,
        _mock_banner: MagicMock,
        mock_sandbox_create: MagicMock,
        mock_create: MagicMock,
        mock_stop: MagicMock,
    ) -> None:
        mock_sandbox = MagicMock()
        mock_sandbox_create.return_value = mock_sandbox

        mock_agent = MagicMock()
        mock_deps = MagicMock()
        mock_deps.todos = []
        mock_deps.checkpoint_store = None
        mock_create.return_value = (mock_agent, mock_deps)

        mock_input.return_value = "/quit"
        await run_interactive(sandbox=True)
        mock_stop.assert_called_once_with(mock_sandbox)

    @patch("builtins.input", return_value="q")
    @patch("cli.interactive._print_model_error")
    @patch("cli.interactive.create_cli_agent", side_effect=ValueError("Bad model"))
    @patch("cli.interactive.console")
    async def test_agent_creation_failure(
        self,
        _mock_console: MagicMock,
        _mock_create: MagicMock,
        mock_error: MagicMock,
        _mock_input: MagicMock,
    ) -> None:
        await run_interactive()
        mock_error.assert_called_once()


class TestProcessStreamBranches:
    """Tests for branch coverage in _process_stream()."""

    @patch("cli.interactive.console")
    async def test_user_prompt_node_ignored(self, _mock_console: MagicMock) -> None:
        """UserPromptNode should be silently skipped."""
        from pydantic_ai._agent_graph import UserPromptNode

        from cli.interactive import _process_stream

        mock_agent = MagicMock()
        user_node = MagicMock(spec=UserPromptNode)
        mock_agent.iter.return_value = _FakeIterRun([user_node], result_messages=["m"])
        mock_agent.is_model_request_node.return_value = False
        mock_agent.is_call_tools_node.return_value = False

        deps = MagicMock()
        result = await _process_stream(mock_agent, "test", deps, [])
        assert result == ["m"]
