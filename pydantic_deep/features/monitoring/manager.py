"""MonitorManager — runs background watches and pushes new output to a sink.

A *monitor* is a long-lived command (a log tail, a CI poller, a file watcher,
a dev server) whose output the agent wants to *react* to without polling. The
manager runs the command in the workspace with its output going to a log file
there, reads what is new on an interval, filters new lines by an optional
regex, and emits a
:class:`MonitorEvent` for each batch through an ``on_event`` sink. The default
wiring points that sink at the agent's :class:`MessageQueue` so each event is
delivered into the conversation (see ``create_monitor_toolset``).

This is the engine behind Claude Code's ``Monitor`` tool. A Pydantic AI
workspace has no background processes of its own, so a monitor is a command
run as a task: stopping the monitor cancels it, and a workspace stops a
cancelled command together with everything it started.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import shlex
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic_deep.features.monitoring.types import MonitorEvent, MonitorInfo

if TYPE_CHECKING:
    from pydantic_ai.workspaces import CommandResult, Workspace

#: Sink invoked for every emitted event (the "react" hook).
EventSink = Callable[[MonitorEvent], Awaitable[None]]

_DEFAULT_POLL_INTERVAL = 1.0
_MAX_RECENT_EVENTS = 20

LOG_DIR = ".deep/monitors"
"""Where each monitor's output is written, relative to the workspace's working directory."""


@dataclass
class _Monitor:
    monitor_id: str
    label: str
    command: str
    log_path: str
    process: asyncio.Task[CommandResult]
    matcher: re.Pattern[str] | None
    match_str: str | None
    events: deque[MonitorEvent] = field(default_factory=lambda: deque(maxlen=_MAX_RECENT_EVENTS))
    task: asyncio.Task[None] | None = None
    running: bool = True
    exit_code: int | None = None
    event_count: int = 0
    read_offset: int = 0


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
        workspace: The workspace monitors run in. It must run commands.
        on_event: Async callback invoked for each :class:`MonitorEvent`. When
            omitted, events are still buffered (visible via :meth:`list`).
        poll_interval: Seconds between output polls.
    """

    def __init__(
        self,
        workspace: Workspace,
        *,
        on_event: EventSink | None = None,
        poll_interval: float = _DEFAULT_POLL_INTERVAL,
    ) -> None:
        self._workspace = workspace
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
        """Start ``command`` in the workspace and begin watching its output."""
        self._counter += 1
        monitor_id = f"mon_{self._counter}"
        log_path = f"{LOG_DIR}/{monitor_id}.log"
        await self._workspace.make_dir(LOG_DIR)
        # `exec` sends the rest of the script's output to the log, so the
        # model's command runs exactly as it wrote it, compound or not.
        script = f"exec > {shlex.quote(log_path)} 2>&1\n{command}"
        mon = _Monitor(
            monitor_id=monitor_id,
            label=label or monitor_id,
            command=command,
            log_path=log_path,
            process=asyncio.create_task(self._workspace.run(script, shell=True)),
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
        for task in (mon.task, mon.process):
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task

    async def _new_lines(self, mon: _Monitor) -> list[str]:
        """The non-blank lines written to the log since the last read."""
        try:
            data = await self._workspace.read_bytes(mon.log_path)
        except FileNotFoundError:
            return []
        new, mon.read_offset = data[mon.read_offset :], len(data)
        return [ln for ln in new.decode("utf-8", errors="replace").splitlines() if ln.strip()]

    async def _watch(self, mon: _Monitor) -> None:
        """Read new output on an interval and emit events until the command exits."""
        try:
            while True:
                await asyncio.sleep(self._poll_interval)
                finished = mon.process.done()
                lines = await self._new_lines(mon)
                matched = [ln for ln in lines if mon.matcher is None or mon.matcher.search(ln)]
                if matched:
                    await self._emit(
                        mon,
                        MonitorEvent(mon.monitor_id, mon.label, mon.command, matched, True, None),
                    )
                if finished:
                    mon.running = False
                    # A command that could not run - the workspace gone, no
                    # commands - has no exit code to report.
                    result = None if mon.process.exception() else mon.process.result()
                    mon.exit_code = result.exit_code if result is not None else None
                    await self._emit(
                        mon,
                        MonitorEvent(
                            mon.monitor_id, mon.label, mon.command, [], False, mon.exit_code
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
