"""Thinking-effort picker — opened by /thinking.

Lets the user dial reasoning depth up or down without editing config. Dismisses
with the chosen effort string (``minimal``…``xhigh`` or ``false`` for off).
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

# (value, label, blurb) ordered from least to most reasoning.
_LEVELS: tuple[tuple[str, str, str], ...] = (
    ("false", "Off", "no extended thinking — fastest"),
    ("minimal", "Minimal", "a little reasoning"),
    ("low", "Low", "light reasoning"),
    ("medium", "Medium", "balanced"),
    ("high", "High", "deep reasoning (default)"),
    ("xhigh", "Extra high", "maximum reasoning — slowest"),
)


class ThinkingPickerModal(ModalScreen[str | None]):
    """Pick a reasoning-effort level. Dismisses with the effort string or None."""

    DEFAULT_CSS = """
    ThinkingPickerModal {
        align: center middle;
    }
    ThinkingPickerModal > #thinking-container {
        width: 60;
        height: auto;
        border: tall $primary;
        background: $surface;
        padding: 1;
    }
    ThinkingPickerModal > #thinking-container > #thinking-list {
        height: auto;
        max-height: 12;
    }
    ThinkingPickerModal > #thinking-container > #thinking-hint {
        height: 1;
        color: $text-disabled;
        margin: 1 0 0 0;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, current: str = "high") -> None:
        super().__init__()
        self._current = (current or "high").strip().lower()

    def compose(self) -> ComposeResult:
        with Vertical(id="thinking-container"):
            yield Static("[bold]Reasoning effort[/bold]")
            options: list[Option] = []
            for value, label, blurb in _LEVELS:
                marker = "[green]●[/green]" if value == self._current else " "
                text = f"{marker} [bold]{label}[/bold]  [dim]{blurb}[/dim]"
                options.append(Option(text, id=value))
            yield OptionList(*options, id="thinking-list")
            yield Static("[dim]↑↓ navigate  Enter select  Esc cancel[/dim]", id="thinking-hint")

    def on_mount(self) -> None:
        option_list = self.query_one("#thinking-list", OptionList)
        for i, (value, _label, _blurb) in enumerate(_LEVELS):
            if value == self._current:
                option_list.highlighted = i
                break
        option_list.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option.id) if event.option.id else None)

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = ["ThinkingPickerModal"]
