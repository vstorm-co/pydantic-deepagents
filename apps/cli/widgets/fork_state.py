"""Canonical per-branch-state palette shared by every fork widget.

Three widgets render the same lifecycle states differently:

- :class:`~apps.cli.widgets.fork_tabs.ForkTabsWidget` shows just the icon
- :class:`~apps.cli.widgets.branch_panel.BranchPanelWidget` shows icon + word
- :class:`~apps.cli.widgets.fork_overview.ForkOverviewWidget` shows the colored word only

Defining all slices in one place keeps them from drifting when the
palette gets touched.
"""

from __future__ import annotations

from typing import Literal, TypedDict

BranchState = Literal[
    "running",
    "done",
    "failed",
    "terminated",
    "budget_exhausted",
    "aggregate_budget_exhausted",
]


class _StatePalette(TypedDict):
    icon: str
    label: str
    word: str


STATE_PALETTE: dict[str, _StatePalette] = {
    "running": {
        "icon": "[yellow]●[/yellow]",
        "label": "[yellow]●[/yellow] running",
        "word": "[yellow]running[/yellow]",
    },
    "done": {
        "icon": "[green]✓[/green]",
        "label": "[green]✓[/green] done",
        "word": "[green]done[/green]",
    },
    "failed": {
        "icon": "[red]✗[/red]",
        "label": "[red]✗[/red] failed",
        "word": "[red]failed[/red]",
    },
    "terminated": {
        "icon": "[dim]⊘[/dim]",
        "label": "[dim]⊘ terminated[/dim]",
        "word": "[dim]terminated[/dim]",
    },
    "budget_exhausted": {
        "icon": "[orange1]$[/orange1]",
        "label": "[orange1]$ budget exhausted[/orange1]",
        "word": "[orange1]budget exhausted[/orange1]",
    },
    "aggregate_budget_exhausted": {
        "icon": "[red]$$[/red]",
        "label": "[red]$$ agg-exhausted[/red]",
        "word": "[red]agg-exhausted[/red]",
    },
}


def state_icon(state: str) -> str:
    """Return the bare icon for `state` (falls back to the raw state name)."""
    palette = STATE_PALETTE.get(state)
    return palette["icon"] if palette is not None else state


def state_label(state: str) -> str:
    """Return icon + word for `state` (falls back to the raw state name)."""
    palette = STATE_PALETTE.get(state)
    return palette["label"] if palette is not None else state


def state_word(state: str) -> str:
    """Return the colored word for `state` (falls back to the raw state name)."""
    palette = STATE_PALETTE.get(state)
    return palette["word"] if palette is not None else state
