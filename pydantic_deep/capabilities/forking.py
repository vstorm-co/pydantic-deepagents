"""Deprecated import location for `LiveForkCapability`.

The implementation moved to :mod:`pydantic_deep.features.forking` (see the
CHANGELOG). This module re-exports it for backward compatibility and will be
removed in the next minor release. Import from
``pydantic_deep.features.forking`` or the top-level ``pydantic_deep`` instead.
"""

from __future__ import annotations

import warnings

from pydantic_deep.features.forking.capability import LiveForkCapability

__all__ = ["LiveForkCapability"]

warnings.warn(
    "pydantic_deep.capabilities.forking has moved to pydantic_deep.features.forking; "
    "update your imports (this shim will be removed in the next minor release).",
    DeprecationWarning,
    stacklevel=2,
)
