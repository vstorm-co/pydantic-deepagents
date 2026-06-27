"""Fixed top header bar showing session info and spinner during streaming."""

from __future__ import annotations

import re

from textual.app import ComposeResult
from textual.events import Resize
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from apps.cli.widgets.spinner import Spinner

_MARKUP_RE = re.compile(r"\[/?[^\]]*\]")


def _plain_len(markup: str) -> int:
    """Length of `markup` with all `[...]` tags removed (for layout maths)."""
    return len(_MARKUP_RE.sub("", markup))


def _shimmer_rule(width: int, pos: int, *, band: int = 7) -> str:
    """A faint horizontal rule with a bright accent band travelling along it.

    Rendered while streaming to signal "alive" activity — the band sweeps left
    to right at `pos` (advanced once per spinner tick) over a dim base rule.
    """
    if width <= 0:
        return ""
    cycle = width + band
    center = pos % cycle
    out: list[str] = []
    run: list[str] = []
    run_bright = False

    def _flush() -> None:
        if not run:
            return
        color = "$accent" if run_bright else "$text-muted"
        out.append(f"[{color}]{''.join(run)}[/]")

    for i in range(width):
        dist = abs(i - center)
        bright = dist <= band // 2
        if bright != run_bright and run:
            _flush()
            run.clear()
        run_bright = bright
        run.append("─")
    _flush()
    return "".join(out)


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
    total_input_tokens: reactive[int] = reactive(0)
    total_output_tokens: reactive[int] = reactive(0)
    total_cost: reactive[float] = reactive(0.0)

    _timer_handle: object | None = None
    _width: int = 80
    _shimmer_pos: int = 0

    def __init__(self) -> None:
        super().__init__()
        self._spinner = Spinner()

    def compose(self) -> ComposeResult:
        yield Static(id="header-content")

    def on_mount(self) -> None:
        self._timer_handle = self._spinner.start_on(
            self,
            gate=lambda: self.is_streaming,
            on_advance=self._refresh_content,
        )

    def on_resize(self, event: Resize) -> None:
        self._width = event.size.width
        self._refresh_content()

    def watch_version(self) -> None:
        self._refresh_content()

    def watch_branch(self) -> None:
        self._refresh_content()

    def watch_model_name(self) -> None:
        self._refresh_content()

    def watch_is_streaming(self, streaming: bool) -> None:
        if streaming:
            self._spinner.reset()
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

        sep = "  [$text-muted]·[/]  "
        parts: list[str] = [f"[$accent]◆[/] [b]pydantic-deep[/b] [$text-muted]v{self.version}[/]"]
        if self.branch:
            parts.append(f"[$text-muted]{self.branch}[/]")

        if self.is_streaming:
            frame = self._spinner.frame
            elapsed = self._spinner.elapsed
            if self.is_thinking:
                parts.append(
                    f"[$accent]{frame}[/] [i $text-muted]thinking…[/] "
                    f"[$text-muted]{elapsed:.0f}s[/]"
                )
            else:
                parts.append(f"[$accent]{frame}[/] [$text-muted]{elapsed:.0f}s[/]")
            info_text = sep.join(parts)
            # Animated shimmer rule fills the rest, sweeping with each tick.
            self._shimmer_pos += 1
            available = self._width - _plain_len(info_text) - 3
            if available > 4:
                content.update(f"{info_text}  {_shimmer_rule(available - 2, self._shimmer_pos)}")
            else:
                content.update(info_text)
        else:
            if self.model_name:
                parts.append(f"[$text-muted]{self.model_name}[/]")
            # Token usage and cost
            total = self.total_input_tokens + self.total_output_tokens
            if total > 0:
                parts.append(
                    f"[$text-muted]in:{_fmt(self.total_input_tokens)} "
                    f"out:{_fmt(self.total_output_tokens)}[/]"
                )
            if self.total_cost > 0:
                cost_str = (
                    f"${self.total_cost:.4f}"
                    if self.total_cost < 0.01
                    else f"${self.total_cost:.2f}"
                )
                parts.append(f"[$text-muted]{cost_str}[/]")
            info_text = sep.join(parts)
            # Fill remaining width with a faint rule, using a markup-stripped length.
            available = self._width - _plain_len(info_text) - 3  # 3 = padding + gap
            if available > 2:
                separator = " " + "─" * available
                content.update(f"{info_text}[$text-muted]{separator}[/]")
            else:
                content.update(info_text)
