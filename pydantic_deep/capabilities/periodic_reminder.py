"""Deprecated import location for the periodic-reminder feature.

The implementation moved to :mod:`pydantic_deep.features.periodic_reminder` (see
the CHANGELOG). This module re-exports the public names for backward
compatibility and will be removed in the next minor release. Import from
``pydantic_deep.features.periodic_reminder`` or the top-level ``pydantic_deep``
instead.
"""

from __future__ import annotations

import warnings

from pydantic_deep.features.periodic_reminder.capability import (
    LLMReminderGenerator,
    PeriodicReminderCapability,
    PeriodicReminderConfig,
    ReminderGenerator,
    _default_generate,
    _render,
    _should_fire,
    build_compact_transcript,
    make_config_for_mode,
)

__all__ = [
    "LLMReminderGenerator",
    "PeriodicReminderCapability",
    "PeriodicReminderConfig",
    "ReminderGenerator",
    "_default_generate",
    "_render",
    "_should_fire",
    "build_compact_transcript",
    "make_config_for_mode",
]

warnings.warn(
    "pydantic_deep.capabilities.periodic_reminder has moved to "
    "pydantic_deep.features.periodic_reminder; update your imports "
    "(this shim will be removed in the next minor release).",
    DeprecationWarning,
    stacklevel=2,
)
