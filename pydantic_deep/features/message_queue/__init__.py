"""Message-queue feature — peer/steering message queue for live agent runs.

A lifecycle-only slice: `capability.py` (MessageQueue, MessageQueueCapability,
QueuedMessage, run_with_queue, and the steering/follow-up formatters).
"""

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
