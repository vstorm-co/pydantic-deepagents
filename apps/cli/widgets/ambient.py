"""Ambient animated squares — a subtle pulsing/floating motion band.

A one-line row of squares that breathe in a slow traveling sine wave. It is
purely content-driven (no layout animation): every tick recomputes a per-square
brightness from ``sin(phase - i * spread)`` and blends a colour from a dim base
toward the active theme's accent. Reads theme colours live, so it follows
`/theme` changes, and pauses itself whenever it is not on screen.

Used by the welcome hero and the idle indicator to give the TUI a calm,
premium "alive but quiet" feel.
"""

from __future__ import annotations

import math

from textual.app import ComposeResult
from textual.color import Color
from textual.widget import Widget
from textual.widgets import Static

#: ~20 fps — smooth without being busy. One shared cadence for all ambients.
_TICK_S: float = 1 / 20

#: Fallback palette when the active theme can't be read (e.g. headless tests).
_FALLBACK_DIM = "#1b2a24"
_FALLBACK_BRIGHT = "#6ee7b7"


def _smoothstep(t: float) -> float:
    """Ease 0..1 with a smoothstep curve so the pulse 'pops' gently at the peak."""
    return t * t * (3.0 - 2.0 * t)


class AmbientBand(Widget):
    """A one-line band of squares that pulse in a slow travelling wave."""

    DEFAULT_CSS = """
    AmbientBand {
        height: 1;
        width: auto;
    }
    """

    def __init__(
        self,
        *,
        count: int = 16,
        glyph: str = "■",
        spread: float = 0.55,
        speed: float = 0.16,
        floor: float = 0.18,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        """Create an ambient band.

        Args:
            count: Number of squares.
            glyph: Character drawn for each square.
            spread: Phase offset between adjacent squares (wave tightness).
            speed: Phase advance per tick (wave speed).
            floor: Minimum brightness (0..1) so dim squares stay faintly visible.
            id: Optional widget id.
            classes: Optional CSS classes.
        """
        super().__init__(id=id, classes=classes)
        self._count = count
        self._glyph = glyph
        self._spread = spread
        self._speed = speed
        self._floor = floor
        self._phase = 0.0

    def compose(self) -> ComposeResult:
        yield Static(id="ambient-content")

    def on_mount(self) -> None:
        self.set_interval(_TICK_S, self._advance)
        self._render()

    def _advance(self) -> None:
        # Pause the wave whenever the band isn't actually visible — cheap idle.
        if not self.display:
            return
        self._phase += self._speed
        self._render()

    def _palette(self) -> tuple[Color, Color]:
        """Return (dim, bright) colours, following the active theme when possible."""
        dim = Color.parse(_FALLBACK_DIM)
        bright = Color.parse(_FALLBACK_BRIGHT)
        theme = getattr(self.app, "current_theme", None)
        if theme is not None:
            try:
                bright = Color.parse(theme.accent or theme.primary)
                base = Color.parse(theme.background) if theme.background else dim
                dim = base.blend(bright, 0.16)
            except Exception:
                pass
        return dim, bright

    def _render(self) -> None:
        try:
            content = self.query_one("#ambient-content", Static)
        except Exception:
            return  # not composed yet
        dim, bright = self._palette()
        cells: list[str] = []
        for i in range(self._count):
            wave = (math.sin(self._phase - i * self._spread) + 1.0) / 2.0
            t = self._floor + (1.0 - self._floor) * _smoothstep(wave)
            color = dim.blend(bright, t)
            cells.append(f"[{color.hex}]{self._glyph}[/]")
        content.update(" ".join(cells))


__all__ = ["AmbientBand"]
