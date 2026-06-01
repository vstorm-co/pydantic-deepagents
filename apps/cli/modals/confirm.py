"""Generic yes/no confirmation modal — used by Esc-terminate / Esc-abort flows."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class ConfirmModal(ModalScreen[bool]):
    """Tiny single-question modal that resolves to `True` (yes) or `False` (no/cancel)."""

    DEFAULT_CSS = """
    ConfirmModal {
        align: center middle;
    }
    ConfirmModal > #confirm-container {
        width: 60;
        height: auto;
        border: wide $warning;
        background: $surface;
        padding: 1 2;
    }
    ConfirmModal > #confirm-container > #confirm-question {
        text-style: bold;
        color: $warning;
        margin: 0 0 1 0;
    }
    ConfirmModal > #confirm-container > #confirm-actions {
        margin: 1 0 0 0;
        text-style: bold;
    }
    """

    BINDINGS = [
        Binding("y", "yes", "Yes"),
        Binding("n", "no", "No"),
        Binding("escape", "no", "Cancel", show=False),
    ]

    def __init__(self, question: str) -> None:
        super().__init__()
        self._question = question

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-container"):
            yield Static(self._question, id="confirm-question")
            yield Static(
                "[bold reverse] Y [/] Yes    [bold red reverse] N [/] No    [dim]Esc[/dim] cancel",
                id="confirm-actions",
            )

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)
