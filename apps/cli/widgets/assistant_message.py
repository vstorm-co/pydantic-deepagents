"""Assistant message widget — container for tool calls and streaming text."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from rich.markdown import Markdown
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from apps.cli.widgets.tool_call import ToolCallWidget

# How many trailing lines of the live reasoning stream to keep on screen. The
# model's thinking can run long; showing the most recent few lines reads as a
# calm, growing "thinking…" panel instead of a single truncated line that jumps
# around as new tokens arrive.
_THINKING_TAIL_LINES = 6


def _esc(text: str) -> str:
    """Escape `[` so Rich markup can't mis-pair tags inside model output."""
    return text.replace("[", r"\[")


# A bare http(s) URL not already part of a markdown link `](url)` / autolink
# `<url>` / attribute. Captured ones are wrapped as CommonMark autolinks so Rich
# renders them as OSC-8 hyperlinks (cmd/ctrl+click to open in modern terminals).
_BARE_URL_RE = re.compile(r"""(?<![\(<\]="'])\bhttps?://[^\s<>)\]]+""")


def _linkify_bare_urls(text: str) -> str:
    """Wrap bare URLs in `<...>` so Markdown turns them into clickable links."""

    def repl(match: re.Match[str]) -> str:
        raw = match.group(0)
        url = raw.rstrip(".,;:!?")
        return f"<{url}>{raw[len(url) :]}"

    return _BARE_URL_RE.sub(repl, text)


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
            f"[$primary b]Assistant[/]  [$text-muted]{time_str}[/]",
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

    def has_tool_call(self, call_id: str) -> bool:
        """True when this message holds the tool-call widget for `call_id`."""
        return call_id in self._tool_widgets

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

    def mark_pending_cancelling(self) -> None:
        """Flag all still-running tool calls as stopping (on user interrupt)."""
        for widget in self._tool_widgets.values():
            widget.mark_cancelling()

    def append_thinking(self, delta: str) -> None:
        """Append a streaming thinking delta — shown as a live, dimmed panel.

        Renders the most recent :data:`_THINKING_TAIL_LINES` non-empty lines of
        the accumulated reasoning so the panel reads as a calm, growing stream
        rather than a single line that jumps as tokens arrive.
        """
        self._thinking += delta
        if self._thinking_widget is not None:
            self._thinking_widget.display = True
            self._thinking_widget.update(self._render_thinking_stream())

    def _render_thinking_stream(self) -> str:
        """Build the live thinking panel: a header plus the trailing lines."""
        lines = [ln for ln in self._thinking.splitlines() if ln.strip()]
        header = "[dim italic]💭 Thinking…[/dim italic]"
        if not lines:
            return header
        tail = lines[-_THINKING_TAIL_LINES:]
        body = "\n".join(f"[dim italic]{_esc(ln.strip())}[/dim italic]" for ln in tail)
        return f"{header}\n{body}"

    def finalize_thinking(self) -> None:
        """Collapse the thinking panel to a one-line summary once it completes."""
        if self._thinking_widget is None or not self._thinking.strip():
            return
        n = len([ln for ln in self._thinking.splitlines() if ln.strip()])
        plural = "s" if n != 1 else ""
        self._thinking_widget.update(f"[dim italic]💭 Thought for {n} line{plural}[/dim italic]")

    def append_text(self, delta: str) -> None:
        """Append streaming text delta — renders immediately for real-time feel."""
        self._text += delta
        self._render_text()

    def finalize_text(self) -> None:
        """Final render — called when streaming is done."""
        self._render_text()

    @property
    def text(self) -> str:
        """The accumulated assistant text (public accessor for copy commands)."""
        return self._text

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
            self._text_widget.update(Markdown(_linkify_bare_urls(text)))
        else:
            self._text_widget.update("")
