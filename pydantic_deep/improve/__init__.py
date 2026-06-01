"""Self-improving agent system.

Analyzes historical conversation sessions, extracts patterns, failures,
and user preferences, then proposes updates to context files (SOUL.md,
AGENTS.md, MEMORY.md) and skills.

Core components:

- :class:`SessionExtractor` - extracts insights from a single session
- :class:`SessionInsights` - structured insights from one session
- :class:`ProposedChange` - a proposed update to a context file
- :class:`ImprovementReport` - full report from an improve run
"""

from __future__ import annotations

from pydantic_deep.improve.analyzer import DEFAULT_CONTEXT_FILES
from pydantic_deep.improve.extractor import SessionExtractor
from pydantic_deep.improve.types import (
    AgentLearningInsight,
    ContextInsight,
    DecisionInsight,
    FailureInsight,
    ImprovementReport,
    PatternInsight,
    PreferenceInsight,
    ProposedChange,
    SessionInsights,
    UserFactInsight,
)

__all__ = [
    "AgentLearningInsight",
    "DEFAULT_CONTEXT_FILES",
    "ContextInsight",
    "DecisionInsight",
    "FailureInsight",
    "ImprovementReport",
    "PatternInsight",
    "PreferenceInsight",
    "ProposedChange",
    "SessionExtractor",
    "SessionInsights",
    "UserFactInsight",
]
