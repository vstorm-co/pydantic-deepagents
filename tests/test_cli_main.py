"""Tests for CLI main entry point."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from pydantic_deep.cli.main import app, main

runner = CliRunner()


class TestRunCommand:
    """Tests for the 'run' command."""

    @patch("pydantic_deep.cli.main.asyncio.run")
    def test_run_basic(self, mock_asyncio_run: AsyncMock) -> None:
        mock_asyncio_run.return_value = 0
        result = runner.invoke(app, ["run", "Create hello.py"])
        # Exit code from typer.Exit(0) is 0
        assert result.exit_code == 0

    @patch("pydantic_deep.cli.main.asyncio.run")
    def test_run_with_model(self, mock_asyncio_run: AsyncMock) -> None:
        mock_asyncio_run.return_value = 0
        result = runner.invoke(app, ["run", "test", "--model", "openai:gpt-4o"])
        assert result.exit_code == 0

    @patch("pydantic_deep.cli.main.asyncio.run")
    def test_run_with_working_dir(self, mock_asyncio_run: AsyncMock) -> None:
        mock_asyncio_run.return_value = 0
        result = runner.invoke(app, ["run", "test", "--working-dir", "/tmp"])
        assert result.exit_code == 0

    @patch("pydantic_deep.cli.main.asyncio.run")
    def test_run_with_quiet(self, mock_asyncio_run: AsyncMock) -> None:
        mock_asyncio_run.return_value = 0
        result = runner.invoke(app, ["run", "test", "--quiet"])
        assert result.exit_code == 0

    @patch("pydantic_deep.cli.main.asyncio.run")
    def test_run_with_no_stream(self, mock_asyncio_run: AsyncMock) -> None:
        mock_asyncio_run.return_value = 0
        result = runner.invoke(app, ["run", "test", "--no-stream"])
        assert result.exit_code == 0

    @patch("pydantic_deep.cli.main.asyncio.run")
    def test_run_with_shell_allow_list(self, mock_asyncio_run: AsyncMock) -> None:
        mock_asyncio_run.return_value = 0
        result = runner.invoke(
            app, ["run", "test", "--shell-allow-list", "python", "--shell-allow-list", "pip"]
        )
        assert result.exit_code == 0

    @patch("pydantic_deep.cli.main.asyncio.run")
    def test_run_error_exit_code(self, mock_asyncio_run: AsyncMock) -> None:
        mock_asyncio_run.return_value = 1
        result = runner.invoke(app, ["run", "test"])
        assert result.exit_code == 1


class TestChatCommand:
    """Tests for the 'chat' command."""

    @patch("pydantic_deep.cli.main.asyncio.run")
    def test_chat_basic(self, mock_asyncio_run: AsyncMock) -> None:
        mock_asyncio_run.return_value = None
        result = runner.invoke(app, ["chat"])
        assert result.exit_code == 0

    @patch("pydantic_deep.cli.main.asyncio.run")
    def test_chat_with_model(self, mock_asyncio_run: AsyncMock) -> None:
        mock_asyncio_run.return_value = None
        result = runner.invoke(app, ["chat", "--model", "openai:gpt-4o"])
        assert result.exit_code == 0

    @patch("pydantic_deep.cli.main.asyncio.run")
    def test_chat_with_working_dir(self, mock_asyncio_run: AsyncMock) -> None:
        mock_asyncio_run.return_value = None
        result = runner.invoke(app, ["chat", "--working-dir", "/tmp"])
        assert result.exit_code == 0


class TestMainFunction:
    """Tests for the main() entry point."""

    @patch("pydantic_deep.cli.main.app")
    def test_main_calls_app(self, mock_app: AsyncMock) -> None:
        main()
        mock_app.assert_called_once()


class TestAppHelp:
    """Tests for --help output."""

    def test_help(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "Deep Agent CLI" in result.output

    def test_run_help(self) -> None:
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "non-interactively" in result.output

    def test_chat_help(self) -> None:
        result = runner.invoke(app, ["chat", "--help"])
        assert result.exit_code == 0
        assert "interactive" in result.output
