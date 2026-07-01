"""Deprecated import location for the message-queue feature.

The implementation moved to :mod:`pydantic_deep.features.message_queue` (see the
CHANGELOG). This module re-exports the public names for backward compatibility
and will be removed in the next minor release. Import from
``pydantic_deep.features.message_queue`` or the top-level ``pydantic_deep``
instead.
"""

from __future__ import annotations

import warnings

from pydantic_deep.features.message_queue.capability import (
    MessageQueue,
    MessageQueueCapability,
    QueuedMessage,
    format_follow_up,
    format_steering,
    run_with_queue,
)

__all__ = [
    "MessageQueue",
    "MessageQueueCapability",
    "QueuedMessage",
    "format_follow_up",
    "format_steering",
    "run_with_queue",
]

warnings.warn(
    "pydantic_deep.capabilities.message_queue has moved to "
    "pydantic_deep.features.message_queue; update your imports "
    "(this shim will be removed in the next minor release).",
    DeprecationWarning,
    stacklevel=2,
)
