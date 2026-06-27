"""Deprecated import location for the improve feature.

The implementation moved to :mod:`pydantic_deep.features.improve` (see the
CHANGELOG). This module re-exports the public names for backward compatibility
and will be removed in the next minor release. Import from
``pydantic_deep.features.improve`` instead.
"""

from __future__ import annotations

import warnings

from pydantic_deep.features.improve import (
    DEFAULT_CONTEXT_FILES,
    AgentLearningInsight,
    ContextInsight,
    DecisionInsight,
    FailureInsight,
    ImprovementReport,
    ImproveToolset,
    PatternInsight,
    PreferenceInsight,
    ProposedChange,
    SessionExtractor,
    SessionInsights,
    UserFactInsight,
)

__all__ = [
    "DEFAULT_CONTEXT_FILES",
    "AgentLearningInsight",
    "ContextInsight",
    "DecisionInsight",
    "FailureInsight",
    "ImprovementReport",
    "ImproveToolset",
    "PatternInsight",
    "PreferenceInsight",
    "ProposedChange",
    "SessionExtractor",
    "SessionInsights",
    "UserFactInsight",
]

warnings.warn(
    "pydantic_deep.improve has moved to pydantic_deep.features.improve; "
    "update your imports (this shim will be removed in the next minor release).",
    DeprecationWarning,
    stacklevel=2,
)
