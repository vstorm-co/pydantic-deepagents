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
        padding: 0;
        margin: 1 0 0 0;
    }
    SubagentsWidget #subagents-title {
        color: $text-muted;
        text-style: bold;
    }
    """

    agents: reactive[list[dict[str, Any]]] = reactive(list, always_update=True)

    def compose(self) -> ComposeResult:
        yield Static("Subagents", id="subagents-title")
        yield Static("", id="subagents-list")

    def watch_agents(self, agents: list[dict[str, Any]]) -> None:
        # Only surface when something is actually doing work — idle baseline
        # agents stay hidden so the strip under the messages appears on demand.
        active = [a for a in agents if a.get("status", "idle") not in ("idle", "")]
        self.display = bool(active)
        if not active:
            return
        content = self.query_one("#subagents-list", Static)
        agents = active

        glyphs = {
            "running": ("●", "$accent"),
            "waiting": ("○", "$warning"),
            "completed": ("✓", "$success"),
            "error": ("✗", "$error"),
            "idle": ("○", "$text-muted"),
        }
        lines = []
        for agent in agents:
            name = agent.get("name", "?")
            status = agent.get("status", "idle")
            desc = agent.get("description", "")
            glyph, color = glyphs.get(status, ("○", "$text-muted"))

            line = f"[{color}]{glyph}[/] {name}"
            if status not in ("idle", ""):
                line += f"  [{color}]{status}[/]"
            if desc:
                line += f"  [$text-muted]{desc[:30]}[/]"
            lines.append(line)

        content.update("\n".join(lines))
