"""Acceptance modal for above-threshold `auto_with_fallback` resolution.

Shown by the CLI when :meth:`ForkCoordinator.resolve` returns
`auto_eligible=True` (the judge's
confidence is at or above the threshold but the commit was deferred so the
user can override). The widget renders the judge's verdict, then dispatches
on three actions:

- `[enter]` or `[escape]` → `"accept"`: caller commits via
  :meth:`ForkCoordinator.merge_or_select`.
- `[d]` → `"diff"`: caller opens the diff explorer and re-pushes this
  widget on return (Test 10: returning preserves the verdict context).
- `[o]` → `"override"`: caller opens the manual picker with the judge's
  choice preselected (Test 11).

File placement (`widgets/` instead of `modals/`) matches the path the
issue specifies; the implementation is a :class:`ModalScreen` regardless.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Rule, Static

if TYPE_CHECKING:
    from pydantic_deep.features.forking.types import JudgeVerdict


MergeAcceptanceAction = Literal["accept", "diff", "override"]


class MergeAcceptanceWidget(ModalScreen["MergeAcceptanceAction | None"]):
    """Render the judge's verdict and dispatch on the user's choice.

    Constructor takes the already-resolved values that the dispatcher
    composed; the widget itself stays formatting-light.
    """

    DEFAULT_CSS = """
    MergeAcceptanceWidget {
        align: center middle;
    }
    MergeAcceptanceWidget > #accept-container {
        width: 90;
        max-height: 28;
        border: tall $primary;
        background: $surface;
        padding: 0 2;
        layout: vertical;
    }
    MergeAcceptanceWidget > #accept-container > #accept-body {
        height: 1fr;
        padding: 1 0 0 0;
    }
    MergeAcceptanceWidget > #accept-container > #accept-body > #accept-title {
        height: 1;
        text-style: bold;
    }
    MergeAcceptanceWidget > #accept-container > #accept-body > #accept-winner {
        height: 1;
        margin: 1 0 1 0;
    }
    MergeAcceptanceWidget > #accept-container > #accept-body > #accept-reasoning {
        height: auto;
        color: $text-muted;
    }
    MergeAcceptanceWidget > #accept-container > #accept-body > #accept-caveats {
        height: auto;
        color: $warning;
        margin: 1 0 0 0;
    }
    MergeAcceptanceWidget > #accept-container > #accept-body > #accept-followup {
        height: auto;
        color: $text-muted;
        margin: 1 0 0 0;
    }
    MergeAcceptanceWidget > #accept-container > #accept-actions {
        height: auto;
        margin: 1 0 1 0;
        text-style: bold;
    }
    """

    BINDINGS = [
        Binding("enter", "accept", "Accept"),
        Binding("d", "view_diff", "View diff"),
        Binding("o", "override", "Override"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        *,
        fork_id: str,
        winner_label: str,
        effective_confidence: float,
        verdict: JudgeVerdict,
    ) -> None:
        super().__init__()
        self._fork_id = fork_id
        self._winner_label = winner_label
        self._effective_confidence = effective_confidence
        self._verdict = verdict

    def compose(self) -> ComposeResult:
        with Vertical(id="accept-container"):
            with VerticalScroll(id="accept-body"):
                yield Static(
                    f"[FORK {self._fork_id} — auto-merge ready]",
                    id="accept-title",
                )
                yield Static(
                    f"Winner: [bold]{self._winner_label}[/bold] · "
                    f"confidence {self._effective_confidence:.2f}",
                    id="accept-winner",
                )
                yield Static(
                    f"[bold]Why:[/bold] {self._verdict.reasoning}",
                    id="accept-reasoning",
                )
                if self._verdict.caveats:
                    bullets = "\n".join(f"  · {c}" for c in self._verdict.caveats)
                    yield Static(
                        f"[bold]Caveats:[/bold]\n{bullets}",
                        id="accept-caveats",
                    )
                if self._verdict.recommended_followup:
                    yield Static(
                        f"[bold]Suggested follow-up:[/bold] {self._verdict.recommended_followup}",
                        id="accept-followup",
                    )
            yield Rule()
            yield Static(
                "[bold reverse] enter [/] accept  ·  [bold]d[/] view diff  ·  "
                "[bold]o[/] override  ·  [bold reverse] Esc [/] cancel",
                id="accept-actions",
            )

    def action_accept(self) -> None:
        self.dismiss("accept")

    def action_view_diff(self) -> None:
        self.dismiss("diff")

    def action_override(self) -> None:
        self.dismiss("override")

    def action_cancel(self) -> None:
        """Dismiss without committing — judge result stays cached for next /merge."""
        self.dismiss(None)


__all__ = [
    "MergeAcceptanceAction",
    "MergeAcceptanceWidget",
]
