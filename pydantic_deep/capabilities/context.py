"""Deprecated import location for `ContextFilesCapability`.

The implementation moved to :mod:`pydantic_deep.features.context` (see the
CHANGELOG). This module re-exports it for backward compatibility and will be
removed in the next minor release. Import from
``pydantic_deep.features.context`` or the top-level ``pydantic_deep`` instead.
"""

from __future__ import annotations

import warnings

from pydantic_deep.features.context.capability import ContextFilesCapability

__all__ = ["ContextFilesCapability"]

warnings.warn(
    "pydantic_deep.capabilities.context has moved to pydantic_deep.features.context; "
    "update your imports (this shim will be removed in the next minor release).",
    DeprecationWarning,
    stacklevel=2,
)
