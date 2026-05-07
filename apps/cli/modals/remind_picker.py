"""Reminder mode picker modal — opened by /remind."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

_MODES: list[tuple[str, str]] = [
    ("off", "Off — no periodic reminders"),
    ("first", "First message — re-states original task verbatim (zero-cost)"),
    ("context", "Context — first message + recent turns condensed (zero-cost)"),
    ("llm", "LLM — small model summarizes goal and progress"),
]


class ReminderPickerModal(ModalScreen[str | None]):
    """Modal for switching the periodic reminder mode."""

    DEFAULT_CSS = """
    ReminderPickerModal {
        align: center middle;
    }
    ReminderPickerModal > #remind-container {
        width: 68;
        max-height: 16;
        border: tall $primary;
        background: $surface;
        padding: 1;
    }
    ReminderPickerModal > #remind-container > #remind-list {
        height: auto;
        max-height: 8;
    }
    ReminderPickerModal > #remind-container > #remind-hint {
        height: 1;
        color: $text-disabled;
        margin: 1 0 0 0;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, current_mode: str = "off") -> None:
        super().__init__()
        self._current = current_mode

    def compose(self) -> ComposeResult:
        with Vertical(id="remind-container"):
            yield Static("[bold]Reminder Mode[/bold]")
            options: list[Option] = []
            for mode, desc in _MODES:
                label = desc
                if mode == self._current:
                    label += "  [bold](current)[/bold]"
                options.append(Option(label, id=mode))
            yield OptionList(*options, id="remind-list")
            yield Static(
                "[dim]↑↓ navigate  Enter select  Esc cancel[/dim]",
                id="remind-hint",
            )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option.id) if event.option.id else None)

    def action_cancel(self) -> None:
        self.dismiss(None)
