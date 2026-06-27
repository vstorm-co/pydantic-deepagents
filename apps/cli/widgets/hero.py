"""Welcome hero — a clean, minimalist landing banner with a live ambient band.

Shown once at session start in place of a plain text welcome. A small accent
mark, the wordmark, a tagline, the animated :class:`AmbientBand`, optional
project context, and a one-line hint. Designed to read as calm and premium:
one moving element (the band), everything else still.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Static

from apps.cli.widgets.ambient import AmbientBand

_TAGLINE = "deep agents · orchestrated end to end"
_HINT = "Type to begin    [b]/[/b] commands    [b]@[/b] files    [b]?[/b] help"


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
    HeroBanner .hero-titlerow {
        height: 1;
        width: 1fr;
    }
    HeroBanner .hero-mark {
        width: 2;
        color: $accent;
        text-style: bold;
    }
    HeroBanner .hero-title {
        width: auto;
        text-style: bold;
        color: $foreground;
    }
    HeroBanner .hero-version {
        width: 1fr;
        color: $text-muted;
        padding: 0 0 0 2;
    }
    HeroBanner .hero-tagline {
        color: $text-muted;
        padding: 0 0 0 2;
    }
    HeroBanner .hero-band {
        padding: 1 0 1 2;
    }
    HeroBanner .hero-context {
        color: $text-muted;
        padding: 0 0 0 2;
    }
    HeroBanner .hero-hint {
        color: $text-muted;
        padding: 0 0 0 2;
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

    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal(classes="hero-titlerow"):
                yield Static("◆", classes="hero-mark")
                yield Static("pydantic-deep", classes="hero-title")
                yield Static(f"v{self._version}" if self._version else "", classes="hero-version")
            yield Static(_TAGLINE, classes="hero-tagline")
            yield AmbientBand(count=18, classes="hero-band")
            if self._context_lines:
                yield Static("   ".join(self._context_lines), classes="hero-context")
            yield Static(_HINT, classes="hero-hint")


__all__ = ["HeroBanner"]
