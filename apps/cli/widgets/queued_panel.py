"""Queued messages display widget for the side panel."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class QueuedWidget(Widget):
    """Pending steering / follow-up message counts."""

    DEFAULT_CSS = """
    QueuedWidget {
        height: auto;
        padding: 1;
        border: tall $surface-lighten-2;
        margin: 1 0 0 0;
    }
    """

    steering_count: reactive[int] = reactive(0)
    follow_up_count: reactive[int] = reactive(0)

    def compose(self) -> ComposeResult:
        yield Static("[bold]Queued[/bold]", id="queued-title")
        yield Static("", id="queued-list")

    def watch_steering_count(self) -> None:
        self._refresh()

    def watch_follow_up_count(self) -> None:
        self._refresh()

    def increment_steering(self) -> None:
        self.steering_count += 1

    def increment_follow_up(self) -> None:
        self.follow_up_count += 1

    def decrement_follow_up(self, n: int = 1) -> None:
        self.follow_up_count = max(0, self.follow_up_count - n)

    def reset(self) -> None:
        self.steering_count = 0
        self.follow_up_count = 0

    def clear_steering(self) -> None:
        self.steering_count = 0

    def _refresh(self) -> None:
        try:
            content = self.query_one("#queued-list", Static)
        except NoMatches:
            return

        lines: list[str] = []
        if self.steering_count > 0:
            lines.append(f"  {self.steering_count} steering")
        if self.follow_up_count > 0:
            lines.append(f"  {self.follow_up_count} follow-up")

        if lines:
            content.update("\n".join(lines))
        else:
            content.update("[dim]No queued messages[/dim]")
