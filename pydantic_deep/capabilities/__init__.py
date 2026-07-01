"""Internal capabilities for pydantic-deep agents.

These wrap pydantic-deep's toolsets as pydantic-ai capabilities,
enabling clean composition via `Agent(capabilities=[...])`.
"""

from pydantic_deep.features.browser import BrowserCapability
from pydantic_deep.features.context import ContextFilesCapability
from pydantic_deep.features.hooks import HooksCapability
from pydantic_deep.features.memory import MemoryCapability
from pydantic_deep.features.message_queue import (
    MessageQueue,
    MessageQueueCapability,
    QueuedMessage,
    format_follow_up,
    format_steering,
    run_with_queue,
)
from pydantic_deep.features.periodic_reminder import (
    LLMReminderGenerator,
    PeriodicReminderCapability,
    PeriodicReminderConfig,
    ReminderGenerator,
    make_config_for_mode,
)
from pydantic_deep.features.skills import SkillsCapability
from pydantic_deep.features.stuck_loop import StuckLoopDetection, StuckLoopError

__all__ = [
    "BrowserCapability",
    "ContextFilesCapability",
    "HooksCapability",
    "LLMReminderGenerator",
    "MemoryCapability",
    "MessageQueue",
    "MessageQueueCapability",
    "PeriodicReminderCapability",
    "PeriodicReminderConfig",
    "QueuedMessage",
    "ReminderGenerator",
    "SkillsCapability",
    "StuckLoopDetection",
    "StuckLoopError",
    "format_follow_up",
    "format_steering",
    "make_config_for_mode",
    "run_with_queue",
]
