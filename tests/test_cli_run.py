"""Tests for the headless runner (pydantic-deep run)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from apps.cli.main import app
from apps.cli.run import _build_json_output, _print_error, execute_headless

runner = CliRunner()


# ── CLI command tests ──────────────────────────────────────────────


class TestRunCommand:
    """Tests for the 'run' CLI command."""

    def test_no_task_or_file(self) -> None:
        result = runner.invoke(app, ["run"])
        assert result.exit_code == 1
        assert "provide a task" in result.output

    def test_task_file_not_found(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["run", "--task-file", str(tmp_path / "nonexistent.md")])
        assert result.exit_code == 1
        assert "not found" in result.output

    def test_empty_task_file(self, tmp_path: Path) -> None:
        task_file = tmp_path / "empty.md"
        task_file.write_text("   \n  ")
        result = runner.invoke(app, ["run", "--task-file", str(task_file)])
        assert result.exit_code == 1
        assert "empty" in result.output

    def test_reads_task_from_file(self, tmp_path: Path) -> None:
        task_file = tmp_path / "task.md"
        task_file.write_text("Fix the bug in auth.py")

        with patch("apps.cli.run.execute_headless", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = 0
            result = runner.invoke(app, ["run", "--task-file", str(task_file)])

        assert result.exit_code == 0
        mock_exec.assert_called_once()
        call_kwargs = mock_exec.call_args.kwargs
        assert call_kwargs["task"] == "Fix the bug in auth.py"

    def test_passes_task_argument(self) -> None:
        with patch("apps.cli.run.execute_headless", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = 0
            result = runner.invoke(app, ["run", "Fix the bug"])

        assert result.exit_code == 0
        call_kwargs = mock_exec.call_args.kwargs
        assert call_kwargs["task"] == "Fix the bug"

    def test_passes_options(self) -> None:
        with patch("apps.cli.run.execute_headless", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = 0
            result = runner.invoke(
                app,
                [
                    "run",
                    "Do something",
                    "--model",
                    "test:model",
                    "--working-dir",
                    "/tmp",
                    "--json",
                    "--max-turns",
                    "10",
                    "--timeout",
                    "60",
                ],
            )

        assert result.exit_code == 0
        call_kwargs = mock_exec.call_args.kwargs
        assert call_kwargs["model"] == "test:model"
        assert call_kwargs["working_dir"] == "/tmp"
        assert call_kwargs["output_json"] is True
        assert call_kwargs["max_turns"] == 10
        assert call_kwargs["timeout"] == 60

    def test_returns_nonzero_on_error(self) -> None:
        with patch("apps.cli.run.execute_headless", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = 1
            result = runner.invoke(app, ["run", "Do something"])

        assert result.exit_code == 1

    def test_help(self) -> None:
        result = runner.invoke(app, ["run", "--help"])
        assert result.exit_code == 0
        assert "headless" in result.output.lower()


# ── execute_headless tests ─────────────────────────────────────────


class TestExecuteHeadless:
    """Tests for execute_headless()."""

    @pytest.fixture()
    def mock_agent(self) -> MagicMock:
        """Create a mock agent with a run() method returning a result."""
        agent = MagicMock()
        mock_result = MagicMock()
        mock_result.output = "Task completed successfully"
        mock_usage = MagicMock()
        mock_usage.total_tokens = 1000
        mock_usage.request_tokens = 800
        mock_usage.response_tokens = 200
        mock_usage.requests = 3
        mock_result.usage.return_value = mock_usage
        agent.run = AsyncMock(return_value=mock_result)
        return agent

    @pytest.fixture()
    def mock_deps(self) -> MagicMock:
        return MagicMock()

    async def test_basic_run(
        self, mock_agent: MagicMock, mock_deps: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch("apps.cli.run.create_cli_agent", return_value=(mock_agent, mock_deps)):
            exit_code = await execute_headless(task="Fix the bug", working_dir="/tmp")

        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Task completed successfully" in captured.out

    async def test_json_output(
        self, mock_agent: MagicMock, mock_deps: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with patch("apps.cli.run.create_cli_agent", return_value=(mock_agent, mock_deps)):
            exit_code = await execute_headless(
                task="Fix the bug", working_dir="/tmp", output_json=True
            )

        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["output"] == "Task completed successfully"
        assert data["usage"]["total_tokens"] == 1000
        assert data["usage"]["requests"] == 3

    async def test_max_turns_passed(self, mock_agent: MagicMock, mock_deps: MagicMock) -> None:
        with patch("apps.cli.run.create_cli_agent", return_value=(mock_agent, mock_deps)):
            await execute_headless(task="Fix the bug", working_dir="/tmp", max_turns=25)

        _, call_kwargs = mock_agent.run.call_args
        assert call_kwargs["max_turns"] == 25

    async def test_timeout(
        self, mock_agent: MagicMock, mock_deps: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import asyncio

        async def slow_run(*args: object, **kwargs: object) -> None:
            await asyncio.sleep(10)

        mock_agent.run = AsyncMock(side_effect=slow_run)

        with patch("apps.cli.run.create_cli_agent", return_value=(mock_agent, mock_deps)):
            exit_code = await execute_headless(task="Slow task", working_dir="/tmp", timeout=0)

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Timed out" in captured.err

    async def test_timeout_json_error(
        self, mock_agent: MagicMock, mock_deps: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import asyncio

        async def slow_run(*args: object, **kwargs: object) -> None:
            await asyncio.sleep(10)

        mock_agent.run = AsyncMock(side_effect=slow_run)

        with patch("apps.cli.run.create_cli_agent", return_value=(mock_agent, mock_deps)):
            exit_code = await execute_headless(
                task="Slow task",
                working_dir="/tmp",
                timeout=0,
                output_json=True,
            )

        assert exit_code == 1
        captured = capsys.readouterr()
        error_data = json.loads(captured.err)
        assert error_data["error"] == "Timed out"

    async def test_model_override(self, mock_agent: MagicMock, mock_deps: MagicMock) -> None:
        with patch(
            "apps.cli.run.create_cli_agent", return_value=(mock_agent, mock_deps)
        ) as mock_create:
            await execute_headless(task="Fix the bug", working_dir="/tmp", model="openai:gpt-5.4")

        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["model"] == "openai:gpt-5.4"

    async def test_non_interactive_flags(self, mock_agent: MagicMock, mock_deps: MagicMock) -> None:
        with patch(
            "apps.cli.run.create_cli_agent", return_value=(mock_agent, mock_deps)
        ) as mock_create:
            await execute_headless(task="Fix the bug", working_dir="/tmp")

        call_kwargs = mock_create.call_args.kwargs
        assert call_kwargs["non_interactive"] is True
        # Feature flags not passed = use config defaults
        assert "include_plan" not in call_kwargs
        assert "include_memory" not in call_kwargs


# ── Helper function tests ──────────���───────────────────────────────


class TestBuildJsonOutput:
    """Tests for _build_json_output()."""

    def test_builds_output(self) -> None:
        usage = MagicMock()
        usage.total_tokens = 500
        usage.request_tokens = 400
        usage.response_tokens = 100
        usage.requests = 2

        result = _build_json_output("Done", usage)

        assert result["output"] == "Done"
        assert result["usage"]["total_tokens"] == 500
        assert result["usage"]["request_tokens"] == 400
        assert result["usage"]["response_tokens"] == 100
        assert result["usage"]["requests"] == 2


class TestPrintError:
    """Tests for _print_error()."""

    def test_plain_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        _print_error("Something went wrong", output_json=False)
        captured = capsys.readouterr()
        assert "Error: Something went wrong" in captured.err

    def test_json_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        _print_error("Something went wrong", output_json=True)
        captured = capsys.readouterr()
        data = json.loads(captured.err)
        assert data["error"] == "Something went wrong"
