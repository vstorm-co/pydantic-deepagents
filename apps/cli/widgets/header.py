"""Fixed top header bar showing session info and spinner during streaming."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.events import Resize
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def _fmt(count: int) -> str:
    """Format token count compactly."""
    if count < 1000:
        return str(count)
    elif count < 100_000:
        return f"{count / 1000:.1f}K"
    else:
        return f"{count // 1000}K"


class DeepHeader(Widget):
    """Fixed one-line header: version · branch · model | separator line.

    When NOT streaming, shows info followed by ─ separator filling remaining width.
    When streaming, hides model name to save space and shows spinner + elapsed.
    """

    DEFAULT_CSS = """
    DeepHeader {
        dock: top;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """

    version: reactive[str] = reactive("0.0.0")
    branch: reactive[str] = reactive("")
    model_name: reactive[str] = reactive("")
    is_streaming: reactive[bool] = reactive(False)
    is_thinking: reactive[bool] = reactive(False)
    elapsed: reactive[float] = reactive(0.0)
    total_input_tokens: reactive[int] = reactive(0)
    total_output_tokens: reactive[int] = reactive(0)
    total_cost: reactive[float] = reactive(0.0)

    _spinner_index: int = 0
    _timer_handle: object | None = None
    _width: int = 80

    def compose(self) -> ComposeResult:
        yield Static(id="header-content")

    def on_mount(self) -> None:
        self._timer_handle = self.set_interval(1 / 12, self._tick)

    def on_resize(self, event: Resize) -> None:
        self._width = event.size.width
        self._refresh_content()

    def _tick(self) -> None:
        if self.is_streaming:
            self._spinner_index = (self._spinner_index + 1) % len(_SPINNER_FRAMES)
            self.elapsed += 1 / 12
        self._refresh_content()

    def watch_version(self) -> None:
        self._refresh_content()

    def watch_branch(self) -> None:
        self._refresh_content()

    def watch_model_name(self) -> None:
        self._refresh_content()

    def watch_is_streaming(self, streaming: bool) -> None:
        if streaming:
            self.elapsed = 0.0
            self._spinner_index = 0
        self._refresh_content()

    def watch_is_thinking(self) -> None:
        self._refresh_content()

    def watch_total_input_tokens(self) -> None:
        self._refresh_content()

    def watch_total_cost(self) -> None:
        self._refresh_content()

    def _refresh_content(self) -> None:
        try:
            content = self.query_one("#header-content", Static)
        except Exception:
            return  # Not yet composed

        parts: list[str] = []
        parts.append(f"[bold]pydantic-deep[/bold] v{self.version}")
        if self.branch:
            parts.append(self.branch)

        if self.is_streaming:
            frame = _SPINNER_FRAMES[self._spinner_index]
            if self.is_thinking:
                parts.append(
                    f"[bold]{frame}[/bold] [italic]thinking...[/italic] {self.elapsed:.0f}s"
                )
            else:
                parts.append(f"[bold]{frame}[/bold] {self.elapsed:.0f}s")
            content.update("  ·  ".join(parts))
        else:
            if self.model_name:
                parts.append(self.model_name)
            # Token usage and cost
            total = self.total_input_tokens + self.total_output_tokens
            if total > 0:
                parts.append(
                    f"in:{_fmt(self.total_input_tokens)} out:{_fmt(self.total_output_tokens)}"
                )
            if self.total_cost > 0:
                cost_str = (
                    f"${self.total_cost:.4f}"
                    if self.total_cost < 0.01
                    else f"${self.total_cost:.2f}"
                )
                parts.append(cost_str)
            info_text = "  ·  ".join(parts)
            # Calculate plain text length (strip Rich markup for length calc)
            plain_len = len(info_text.replace("[bold]", "").replace("[/bold]", ""))
            # Fill remaining width with ─ separator
            available = self._width - plain_len - 3  # 3 = padding + gap
            if available > 2:
                separator = " " + "─" * available
                content.update(f"{info_text}[dim]{separator}[/dim]")
            else:
                content.update(info_text)
