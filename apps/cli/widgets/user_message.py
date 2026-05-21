"""User message widget."""

from __future__ import annotations

from datetime import datetime

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static


class UserMessage(Widget):
    """Displays a user message with timestamp."""

    DEFAULT_CSS = """
    UserMessage {
        height: auto;
        padding: 0 2;
        margin: 1 0 0 0;
    }
    """

    def __init__(self, text: str, timestamp: datetime | None = None) -> None:
        super().__init__()
        self._text = text
        self._timestamp = timestamp or datetime.now()

    def compose(self) -> ComposeResult:
        time_str = self._timestamp.strftime("%H:%M")
        escaped = self._text.replace("[", r"\[")
        yield Static(f"[bold cyan]You[/bold cyan]  [dim]{time_str}[/dim]")
        yield Static(f"  {escaped}")
