"""Left session sidebar — a calm, Tau-style at-a-glance panel.

Shows the wordmark and a few labelled sections (session, context, workspace)
drawn from the live app state. Borderless except for a faint right rule that
separates it from the conversation. Purely informational; no input.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

# Project docs surfaced under "context", in priority order.
_CONTEXT_FILES = ("DEEP.md", "AGENTS.md", "CLAUDE.md", "SOUL.md")

_LABEL_W = 9  # label column width for the key/value rows


def _row(label: str, value: str) -> str:
    """A dim label + value row, label padded to a fixed column."""
    return f"[$text-muted]{label.ljust(_LABEL_W)}[/][$foreground]{value}[/]"


def _header(text: str) -> str:
    return f"[$text-muted b]{text}[/]"


class SessionSidebar(Widget):
    """Left-docked session/context panel."""

    DEFAULT_CSS = """
    SessionSidebar {
        width: 30;
        padding: 1 2 0 2;
        border-right: tall $panel;
        background: $surface;
    }
    SessionSidebar.hidden {
        display: none;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(id="sidebar-content")

    def on_mount(self) -> None:
        self.refresh_session()

    def refresh_session(self) -> None:
        """Re-read app state and repaint the sidebar."""
        try:
            content = self.query_one("#sidebar-content", Static)
        except Exception:
            return

        app = self.app
        model = str(getattr(app, "model_name", "") or "")
        provider = model.split(":", 1)[0] if ":" in model else ""
        short_model = model.split(":", 1)[1] if ":" in model else model
        fallback = str(getattr(app, "fallback_model_name", "") or "")
        thinking = self._thinking_level()
        working_dir = str(getattr(app, "working_dir", "."))
        branch = str(getattr(app, "_branch", "") or "")

        lines: list[str] = ["[$accent b]◆[/] [$foreground b]pydantic-deep[/]", ""]

        lines.append(_header("session"))
        if provider:
            lines.append(_row("provider", provider))
        if short_model:
            lines.append(_row("model", short_model))
        if thinking:
            lines.append(_row("thinking", thinking))
        if fallback:
            fb = fallback.split(":", 1)[1] if ":" in fallback else fallback
            lines.append(_row("fallback", fb))

        context = self._context_files(Path(working_dir))
        if context:
            lines += ["", _header("context")]
            lines += [f"[$accent]•[/] [$foreground]{name}[/]" for name in context]

        lines += ["", _header("workspace")]
        lines.append(f"[$foreground]{self._short_path(working_dir)}[/]")
        if branch:
            lines.append(f"[$text-muted]⎇ {branch}[/]")

        content.update("\n".join(lines))

    @staticmethod
    def _thinking_level() -> str:
        try:
            from apps.cli.config import load_config

            return str(load_config().thinking_effort or "")
        except Exception:
            return ""

    @staticmethod
    def _context_files(root: Path) -> list[str]:
        found: list[str] = []
        for name in _CONTEXT_FILES:
            try:
                if (root / name).is_file():
                    found.append(name)
            except Exception:
                pass
        return found

    @staticmethod
    def _short_path(path: str) -> str:
        """Render a path with ~ for home, truncated to fit the sidebar."""
        try:
            p = Path(path)
            home = Path.home()
            text = f"~/{p.relative_to(home)}" if p.is_relative_to(home) else str(p)
        except Exception:
            text = path
        return text if len(text) <= 24 else "…" + text[-23:]


__all__ = ["SessionSidebar"]
