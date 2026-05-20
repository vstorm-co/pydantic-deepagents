"""Side-panel chip displayed while a fork is active.

Mirrors :class:`apps.cli.widgets.queued_panel.QueuedWidget` — a small
status chip that takes the issue's `[FORK: 2 branches · $0.34]` example
literally. When no fork is active the widget hides itself via
``display: none`` (toggled from ``ChatScreen.watch_active_fork``).
"""

from __future__ import annotations

import contextlib

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class ForkBadgeWidget(Widget):
    """Fork-wide status chip — branch count, status summary, cost estimate.

    Cost is rendered as ``$—`` when :class:`~pydantic_ai_shields.CostTracking`
    is not registered on the agent, to avoid the misleading ``$0.00`` reading
    that would imply branches are free.
    """

    DEFAULT_CSS = """
    ForkBadgeWidget {
        height: auto;
        padding: 1;
        border: tall $primary;
        margin: 1 0 0 0;
        display: none;
    }
    ForkBadgeWidget.visible {
        display: block;
    }
    """

    branch_count: reactive[int] = reactive(0)
    status_summary: reactive[str] = reactive("")
    aggregate_usd: reactive[float | None] = reactive["float | None"](None)
    aggregate_budget_usd: reactive[float | None] = reactive["float | None"](None)

    def compose(self) -> ComposeResult:
        yield Static("", id="fork-badge-text")

    def _format(self) -> str:
        if self.branch_count == 0:
            return "[dim]No active fork[/dim]"
        if self.aggregate_usd is None:
            cost_str = "$—"
        elif self.aggregate_budget_usd is not None:
            cost_str = f"${self.aggregate_usd:.2f}/${self.aggregate_budget_usd:.2f}"
        else:
            cost_str = f"${self.aggregate_usd:.2f}"
        summary = self.status_summary or "active"
        return f"[bold]FORK[/bold]: {self.branch_count} branches · {summary} · {cost_str}"

    def _refresh(self) -> None:
        with contextlib.suppress(Exception):  # widget not yet mounted
            self.query_one("#fork-badge-text", Static).update(self._format())

    def watch_branch_count(self) -> None:
        self._refresh()

    def watch_status_summary(self) -> None:
        self._refresh()

    def watch_aggregate_usd(self) -> None:
        self._refresh()

    def watch_aggregate_budget_usd(self) -> None:
        self._refresh()

    def show(self) -> None:
        """Make the badge visible (called when ``app.active_fork`` becomes non-None)."""
        self.add_class("visible")
        self._refresh()

    def hide(self) -> None:
        """Hide the badge (called when ``app.active_fork`` is cleared)."""
        self.remove_class("visible")

    def update_from_statuses(
        self,
        statuses: list[object],  # list[BranchStatus] — Any to avoid import cycle
        *,
        aggregate_usd: float | None,
        aggregate_budget_usd: float | None = None,
    ) -> None:
        """Recompute the chip's text from a fresh ``inspect_branches()`` snapshot."""
        if not statuses:
            self.branch_count = 0
            self.status_summary = ""
            self.aggregate_usd = aggregate_usd
            self.aggregate_budget_usd = aggregate_budget_usd
            return
        states = [getattr(s, "state", "") for s in statuses]
        self.branch_count = len(statuses)
        if all(state == "running" for state in states):
            self.status_summary = f"{len(states)} running"
        else:
            from collections import Counter

            counts = Counter(states)
            parts = [f"{n} {state}" for state, n in sorted(counts.items())]
            self.status_summary = ", ".join(parts)
        self.aggregate_usd = aggregate_usd
        self.aggregate_budget_usd = aggregate_budget_usd
