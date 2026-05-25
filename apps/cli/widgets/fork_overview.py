"""Overview pseudo-tab — summary view of all branches before ``/merge``."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Static

from apps.cli.widgets.fork_state import state_word
from apps.cli.widgets.spinner import Spinner

if TYPE_CHECKING:
    from pydantic_deep.types import BranchStatus


class ForkOverviewWidget(Vertical):
    """Renders one row per branch and a ``/merge`` hint.

    The CLI screen mounts this as the ``+`` pseudo-tab and shows it
    instead of a :class:`BranchPanelWidget` when the user focuses the
    overview chip. ``/merge`` is dispatched from here.
    """

    DEFAULT_CSS = """
    ForkOverviewWidget {
        height: 1fr;
        padding: 1 2;
        display: none;
    }
    ForkOverviewWidget.active {
        display: block;
    }
    ForkOverviewWidget > .overview-title {
        height: 1;
        text-style: bold;
    }
    ForkOverviewWidget > .overview-row {
        height: 1;
        padding: 0 1;
    }
    ForkOverviewWidget > .overview-hint {
        height: auto;
        color: $text-muted;
        margin: 1 0 0 0;
    }
    """

    statuses: reactive[list[BranchStatus]] = reactive(list, always_update=True)

    def __init__(self) -> None:
        super().__init__()
        self.can_focus = True
        self._spinner = Spinner()
        self._spinner_timer: Any = None
        self._models: dict[str, str] = {}

    def set_models(self, mapping: dict[str, str]) -> None:
        """Set the per-branch model mapping used when rendering rows."""
        self._models = dict(mapping)
        self._render_rows()

    def compose(self) -> ComposeResult:
        yield Static("[bold]Active fork[/bold]", classes="overview-title")
        yield Static("", id="overview-rows")
        yield Static(
            "\n[bold]Controls[/bold]\n"
            "  [cyan]Tab[/cyan]            cycle between overview ↔ branch panels\n"
            "  [cyan]>>{label} msg[/cyan]  steer that branch (only while "
            "[yellow]running[/yellow])\n"
            "  [cyan]Enter[/cyan]          on a [green]done[/green] branch panel — "
            "merge it as winner\n"
            "  [cyan]/merge[/cyan]         resolve using strategy from /fork-config "
            "(judge or manual picker)\n"
            "  [cyan]/fork diff[/cyan]     pick file + branches → open in external diff tool\n"
            "  [cyan]Esc[/cyan]            on a branch panel — terminate that branch\n"
            "                 on this overview — abort the whole fork",
            classes="overview-hint",
        )

    def _render_rows(self) -> None:
        try:
            rows_widget = self.query_one("#overview-rows", Static)
        except Exception:  # pragma: no cover - widget not yet mounted
            return
        if not self.statuses:
            rows_widget.update("[dim]no branches[/dim]")
            return
        frame = self._spinner.frame
        lines: list[str] = []
        for s in self.statuses:
            if s.state == "running":
                status_text = f"[yellow]{frame} running[/yellow]"
            else:
                status_text = state_word(s.state)
            model = self._models.get(s.id)
            model_part = f"  ·  [dim]{model}[/dim]" if model else ""
            lines.append(
                f"  [bold]{s.label}[/bold]  ·  {status_text}  ·  turn {s.current_turn}{model_part}"
            )
        rows_widget.update("\n".join(lines))

    def watch_statuses(self, _old: list[BranchStatus], _new: list[BranchStatus]) -> None:
        self._render_rows()

    def set_active(self, active: bool) -> None:
        if active:
            self.add_class("active")
            if self._spinner_timer is None:
                self._spinner_timer = self._spinner.start_on(
                    self,
                    gate=lambda: any(s.state == "running" for s in self.statuses),
                    on_advance=self._render_rows,
                )
        else:
            self.remove_class("active")
            if self._spinner_timer is not None:
                with contextlib.suppress(Exception):
                    self._spinner_timer.stop()
                self._spinner_timer = None
