"""Tab strip showing one chip per branch + a ``+`` overview pseudo-tab."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static

from apps.cli.widgets.fork_state import state_icon

if TYPE_CHECKING:
    from pydantic_deep.types import BranchCost, BranchStatus

OVERVIEW_TAB_ID = "__overview__"
"""Sentinel branch id returned by :class:`ForkTabsWidget.BranchTabSelected` for the ``+`` tab."""


class ForkTabsWidget(Horizontal):
    """Horizontal strip rendering one chip per branch plus a ``+`` overview tab.

    The widget is rendered as plain Static labels rather than Textual's
    built-in ``Tabs`` so we can mix branch chips with the overview chip
    and keep the chip styling consistent with the existing CLI palette.
    """

    DEFAULT_CSS = """
    ForkTabsWidget {
        height: 1;
        background: $surface-lighten-1;
        display: none;
    }
    ForkTabsWidget.active {
        display: block;
    }
    ForkTabsWidget > .fork-tab {
        padding: 0 2;
        color: $text-muted;
    }
    ForkTabsWidget > .fork-tab.active {
        color: $text;
        background: $surface-lighten-2;
        text-style: bold;
    }
    """

    statuses: reactive[list[BranchStatus]] = reactive(list, always_update=True)
    branch_costs: reactive[dict[str, BranchCost]] = reactive(dict, always_update=True)
    active_id: reactive[str] = reactive(OVERVIEW_TAB_ID)

    class BranchTabSelected(Message):
        """Posted when the user clicks a branch chip or cycles via ``Tab``."""

        def __init__(self, branch_id: str) -> None:
            super().__init__()
            self.branch_id = branch_id

    def compose(self) -> ComposeResult:
        overview = Static(
            self._format_overview(), classes="fork-tab active", id="fork-tab-overview"
        )
        overview.can_focus = True
        yield overview

    def _format_overview(self) -> str:
        return "[bold]+ overview[/bold]"

    def _chip_text(self, status: BranchStatus) -> str:
        base = f"{state_icon(status.state)} {status.label}"
        cost = self.branch_costs.get(status.id)
        if cost is None or cost.cumulative_usd is None or cost.cumulative_usd <= 0:
            return base
        if cost.budget_usd is not None:
            return f"{base} ${cost.cumulative_usd:.2f}/${cost.budget_usd:.2f}"
        return f"{base} ${cost.cumulative_usd:.2f}"

    def _chip_id(self, branch_id: str) -> str:
        return f"fork-tab-{branch_id}"

    async def watch_statuses(self, _old: list[BranchStatus], new: list[BranchStatus]) -> None:
        for child in list(self.children):
            if child.id != "fork-tab-overview":
                await child.remove()
        for status in new:
            chip_id = self._chip_id(status.id)
            chip = Static(
                self._chip_text(status),
                classes="fork-tab",
                id=chip_id,
            )
            chip.can_focus = True
            if status.id == self.active_id:
                chip.add_class("active")
            await self.mount(chip)

    def watch_branch_costs(
        self,
        _old: dict[str, BranchCost],
        _new: dict[str, BranchCost],
    ) -> None:
        """Re-render chip text in-place when per-branch costs change.

        ``watch_statuses`` mounts chips with ``await self.mount(...)`` (async),
        so when ``_poll_fork_state`` sets ``statuses`` then ``branch_costs`` in the
        same turn the chip may not exist yet on this synchronous pass. Re-apply
        once immediately (for already-mounted chips) and again after the next
        refresh (once the pending mounts have completed) so a freshly mounted
        chip still gets its ``$x/$y`` cost instead of lagging a tick.
        """
        self._apply_costs()
        self.call_after_refresh(self._apply_costs)

    def _apply_costs(self) -> None:
        for status in self.statuses:
            chip_id = self._chip_id(status.id)
            chip = next(
                (c for c in self.children if isinstance(c, Static) and c.id == chip_id),
                None,
            )
            if chip is not None:
                chip.update(self._chip_text(status))

    def watch_active_id(self, _old: str, _new: str) -> None:
        for child in self.children:
            if not isinstance(child, Static):  # pragma: no cover - defensive
                continue
            child.remove_class("active")
            chip_target_id = "fork-tab-overview" if _new == OVERVIEW_TAB_ID else self._chip_id(_new)
            if child.id == chip_target_id:
                child.add_class("active")

    def cycle_focus(self) -> str:
        """Advance ``active_id`` to the next chip and return it.

        Order: overview → branch[0] → branch[1] → … → overview.
        """
        order: list[str] = [OVERVIEW_TAB_ID] + [s.id for s in self.statuses]
        try:
            idx = order.index(self.active_id)
        except ValueError:
            idx = -1
        next_id = order[(idx + 1) % len(order)]
        self.active_id = next_id
        self.post_message(self.BranchTabSelected(next_id))
        return next_id

    def select(self, branch_id: str) -> None:
        """Programmatically focus a specific branch tab (or the overview)."""
        self.active_id = branch_id
        self.post_message(self.BranchTabSelected(branch_id))
