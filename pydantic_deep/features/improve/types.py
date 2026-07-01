"""Type definitions for the improve module.

The per-session insight models and `ProposedChange` are pydantic `BaseModel`s so
they can be used directly as agent `output_type`s. `ImprovementReport` is a plain
dataclass: it is assembled in code (not produced by an LLM) and holds `Exception`
diagnostics that don't belong in a validated model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

ChangeType = Literal["append", "update", "create"]
"""Valid change types for a :class:`ProposedChange`."""


class FailureInsight(BaseModel):
    """A failure observed during a session."""

    description: str
    root_cause: str
    resolution: str
    tool_calls: list[str] = Field(default_factory=list)


class PatternInsight(BaseModel):
    """A recurring pattern observed across tool usage."""

    pattern: str
    frequency: int
    context: str


class PreferenceInsight(BaseModel):
    """A user preference inferred from corrections or explicit requests."""

    preference: str
    evidence: str


class ContextInsight(BaseModel):
    """A project fact discovered from session interactions."""

    fact: str
    confidence: float


class DecisionInsight(BaseModel):
    """An important decision made during a session."""

    decision: str
    reasoning: str
    confirmed: bool


class UserFactInsight(BaseModel):
    """A personal fact about the user discovered in conversation."""

    fact: str
    category: str
    confidence: float


class AgentLearningInsight(BaseModel):
    """Something the agent learned from its own behavior during a session."""

    learning: str
    category: str
    evidence: str
    confidence: float


class SessionInsights(BaseModel):
    """Extracted insights from a single session."""

    session_id: str
    timestamp: str
    message_count: int
    tool_calls_count: int
    failures: list[FailureInsight] = Field(default_factory=list)
    patterns: list[PatternInsight] = Field(default_factory=list)
    preferences: list[PreferenceInsight] = Field(default_factory=list)
    project_context: list[ContextInsight] = Field(default_factory=list)
    decisions: list[DecisionInsight] = Field(default_factory=list)
    user_facts: list[UserFactInsight] = Field(default_factory=list)
    agent_learnings: list[AgentLearningInsight] = Field(default_factory=list)


class ProposedChange(BaseModel):
    """A proposed change to a context file."""

    target_file: str
    """Target file: 'SOUL.md', 'AGENTS.md', 'MEMORY.md', or 'skills/...'."""
    change_type: ChangeType
    section: str | None = None
    content: str
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    source_sessions: list[str] = Field(default_factory=list)


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
