"""Tests for CLI display utilities."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from rich.console import Console
from rich.markdown import Markdown

from cli.display import (
    SimpleCodeBlock,
    _get_git_branch,
    format_cost_line,
    format_tokens,
    install_prettier_code_blocks,
    print_error,
    print_warning,
    print_welcome_banner,
    render_markdown,
)


class TestSimpleCodeBlock:
    """Tests for SimpleCodeBlock rendering."""

    def test_renders_code(self) -> None:
        block = SimpleCodeBlock(lexer_name="python", theme="monokai")
        block.text = "print('hello')"
        console = Console(width=80, force_terminal=False)
        options = console.options
        parts = list(block.__rich_console__(console, options))
        assert len(parts) == 3  # language label, syntax, closing label


class TestInstallPrettierCodeBlocks:
    """Tests for install_prettier_code_blocks()."""

    def test_registers_simple_code_block(self) -> None:
        install_prettier_code_blocks()
        assert Markdown.elements["fence"] == SimpleCodeBlock


class TestGetGitBranch:
    """Tests for _get_git_branch()."""

    @patch("subprocess.run")
    def test_returns_branch_name(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0, stdout="main\n")
        assert _get_git_branch() == "main"

    @patch("subprocess.run")
    def test_returns_none_on_nonzero_exit(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=128)
        assert _get_git_branch() is None

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_returns_none_when_git_not_found(self, mock_run: MagicMock) -> None:
        assert _get_git_branch() is None

    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired("git", 2))
    def test_returns_none_on_timeout(self, mock_run: MagicMock) -> None:
        assert _get_git_branch() is None


class TestPrintWelcomeBanner:
    """Tests for print_welcome_banner()."""

    @patch("cli.display._get_git_branch", return_value="main")
    def test_with_all_info(self, _mock: MagicMock) -> None:
        console = MagicMock()
        print_welcome_banner(console, model="gpt-4o", working_dir="/tmp")
        assert console.print.call_count >= 3

    @patch("cli.display._get_git_branch", return_value=None)
    def test_without_branch(self, _mock: MagicMock) -> None:
        console = MagicMock()
        print_welcome_banner(console)
        assert console.print.called

    @patch("cli.display._get_git_branch", return_value="main")
    def test_without_model(self, _mock: MagicMock) -> None:
        console = MagicMock()
        print_welcome_banner(console, working_dir="/tmp")
        assert console.print.called

    @patch("cli.display._get_git_branch", return_value="main")
    def test_without_working_dir(self, _mock: MagicMock) -> None:
        console = MagicMock()
        print_welcome_banner(console, model="gpt-4o")
        assert console.print.called


class TestRenderMarkdown:
    """Tests for render_markdown()."""

    def test_renders_rich_on_terminal(self) -> None:
        console = MagicMock()
        console.is_terminal = True
        render_markdown(console, "# Hello")
        console.print.assert_called_once()
        args = console.print.call_args[0]
        assert isinstance(args[0], Markdown)

    def test_renders_raw_on_pipe(self) -> None:
        console = MagicMock()
        console.is_terminal = False
        render_markdown(console, "Hello world")
        console.print.assert_called_once_with("Hello world", end="\n")

    def test_no_extra_newline(self) -> None:
        console = MagicMock()
        console.is_terminal = False
        render_markdown(console, "Hello\n")
        console.print.assert_called_once_with("Hello\n", end="")


class TestFormatTokens:
    """Tests for format_tokens()."""

    def test_below_thousand(self) -> None:
        assert format_tokens(500) == "500"

    def test_zero(self) -> None:
        assert format_tokens(0) == "0"

    def test_one_decimal_k(self) -> None:
        assert format_tokens(1200) == "1.2K"

    def test_exactly_one_k(self) -> None:
        assert format_tokens(1000) == "1.0K"

    def test_large_k(self) -> None:
        assert format_tokens(150000) == "150K"

    def test_ten_k(self) -> None:
        assert format_tokens(10000) == "10K"


class TestFormatCostLine:
    """Tests for format_cost_line()."""

    def test_run_cost_only(self) -> None:
        result = format_cost_line(run_cost=0.0123)
        assert "$0.0123" in result
        assert "total" not in result

    def test_run_and_total(self) -> None:
        result = format_cost_line(run_cost=0.0123, total_cost=0.0456)
        assert "$0.0123" in result
        assert "total: $0.0456" in result

    def test_total_only(self) -> None:
        result = format_cost_line(total_cost=0.0456)
        assert "Total: $0.0456" in result

    def test_tokens_only(self) -> None:
        result = format_cost_line(tokens=1500)
        assert "1.5K tokens" in result

    def test_all_data(self) -> None:
        result = format_cost_line(run_cost=0.01, total_cost=0.05, tokens=2000)
        assert "$0.01" in result
        assert "2.0K tokens" in result

    def test_no_data(self) -> None:
        assert format_cost_line() == ""

    def test_returns_dim_markup(self) -> None:
        result = format_cost_line(run_cost=0.01)
        assert result.startswith("[dim]")
        assert result.endswith("[/dim]")


class TestPrintError:
    """Tests for print_error()."""

    def test_basic_error(self) -> None:
        console = MagicMock()
        print_error(console, "Something went wrong")
        console.print.assert_called_once()

    def test_error_with_hint(self) -> None:
        console = MagicMock()
        print_error(console, "API key missing", hint="Set OPENAI_API_KEY")
        console.print.assert_called_once()

    def test_custom_title(self) -> None:
        console = MagicMock()
        print_error(console, "oops", title="Warning")
        console.print.assert_called_once()


class TestPrintWarning:
    """Tests for print_warning()."""

    def test_prints_warning(self) -> None:
        console = MagicMock()
        print_warning(console, "Something might be wrong")
        console.print.assert_called_once()
        call_str = str(console.print.call_args)
        assert "Something might be wrong" in call_str
