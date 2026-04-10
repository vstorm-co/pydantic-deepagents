"""Context usage modal — /context command."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from apps.cli.widgets.status_bar import _context_bar, _format_tokens


class ContextViewModal(ModalScreen[str | None]):
    """Shows context window usage with progress bar, stats, and compact button."""

    DEFAULT_CSS = """
    ContextViewModal {
        align: center middle;
    }
    ContextViewModal > #ctx-container {
        width: 55;
        height: auto;
        border: tall $primary;
        background: $surface;
        padding: 1 2;
    }
    ContextViewModal > #ctx-container > Button {
        margin: 1 0 0 0;
        width: 100%;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
    ]

    def __init__(
        self,
        pct: float = 0.0,
        current: int = 0,
        maximum: int = 0,
        message_count: int = 0,
        total_input_tokens: int = 0,
        total_output_tokens: int = 0,
        total_requests: int = 0,
        total_cost: float = 0.0,
    ) -> None:
        super().__init__()
        self._pct = pct
        self._current = current
        self._max = maximum
        self._msg_count = message_count
        self._total_input = total_input_tokens
        self._total_output = total_output_tokens
        self._total_requests = total_requests
        self._total_cost = total_cost

    def compose(self) -> ComposeResult:
        threshold = int(self._max * 0.9) if self._max else 0

        with Vertical(id="ctx-container"):
            yield Static("[bold]Context Usage[/bold]\n")
            yield Static(f"  {_context_bar(self._pct, width=24)}\n")
            yield Static(
                f"  Current tokens:   {_format_tokens(self._current)}\n"
                f"  Max tokens:       {_format_tokens(self._max)}\n"
                f"  Compression at:   90% ({_format_tokens(threshold)} tokens)\n"
                f"  Messages:         {self._msg_count}"
            )

            yield Static("\n[bold]Session Usage[/bold]\n")
            cost_str = (
                f"${self._total_cost:.4f}"
                if self._total_cost < 0.01
                else f"${self._total_cost:.2f}"
            )
            yield Static(
                f"  Input tokens:     {_format_tokens(self._total_input)}\n"
                f"  Output tokens:    {_format_tokens(self._total_output)}\n"
                f"  Total tokens:     {_format_tokens(self._total_input + self._total_output)}\n"
                f"  Requests:         {self._total_requests}\n"
                f"  Cost:             {cost_str}"
            )

            if self._pct >= 0.7:
                yield Button("Compact now", variant="warning", id="btn-compact")
            else:
                yield Button("Compact now", variant="default", id="btn-compact")

            yield Static("\n[dim]Esc to close[/dim]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-compact":
            self.dismiss("compact")

    def action_dismiss(self) -> None:
        self.dismiss(None)
