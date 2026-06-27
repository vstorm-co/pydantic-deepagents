"""Monitor (watch & react) — background watches that push output to the agent.

A monitor runs a long-lived command (log tail, CI poll, file watch, dev server)
and delivers each new line of matching output back into the conversation via the
message queue, so the agent reacts without polling. Built on the backend's
background-process support.
"""

from __future__ import annotations

from pydantic_deep.features.monitoring.manager import EventSink, MonitorManager
from pydantic_deep.features.monitoring.toolset import create_monitor_toolset
from pydantic_deep.features.monitoring.types import MonitorEvent, MonitorInfo

__all__ = [
    "EventSink",
    "MonitorEvent",
    "MonitorInfo",
    "MonitorManager",
    "create_monitor_toolset",
]
