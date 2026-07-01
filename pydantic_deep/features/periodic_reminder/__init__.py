"""Periodic-reminder feature — inject a steering reminder every N turns.

A lifecycle-only slice: `capability.py` (PeriodicReminderCapability,
PeriodicReminderConfig, the reminder generators, and `make_config_for_mode`).
"""

from pydantic_deep.features.periodic_reminder.capability import (
    LLMReminderGenerator,
    PeriodicReminderCapability,
    PeriodicReminderConfig,
    ReminderGenerator,
    build_compact_transcript,
    make_config_for_mode,
)

__all__ = [
    "LLMReminderGenerator",
    "PeriodicReminderCapability",
    "PeriodicReminderConfig",
    "ReminderGenerator",
    "build_compact_transcript",
    "make_config_for_mode",
]
