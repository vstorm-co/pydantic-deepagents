"""Deprecated import location for the eviction feature.

The implementation moved to :mod:`pydantic_deep.features.eviction` (see the
CHANGELOG). This module re-exports the public names for backward compatibility
and will be removed in the next minor release. Import from
``pydantic_deep.features.eviction`` or the top-level ``pydantic_deep`` instead.
"""

from __future__ import annotations

import warnings

from pydantic_deep.features.eviction.capability import (
    BINARY_PRUNED_TEMPLATE,
    DEFAULT_EVICTION_PATH,
    DEFAULT_MAX_BINARY_CONTENT,
    DEFAULT_TOKEN_LIMIT,
    EVICTION_MESSAGE_TEMPLATE,
    EvictionCapability,
    _content_to_str,
    _extension_for_media_type,
    _sanitize_id,
)

__all__ = [
    "BINARY_PRUNED_TEMPLATE",
    "DEFAULT_EVICTION_PATH",
    "DEFAULT_MAX_BINARY_CONTENT",
    "DEFAULT_TOKEN_LIMIT",
    "EVICTION_MESSAGE_TEMPLATE",
    "EvictionCapability",
    "_content_to_str",
    "_extension_for_media_type",
    "_sanitize_id",
]

warnings.warn(
    "pydantic_deep.processors.eviction has moved to pydantic_deep.features.eviction; "
    "update your imports (this shim will be removed in the next minor release).",
    DeprecationWarning,
    stacklevel=2,
)
