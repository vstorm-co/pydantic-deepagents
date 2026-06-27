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

    def __init__(
        self,
        text: str,
        timestamp: datetime | None = None,
        attachments: list[str] | None = None,
    ) -> None:
        super().__init__()
        self._text = text
        self._timestamp = timestamp or datetime.now()
        self._attachments = attachments or []

    @property
    def text(self) -> str:
        """The message text (public accessor for copy commands)."""
        return self._text

    def compose(self) -> ComposeResult:
        time_str = self._timestamp.strftime("%H:%M")
        escaped = self._text.replace("[", r"\[")
        yield Static(f"[$accent b]You[/]  [$text-muted]{time_str}[/]")
        if escaped:
            yield Static(f"  {escaped}")
        for label in self._attachments:
            # A dim tree-branch sub-line per attachment (brackets escaped so a
            # label like [Image #1] isn't parsed as markup).
            chip = label.replace("[", r"\[")
            yield Static(f"  [$text-muted]└ {chip}[/]")
