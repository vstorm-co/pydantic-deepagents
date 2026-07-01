"""Deprecated import location for the browser feature toolset.

The implementation moved to :mod:`pydantic_deep.features.browser` (see the
CHANGELOG). This module re-exports the public names for backward compatibility
and will be removed in the next minor release. Import from
``pydantic_deep.features.browser`` or the top-level ``pydantic_deep`` instead.
"""

from __future__ import annotations

import warnings

from pydantic_deep.features.browser.toolset import (
    CLICK_DESCRIPTION,
    DEFAULT_MAX_CONTENT_TOKENS,
    DEFAULT_TIMEOUT_MS,
    EXECUTE_JS_DESCRIPTION,
    GET_TEXT_DESCRIPTION,
    GO_BACK_DESCRIPTION,
    GO_FORWARD_DESCRIPTION,
    NAVIGATE_DESCRIPTION,
    SCREENSHOT_DESCRIPTION,
    SCROLL_DESCRIPTION,
    TYPE_TEXT_DESCRIPTION,
    BrowserToolset,
    _BrowserState,
    _check_allowed_domain,
    _html_to_markdown,
    _require_browser,
)

__all__ = [
    "CLICK_DESCRIPTION",
    "DEFAULT_MAX_CONTENT_TOKENS",
    "DEFAULT_TIMEOUT_MS",
    "EXECUTE_JS_DESCRIPTION",
    "GET_TEXT_DESCRIPTION",
    "GO_BACK_DESCRIPTION",
    "GO_FORWARD_DESCRIPTION",
    "NAVIGATE_DESCRIPTION",
    "SCREENSHOT_DESCRIPTION",
    "SCROLL_DESCRIPTION",
    "TYPE_TEXT_DESCRIPTION",
    "BrowserToolset",
    "_BrowserState",
    "_check_allowed_domain",
    "_html_to_markdown",
    "_require_browser",
]

warnings.warn(
    "pydantic_deep.toolsets.browser has moved to pydantic_deep.features.browser; "
    "update your imports (this shim will be removed in the next minor release).",
    DeprecationWarning,
    stacklevel=2,
)
