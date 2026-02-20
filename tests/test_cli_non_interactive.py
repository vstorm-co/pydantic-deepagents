"""Tests for CLI non-interactive execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cli.non_interactive import (
    _stream_execution,
    _truncate,
    run_non_interactive,
)


class TestTruncate:
    """Tests for _truncate()."""

    def test_short_text_unchanged(self) -> None:
        assert _truncate("hello", 120) == "hello"

    def test_long_text_truncated(self) -> None:
        text = "x" * 200
        result = _truncate(text, 120)
        assert len(result) <= 120
        # Ends with glyph ellipsis (Unicode "…" or ASCII "...")
        assert result.endswith("\u2026") or result.endswith("...")

    def test_exact_length(self) -> None:
        text = "x" * 120
        assert _truncate(text, 120) == text

    def test_custom_max_len(self) -> None:
        text = "hello world, this is a test"
        result = _truncate(text, 10)
        assert len(result) <= 10
        assert result.endswith("\u2026") or result.endswith("...")


class TestRunNonInteractive:
    """Tests for run_non_interactive()."""

    @patch("cli.non_interactive.create_cli_agent")
    async def test_returns_zero_on_success(self, mock_create: MagicMock, tmp_path: Path) -> None:
        mock_agent = AsyncMock()
        mock_result = MagicMock()
        mock_result.output = "Task completed successfully"
        mock_agent.run = AsyncMock(return_value=mock_result)
        mock_deps = MagicMock()
        mock_create.return_value = (mock_agent, mock_deps)

        exit_code = await run_non_interactive(
            message="Create hello.py",
            working_dir=str(tmp_path),
            stream=False,
        )
        assert exit_code == 0

    @patch("cli.non_interactive.create_cli_agent")
    async def test_returns_one_on_error(self, mock_create: MagicMock) -> None:
        mock_create.side_effect = ValueError("Model not found")

        exit_code = await run_non_interactive(
            message="test",
            stream=False,
        )
        assert exit_code == 1

    @patch("cli.non_interactive.create_cli_agent")
    async def test_quiet_mode(
        self, mock_create: MagicMock, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mock_agent = AsyncMock()
        mock_result = MagicMock()
        mock_result.output = "Done"
        mock_agent.run = AsyncMock(return_value=mock_result)
        mock_deps = MagicMock()
        mock_create.return_value = (mock_agent, mock_deps)

        exit_code = await run_non_interactive(
            message="test",
            working_dir=str(tmp_path),
            quiet=True,
            stream=False,
        )
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Done" in captured.out

    @patch("cli.non_interactive.create_cli_agent")
    async def test_passes_shell_allow_list(self, mock_create: MagicMock, tmp_path: Path) -> None:
        mock_agent = AsyncMock()
        mock_result = MagicMock()
        mock_result.output = "OK"
        mock_agent.run = AsyncMock(return_value=mock_result)
        mock_deps = MagicMock()
        mock_create.return_value = (mock_agent, mock_deps)

        await run_non_interactive(
            message="test",
            working_dir=str(tmp_path),
            shell_allow_list=["python", "pip"],
            stream=False,
        )

        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["shell_allow_list"] == ["python", "pip"]

    @patch("cli.non_interactive.create_cli_agent")
    async def test_response_ending_with_newline(
        self, mock_create: MagicMock, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When response already ends with newline, don't add another."""
        mock_agent = AsyncMock()
        mock_result = MagicMock()
        mock_result.output = "Done\n"
        mock_agent.run = AsyncMock(return_value=mock_result)
        mock_deps = MagicMock()
        mock_create.return_value = (mock_agent, mock_deps)

        exit_code = await run_non_interactive(
            message="test",
            working_dir=str(tmp_path),
            quiet=True,
            stream=False,
        )
        assert exit_code == 0
        captured = capsys.readouterr()
        # Should have exactly one newline at end
        assert captured.out == "Done\n"

    @patch("cli.non_interactive.create_cli_agent")
    async def test_empty_response(
        self, mock_create: MagicMock, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Empty response should not write to stdout."""
        mock_agent = AsyncMock()
        mock_result = MagicMock()
        mock_result.output = ""
        mock_agent.run = AsyncMock(return_value=mock_result)
        mock_deps = MagicMock()
        mock_create.return_value = (mock_agent, mock_deps)

        exit_code = await run_non_interactive(
            message="test",
            working_dir=str(tmp_path),
            quiet=True,
            stream=False,
        )
        assert exit_code == 0
        captured = capsys.readouterr()
        assert captured.out == ""

    @patch("cli.non_interactive.create_cli_agent")
    async def test_stream_mode(
        self, mock_create: MagicMock, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test streaming execution mode."""
        mock_agent = MagicMock()
        mock_deps = MagicMock()
        mock_create.return_value = (mock_agent, mock_deps)

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            from pydantic_ai import AgentRunResultEvent

            re = MagicMock(spec=AgentRunResultEvent)
            re.result = MagicMock()
            re.result.output = "stream result"
            yield re

        mock_agent.run_stream_events = mock_stream

        exit_code = await run_non_interactive(
            message="test",
            working_dir=str(tmp_path),
            stream=True,
            quiet=True,
        )
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "stream result" in captured.out

    @patch("cli.non_interactive.create_cli_agent")
    async def test_keyboard_interrupt(self, mock_create: MagicMock) -> None:
        """Test keyboard interrupt returns 130."""
        mock_agent = AsyncMock()
        mock_agent.run = AsyncMock(side_effect=KeyboardInterrupt())
        mock_deps = MagicMock()
        mock_create.return_value = (mock_agent, mock_deps)

        exit_code = await run_non_interactive(
            message="test",
            stream=False,
        )
        assert exit_code == 130

    @patch("cli.non_interactive.create_cli_agent")
    async def test_cost_callback_called(self, mock_create: MagicMock, tmp_path: Path) -> None:
        """Verify on_cost_update is passed to create_cli_agent."""
        mock_agent = AsyncMock()
        mock_result = MagicMock()
        mock_result.output = "OK"
        mock_agent.run = AsyncMock(return_value=mock_result)
        mock_deps = MagicMock()
        mock_create.return_value = (mock_agent, mock_deps)

        await run_non_interactive(
            message="test",
            working_dir=str(tmp_path),
            stream=False,
        )

        # Verify callback was passed
        call_kwargs = mock_create.call_args[1]
        callback = call_kwargs["on_cost_update"]

        # Test the callback
        cost_info = MagicMock()
        cost_info.run_cost_usd = 0.01
        callback(cost_info)  # Should not raise

    @patch("cli.non_interactive.create_cli_agent")
    async def test_cost_callback_quiet(self, mock_create: MagicMock, tmp_path: Path) -> None:
        """Cost callback does nothing in quiet mode."""
        mock_agent = AsyncMock()
        mock_result = MagicMock()
        mock_result.output = "OK"
        mock_agent.run = AsyncMock(return_value=mock_result)
        mock_deps = MagicMock()
        mock_create.return_value = (mock_agent, mock_deps)

        await run_non_interactive(
            message="test",
            working_dir=str(tmp_path),
            quiet=True,
            stream=False,
        )

        call_kwargs = mock_create.call_args[1]
        callback = call_kwargs["on_cost_update"]

        # In quiet mode, callback should not print anything
        cost_info = MagicMock()
        cost_info.run_cost_usd = 0.01
        callback(cost_info)  # Should not raise

    @patch("cli.non_interactive.create_cli_agent")
    async def test_cost_callback_no_run_cost(self, mock_create: MagicMock, tmp_path: Path) -> None:
        """Cost callback handles missing run_cost_usd."""
        mock_agent = AsyncMock()
        mock_result = MagicMock()
        mock_result.output = "OK"
        mock_agent.run = AsyncMock(return_value=mock_result)
        mock_deps = MagicMock()
        mock_create.return_value = (mock_agent, mock_deps)

        await run_non_interactive(
            message="test",
            working_dir=str(tmp_path),
            stream=False,
        )

        call_kwargs = mock_create.call_args[1]
        callback = call_kwargs["on_cost_update"]

        # Object without run_cost_usd
        callback(object())  # Should not raise


class TestStreamExecution:
    """Tests for _stream_execution()."""

    async def test_returns_result_from_agent_run_result(self) -> None:
        """AgentRunResultEvent output is returned."""
        from pydantic_ai import AgentRunResultEvent

        from rich.console import Console

        mock_agent = MagicMock()

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            re = MagicMock(spec=AgentRunResultEvent)
            re.result = MagicMock()
            re.result.output = "Final output"
            yield re

        mock_agent.run_stream_events = mock_stream
        console = Console(stderr=True)

        result = await _stream_execution(mock_agent, "test", MagicMock(), console)
        assert result == "Final output"

    async def test_collects_part_deltas(self) -> None:
        """When no AgentRunResultEvent, collects text from PartDeltaEvents."""
        from pydantic_ai import PartDeltaEvent

        from rich.console import Console

        mock_agent = MagicMock()

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            pe1 = MagicMock(spec=PartDeltaEvent)
            pe1.delta = MagicMock()
            pe1.delta.content_delta = "Hello "

            pe2 = MagicMock(spec=PartDeltaEvent)
            pe2.delta = MagicMock()
            pe2.delta.content_delta = "world"

            yield pe1
            yield pe2

        mock_agent.run_stream_events = mock_stream
        console = Console(stderr=True)

        result = await _stream_execution(mock_agent, "test", MagicMock(), console)
        assert result == "Hello world"

    async def test_null_content_delta(self) -> None:
        """None content_delta should not crash."""
        from pydantic_ai import PartDeltaEvent

        from rich.console import Console

        mock_agent = MagicMock()

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            pe = MagicMock(spec=PartDeltaEvent)
            pe.delta = MagicMock()
            pe.delta.content_delta = None
            yield pe

        mock_agent.run_stream_events = mock_stream
        console = Console(stderr=True)

        result = await _stream_execution(mock_agent, "test", MagicMock(), console)
        assert result == ""

    async def test_tool_call_event_not_quiet(self) -> None:
        """Tool calls are printed to console when not quiet."""
        from pydantic_ai import FunctionToolCallEvent

        from rich.console import Console

        mock_agent = MagicMock()

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            tc = MagicMock(spec=FunctionToolCallEvent)
            tc.part = MagicMock()
            tc.part.tool_name = "read_file"
            tc.part.args = {"path": "/test.py"}
            yield tc

        mock_agent.run_stream_events = mock_stream

        with patch.object(Console, "print") as mock_print:
            console = Console(stderr=True)
            console.print = mock_print
            await _stream_execution(mock_agent, "test", MagicMock(), console, quiet=False)
            mock_print.assert_called()

    async def test_tool_call_event_quiet(self) -> None:
        """Tool calls are suppressed in quiet mode."""
        from pydantic_ai import FunctionToolCallEvent

        from rich.console import Console

        mock_agent = MagicMock()

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            tc = MagicMock(spec=FunctionToolCallEvent)
            tc.part = MagicMock()
            tc.part.tool_name = "read_file"
            tc.part.args = {"path": "/test.py"}
            yield tc

        mock_agent.run_stream_events = mock_stream
        mock_console = MagicMock(spec=Console)

        await _stream_execution(mock_agent, "test", MagicMock(), mock_console, quiet=True)
        mock_console.print.assert_not_called()

    async def test_tool_result_event_not_quiet(self) -> None:
        """Tool results are printed when not quiet."""
        from pydantic_ai import FunctionToolResultEvent

        from rich.console import Console

        mock_agent = MagicMock()

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            tr = MagicMock(spec=FunctionToolResultEvent)
            tr.result = MagicMock()
            tr.result.content = "file content\nline 2"
            yield tr

        mock_agent.run_stream_events = mock_stream

        mock_console = MagicMock(spec=Console)

        await _stream_execution(mock_agent, "test", MagicMock(), mock_console, quiet=False)
        mock_console.print.assert_called()

    async def test_tool_result_event_quiet(self) -> None:
        """Tool results are suppressed in quiet mode."""
        from pydantic_ai import FunctionToolResultEvent

        from rich.console import Console

        mock_agent = MagicMock()

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            tr = MagicMock(spec=FunctionToolResultEvent)
            tr.result = MagicMock()
            tr.result.content = "result"
            yield tr

        mock_agent.run_stream_events = mock_stream
        mock_console = MagicMock(spec=Console)

        await _stream_execution(mock_agent, "test", MagicMock(), mock_console, quiet=True)
        mock_console.print.assert_not_called()

    async def test_delta_without_content_delta_attr(self) -> None:
        """PartDeltaEvent where delta lacks content_delta attribute."""
        from pydantic_ai import PartDeltaEvent

        from rich.console import Console

        mock_agent = MagicMock()

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            pe = MagicMock(spec=PartDeltaEvent)
            pe.delta = MagicMock(spec=[])  # No content_delta
            yield pe

        mock_agent.run_stream_events = mock_stream
        console = Console(stderr=True)

        result = await _stream_execution(mock_agent, "test", MagicMock(), console)
        assert result == ""

    async def test_unknown_event_type(self) -> None:
        """Unknown event types are silently skipped."""
        from rich.console import Console

        mock_agent = MagicMock()

        async def mock_stream(*args: Any, **kwargs: Any) -> Any:
            # An event that doesn't match any isinstance check
            yield MagicMock()

        mock_agent.run_stream_events = mock_stream
        console = Console(stderr=True)

        result = await _stream_execution(mock_agent, "test", MagicMock(), console)
        assert result == ""
