"""Assistant message widget — container for tool calls and streaming text."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from rich.markdown import Markdown
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from apps.cli.widgets.tool_call import ToolCallWidget


def _fmt_tokens(count: int) -> str:
    """Format token count compactly: 500, 1.2K, 150K."""
    if count < 1000:
        return str(count)
    elif count < 100_000:
        return f"{count / 1000:.1f}K"
    else:
        return f"{count // 1000}K"


class AssistantMessage(Widget):
    """Container widget for a single assistant response turn.

    Holds tool calls (ToolCallWidget instances) and accumulated text.
    Uses a simple Static for text (not a separate StreamingText widget)
    to avoid mount-timing issues.
    """

    DEFAULT_CSS = """
    AssistantMessage {
        height: auto;
        padding: 0 0;
        margin: 1 0 0 0;
    }
    AssistantMessage .assistant-label {
        padding: 0 2;
    }
    AssistantMessage .assistant-thinking {
        padding: 0 2;
        height: auto;
        color: $text-muted;
    }
    AssistantMessage .assistant-text {
        padding: 0 2;
        height: auto;
    }
    AssistantMessage .assistant-usage {
        padding: 0 2;
        height: auto;
        color: $text-muted;
    }
    """

    def __init__(self, timestamp: datetime | None = None) -> None:
        super().__init__()
        self._timestamp = timestamp or datetime.now()
        self._tool_widgets: dict[str, ToolCallWidget] = {}
        self._text: str = ""
        self._thinking: str = ""
        self._text_widget: Static | None = None
        self._thinking_widget: Static | None = None
        self._label_widget: Static | None = None
        self._usage_widget: Static | None = None

    def compose(self) -> ComposeResult:
        time_str = self._timestamp.strftime("%H:%M")
        self._label_widget = Static(
            f"[bold green]Assistant[/bold green]  [dim]{time_str}[/dim]",
            classes="assistant-label",
        )
        yield self._label_widget
        self._thinking_widget = Static("", classes="assistant-thinking")
        self._thinking_widget.display = False
        yield self._thinking_widget
        self._text_widget = Static("", classes="assistant-text")
        yield self._text_widget
        self._usage_widget = Static("", classes="assistant-usage")
        self._usage_widget.display = False
        yield self._usage_widget

    def add_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        call_id: str,
        *,
        is_subagent_tool: bool = False,
    ) -> ToolCallWidget:
        """Add a new tool call widget to this message."""
        widget = ToolCallWidget(
            tool_name=tool_name,
            args=args,
            call_id=call_id,
            is_subagent_tool=is_subagent_tool,
        )
        self._tool_widgets[call_id] = widget

        # Mount before text widget if it exists
        if self._text_widget is not None:
            self.mount(widget, before=self._text_widget)
        else:
            self.mount(widget)
        return widget

    def complete_tool_call(
        self,
        call_id: str,
        result: str,
        elapsed: float,
        error: bool = False,
    ) -> None:
        """Mark a tool call as completed."""
        widget = self._tool_widgets.get(call_id)
        if widget and widget.status == "pending":
            widget.complete(result, elapsed, error)

    def append_thinking(self, delta: str) -> None:
        """Append streaming thinking delta — shown as dimmed text."""
        self._thinking += delta
        if self._thinking_widget is not None:
            self._thinking_widget.display = True
            # Show truncated thinking with prefix
            lines = self._thinking.strip().splitlines()
            preview = lines[-1][:120] if lines else ""
            self._thinking_widget.update(f"[dim italic]thinking: {preview}[/dim italic]")

    def finalize_thinking(self) -> None:
        """Collapse thinking to a summary after streaming completes."""
        if self._thinking_widget is None or not self._thinking:
            return
        lines = self._thinking.strip().splitlines()
        n = len(lines)
        first = lines[0][:100] if lines else ""
        self._thinking_widget.update(f"[dim italic]thought ({n} lines): {first}...[/dim italic]")

    def append_text(self, delta: str) -> None:
        """Append streaming text delta — renders immediately for real-time feel."""
        self._text += delta
        self._render_text()

    def finalize_text(self) -> None:
        """Final render — called when streaming is done."""
        self._render_text()

    @property
    def is_empty(self) -> bool:
        """True when the message has no visible content."""
        return not self._text.strip() and not self._thinking.strip() and not self._tool_widgets

    def set_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        requests: int,
    ) -> None:
        """Show per-turn usage stats below the response."""
        if self._usage_widget is None:
            return
        total = input_tokens + output_tokens
        parts = [
            f"in:{_fmt_tokens(input_tokens)}",
            f"out:{_fmt_tokens(output_tokens)}",
            f"total:{_fmt_tokens(total)}",
            f"reqs:{requests}",
        ]
        self._usage_widget.update(f"[dim]{' · '.join(parts)}[/dim]")
        self._usage_widget.display = True

    def _render_text(self) -> None:
        """Re-render the accumulated text as Markdown."""
        if self._text_widget is None:
            return
        text = self._text.strip()
        if text:
            self._text_widget.update(Markdown(text))
        else:
            self._text_widget.update("")
