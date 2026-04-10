"""Optional side panel showing TODOs and subagents."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical

from apps.cli.widgets.subagents_panel import SubagentsWidget
from apps.cli.widgets.todos_panel import TodosWidget

_MIN_WIDTH = 100


class SidePanel(Vertical):
    """Right-side panel with TODOs and subagent status."""

    DEFAULT_CSS = """
    SidePanel {
        width: 32;
        display: none;
        padding: 0 1;
        border-left: tall $surface-lighten-2;
    }
    SidePanel.visible {
        display: block;
    }
    """

    def compose(self) -> ComposeResult:
        yield TodosWidget()
        yield SubagentsWidget()

    def update_for_width(self, width: int) -> None:
        """Show or hide based on terminal width."""
        if width >= _MIN_WIDTH:
            self.add_class("visible")
        else:
            self.remove_class("visible")

    def show_if_needed(self, width: int, has_content: bool) -> None:
        """Legacy API — kept for callers."""
        self.update_for_width(width)
