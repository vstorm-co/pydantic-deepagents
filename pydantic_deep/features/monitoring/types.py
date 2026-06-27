"""Types for the Monitor (watch & react) feature."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MonitorEvent:
    """A batch of new output from a monitored process, pushed to the agent.

    ``lines`` holds the new matching output lines since the last poll. A final
    event with ``running=False`` is emitted once the process exits (its
    ``lines`` may be empty — it signals completion).
    """

    monitor_id: str
    label: str
    command: str
    lines: list[str]
    running: bool
    exit_code: int | None = None


@dataclass
class MonitorInfo:
    """Snapshot of a monitor's state for `list_monitors` and tool results."""

    monitor_id: str
    label: str
    command: str
    running: bool
    match: str | None = None
    event_count: int = 0
    exit_code: int | None = None
    last_lines: list[str] = field(default_factory=list)
