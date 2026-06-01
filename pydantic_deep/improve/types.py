"""Type definitions for the improve module.

Dataclasses representing insights extracted from sessions, proposed changes
to context files, and full improvement reports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ChangeType = Literal["append", "update", "create"]
"""Valid change types for a :class:`ProposedChange`."""


@dataclass
class FailureInsight:
    """A failure observed during a session."""

    description: str
    """What went wrong."""
    root_cause: str
    """Why it happened (if identifiable)."""
    resolution: str
    """How it was resolved (empty if unresolved)."""
    tool_calls: list[str] = field(default_factory=list)
    """Tool calls involved in the failure."""


@dataclass
class PatternInsight:
    """A recurring pattern observed across tool usage."""

    pattern: str
    """Description of the pattern (e.g., 'read → edit → test → commit')."""
    frequency: int
    """How many times the pattern appeared."""
    context: str
    """When/where this pattern is typically used."""


@dataclass
class PreferenceInsight:
    """A user preference inferred from corrections or explicit requests."""

    preference: str
    """What the user prefers."""
    evidence: str
    """Evidence from the session (e.g., user correction, explicit request)."""


@dataclass
class ContextInsight:
    """A project fact discovered from session interactions."""

    fact: str
    """The discovered fact about the project."""
    confidence: float
    """Confidence level from 0.0 to 1.0."""


@dataclass
class DecisionInsight:
    """An important decision made during a session."""

    decision: str
    """What was decided."""
    reasoning: str
    """Why this decision was made."""
    confirmed: bool
    """Whether the user explicitly confirmed/approved."""


@dataclass
class UserFactInsight:
    """A personal fact about the user discovered in conversation."""

    fact: str
    """The fact (e.g., 'User's name is Kacper', 'User speaks Polish')."""
    category: str
    """Category: 'identity', 'role', 'language', 'expertise', 'preference', 'other'."""
    confidence: float
    """Confidence level from 0.0 to 1.0."""


@dataclass
class AgentLearningInsight:
    """Something the agent learned from its own behavior during a session."""

    learning: str
    """What was learned (e.g., 'tests are in tests/ dir', 'uv run pytest works')."""
    category: str
    """Category: 'tool_chain', 'file_location', 'build_command',
    'environment', 'workaround', 'other'."""
    evidence: str
    """Tool calls or actions that demonstrated this."""
    confidence: float
    """Confidence level from 0.0 to 1.0."""


@dataclass
class SessionInsights:
    """Extracted insights from a single session."""

    session_id: str
    """Unique identifier for the session."""
    timestamp: str
    """ISO timestamp of the session."""
    message_count: int
    """Total number of messages in the session."""
    tool_calls_count: int
    """Total number of tool calls in the session."""
    failures: list[FailureInsight] = field(default_factory=list)
    """Failures observed during the session."""
    patterns: list[PatternInsight] = field(default_factory=list)
    """Recurring patterns observed."""
    preferences: list[PreferenceInsight] = field(default_factory=list)
    """User preferences inferred."""
    project_context: list[ContextInsight] = field(default_factory=list)
    """Project facts discovered."""
    decisions: list[DecisionInsight] = field(default_factory=list)
    """Important decisions made."""
    user_facts: list[UserFactInsight] = field(default_factory=list)
    """Personal facts about the user."""
    agent_learnings: list[AgentLearningInsight] = field(default_factory=list)
    """Behavioral learnings from agent's own actions."""


@dataclass
class ProposedChange:
    """A proposed change to a context file."""

    target_file: str
    """Target file: 'SOUL.md', 'AGENTS.md', 'MEMORY.md', or 'skills/...'."""
    change_type: ChangeType
    """Type of change: 'append', 'update', or 'create'."""
    section: str | None
    """Section in the file (for 'update' changes), or None."""
    content: str
    """New or modified content."""
    reason: str
    """Why this change is proposed."""
    confidence: float
    """Confidence level from 0.0 to 1.0."""
    source_sessions: list[str] = field(default_factory=list)
    """Session IDs that support this change."""


@dataclass
class ImprovementReport:
    """Full report from an improve run."""

    analyzed_sessions: int
    """Number of sessions analyzed."""
    time_range: str
    """Human-readable time range (e.g., 'last 7 days')."""
    total_chunks: int
    """Total number of chunks processed across all sessions."""
    insights: list[SessionInsights] = field(default_factory=list)
    """Per-session insights."""
    proposed_changes: list[ProposedChange] = field(default_factory=list)
    """All proposed changes."""
    accepted_changes: list[ProposedChange] = field(default_factory=list)
    """Changes accepted by the user."""
    rejected_changes: list[ProposedChange] = field(default_factory=list)
    """Changes rejected by the user."""
    failed_sessions: int = 0
    """Number of sessions that failed extraction."""
    last_error: Exception | None = field(default=None, repr=False)
    """Last extraction error (for diagnostics)."""
    extraction_errors: list[tuple[str, Exception]] = field(default_factory=list, repr=False)
    """All extraction failures as (session_id, error) pairs (for diagnostics)."""
    timestamp: str = ""
    """ISO timestamp of when the report was generated."""
