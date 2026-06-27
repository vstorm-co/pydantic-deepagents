"""Deprecated import location for the liteparse feature.

The implementation moved to :mod:`pydantic_deep.features.liteparse` (see the
CHANGELOG). This module re-exports the public names for backward compatibility
and will be removed in the next minor release. Import from
``pydantic_deep.features.liteparse`` or the top-level ``pydantic_deep`` instead.
"""

from __future__ import annotations

import warnings

from pydantic_deep.features.liteparse.toolset import (
    PARSE_DOCUMENT_DESCRIPTION,
    SCREENSHOT_DOCUMENT_DESCRIPTION,
    LiteparseToolset,
)

__all__ = [
    "PARSE_DOCUMENT_DESCRIPTION",
    "SCREENSHOT_DOCUMENT_DESCRIPTION",
    "LiteparseToolset",
]

warnings.warn(
    "pydantic_deep.toolsets.liteparse has moved to pydantic_deep.features.liteparse; "
    "update your imports (this shim will be removed in the next minor release).",
    DeprecationWarning,
    stacklevel=2,
)
