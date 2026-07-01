"""Deprecated import location for the plan feature.

The implementation moved to :mod:`pydantic_deep.features.plan` (see the
CHANGELOG). This module re-exports the public names for backward compatibility
and will be removed in the next minor release. Import from
``pydantic_deep.features.plan`` or the top-level ``pydantic_deep`` instead.
"""

from __future__ import annotations

import warnings

from pydantic_deep.features.plan import (
    DEFAULT_PLANS_DIR,
    PLANNER_DESCRIPTION,
    PLANNER_INSTRUCTIONS,
    PlanOption,
    create_plan_toolset,
)

__all__ = [
    "DEFAULT_PLANS_DIR",
    "PLANNER_DESCRIPTION",
    "PLANNER_INSTRUCTIONS",
    "PlanOption",
    "create_plan_toolset",
]

warnings.warn(
    "pydantic_deep.toolsets.plan has moved to pydantic_deep.features.plan; "
    "update your imports (this shim will be removed in the next minor release).",
    DeprecationWarning,
    stacklevel=2,
)
