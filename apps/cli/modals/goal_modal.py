"""Goal modal — interactive input for the /goal command.

Opened when the user runs ``/goal`` with no condition, so they can type the
completion condition the agent should keep working toward (mirrors the
``/remember`` flow). Inline ``/goal <condition>`` and ``/goal clear`` bypass
this modal.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Static


class GoalModal(ModalScreen[str | None]):
    """Input modal for setting a goal condition."""

    DEFAULT_CSS = """
    GoalModal {
        align: center middle;
    }
    GoalModal > #goal-container {
        width: 70;
        height: auto;
        border: tall $primary;
        background: $surface;
        padding: 1 2;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, initial_text: str = "") -> None:
        super().__init__()
        self._initial_text = initial_text

    def compose(self) -> ComposeResult:
        with Vertical(id="goal-container"):
            yield Static("[bold]◎ Goal[/bold]")
            yield Static(
                "Describe a condition to keep working toward. The agent loops, "
                "re-evaluating after each turn, until it's met.\n"
            )
            yield Input(
                value=self._initial_text,
                placeholder="e.g. all tests in tests/ pass",
                id="goal-input",
            )
            yield Static("\n[dim]Enter to set  ·  Esc to cancel[/dim]")

    def on_mount(self) -> None:
        self.query_one("#goal-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        self.dismiss(text or None)

    def action_cancel(self) -> None:
        self.dismiss(None)
