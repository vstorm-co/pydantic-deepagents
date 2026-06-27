"""Deprecated import location for `BrowserCapability`.

The implementation moved to :mod:`pydantic_deep.features.browser` (see the
CHANGELOG). This module re-exports the public names for backward compatibility
and will be removed in the next minor release. Import from
``pydantic_deep.features.browser`` or the top-level ``pydantic_deep`` instead.
"""

from __future__ import annotations

import warnings

from pydantic_deep.features.browser.capability import (
    BROWSER_INSTRUCTIONS,
    BrowserCapability,
    _auto_install_chromium,
)

__all__ = ["BROWSER_INSTRUCTIONS", "BrowserCapability", "_auto_install_chromium"]

warnings.warn(
    "pydantic_deep.capabilities.browser has moved to pydantic_deep.features.browser; "
    "update your imports (this shim will be removed in the next minor release).",
    DeprecationWarning,
    stacklevel=2,
)
