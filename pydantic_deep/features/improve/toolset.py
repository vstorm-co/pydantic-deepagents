"""Improve toolset - agent-callable tools for self-improvement.

Provides `improve` and `get_improvement_status` tools so the agent
can trigger the improve pipeline and check its status.
"""

from __future__ import annotations

import contextlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from pydantic_deep.features.improve.analyzer import ImprovementAnalyzer
from pydantic_deep.features.improve.types import ImprovementReport
from pydantic_deep.models import DEFAULT_IMPROVE_MODEL

# Tool description constants

IMPROVE_DESCRIPTION = """\
Analyze recent conversation sessions and propose improvements to context files.

Runs the improve pipeline: discovers sessions from the last N days, extracts
insights (failures, patterns, preferences, project facts, decisions), and
synthesizes proposed changes to SOUL.md, AGENTS.md, MEMORY.md, and skills.

Returns a formatted report with proposed changes and their confidence scores."""

GET_STATUS_DESCRIPTION = """\
Check when the improve command was last run and what changed.

Returns the last run timestamp, number of sessions analyzed, changes made,
and total number of improve runs."""


def _format_report(report: ImprovementReport) -> str:
    """Format an improvement report as a human-readable string.

    Args:
        report: The improvement report to format.

    Returns:
        Formatted string summary of the report.
    """
    lines: list[str] = []
    lines.append(f"Analyzed {report.analyzed_sessions} sessions ({report.time_range})")

    if not report.proposed_changes:
        lines.append("No changes proposed.")
        return "\n".join(lines)

    lines.append(f"Proposed {len(report.proposed_changes)} changes:\n")
    for i, change in enumerate(report.proposed_changes, 1):
        lines.append(f"{i}. {change.target_file} ({change.change_type})")
        lines.append(f"   Confidence: {change.confidence:.2f}")
        lines.append(f"   Reason: {change.reason}")
        preview = change.content[:200]
        if len(change.content) > 200:
            preview += "..."
        lines.append(f"   Content: {preview}")
        if change.source_sessions:
            lines.append(f"   Sources: {', '.join(change.source_sessions)}")
        lines.append("")

    return "\n".join(lines)


def _format_status(
    last_run: datetime | None,
    state: dict[str, Any],
) -> str:
    """Format improvement status as a human-readable string.

    Args:
        last_run: Datetime of the last run, or None.
        state: Full state dict from improve_state.json.

    Returns:
        Formatted status string.
    """
    if last_run is None:
        return "Improve has never been run. Use the improve tool to analyze sessions."

    now = datetime.now(timezone.utc)
    delta = now - last_run
    hours = delta.total_seconds() / 3600

    if hours < 1:
        time_ago = f"{int(delta.total_seconds() / 60)} minutes ago"
    elif hours < 24:
        time_ago = f"{int(hours)} hours ago"
    else:
        time_ago = f"{int(hours / 24)} days ago"

    lines: list[str] = [
        f"Last run: {last_run.isoformat()} ({time_ago})",
        f"Sessions analyzed: {state.get('last_run_sessions', '?')}",
        f"Changes proposed: {state.get('last_run_changes', '?')}",
        f"Total runs: {state.get('total_runs', '?')}",
    ]
    return "\n".join(lines)


IMPROVE_SYSTEM_PROMPT = """\
## Self-Improvement

You have access to a self-improvement system via the `improve` and \
`get_improvement_status` tools.

### When to use `improve`:
- When the user asks you to learn from past sessions
- When the user says "/improve" or asks you to self-improve
- After completing a long or complex task, suggest running improve
- When you notice you're repeating mistakes or the user keeps correcting you

### When to use `get_improvement_status`:
- When the user asks when improve was last run
- Before running improve, to check if it was run recently (avoid running \
  too often — once per day is usually enough)

### What improve does:
1. Analyzes recent conversation sessions (default: last 7 days)
2. Extracts patterns, failures, user preferences, and project context
3. Proposes changes to SOUL.md (preferences), AGENTS.md (conventions), \
   MEMORY.md (learnings)
4. The user reviews and approves changes

### Do NOT:
- Run improve without the user's awareness
- Run improve more than once per day unless explicitly asked
- Modify SOUL.md, AGENTS.md, or MEMORY.md directly — let improve handle it
"""


class ImproveToolset(FunctionToolset[Any]):
    """Provides improve and get_improvement_status tools.

    Allows an agent to trigger the self-improvement pipeline and
    check when it was last run.
    """

    def __init__(
        self,
        sessions_dir: Path | None = None,
        working_dir: Path | None = None,
        model: str = DEFAULT_IMPROVE_MODEL,
        context_files: dict[str, str] | None = None,
    ) -> None:
        """Initialize the improve toolset.

        Args:
            sessions_dir: Directory containing session folders with messages.json.
            working_dir: Working directory where context files live.
            model: Model identifier for the extraction/synthesis agents.
            context_files: Mapping of logical context file names to paths
                relative to working_dir. See
                :data:`~pydantic_deep.improve.analyzer.DEFAULT_CONTEXT_FILES`.
        """
        super().__init__(id="deep-improve")
        self._sessions_dir = sessions_dir
        self._working_dir = working_dir
        self._model = model
        self._context_files = context_files
        self._instructions = [IMPROVE_SYSTEM_PROMPT]

        @self.tool(description=IMPROVE_DESCRIPTION)
        async def improve(  # pragma: no cover - thin wrapper, tested via analyzer
            ctx: RunContext[Any],
            days: int = 7,
            focus: str | None = None,
        ) -> str:
            """Analyze recent sessions and propose improvements.

            Args:
                days: Number of days to look back for sessions.
                focus: Optional focus area (e.g., "code style", "error handling").
            """
            s_dir = self._sessions_dir
            w_dir = self._working_dir
            if w_dir is None:
                w_dir = Path(getattr(ctx.deps, "working_dir", "."))

            analyzer = ImprovementAnalyzer(
                model=self._model,
                sessions_dir=s_dir,
                working_dir=w_dir,
                context_files=self._context_files,
            )
            report = await analyzer.analyze(days=days, focus=focus)
            analyzer.save_improve_state(report)
            return _format_report(report)

        @self.tool(description=GET_STATUS_DESCRIPTION)
        async def get_improvement_status(  # pragma: no cover - thin wrapper, tested via analyzer
            ctx: RunContext[Any],
        ) -> str:
            """Check when improve was last run and what changed."""
            w_dir = self._working_dir
            if w_dir is None:
                w_dir = Path(getattr(ctx.deps, "working_dir", "."))

            analyzer = ImprovementAnalyzer(
                model=self._model,
                sessions_dir=self._sessions_dir,
                working_dir=w_dir,
            )

            last_run = analyzer.get_last_improve_time()
            state: dict[str, Any] = {}
            state_path = w_dir / ".pydantic-deep" / "improve_state.json"
            if state_path.is_file():
                with contextlib.suppress(json.JSONDecodeError, OSError):
                    state = json.loads(state_path.read_text(encoding="utf-8"))

            return _format_status(last_run, state)
