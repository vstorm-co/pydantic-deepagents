"""MonitorManager — runs background watches and pushes new output to a sink.

A *monitor* is a long-lived command (a log tail, a CI poller, a file watcher,
a dev server) whose output the agent wants to *react* to without polling. The
manager spawns the command via the backend's background-process support, drains
its output on an interval, filters new lines by an optional regex, and emits a
:class:`MonitorEvent` for each batch through an ``on_event`` sink. The default
wiring points that sink at the agent's :class:`MessageQueue` so each event is
delivered into the conversation (see ``create_monitor_toolset``).

This is the engine behind Claude Code's ``Monitor`` tool, built on our own
background-process substrate (``execute_background`` / ``read_background``).
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic_deep.features.monitoring.types import MonitorEvent, MonitorInfo

#: Sink invoked for every emitted event (the "react" hook).
EventSink = Callable[[MonitorEvent], Awaitable[None]]

_DEFAULT_POLL_INTERVAL = 1.0
_MAX_RECENT_EVENTS = 20


@dataclass
class _Monitor:
    monitor_id: str
    label: str
    command: str
    shell_id: str
    matcher: re.Pattern[str] | None
    match_str: str | None
    events: deque[MonitorEvent] = field(default_factory=lambda: deque(maxlen=_MAX_RECENT_EVENTS))
    task: asyncio.Task[None] | None = None
    running: bool = True
    exit_code: int | None = None
    event_count: int = 0


def _compile(match: str | None) -> re.Pattern[str] | None:
    """Compile ``match`` as a regex, falling back to a literal substring match."""
    if not match:
        return None
    try:
        return re.compile(match)
    except re.error:
        return re.compile(re.escape(match))


class MonitorManager:
    """Owns active monitors and their background drain loops.

    Args:
        backend: An async background-capable backend (exposes
            ``execute_background`` / ``read_background`` / ``kill_background``).
        on_event: Async callback invoked for each :class:`MonitorEvent`. When
            omitted, events are still buffered (visible via :meth:`list`).
        poll_interval: Seconds between output polls.
    """

    def __init__(
        self,
        backend: Any,
        *,
        on_event: EventSink | None = None,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
    ) -> None:
        self._backend = backend
        self._on_event = on_event
        self._poll_interval = poll_interval
        self._monitors: dict[str, _Monitor] = {}
        self._counter = 0

    def set_sink(self, on_event: EventSink | None) -> None:
        """Set or replace the react sink (used when wiring after construction)."""
        self._on_event = on_event

    async def start(
        self, command: str, *, label: str | None = None, match: str | None = None
    ) -> MonitorInfo:
        """Spawn ``command`` in the background and begin watching its output."""
        handle = await self._backend.execute_background(command)
        self._counter += 1
        monitor_id = f"mon_{self._counter}"
        mon = _Monitor(
            monitor_id=monitor_id,
            label=label or monitor_id,
            command=command,
            shell_id=handle.shell_id,
            matcher=_compile(match),
            match_str=match,
        )
        self._monitors[monitor_id] = mon
        mon.task = asyncio.create_task(self._watch(mon))
        return self._info(mon)

    async def stop(self, monitor_id: str) -> bool:
        """Stop a monitor and kill its process. False if unknown."""
        mon = self._monitors.pop(monitor_id, None)
        if mon is None:
            return False
        await self._teardown(mon)
        return True

    async def stop_all(self) -> None:
        """Stop every monitor (e.g. on session end)."""
        for mon in list(self._monitors.values()):
            await self._teardown(mon)
        self._monitors.clear()

    def list_monitors(self) -> list[MonitorInfo]:
        """Snapshot of all tracked monitors."""
        return [self._info(m) for m in self._monitors.values()]

    def recent_events(self, monitor_id: str) -> list[MonitorEvent]:
        """Buffered recent events for a monitor (empty if unknown)."""
        mon = self._monitors.get(monitor_id)
        return list(mon.events) if mon else []

    # ── internals ────────────────────────────────────────────────────────

    async def _teardown(self, mon: _Monitor) -> None:
        if mon.task is not None:
            mon.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await mon.task
        with contextlib.suppress(Exception):
            await self._backend.kill_background(mon.shell_id)

    async def _watch(self, mon: _Monitor) -> None:
        """Drain new output on an interval and emit events until the process exits."""
        try:
            while True:
                await asyncio.sleep(self._poll_interval)
                out = await self._backend.read_background(mon.shell_id)
                text = out.stdout or ""
                if out.stderr:
                    text = f"{text}\n{out.stderr}" if text else out.stderr
                lines = [ln for ln in text.splitlines() if ln.strip()]
                matched = [ln for ln in lines if mon.matcher is None or mon.matcher.search(ln)]
                if matched:
                    await self._emit(
                        mon,
                        MonitorEvent(
                            mon.monitor_id, mon.label, mon.command, matched, True, out.exit_code
                        ),
                    )
                if not out.running:
                    mon.running = False
                    mon.exit_code = out.exit_code
                    await self._emit(
                        mon,
                        MonitorEvent(
                            mon.monitor_id, mon.label, mon.command, [], False, out.exit_code
                        ),
                    )
                    return
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - defensive: never let a watch crash loudly
            mon.running = False

    async def _emit(self, mon: _Monitor, event: MonitorEvent) -> None:
        mon.events.append(event)
        if event.lines:
            mon.event_count += 1
        if self._on_event is not None:
            with contextlib.suppress(Exception):
                await self._on_event(event)

    def _info(self, mon: _Monitor) -> MonitorInfo:
        last = mon.events[-1].lines if mon.events else []
        return MonitorInfo(
            monitor_id=mon.monitor_id,
            label=mon.label,
            command=mon.command,
            running=mon.running,
            match=mon.match_str,
            event_count=mon.event_count,
            exit_code=mon.exit_code,
            last_lines=list(last),
        )
