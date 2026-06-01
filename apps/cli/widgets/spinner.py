"""Shared braille spinner — one frame set, one tick rate, one tiny state machine.

Three widgets need a spinner while something is "in flight":

- :class:`~apps.cli.widgets.header.DeepHeader` — global streaming indicator
- :class:`~apps.cli.widgets.tool_call.ToolCallWidget` — per-tool-call pending state
- :class:`~apps.cli.widgets.fork_overview.ForkOverviewWidget` — per-fork running state

Each owns its own `set_interval` timer (because gating and start/stop
semantics differ), but the *frame set*, *tick rate*, and *advance logic*
are identical — and were previously duplicated three times. This module
hosts all three.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from textual.timer import Timer

_SPINNER_TICK_S: float = 1 / 12


class _SupportsSetInterval(Protocol):
    """Anything Textual-shaped enough to schedule a tick — `Widget`, etc."""

    def set_interval(self, interval: float, callback: Callable[[], None]) -> Timer: ...


BRAILLE_SPINNER_FRAMES: tuple[str, ...] = (
    "⠋",
    "⠙",
    "⠹",
    "⠸",
    "⠼",
    "⠴",
    "⠦",
    "⠧",
    "⠇",
    "⠏",
)


class Spinner:
    """Tiny stateful spinner — one instance per widget.

    Owns the frame index AND the elapsed-seconds accumulator. The widget
    never sees the tick rate: it calls :meth:`start_on` once to hook the
    spinner into its Textual loop, then reads :attr:`frame` and
    :attr:`elapsed` during render.

    Example::

        class MyWidget(Widget):
            def __init__(self) -> None:
                super().__init__()
                self._spinner = Spinner()

            def on_mount(self) -> None:
                self._spinner.start_on(
                    self,
                    gate=lambda: self.is_busy,
                    on_advance=self._refresh,
                )

            def _refresh(self) -> None:
                # use self._spinner.frame and self._spinner.elapsed
                ...
    """

    __slots__ = ("_index", "_elapsed_ticks")

    def __init__(self) -> None:
        self._index = 0
        self._elapsed_ticks = 0

    @property
    def frame(self) -> str:
        """Current frame — call from render code."""
        return BRAILLE_SPINNER_FRAMES[self._index]

    @property
    def elapsed(self) -> float:
        """Seconds since the last :meth:`reset` — accumulated tick-by-tick.

        Approximate; assumes the timer fires reliably. For exact wall-clock
        duration (e.g. on tool-call completion), callers should record their
        own `time.monotonic()` and reuse that — the spinner's elapsed is
        intended for the visible "X.Xs running" indicator only.
        """
        return self._elapsed_ticks * _SPINNER_TICK_S

    def tick(self) -> str:
        """Advance to the next frame, bump elapsed, return the new frame."""
        self._index = (self._index + 1) % len(BRAILLE_SPINNER_FRAMES)
        self._elapsed_ticks += 1
        return self.frame

    def reset(self) -> None:
        """Rewind to the first frame and zero elapsed — call on busy-state restart."""
        self._index = 0
        self._elapsed_ticks = 0

    def start_on(
        self,
        widget: _SupportsSetInterval,
        *,
        gate: Callable[[], bool],
        on_advance: Callable[[], None] | None = None,
    ) -> Timer:
        """Schedule a tick on `widget`'s Textual loop.

        Each fired tick checks `gate()`; if True, advances the spinner and
        calls `on_advance` (typically a re-render). The timer keeps firing
        unconditionally — gating happens inside the callback, so the widget
        doesn't have to stop/restart on busy-state transitions.

        Returns the Textual :class:`Timer` so callers that *do* want to
        stop the timer (e.g. when the widget is hidden, like
        `ForkOverviewWidget`) can call `.stop()` on the handle.
        """

        def _tick() -> None:
            if not gate():
                return
            self.tick()
            if on_advance is not None:
                on_advance()

        return widget.set_interval(_SPINNER_TICK_S, _tick)


__all__ = ["BRAILLE_SPINNER_FRAMES", "Spinner"]
