"""Deprecated import location for `MemoryCapability`.

The implementation moved to :mod:`pydantic_deep.features.memory` (see the
CHANGELOG). This module re-exports it for backward compatibility and will be
removed in the next minor release. Import from
``pydantic_deep.features.memory`` or the top-level ``pydantic_deep`` instead.
"""

from __future__ import annotations

import warnings

from pydantic_deep.features.memory.capability import MemoryCapability

__all__ = ["MemoryCapability"]

warnings.warn(
    "pydantic_deep.capabilities.memory has moved to pydantic_deep.features.memory; "
    "update your imports (this shim will be removed in the next minor release).",
    DeprecationWarning,
    stacklevel=2,
)
