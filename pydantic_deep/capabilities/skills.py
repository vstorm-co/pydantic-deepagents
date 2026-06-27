"""Deprecated import location for `SkillsCapability`.

The implementation moved to :mod:`pydantic_deep.features.skills` (see the
CHANGELOG). This module re-exports it for backward compatibility and will be
removed in the next minor release. Import from
``pydantic_deep.features.skills`` or the top-level ``pydantic_deep`` instead.
"""

from __future__ import annotations

import warnings

from pydantic_deep.features.skills import SkillsCapability

__all__ = ["SkillsCapability"]

warnings.warn(
    "pydantic_deep.capabilities.skills has moved to pydantic_deep.features.skills; "
    "update your imports (this shim will be removed in the next minor release).",
    DeprecationWarning,
    stacklevel=2,
)
