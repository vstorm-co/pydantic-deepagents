"""Eviction feature — intercept oversized tool outputs before they enter history.

A lifecycle-only slice: `capability.py` (EvictionCapability + the preview/template
helpers and defaults). No model-callable tools.
"""

from pydantic_deep._text import create_content_preview
from pydantic_deep.features.eviction.capability import (
    BINARY_PRUNED_TEMPLATE,
    DEFAULT_EVICTION_PATH,
    DEFAULT_MAX_BINARY_CONTENT,
    DEFAULT_TOKEN_LIMIT,
    EVICTION_MESSAGE_TEMPLATE,
    EvictionCapability,
)

__all__ = [
    "BINARY_PRUNED_TEMPLATE",
    "DEFAULT_EVICTION_PATH",
    "DEFAULT_MAX_BINARY_CONTENT",
    "DEFAULT_TOKEN_LIMIT",
    "EVICTION_MESSAGE_TEMPLATE",
    "EvictionCapability",
    "create_content_preview",
]
