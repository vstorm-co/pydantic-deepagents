"""Loading overlay shown while the judge LLM evaluates branches.

Pushed by :func:`apps.cli.commands._dispatch_merge` for any non-``manual``
strategy. The screen owns the ``resolve()`` coroutine, runs it as an
``asyncio.Task``, ticks a braille spinner while waiting, and dismisses
itself with the :class:`~pydantic_deep.types.ResolveOutcome` on success or
with the raised :class:`Exception` on failure. The caller branches on
``isinstance(result, Exception)``.

Pressing :kbd:`Escape` cancels the judge task and dismisses with
:class:`JudgeAborted`, giving the user an escape hatch when an LLM call
stalls (network 5xx, provider timeout).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from apps.cli.widgets.spinner import Spinner

if TYPE_CHECKING:
    from pydantic_deep.toolsets.forking.coordinator import ForkCoordinator
    from pydantic_deep.types import MergeStrategy


logger = logging.getLogger(__name__)


class JudgeAborted(Exception):
    """Raised inside the screen's dismiss path when the user hits Escape.

    The caller's ``isinstance(result, Exception)`` branch surfaces this as
    a notification and falls back to the manual picker — same handling as
    any other judge failure, but with a clearer message.
    """


class JudgeLoadingScreen(ModalScreen["Any | Exception"]):
    """Animated spinner overlay while the judge LLM is running.

    Dismisses with the :class:`~pydantic_deep.types.ResolveOutcome` on
    success or with an :class:`Exception` on failure / user abort.
    """

    DEFAULT_CSS = """
    JudgeLoadingScreen {
        align: center middle;
    }
    JudgeLoadingScreen > #judge-box {
        width: 50;
        height: 5;
        border: tall $primary;
        background: $surface;
        padding: 1 2;
        align: center middle;
    }
    JudgeLoadingScreen > #judge-box > #judge-label {
        text-align: center;
        width: 100%;
    }
    """

    BINDINGS = [
        Binding("escape", "abort", "Abort"),
    ]

    def __init__(self, coordinator: ForkCoordinator, strategy: MergeStrategy) -> None:
        super().__init__()
        self._coordinator = coordinator
        self._strategy = strategy
        self._spinner = Spinner()
        self._task: asyncio.Task[Any] | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="judge-box"):
            yield Static("⚖ Judge evaluating…  [dim](esc to abort)[/dim]", id="judge-label")

    def on_mount(self) -> None:
        self._spinner.start_on(
            self,
            gate=lambda: True,
            on_advance=self._refresh,
        )
        self._task = asyncio.create_task(self._run())

    def _refresh(self) -> None:
        elapsed = int(self._spinner.elapsed)
        label = self.query_one("#judge-label", Static)
        label.update(
            f"{self._spinner.frame} Judge evaluating… {elapsed}s  [dim](esc to abort)[/dim]"
        )

    async def _run(self) -> None:
        try:
            outcome = await self._coordinator.resolve(self._strategy)
            self.dismiss(outcome)
        except asyncio.CancelledError:
            # Cancellation comes from action_abort below — surface as a distinct
            # exception class so the caller can format a clearer notification.
            # We swallow CancelledError here; the screen is the boundary.
            self.dismiss(JudgeAborted("Judge aborted by user."))
        except Exception as exc:
            logger.error(
                "Judge resolve failed: %s: %s",
                type(exc).__name__,
                exc,
                exc_info=True,
            )
            self.dismiss(exc)

    def action_abort(self) -> None:
        """Cancel the in-flight judge task; ``_run`` dismisses with :class:`JudgeAborted`."""
        if self._task is not None and not self._task.done():
            self._task.cancel()


__all__ = ["JudgeAborted", "JudgeLoadingScreen"]
