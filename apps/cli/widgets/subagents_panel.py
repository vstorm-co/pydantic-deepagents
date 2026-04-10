"""Subagents display widget for the side panel."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class SubagentsWidget(Widget):
    """Displays active subagent tasks."""

    DEFAULT_CSS = """
    SubagentsWidget {
        height: auto;
        padding: 1;
        border: tall $surface-lighten-2;
        margin: 1 0 0 0;
    }
    """

    agents: reactive[list[dict[str, Any]]] = reactive(list, always_update=True)

    def compose(self) -> ComposeResult:
        yield Static("[bold]Subagents[/bold]", id="subagents-title")
        yield Static("", id="subagents-list")

    def watch_agents(self, agents: list[dict[str, Any]]) -> None:
        content = self.query_one("#subagents-list", Static)
        if not agents:
            content.update("[dim]No active agents[/dim]")
            return

        lines = []
        for agent in agents:
            name = agent.get("name", "?")
            status = agent.get("status", "idle")
            desc = agent.get("description", "")

            if status == "running":
                glyph = "●"
                color = "green"
            elif status == "waiting":
                glyph = "○"
                color = "yellow"
            elif status == "completed":
                glyph = "✓"
                color = "green"
            elif status == "error":
                glyph = "✗"
                color = "red"
            elif status == "idle":
                glyph = "○"
                color = "dim"
            else:
                glyph = "○"
                color = "dim"

            line = f"  [{color}]{glyph}[/{color}] {name}"
            if status != "idle":
                line += f"  [{color}]{status}[/{color}]"
            if desc:
                line += f"  [dim]{desc[:30]}[/dim]"
            lines.append(line)

        content.update("\n".join(lines))
