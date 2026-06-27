"""Diff view modal — /diff command. Shows colored git diff."""

from __future__ import annotations

import asyncio
import contextlib
import subprocess

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static


def _colorize_diff(diff_text: str) -> str:
    """Apply Rich markup colors to diff lines."""
    lines: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            lines.append(f"[bold]{line}[/bold]")
        elif line.startswith("+"):
            lines.append(f"[green]{line}[/green]")
        elif line.startswith("-"):
            lines.append(f"[red]{line}[/red]")
        elif line.startswith("@@"):
            lines.append(f"[cyan]{line}[/cyan]")
        elif line.startswith("diff "):
            lines.append(f"[yellow bold]{line}[/]")
        else:
            lines.append(line)
    return "\n".join(lines)


class DiffViewModal(ModalScreen[None]):
    """Shows git diff --stat and full diff in a scrollable overlay."""

    DEFAULT_CSS = """
    DiffViewModal {
        align: center middle;
    }
    DiffViewModal > #diff-container {
        width: 90%;
        max-width: 100;
        max-height: 85%;
        border: tall $primary;
        background: $surface;
        padding: 1 2;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
    ]

    def __init__(self, working_dir: str = ".") -> None:
        super().__init__()
        self._working_dir = working_dir

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="diff-container"):
            yield Static("[dim]Loading diff…[/dim]", id="diff-content")
            yield Static("\n[dim]Esc or q to close[/dim]")

    def on_mount(self) -> None:
        # git can be slow on big repos — gather the diff off the event loop so
        # opening the modal never freezes the UI.
        self.run_worker(self._load_diff(), exclusive=True)

    async def _load_diff(self) -> None:
        try:
            text = await asyncio.to_thread(self._gather_diff)
        except Exception as e:  # pragma: no cover - defensive
            text = f"[bold]Git Changes[/bold]\n\n[red]Error: {e}[/red]"
        with contextlib.suppress(Exception):
            self.query_one("#diff-content", Static).update(text)

    def _git(self, *args: str, timeout: int = 10) -> str:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
            cwd=self._working_dir,
            timeout=timeout,
        )
        return result.stdout

    def _gather_diff(self) -> str:
        """Run the git commands (blocking) and return the colorized markup."""
        branch = self._git("rev-parse", "--abbrev-ref", "HEAD", timeout=5).strip() or "?"
        stat = self._git("diff", "--stat").strip()
        staged = self._git("diff", "--cached", "--stat").strip()
        diff = self._git("diff")

        parts = [f"[bold]Git Changes[/bold]  [dim]{branch}[/dim]\n"]
        parts.append(stat + "\n" if stat else "[dim]No uncommitted changes[/dim]\n")
        if staged:
            parts.append(f"\n[bold]Staged[/bold]\n{staged}\n")
        if diff.strip():
            parts.append(f"\n{_colorize_diff(diff)}")
        return "\n".join(parts)

    def action_dismiss(self, result: object = None) -> None:
        self.dismiss(None)
