"""Internal capabilities for pydantic-deep agents.

These wrap pydantic-deep's toolsets as pydantic-ai capabilities,
enabling clean composition via ``Agent(capabilities=[...])``.
"""

from pydantic_deep.capabilities.browser import BrowserCapability
from pydantic_deep.capabilities.context import ContextFilesCapability
from pydantic_deep.capabilities.hooks import HooksCapability
from pydantic_deep.capabilities.memory import MemoryCapability
from pydantic_deep.capabilities.message_queue import (
    MessageQueue,
    MessageQueueCapability,
    QueuedMessage,
    format_follow_up,
    format_steering,
    run_with_queue,
)
from pydantic_deep.capabilities.plan import PlanCapability
from pydantic_deep.capabilities.skills import SkillsCapability
from pydantic_deep.capabilities.stuck_loop import StuckLoopDetection, StuckLoopError
from pydantic_deep.capabilities.teams import TeamCapability

__all__ = [
    "BrowserCapability",
    "ContextFilesCapability",
    "HooksCapability",
    "MemoryCapability",
    "MessageQueue",
    "MessageQueueCapability",
    "PlanCapability",
    "QueuedMessage",
    "format_follow_up",
    "format_steering",
    "SkillsCapability",
    "StuckLoopDetection",
    "StuckLoopError",
    "TeamCapability",
    "run_with_queue",
]
