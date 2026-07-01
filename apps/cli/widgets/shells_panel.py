"""Background shells display widget for the pinned activity strip.

Mirrors :class:`~apps.cli.widgets.subagents_panel.SubagentsWidget`: it sits in
the bottom activity dock and surfaces long-lived background processes started
via the ``run_in_background`` tool (backed by ``LocalBackend.list_background``).
Each row shows a status glyph, the shell id, and the (truncated) command; the
panel collapses entirely when no background shells are tracked.
"""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

# How many shell rows to render before collapsing the rest behind a "+N more".
_MAX_ROWS = 6
# Command text budget per row in the one-line strip.
_CMD_BUDGET = 44


def _shell_fields(shell: Any) -> tuple[str, str, bool, int | None]:
    """Pull (shell_id, command, running, exit_code) from a BackgroundProcessInfo
    or an equivalent mapping, tolerating either shape."""
    if isinstance(shell, dict):
        return (
            str(shell.get("shell_id", "?")),
            str(shell.get("command", "")),
            bool(shell.get("running", False)),
            shell.get("exit_code"),
        )
    return (
        str(getattr(shell, "shell_id", "?")),
        str(getattr(shell, "command", "")),
        bool(getattr(shell, "running", False)),
        getattr(shell, "exit_code", None),
    )


class ShellsWidget(Widget):
    """Displays tracked background shells (running first, then exited)."""

    DEFAULT_CSS = """
    ShellsWidget {
        height: auto;
        padding: 0;
        margin: 1 0 0 0;
    }
    ShellsWidget #shells-title {
        color: $text-muted;
        text-style: bold;
    }
    """

    shells: reactive[list[Any]] = reactive(list, always_update=True)

    def compose(self) -> ComposeResult:
        yield Static("Background", id="shells-title")
        yield Static("", id="shells-list")

    def watch_shells(self, shells: list[Any]) -> None:
        # Collapse when nothing is tracked — this panel is pinned above the input,
        # so an empty placeholder would just take a permanent row.
        self.display = bool(shells)
        if not shells:
            return
        try:
            content = self.query_one("#shells-list", Static)
            title = self.query_one("#shells-title", Static)
        except NoMatches:  # pragma: no cover - panel not mounted yet
            return

        parsed = [_shell_fields(s) for s in shells]
        # Running shells are the headline; exited ones drop below, dimmed.
        running = [p for p in parsed if p[2]]
        exited = [p for p in parsed if not p[2]]
        ordered = [*running, *exited]

        running_n = len(running)
        title.update(f"Background  [$text-muted]{running_n} running[/]")

        lines: list[str] = []
        for shell_id, command, is_running, exit_code in ordered[:_MAX_ROWS]:
            cmd = " ".join(command.split())
            if len(cmd) > _CMD_BUDGET:
                cmd = cmd[: _CMD_BUDGET - 1] + "…"
            if is_running:
                lines.append(f"[$accent]●[/] [bold]{shell_id}[/]  [$text-muted]{cmd}[/]")
            elif exit_code in (0, None):
                lines.append(f"[$text-muted]✓ {shell_id}  {cmd}[/]")
            else:
                lines.append(
                    f"[$error]✗[/] [bold]{shell_id}[/]  "
                    f"[$text-muted]{cmd}[/]  [$error]exit {exit_code}[/]"
                )

        if len(ordered) > _MAX_ROWS:
            lines.append(f"[$text-muted]+{len(ordered) - _MAX_ROWS} more[/]")

        content.update("\n".join(lines))
