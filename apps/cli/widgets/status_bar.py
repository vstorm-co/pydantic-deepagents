"""Fixed bottom status bar showing cost, context usage, todos, model."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


def _context_bar(pct: float, width: int = 10) -> str:
    """Render a progress bar like ████░░░░░░ 73%."""
    filled = int(pct * width)
    empty = width - filled
    if pct >= 0.9:
        color = "red"
    elif pct >= 0.7:
        color = "yellow"
    else:
        color = "green"
    bar = f"[{color}]{'█' * filled}[/{color}]{'░' * empty}"
    return f"{bar} {pct:.0%}"


def _format_tokens(count: int) -> str:
    """Format token count: 500, 1.2K, 150K."""
    if count < 1000:
        return str(count)
    elif count < 100_000:
        return f"{count / 1000:.1f}K"
    else:
        return f"{count // 1000}K"


class StatusBar(Widget):
    """Fixed one-line status bar above the input area."""

    DEFAULT_CSS = """
    StatusBar {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """

    approve_mode: reactive[str] = reactive("manual")
    active_todos: reactive[int] = reactive(0)
    total_todos: reactive[int] = reactive(0)
    current_cost: reactive[float] = reactive(0.0)
    total_cost: reactive[float] = reactive(0.0)
    context_pct: reactive[float] = reactive(0.0)
    context_current: reactive[int] = reactive(0)
    context_max: reactive[int] = reactive(0)
    total_input_tokens: reactive[int] = reactive(0)
    total_output_tokens: reactive[int] = reactive(0)
    message_count: reactive[int] = reactive(0)
    model_name: reactive[str] = reactive("")

    def compose(self) -> ComposeResult:
        yield Static(id="status-content")

    def on_mount(self) -> None:
        self._refresh_content()

    def watch_approve_mode(self) -> None:
        self._refresh_content()

    def watch_active_todos(self) -> None:
        self._refresh_content()

    def watch_total_todos(self) -> None:
        self._refresh_content()

    def watch_current_cost(self) -> None:
        self._refresh_content()

    def watch_context_pct(self) -> None:
        self._refresh_content()

    def watch_total_input_tokens(self) -> None:
        self._refresh_content()

    def watch_total_output_tokens(self) -> None:
        self._refresh_content()

    def watch_message_count(self) -> None:
        self._refresh_content()

    def watch_model_name(self) -> None:
        self._refresh_content()

    def _refresh_content(self) -> None:
        try:
            content = self.query_one("#status-content", Static)
        except Exception:
            return  # Not yet composed

        parts: list[str] = []

        # Approve mode — always show
        if self.approve_mode == "manual":
            parts.append("[dim]manual[/dim]")
        else:
            parts.append("[green]auto[/green]")

        # Todos
        if self.total_todos > 0:
            parts.append(f"{self.active_todos}/{self.total_todos} todos")

        # Cost — show even small amounts
        if self.current_cost > 0 or self.total_cost > 0:
            # Show total if we have it, otherwise run cost
            cost_val = self.total_cost if self.total_cost > 0 else self.current_cost
            if cost_val < 0.01:
                parts.append(f"${cost_val:.4f}")
            else:
                parts.append(f"${cost_val:.2f}")

        # Token usage — show input/output breakdown
        total_tokens = self.total_input_tokens + self.total_output_tokens
        if total_tokens > 0:
            parts.append(
                f"in:{_format_tokens(self.total_input_tokens)} "
                f"out:{_format_tokens(self.total_output_tokens)}"
            )

        # Context usage — show bar when meaningful
        if self.context_max > 0 and self.context_pct >= 0.05:
            bar = _context_bar(self.context_pct)
            parts.append(bar)

        # Message count — always show
        parts.append(f"{self.message_count} msgs")

        # Model name (shortened) — always show
        if self.model_name:
            short = self.model_name.split(":")[-1] if ":" in self.model_name else self.model_name
            parts.append(f"[dim]{short}[/dim]")

        content.update(" · ".join(parts))
