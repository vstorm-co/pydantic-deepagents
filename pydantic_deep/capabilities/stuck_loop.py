"""Deprecated import location for the stuck-loop-detection feature.

The implementation moved to :mod:`pydantic_deep.features.stuck_loop` (see the
CHANGELOG). This module re-exports the public names for backward compatibility
and will be removed in the next minor release. Import from
``pydantic_deep.features.stuck_loop`` or the top-level ``pydantic_deep`` instead.
"""

from __future__ import annotations

import warnings

from pydantic_deep.features.stuck_loop.capability import StuckLoopDetection, StuckLoopError

__all__ = ["StuckLoopDetection", "StuckLoopError"]

warnings.warn(
    "pydantic_deep.capabilities.stuck_loop has moved to pydantic_deep.features.stuck_loop; "
    "update your imports (this shim will be removed in the next minor release).",
    DeprecationWarning,
    stacklevel=2,
)
