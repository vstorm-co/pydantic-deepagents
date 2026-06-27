"""Tests for the Monitor (watch & react) feature."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from pydantic_ai_backends import LocalBackend, ensure_async

from pydantic_deep.features.monitoring import (
    MonitorEvent,
    MonitorManager,
    create_monitor_toolset,
)


def _async_backend(tmp_path: Path) -> Any:
    return ensure_async(LocalBackend(root_dir=str(tmp_path)))


async def _drain_until_done(events: list[MonitorEvent], timeout: float = 5.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if any(not e.running for e in events):
            return
        await asyncio.sleep(0.02)
    raise AssertionError("monitor did not finish in time")


class TestMonitorManager:
    async def test_emits_lines_and_exit_event(self, tmp_path: Path) -> None:
        events: list[MonitorEvent] = []

        async def sink(e: MonitorEvent) -> None:
            events.append(e)

        mgr = MonitorManager(_async_backend(tmp_path), on_event=sink, poll_interval=0.05)
        info = await mgr.start("echo alpha; sleep 0.2; echo beta", label="t")
        assert info.monitor_id == "mon_1"
        assert info.running is True

        await _drain_until_done(events)
        seen = [ln for e in events for ln in e.lines]
        assert "alpha" in seen
        assert "beta" in seen
        # A final, non-running event signals completion.
        assert any(not e.running and e.exit_code == 0 for e in events)
        await mgr.stop_all()

    async def test_reports_stderr_lines(self, tmp_path: Path) -> None:
        events: list[MonitorEvent] = []

        async def sink(e: MonitorEvent) -> None:
            events.append(e)

        mgr = MonitorManager(_async_backend(tmp_path), on_event=sink, poll_interval=0.05)
        # Writes to stderr (and a touch of stdout) — both streams are watched.
        await mgr.start("echo out-line; echo err-line >&2; sleep 0.2", label="s")
        await _drain_until_done(events)
        seen = [ln for e in events for ln in e.lines]
        assert "err-line" in seen
        await mgr.stop_all()

    async def test_match_filter_only_reports_matches(self, tmp_path: Path) -> None:
        events: list[MonitorEvent] = []

        async def sink(e: MonitorEvent) -> None:
            if e.lines:
                events.append(e)

        mgr = MonitorManager(_async_backend(tmp_path), on_event=sink, poll_interval=0.05)
        await mgr.start(
            "echo ok-one; echo ERROR-boom; echo ok-two; sleep 0.1",
            label="errs",
            match="ERROR",
        )
        await asyncio.sleep(0.6)
        reported = [ln for e in events for ln in e.lines]
        assert "ERROR-boom" in reported
        assert "ok-one" not in reported
        await mgr.stop_all()

    async def test_invalid_regex_falls_back_to_literal(self, tmp_path: Path) -> None:
        events: list[MonitorEvent] = []

        async def sink(e: MonitorEvent) -> None:
            if e.lines:
                events.append(e)

        mgr = MonitorManager(_async_backend(tmp_path), on_event=sink, poll_interval=0.05)
        # "[oops" is invalid regex → treated as a literal substring.
        await mgr.start("echo has-[oops-here; echo nope; sleep 0.1", match="[oops")
        await asyncio.sleep(0.6)
        reported = [ln for e in events for ln in e.lines]
        assert any("[oops" in ln for ln in reported)
        assert "nope" not in reported
        await mgr.stop_all()

    async def test_list_and_stop(self, tmp_path: Path) -> None:
        mgr = MonitorManager(_async_backend(tmp_path), poll_interval=0.05)
        info = await mgr.start("sleep 30", label="long")
        listed = mgr.list_monitors()
        assert len(listed) == 1 and listed[0].running is True and listed[0].label == "long"
        assert await mgr.stop(info.monitor_id) is True
        assert mgr.list_monitors() == []
        assert await mgr.stop("nope") is False

    async def test_stop_all_clears(self, tmp_path: Path) -> None:
        mgr = MonitorManager(_async_backend(tmp_path), poll_interval=0.05)
        await mgr.start("sleep 30")
        await mgr.start("sleep 30")
        assert len(mgr.list_monitors()) == 2
        await mgr.stop_all()
        assert mgr.list_monitors() == []

    async def test_set_sink_replaces_callback(self, tmp_path: Path) -> None:
        seen: list[MonitorEvent] = []

        async def sink(e: MonitorEvent) -> None:
            seen.append(e)

        mgr = MonitorManager(_async_backend(tmp_path), poll_interval=0.05)
        mgr.set_sink(sink)  # wired after construction
        await mgr.start("echo wired; sleep 0.1")
        await asyncio.sleep(0.5)
        assert any("wired" in ln for e in seen for ln in e.lines)
        await mgr.stop_all()

    async def test_recent_events_known_and_unknown(self, tmp_path: Path) -> None:
        mgr = MonitorManager(_async_backend(tmp_path), poll_interval=0.05)
        info = await mgr.start("echo hi; sleep 0.1")
        await asyncio.sleep(0.4)
        assert mgr.recent_events(info.monitor_id)  # known → has events
        assert mgr.recent_events("nope") == []  # unknown → empty
        await mgr.stop_all()

    async def test_stop_monitor_without_task(self, tmp_path: Path) -> None:
        # Defensive: a monitor whose drain task was never set still tears down.
        from pydantic_deep.features.monitoring.manager import _Monitor

        mgr = MonitorManager(_async_backend(tmp_path), poll_interval=0.05)
        handle = await mgr._backend.execute_background("sleep 30")
        mon = _Monitor(
            monitor_id="mon_x",
            label="x",
            command="sleep 30",
            shell_id=handle.shell_id,
            matcher=None,
            match_str=None,
            task=None,
        )
        mgr._monitors["mon_x"] = mon
        assert await mgr.stop("mon_x") is True
        assert mgr.list_monitors() == []


@dataclass
class _Deps:
    backend: Any
    message_queue: Any = None
    monitor_manager: Any = None


@dataclass
class _FakeQueue:
    steered: list[str] = field(default_factory=list)

    async def steer(self, content: str, **_: Any) -> None:
        self.steered.append(content)


def _ctx(deps: _Deps) -> RunContext[Any]:
    return RunContext(deps=deps, model=TestModel(), usage=RunUsage())


class TestMonitorToolset:
    async def test_tools_registered(self) -> None:
        ts = create_monitor_toolset()
        for name in ("start_monitor", "list_monitors", "stop_monitor"):
            assert name in ts.tools

    async def test_no_background_backend_errors(self) -> None:
        ts = create_monitor_toolset()
        # Every tool reports the same error when the backend can't run bg procs.
        for name, args in (
            ("start_monitor", ("sleep 1",)),
            ("list_monitors", ()),
            ("stop_monitor", ("mon_1",)),
        ):
            deps = _Deps(backend=object())  # no execute_background
            out = await ts.tools[name].function(_ctx(deps), *args)
            assert "background-capable backend" in out

    async def test_start_pushes_events_to_queue(self, tmp_path: Path) -> None:
        ts = create_monitor_toolset()
        queue = _FakeQueue()
        deps = _Deps(backend=_async_backend(tmp_path), message_queue=queue)
        started = await ts.tools["start_monitor"].function(
            _ctx(deps), "echo hello-world; sleep 0.1", "greeter"
        )
        assert "Started monitor mon_1" in started
        # Wait for the watch loop to drain output into the queue (react path).
        for _ in range(50):
            await asyncio.sleep(0.05)
            if queue.steered:
                break
        assert any("hello-world" in m and "monitor:greeter" in m for m in queue.steered)
        await deps.monitor_manager.stop_all()

    async def test_list_and_stop_via_tools(self, tmp_path: Path) -> None:
        ts = create_monitor_toolset()
        deps = _Deps(backend=_async_backend(tmp_path))
        await ts.tools["start_monitor"].function(_ctx(deps), "sleep 30", "svc")
        listing = await ts.tools["list_monitors"].function(_ctx(deps))
        assert "mon_1" in listing and "svc" in listing
        stopped = await ts.tools["stop_monitor"].function(_ctx(deps), "mon_1")
        assert "Stopped monitor mon_1" in stopped
        empty = await ts.tools["list_monitors"].function(_ctx(deps))
        assert "No active monitors" in empty
