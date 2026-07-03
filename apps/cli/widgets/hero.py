"""Welcome hero — an ASCII wordmark, a live ambient band, and a rotating tip.

Shown once at session start in place of a plain text welcome: the magenta
``pydantic`` wordmark, a tagline, the animated :class:`AmbientBand`, optional
project context, and a tip that cycles every few seconds.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Static

from apps.cli.widgets.ambient import AmbientBand

# ANSI-shadow wordmark. Kept as one block so a narrow terminal can swap it for
# the compact mark below.
_WORDMARK = r"""██████╗ ██╗   ██╗██████╗  █████╗ ███╗   ██╗████████╗██╗ ██████╗
██╔══██╗╚██╗ ██╔╝██╔══██╗██╔══██╗████╗  ██║╚══██╔══╝██║██╔════╝
██████╔╝ ╚████╔╝ ██║  ██║███████║██╔██╗ ██║   ██║   ██║██║
██╔═══╝   ╚██╔╝  ██║  ██║██╔══██║██║╚██╗██║   ██║   ██║██║
██║        ██║   ██████╔╝██║  ██║██║ ╚████║   ██║   ██║╚██████╗
╚═╝        ╚═╝   ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝   ╚═╝ ╚═════╝"""
_WORDMARK_WIDTH = 63

_HINT = "Type to begin    [b]/[/b] commands    [b]@[/b] files    [b]?[/b] help"
_TIP_INTERVAL = 9.0  # seconds between tip rotations


class HeroBanner(Widget):
    """Animated welcome banner mounted at the top of the message list."""

    DEFAULT_CSS = """
    HeroBanner {
        height: auto;
        padding: 1 2 1 2;
    }
    HeroBanner > Vertical {
        height: auto;
    }
    HeroBanner .hero-wordmark {
        color: #e5238f;
        text-style: bold;
        height: auto;
        padding: 0 0 1 0;
    }
    HeroBanner .hero-band {
        padding: 1 0 1 0;
    }
    HeroBanner .hero-context {
        color: $text-muted;
    }
    HeroBanner .hero-tip {
        color: $text-muted;
        padding: 1 0 0 0;
    }
    HeroBanner .hero-hint {
        color: $text-muted;
    }
    """

    def __init__(
        self,
        *,
        version: str = "",
        context_lines: list[str] | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._version = version
        self._context_lines = [ln for ln in (context_lines or []) if ln.strip()]
        self._tips: list[str] = []
        self._tip_idx = 0

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(_WORDMARK, classes="hero-wordmark", id="hero-wordmark")
            yield AmbientBand(count=18, classes="hero-band")
            if self._context_lines:
                yield Static("   ".join(self._context_lines), classes="hero-context")
            yield Static("", classes="hero-tip", id="hero-tip")
            yield Static(_HINT, classes="hero-hint")

    def on_mount(self) -> None:
        from apps.cli.tips import random_tip, tip_cycle

        self._tips = tip_cycle(random_tip())
        self._show_tip()
        self.set_interval(_TIP_INTERVAL, self._next_tip)
        self._fit_wordmark()

    def on_resize(self, _event: object) -> None:
        self._fit_wordmark()

    def _fit_wordmark(self) -> None:
        # Swap the big wordmark for a compact mark when the terminal is too narrow.
        from contextlib import suppress

        from textual.css.query import NoMatches

        with suppress(NoMatches):
            wm = self.query_one("#hero-wordmark", Static)
            if self.size.width and self.size.width < _WORDMARK_WIDTH + 4:
                wm.update("[b]◆ pydantic-deepagents[/b]")
            else:
                wm.update(_WORDMARK)

    def _show_tip(self) -> None:
        from contextlib import suppress

        from textual.css.query import NoMatches

        if not self._tips:
            return
        with suppress(NoMatches):
            tip = self._tips[self._tip_idx % len(self._tips)]
            self.query_one("#hero-tip", Static).update(f"[b]Tip[/b]  {tip}")

    def _next_tip(self) -> None:
        self._tip_idx += 1
        self._show_tip()


__all__ = ["HeroBanner"]
