"""Improvement analyzer - orchestrates the full improve pipeline.

Discovers recent sessions, extracts insights in parallel, loads current
context files, synthesizes proposed changes, and optionally applies them.
"""

from __future__ import annotations

import contextlib
import json
import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic_deep.features.improve.extractor import SessionExtractor
from pydantic_deep.features.improve.synthesizer import InsightSynthesizer
from pydantic_deep.features.improve.types import ImprovementReport, ProposedChange, SessionInsights
from pydantic_deep.features.memory import DEFAULT_MEMORY_DIR, get_memory_path
from pydantic_deep.models import DEFAULT_IMPROVE_MODEL

# Default MEMORY.md path, aligned with the memory toolset's default location
# (`get_memory_path(DEFAULT_MEMORY_DIR, "main")`) so that improve writes
# memory changes where the toolset reads them. The leading slash is stripped so
# the path composes correctly under `working_dir`.
_DEFAULT_MEMORY_PATH: str = get_memory_path(DEFAULT_MEMORY_DIR, "main").lstrip("/")

# Default context file mapping: logical name -> path relative to working_dir.
# Callers can override via context_files parameter to match their backend layout.
DEFAULT_CONTEXT_FILES: dict[str, str] = {
    "SOUL.md": "SOUL.md",
    "AGENTS.md": "AGENTS.md",
    "MEMORY.md": _DEFAULT_MEMORY_PATH,
}

# State file location
_STATE_DIR = ".pydantic-deep"
_STATE_FILE = "improve_state.json"


ProgressCallback = Callable[[str, int, int], None]
"""Progress callback receiving (stage, current, total)."""


def _parse_md_heading(line: str) -> tuple[int, str] | None:
    """Parse a markdown heading line into `(level, text)`.

    Returns `None` for non-heading lines. `level` is the number of leading
    `#` characters and `text` is the heading text with surrounding `#` and
    whitespace stripped.
    """
    stripped = line.lstrip()
    if not stripped.startswith("#"):
        return None
    hashes = len(stripped) - len(stripped.lstrip("#"))
    return hashes, stripped[hashes:].strip()


