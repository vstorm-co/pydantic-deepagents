"""Input-history picker — opened with Ctrl+P to reuse a past prompt."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from apps.cli.fuzzy import fuzzy_filter
from apps.cli.modals._filter_input import FilterInput


def _recent_unique(history: list[str], limit: int = 200) -> list[str]:
    """Most-recent-first, de-duplicated prompts (keeps the latest occurrence)."""
    seen: set[str] = set()
    out: list[str] = []
    for line in reversed(history):
        text = line.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= limit:
            break
    return out


class HistoryPickerModal(ModalScreen[str | None]):
    """Floating picker over past prompts with real-time fuzzy filtering."""

    DEFAULT_CSS = """
    HistoryPickerModal {
        align: center middle;
    }
    HistoryPickerModal > #picker-container {
        width: 80;
        max-height: 24;
        border: tall $primary;
        background: $surface;
        padding: 1;
    }
    HistoryPickerModal > #picker-container > #history-filter {
        height: 1;
        margin: 0 0 1 0;
        border: none;
    }
    HistoryPickerModal > #picker-container > #history-list {
        height: auto;
        max-height: 16;
    }
    HistoryPickerModal > #picker-container > #history-hint {
        height: 1;
        color: $text-disabled;
        margin: 1 0 0 0;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, history: list[str]) -> None:
        super().__init__()
        self._entries = _recent_unique(history)

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-container"):
            yield Static("[bold]History[/bold]  [dim]recent prompts[/dim]", id="history-title")
            yield FilterInput(
                placeholder="Type to filter…",
                id="history-filter",
                list_id="history-list",
                enter_selects=True,
            )
            yield OptionList(id="history-list")
            yield Static(
                "[dim]↑↓ navigate  Enter use  Esc cancel[/dim]",
                id="history-hint",
            )

    def on_mount(self) -> None:
        self._update_list(self._entries[:50])
        self.query_one("#history-filter", FilterInput).focus()

    def _update_list(self, entries: list[str]) -> None:
        option_list = self.query_one("#history-list", OptionList)
        option_list.clear_options()
        for entry in entries:
            # One-line label; the id carries the full text to return on select.
            label = entry if len(entry) <= 76 else entry[:75] + "…"
            option_list.add_option(Option(label, id=entry))

    def on_input_changed(self, event: Input.Changed) -> None:
        filtered = fuzzy_filter(event.value, self._entries, key=lambda e: e)
        self._update_list(filtered[:50])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option.id) if event.option.id else None)

    def action_cancel(self) -> None:
        self.dismiss(None)
