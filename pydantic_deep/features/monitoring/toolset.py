"""Agent-facing tools for the Monitor (watch & react) feature.

Exposes ``start_monitor`` / ``list_monitors`` / ``stop_monitor``. The manager
is created lazily on first use and stored on ``ctx.deps.monitor_manager``; its
react sink is wired to ``ctx.deps.message_queue`` when present, so each new line
of monitored output is delivered back into the conversation as a steering
message and the agent reacts without polling.
"""

from __future__ import annotations

from typing import Any, cast

from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets.function import FunctionToolset

from pydantic_deep.features.monitoring.manager import EventSink, MonitorManager
from pydantic_deep.features.monitoring.types import MonitorEvent

START_MONITOR_DESCRIPTION = """\
Start watching a long-running command and react to its output as it appears.

Use this for things you want to be told about while you keep working — a build
or test watcher, tailing a log for errors, polling CI or a deploy, watching a
dev server. The command runs in the background and each new line of output is
delivered back to you automatically (you do NOT need to poll). Prefer this over
`execute` for anything that streams output over time or never exits.

Args:
- command: the shell command to run and watch (e.g. `npm run test:watch`).
- label: a short name for this monitor (defaults to its id).
- match: optional regex; only output lines matching it are reported to you
  (e.g. `error|fail|exception` to hear only about failures).

Stop it with `stop_monitor` when you no longer need it."""

LIST_MONITORS_DESCRIPTION = "List active monitors with their status and most recent output line."

STOP_MONITOR_DESCRIPTION = "Stop a monitor by its id and kill the watched process."


def _make_queue_sink(queue: Any) -> EventSink:
    """React sink: deliver each monitor event into the agent's message queue."""

    async def sink(event: MonitorEvent) -> None:
        if event.lines:
            body = "\n".join(event.lines[:20])
            extra = "" if len(event.lines) <= 20 else f"\n… (+{len(event.lines) - 20} more)"
            msg = (
                f"[monitor:{event.label}] {len(event.lines)} new line(s) "
                f"from `{event.command}`:\n{body}{extra}"
            )
        elif not event.running:
            msg = (
                f"[monitor:{event.label}] process `{event.command}` "
                f"exited (code {event.exit_code})."
            )
        else:  # pragma: no cover - no-op event
            return
        await queue.steer(msg, metadata={"source": "monitor", "monitor_id": event.monitor_id})

    return sink


def _manager(ctx: RunContext[Any]) -> MonitorManager | None:
    """Return (lazily creating) the deps-scoped MonitorManager, or None when the
    backend can't run background processes."""
    mgr = getattr(ctx.deps, "monitor_manager", None)
    if mgr is not None:
        return cast("MonitorManager", mgr)
    backend = getattr(ctx.deps, "backend", None)
    if backend is None or not hasattr(backend, "execute_background"):
        return None
    queue = getattr(ctx.deps, "message_queue", None)
    on_event = _make_queue_sink(queue) if queue is not None else None
    mgr = MonitorManager(backend, on_event=on_event)
    ctx.deps.monitor_manager = mgr
    return mgr


def create_monitor_toolset(
    *,
    id: str | None = None,
    descriptions: dict[str, str] | None = None,
) -> FunctionToolset[Any]:
    """Build the monitor toolset (start_monitor / list_monitors / stop_monitor)."""
    descs = descriptions or {}
    toolset: FunctionToolset[Any] = FunctionToolset(id=id or "deep-monitor")

    _no_backend = (
        "Error: monitoring needs a background-capable backend (e.g. LocalBackend); "
        "this session's backend does not support it."
    )

    @toolset.tool(description=descs.get("start_monitor", START_MONITOR_DESCRIPTION))
    async def start_monitor(
        ctx: RunContext[Any], command: str, label: str = "", match: str = ""
    ) -> str:
        mgr = _manager(ctx)
        if mgr is None:
            return _no_backend
        info = await mgr.start(command, label=label or None, match=match or None)
        scope = f" (filter: {match})" if match else ""
        return (
            f"Started monitor {info.monitor_id} '{info.label}' watching `{command}`{scope}. "
            "New output will be reported to you as it appears."
        )

    @toolset.tool(description=descs.get("list_monitors", LIST_MONITORS_DESCRIPTION))
    async def list_monitors(ctx: RunContext[Any]) -> str:
        mgr = _manager(ctx)
        if mgr is None:
            return _no_backend
        monitors = mgr.list_monitors()
        if not monitors:
            return "No active monitors."
        lines = []
        for m in monitors:
            state = "running" if m.running else f"exited({m.exit_code})"
            tail = f"  {m.last_lines[-1][:60]}" if m.last_lines else ""
            lines.append(f"{m.monitor_id} [{state}] {m.label}: `{m.command}`{tail}")
        return "\n".join(lines)

    @toolset.tool(description=descs.get("stop_monitor", STOP_MONITOR_DESCRIPTION))
    async def stop_monitor(ctx: RunContext[Any], monitor_id: str) -> str:
        mgr = _manager(ctx)
        if mgr is None:
            return _no_backend
        stopped = await mgr.stop(monitor_id)
        return f"Stopped monitor {monitor_id}." if stopped else f"No such monitor: {monitor_id}."

    return toolset
