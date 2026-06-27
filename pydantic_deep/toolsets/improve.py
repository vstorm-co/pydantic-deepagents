"""Deprecated import location for the improve toolset.

The implementation moved to :mod:`pydantic_deep.features.improve` (see the
CHANGELOG). This module re-exports the public names for backward compatibility
and will be removed in the next minor release. Import from
``pydantic_deep.features.improve`` instead.
"""

from __future__ import annotations

import warnings

from pydantic_deep.features.improve.toolset import (
    ImproveToolset,
    _format_report,
    _format_status,
)

__all__ = ["ImproveToolset", "_format_report", "_format_status"]

warnings.warn(
    "pydantic_deep.toolsets.improve has moved to pydantic_deep.features.improve; "
    "update your imports (this shim will be removed in the next minor release).",
    DeprecationWarning,
    stacklevel=2,
)