class ImprovementAnalyzer:
    """Orchestrates the full improve pipeline.

    Discovers sessions, extracts insights per session (in parallel),
    loads current context files, and synthesizes proposed changes.

    The `context_files` parameter controls where context files are read
    from and written to, making this work with any backend layout::

        # Default (CLI/TUI with LocalBackend):
        analyzer = ImprovementAnalyzer(working_dir=Path("."))
        # reads SOUL.md, AGENTS.md from root
        # reads MEMORY.md from .deep/memory/main/MEMORY.md (aligned with the
        # memory toolset default)

        # Custom layout (e.g., Docker sandbox):
        analyzer = ImprovementAnalyzer(
            working_dir=Path("/workspace"),
            context_files={
                "SOUL.md": "SOUL.md",
                "AGENTS.md": "AGENTS.md",
                "MEMORY.md": ".pydantic-deep/main/MEMORY.md",
            },
        )
    """

    def __init__(
        self,
        model: str = DEFAULT_IMPROVE_MODEL,
        sessions_dir: Path | None = None,
        working_dir: Path | None = None,
        on_progress: ProgressCallback | None = None,
        context_files: dict[str, str] | None = None,
    ) -> None:
        """Initialize the analyzer.

        Args:
            model: Model identifier for extraction and synthesis agents.
            sessions_dir: Directory containing session folders with messages.json.
                Defaults to `~/.pydantic-deep/sessions`.
            working_dir: Working directory where context files live.
                Defaults to current working directory.
            on_progress: Callback for progress updates.
                Called with (stage: str, current: int, total: int).
                Stages: "discovering", "extracting", "synthesizing", "done".
            context_files: Mapping of logical context file names to paths
                relative to working_dir. Defaults to :data:`DEFAULT_CONTEXT_FILES`.
                The keys ("SOUL.md", "AGENTS.md", "MEMORY.md") are the logical
                names used in ProposedChange.target_file. The values are the
                actual filesystem paths relative to working_dir.
        """
        self._model = model
        self._sessions_dir = sessions_dir or (Path.home() / ".pydantic-deep" / "sessions")
        self._working_dir = working_dir or Path.cwd()
        self._extractor = SessionExtractor(model=model)
        self._synthesizer = InsightSynthesizer(model=model)
        self._on_progress = on_progress
        self._context_files = context_files or dict(DEFAULT_CONTEXT_FILES)

    def _progress(self, stage: str, current: int = 0, total: int = 0) -> None:
        """Emit progress update."""
        if self._on_progress:
            with contextlib.suppress(Exception):
                self._on_progress(stage, current, total)

    def _resolve_path(self, target_file: str) -> Path:
        """Resolve a logical context file name to an absolute path.

        Uses the context_files mapping to translate logical names (like
        "MEMORY.md") to actual filesystem paths. Falls back to treating
        target_file as a direct relative path if not in the mapping.

        Args:
            target_file: Logical name (e.g., "MEMORY.md") or relative path.

        Returns:
            Absolute path to the file.
        """
        relative = self._context_files.get(target_file, target_file)
        return self._working_dir / relative

    async def analyze(
        self,
        days: int = 7,
        max_sessions: int = 20,
        focus: str | None = None,
    ) -> ImprovementReport:
        """Full pipeline: discover, extract, synthesize.

        Args:
            days: Number of days to look back for sessions.
            max_sessions: Maximum number of sessions to analyze.
            focus: Optional focus area (e.g., "code style", "error handling").
                Currently passed through for future filtering support.

        Returns:
            ImprovementReport with insights and proposed changes.
        """
        # 1. Discover sessions
        self._progress("discovering")
        session_paths = self._discover_sessions(days)
        if not session_paths:
            return ImprovementReport(
                analyzed_sessions=0,
                time_range=f"last {days} days",
                total_chunks=0,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        # Limit to max_sessions (most recent first)
        session_paths = session_paths[:max_sessions]

        # 2. Extract insights per session (sequential with progress)
        self._progress("extracting", 0, len(session_paths))
        insights: list[SessionInsights] = []
        total_chunks = 0
        failed_sessions = 0
        extraction_errors: list[tuple[str, Exception]] = []
        for i, path in enumerate(session_paths):
            self._progress("extracting", i + 1, len(session_paths))
            try:
                session_insights, chunks = await self._extractor.extract(path)
                insights.append(session_insights)
                total_chunks += chunks
            except Exception as exc:
                failed_sessions += 1
                extraction_errors.append((path.name, exc))

        # 3. Load current context files + raw tool sequences
        self._progress("synthesizing", 0, 1)
        current_context = self._load_current_context()
        tool_sequences = self._load_tool_sequences(session_paths)

        # 4. Synthesize (pass raw tool traces - Meta-Harness: traces >> summaries)
        proposed_changes: list[ProposedChange] = []
        if insights:
            proposed_changes = await self._synthesizer.synthesize(
                insights, current_context, tool_sequences=tool_sequences
            )

        self._progress("done", len(insights), len(insights))
        return ImprovementReport(
            analyzed_sessions=len(insights),
            time_range=f"last {days} days",
            total_chunks=total_chunks,
            insights=insights,
            proposed_changes=proposed_changes,
            failed_sessions=failed_sessions,
            last_error=extraction_errors[-1][1] if extraction_errors else None,
            extraction_errors=extraction_errors,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def _discover_sessions(self, days: int) -> list[Path]:
        """Find sessions from last N days, sorted by date (most recent first).

        Args:
            days: Number of days to look back.

        Returns:
            List of session directory paths containing messages.json,
            sorted most-recent-first.
        """
        if not self._sessions_dir.is_dir():
            return []

        cutoff = time.time() - (days * 86400)
        sessions: list[tuple[float, Path]] = []

        for entry in self._sessions_dir.iterdir():
            if not entry.is_dir():
                continue
            messages_file = entry / "messages.json"
            if not messages_file.exists():
                continue
            mtime = messages_file.stat().st_mtime
            if mtime >= cutoff:
                sessions.append((mtime, entry))

        # Sort by mtime descending (most recent first)
        sessions.sort(key=lambda x: x[0], reverse=True)
        return [path for _, path in sessions]

    def _load_tool_sequences(self, session_paths: list[Path]) -> dict[str, str]:
        """Load tool_log.jsonl from each session as raw tool sequences.

        Provides the synthesis agent with raw execution traces, following
        the Meta-Harness insight that raw traces contain critical diagnostic
        information that is lost in LLM-summarized insights.

        Args:
            session_paths: List of session directory paths.

        Returns:
            Mapping of session_id to formatted tool sequence text.
        """
        sequences: dict[str, str] = {}
        for path in session_paths:
            log_file = path / "tool_log.jsonl"
            if not log_file.exists():
                continue
            try:
                content = log_file.read_text(encoding="utf-8").strip()
                if content:
                    sequences[path.name] = content
            except OSError:
                pass
        return sequences

    def _load_current_context(self) -> dict[str, str]:
        """Load context files using the configured path mapping.

        Returns:
            Mapping of logical filename to content. Missing files are omitted.
        """
        context: dict[str, str] = {}
        for logical_name in self._context_files:
            filepath = self._resolve_path(logical_name)
            if filepath.is_file():
                with contextlib.suppress(OSError):
                    context[logical_name] = filepath.read_text(encoding="utf-8")
        return context

    async def apply_changes(self, changes: list[ProposedChange]) -> list[str]:
        """Apply accepted changes to files.

        Uses the context_files mapping to resolve logical names to actual
        paths. For example, a change targeting "MEMORY.md" will be written
        to `.deep/memory/main/MEMORY.md` by default.

        Args:
            changes: List of proposed changes to apply.

        Returns:
            List of modified file paths (relative to working_dir).
        """
        modified: list[str] = []

        for change in changes:
            target = change.target_file
            filepath = self._resolve_path(target)

            if change.change_type == "create":
                filepath.parent.mkdir(parents=True, exist_ok=True)
                filepath.write_text(change.content, encoding="utf-8")
                modified.append(target)

            elif change.change_type == "append":
                filepath.parent.mkdir(parents=True, exist_ok=True)
                existing = ""
                if filepath.is_file():
                    existing = filepath.read_text(encoding="utf-8")
                separator = "\n\n" if existing.strip() else ""
                filepath.write_text(
                    existing.rstrip("\n") + separator + change.content + "\n",
                    encoding="utf-8",
                )
                modified.append(target)

            else:  # "update"
                if not filepath.is_file():
                    # Cannot update a file that doesn't exist, fall back to create
                    filepath.parent.mkdir(parents=True, exist_ok=True)
                    filepath.write_text(change.content, encoding="utf-8")
                    modified.append(target)
                    continue

                existing = filepath.read_text(encoding="utf-8")
                lines = existing.splitlines(keepends=True)

                # Match the section only on a heading line whose text equals the
                # requested section (after stripping leading `#` and whitespace
                # from both), so a section name appearing in body prose is never
                # mistaken for the heading.
                section_text = change.section.lstrip("#").strip() if change.section else ""
                match_index = -1
                match_level = 0
                if section_text:
                    for idx, line in enumerate(lines):
                        heading = _parse_md_heading(line)
                        if heading is not None and heading[1] == section_text:
                            match_index, match_level = idx, heading[0]
                            break

                if match_index >= 0:
                    # Replace the section body: keep the heading, swap in the new
                    # content, and terminate at the next heading of the same or
                    # higher level (fewer-or-equal `#`). When the section is the
                    # last one, `end_index` stays at EOF so nothing is lost.
                    end_index = len(lines)
                    for idx in range(match_index + 1, len(lines)):
                        heading = _parse_md_heading(lines[idx])
                        if heading is not None and heading[0] <= match_level:
                            end_index = idx
                            break
                    new_lines = lines[: match_index + 1]
                    new_lines.append("\n")
                    new_lines.append(change.content)
                    new_lines.append("\n")
                    new_lines.extend(lines[end_index:])
                    filepath.write_text("".join(new_lines), encoding="utf-8")
                else:
                    # No section match — append instead, but log it so repeated
                    # improve runs that keep appending (rather than updating in
                    # place) are visible rather than silently duplicating (B16).
                    logging.getLogger(__name__).warning(
                        "improve: section %r not found in %s; appending instead of updating",
                        change.section,
                        target,
                    )
                    separator = "\n\n" if existing.strip() else ""
                    filepath.write_text(
                        existing.rstrip("\n") + separator + change.content + "\n",
                        encoding="utf-8",
                    )
                modified.append(target)

        return modified

    def get_last_improve_time(self) -> datetime | None:
        """Read last improve timestamp from .pydantic-deep/improve_state.json.

        Returns:
            Datetime of last improve run, or None if never run.
        """
        state_path = self._working_dir / _STATE_DIR / _STATE_FILE
        if not state_path.is_file():
            return None
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            last_run = data.get("last_run")
            if last_run:
                return datetime.fromisoformat(last_run)
        except (json.JSONDecodeError, OSError, ValueError):
            pass
        return None

    def save_improve_state(self, report: ImprovementReport) -> None:
        """Save state + timestamp to .pydantic-deep/improve_state.json.

        Args:
            report: The improvement report to persist.
        """
        state_dir = self._working_dir / _STATE_DIR
        state_dir.mkdir(parents=True, exist_ok=True)
        state_path = state_dir / _STATE_FILE

        # Load existing state
        existing: dict[str, Any] = {}
        if state_path.is_file():
            with contextlib.suppress(json.JSONDecodeError, OSError):
                existing = json.loads(state_path.read_text(encoding="utf-8"))

        total_runs = existing.get("total_runs", 0) + 1
        history: list[dict[str, Any]] = existing.get("history", [])

        history_entry = {
            "timestamp": report.timestamp,
            "sessions_analyzed": report.analyzed_sessions,
            "changes_proposed": len(report.proposed_changes),
            "changes_accepted": len(report.accepted_changes),
            "changes_rejected": len(report.rejected_changes),
        }
        history.append(history_entry)

        state: dict[str, Any] = {
            "last_run": report.timestamp,
            "last_run_sessions": report.analyzed_sessions,
            "last_run_changes": len(report.proposed_changes),
            "total_runs": total_runs,
            "history": history,
        }

        state_path.write_text(
            json.dumps(state, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
