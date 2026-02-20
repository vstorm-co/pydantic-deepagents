"""Rich display utilities for the pydantic-deep CLI.

Provides prettier code blocks, welcome banner, error/warning panels,
token formatting, and Rich Markdown rendering with automatic TTY detection.
"""

from __future__ import annotations

import subprocess

from rich.console import Console, ConsoleOptions, RenderResult
from rich.markdown import CodeBlock, Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

from cli.theme import get_theme


class SimpleCodeBlock(CodeBlock):
    """Code block without background color — cleaner look, easier copy-paste."""

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        code = str(self.text).rstrip()
        yield Text(self.lexer_name, style="dim")
        yield Syntax(
            code,
            self.lexer_name,
            theme=self.theme,
            background_color="default",
            word_wrap=True,
        )
        yield Text(f"/{self.lexer_name}", style="dim")


def install_prettier_code_blocks() -> None:
    """Register the SimpleCodeBlock renderer with Rich Markdown."""
    Markdown.elements["fence"] = SimpleCodeBlock


def _get_git_branch() -> str | None:
    """Get the current git branch, or None if not in a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def print_welcome_banner(
    console: Console,
    *,
    model: str | None = None,
    working_dir: str | None = None,
) -> None:
    """Print a Rich Panel welcome banner with version, model, and context info."""
    from pydantic_deep import __version__

    theme = get_theme()

    lines: list[str] = []
    lines.append(
        f"[bold {theme.primary}]pydantic-deep[/bold {theme.primary}] [dim]v{__version__}[/dim]"
    )

    if model:
        lines.append(f"[dim]Model:[/dim] {model}")

    if working_dir:
        lines.append(f"[dim]Dir:[/dim]   {working_dir}")

    branch = _get_git_branch()
    if branch:
        lines.append(f"[dim]Git:[/dim]   {branch}")

    lines.append("")
    lines.append("[dim]Commands: /help /quit /clear /compact /todos /cost /save /load[/dim]")

    console.print()
    console.print(
        Panel(
            "\n".join(lines),
            border_style=theme.primary,
            padding=(0, 1),
        )
    )
    console.print()


def render_markdown(console: Console, text: str) -> None:
    """Render text as Rich Markdown if the console is a terminal, else raw text."""
    if console.is_terminal:
        install_prettier_code_blocks()
        console.print(Markdown(text))
    else:
        end = "" if text.endswith("\n") else "\n"
        console.print(text, end=end)


def format_tokens(n: int) -> str:
    """Format token count with K suffix: 500 → "500", 1200 → "1.2K", 150000 → "150K"."""
    if n < 1000:
        return str(n)
    k = n / 1000
    if k < 10:
        return f"{k:.1f}K"
    return f"{int(k)}K"


def format_cost_line(
    run_cost: float | None = None,
    total_cost: float | None = None,
    tokens: int | None = None,
) -> str:
    """Format a cost/tokens line for display after a response.

    Returns Rich markup string, or empty string if no data.
    """
    parts: list[str] = []
    if run_cost is not None:
        cost_str = f"${run_cost:.4f}"
        if total_cost is not None:
            cost_str += f" (total: ${total_cost:.4f})"
        parts.append(cost_str)
    elif total_cost is not None:
        parts.append(f"Total: ${total_cost:.4f}")
    if tokens is not None:
        parts.append(f"{format_tokens(tokens)} tokens")
    if not parts:
        return ""
    return "[dim]  " + " · ".join(parts) + "[/dim]"


def print_error(
    console: Console,
    message: str,
    *,
    title: str = "Error",
    hint: str | None = None,
) -> None:
    """Print a structured error panel."""
    theme = get_theme()
    body = message
    if hint:
        body += f"\n\n[{theme.warning}]Hint:[/{theme.warning}] {hint}"
    console.print(
        Panel(
            body,
            title=f"[bold {theme.error}]{title}[/bold {theme.error}]",
            border_style=theme.error,
            padding=(0, 1),
        )
    )


def print_warning(console: Console, message: str) -> None:
    """Print a styled warning message."""
    theme = get_theme()
    console.print(f"[{theme.warning}]Warning:[/{theme.warning}] {message}")


__all__ = [
    "SimpleCodeBlock",
    "format_cost_line",
    "format_tokens",
    "install_prettier_code_blocks",
    "print_error",
    "print_warning",
    "print_welcome_banner",
    "render_markdown",
]
