"""Improve review modal — shows proposed changes for user approval."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Static

from pydantic_deep.features.improve.types import ImprovementReport, ProposedChange


class ImproveReviewModal(ModalScreen[list[ProposedChange] | None]):
    """Review modal for improve results.

    Shows each proposed change with a checkbox. The user can select
    which changes to apply, apply all, or skip.

    Returns the list of selected ProposedChange objects, or None if skipped.
    """

    DEFAULT_CSS = """
    ImproveReviewModal {
        align: center middle;
    }
    ImproveReviewModal > #improve-container {
        width: 90%;
        max-width: 90;
        max-height: 85%;
        border: tall $primary;
        background: $surface;
        padding: 1 2;
    }
    ImproveReviewModal > #improve-container > #improve-title {
        text-style: bold;
        margin: 0 0 1 0;
    }
    ImproveReviewModal > #improve-container > #improve-summary {
        margin: 0 0 1 0;
        color: $text-muted;
    }
    ImproveReviewModal > #improve-container > #improve-changes {
        max-height: 60%;
        margin: 0 0 1 0;
    }
    ImproveReviewModal > #improve-container > #improve-actions {
        height: 3;
        layout: horizontal;
    }
    ImproveReviewModal > #improve-container > #improve-actions > Button {
        margin: 0 1;
    }
    ImproveReviewModal > #improve-container > #improve-hint {
        height: 1;
        color: $text-disabled;
        margin: 1 0 0 0;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, report: ImprovementReport) -> None:
        super().__init__()
        self._report = report
        self._changes = list(report.proposed_changes)

    def compose(self) -> ComposeResult:
        with Vertical(id="improve-container"):
            yield Static("[bold]Improve Report[/bold]", id="improve-title")

            summary = (
                f"Analyzed {self._report.analyzed_sessions} sessions ({self._report.time_range})"
            )
            if not self._changes:
                summary += "\n\nNo changes proposed."
            else:
                summary += f"\nProposing {len(self._changes)} changes:"
            yield Static(summary, id="improve-summary")

            with VerticalScroll(id="improve-changes"):
                for i, change in enumerate(self._changes):
                    # Checkbox for each change
                    preview = change.content[:120]
                    if len(change.content) > 120:
                        preview += "..."
                    preview = preview.replace("\n", " ")

                    label = (
                        f"{change.target_file} -- {change.change_type}\n"
                        f'    "{preview}"\n'
                        f"    Confidence: {change.confidence:.2f}"
                    )
                    if change.source_sessions:
                        label += f"  |  From: {len(change.source_sessions)} sessions"

                    yield Checkbox(
                        label,
                        value=change.confidence >= 0.8,
                        id=f"change-{i}",
                    )

            with Vertical(id="improve-actions"):
                yield Button("Apply selected", variant="primary", id="btn-apply-selected")
                yield Button("Apply all", variant="success", id="btn-apply-all")
                yield Button("Skip", variant="default", id="btn-skip")

            yield Static(
                "[dim]Space to toggle  |  Esc to cancel[/dim]",
                id="improve-hint",
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-apply-all":
            self.dismiss(list(self._changes))
        elif event.button.id == "btn-apply-selected":
            selected = self._get_selected()
            self.dismiss(selected if selected else None)
        elif event.button.id == "btn-skip":
            self.dismiss(None)

    def _get_selected(self) -> list[ProposedChange]:
        """Return list of changes whose checkboxes are checked."""
        selected: list[ProposedChange] = []
        for i, change in enumerate(self._changes):
            try:
                cb = self.query_one(f"#change-{i}", Checkbox)
                if cb.value:
                    selected.append(change)
            except Exception:
                pass
        return selected

    def action_cancel(self) -> None:
        self.dismiss(None)
