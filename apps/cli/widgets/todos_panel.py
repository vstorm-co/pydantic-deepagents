"""Todos display widget for the side panel."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

_STATUS_GLYPHS = {
    "pending": "○",
    "in_progress": "◐",
    "completed": "✓",
}

_STATUS_COLORS = {
    "pending": "$text-muted",
    "in_progress": "$accent",
    "completed": "$success",
}


class TodosWidget(Widget):
    """Displays the current TODO list."""

    DEFAULT_CSS = """
    TodosWidget {
        height: auto;
        padding: 0;
    }
    TodosWidget #todos-title {
        color: $text-muted;
        text-style: bold;
    }
    """

    todos: reactive[list[Any]] = reactive(list, always_update=True)

    def compose(self) -> ComposeResult:
        yield Static("TODOs", id="todos-title")
        yield Static("", id="todos-list")

    def watch_todos(self, todos: list[Any]) -> None:
        # Collapse entirely when empty — this widget is pinned above the input,
        # so an empty placeholder would just take a permanent row.
        self.display = bool(todos)
        if not todos:
            return
        content = self.query_one("#todos-list", Static)
        done = sum(1 for t in todos if getattr(t, "status", "") == "completed")
        self.query_one("#todos-title", Static).update(f"TODOs  [$text-muted]{done}/{len(todos)}[/]")

        lines = []
        for todo in todos:
            status = getattr(todo, "status", "pending")
            text = getattr(todo, "content", str(todo))
            glyph = _STATUS_GLYPHS.get(status, "○")
            color = _STATUS_COLORS.get(status, "$text-muted")
            if status == "completed":
                lines.append(f"[$text-muted]{glyph} {text}[/]")
            else:
                lines.append(f"[{color}]{glyph}[/] {text}")

        content.update("\n".join(lines))
