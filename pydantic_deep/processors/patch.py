"""Deprecated import location for the patch-tool-calls feature.

The implementation moved to :mod:`pydantic_deep.features.patch` (see the
CHANGELOG). This module re-exports the public names for backward compatibility
and will be removed in the next minor release. Import from
``pydantic_deep.features.patch`` or the top-level ``pydantic_deep`` instead.
"""

from __future__ import annotations

import warnings

from pydantic_deep.features.patch.capability import (
    CANCELLED_MESSAGE,
    PatchToolCallsCapability,
    patch_tool_calls_processor,
)

__all__ = [
    "CANCELLED_MESSAGE",
    "PatchToolCallsCapability",
    "patch_tool_calls_processor",
]

warnings.warn(
    "pydantic_deep.processors.patch has moved to pydantic_deep.features.patch; "
    "update your imports (this shim will be removed in the next minor release).",
    DeprecationWarning,
    stacklevel=2,
)
