"""Asyncio-safe dual-priority message queue for mid-run delivery to agents.

Two delivery semantics:
- steering: injected before the next LLM request (interrupt-style)
- follow_up: delivered when the agent would otherwise stop (queue-style)
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Literal

from pydantic_ai import Agent
from pydantic_ai.capabilities import AbstractCapability

if TYPE_CHECKING:
    from pydantic_ai.models import ModelRequestContext
    from pydantic_ai.tools import RunContext

DeliveryMode = Literal["one_at_a_time", "all"]
Priority = Literal["steering", "follow_up"]


@dataclass(frozen=True)
class QueuedMessage:
    """An immutable message waiting for delivery into the agent loop."""

    content: str
    priority: Priority
    delivery_mode: DeliveryMode = "one_at_a_time"
    metadata: dict[str, Any] = field(default_factory=dict)


class MessageQueue:
    """Asyncio-safe dual-priority queue for mid-run message delivery.

    Usage::

        queue = MessageQueue()
        agent = create_deep_agent(message_queue=queue)

        # From another coroutine / task while the agent is running:
        await queue.steer("stop that, try a different approach")
        await queue.follow_up("when done, also summarise")
    """

    def __init__(self) -> None:
        self._steering: deque[QueuedMessage] = deque()
        self._follow_up: deque[QueuedMessage] = deque()
        self._lock = asyncio.Lock()

    async def steer(
        self,
        content: str,
        *,
        delivery_mode: DeliveryMode = "one_at_a_time",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Queue a steering message (delivered before the next LLM call)."""
        async with self._lock:
            self._steering.append(QueuedMessage(content, "steering", delivery_mode, metadata or {}))

    async def follow_up(
        self,
        content: str,
        *,
        delivery_mode: DeliveryMode = "one_at_a_time",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Queue a follow-up message (delivered when the agent would otherwise stop)."""
        async with self._lock:
            self._follow_up.append(
                QueuedMessage(content, "follow_up", delivery_mode, metadata or {})
            )

    async def drain_steering(self) -> list[QueuedMessage]:
        """Return queued steering messages and remove them from the queue."""
        async with self._lock:
            return self._drain(self._steering)

    async def drain_follow_up(self) -> list[QueuedMessage]:
        """Return queued follow-up messages and remove them from the queue."""
        async with self._lock:
            return self._drain(self._follow_up)

    def has_follow_up(self) -> bool:
        """Return True if there are pending follow-up messages (without the lock, display only)."""
        return bool(self._follow_up)

    def pending_count(self) -> tuple[int, int]:
        """Return ``(steering_count, follow_up_count)`` without the lock (display only)."""
        return len(self._steering), len(self._follow_up)

    @staticmethod
    def _drain(dq: deque[QueuedMessage]) -> list[QueuedMessage]:
        if not dq:
            return []
        head = dq[0]
        if head.delivery_mode == "all":
            drained = list(dq)
            dq.clear()
            return drained
        return [dq.popleft()]


@dataclass
class MessageQueueCapability(AbstractCapability[Any]):
    """Injects queued steering messages before each model request.

    Register via ``create_deep_agent(message_queue=queue)`` or directly::

        capability = MessageQueueCapability(queue=queue)
        agent = Agent(model, capabilities=[capability])
    """

    queue: MessageQueue

    async def before_model_request(
        self,
        ctx: RunContext[Any],
        request_context: ModelRequestContext,
    ) -> ModelRequestContext:
        queued = await self.queue.drain_steering()
        if queued:
            from pydantic_ai.messages import ModelRequest, UserPromptPart

            steering_part = UserPromptPart(content=format_steering(queued))

            msgs = request_context.messages
            for i in range(len(msgs) - 1, -1, -1):
                if isinstance(msgs[i], ModelRequest):
                    existing: ModelRequest = msgs[i]  # type: ignore[assignment]
                    msgs[i] = replace(existing, parts=[*existing.parts, steering_part])
                    break
            else:
                # No existing ModelRequest (e.g. very first call with empty history).
                msgs.append(ModelRequest(parts=[steering_part]))

        return request_context


async def run_with_queue(
    agent: Agent[Any, Any],
    prompt: str,
    *,
    deps: Any,
    queue: MessageQueue,
    message_history: list[Any] | None = None,
    **run_kwargs: Any,
) -> Any:
    """Run an agent and re-enter the loop when follow-up messages arrive.

    Steering messages are handled automatically by :class:`MessageQueueCapability`
    (injected before each LLM request). Follow-up messages are consumed here
    after each completed run, before the next iteration starts.

    Args:
        agent: The agent to run.
        prompt: The initial user prompt.
        deps: Agent dependencies.
        queue: The shared ``MessageQueue`` instance.
        message_history: Existing conversation history (passed through to agent.run).
        **run_kwargs: Extra keyword arguments forwarded to ``agent.run()``.

    Returns:
        The final :class:`~pydantic_ai.AgentRunResult`.
    """
    history: list[Any] = list(message_history or [])
    current_prompt: str | None = prompt
    final = None

    while current_prompt is not None:
        final = await agent.run(current_prompt, deps=deps, message_history=history, **run_kwargs)
        history = list(final.all_messages())
        pending = await queue.drain_follow_up()
        current_prompt = format_follow_up(pending) if pending else None

    assert final is not None
    return final


def format_steering(messages: list[QueuedMessage]) -> str:
    if len(messages) == 1:
        return f"[steering] {messages[0].content}"
    lines = "\n".join(f"- {m.content}" for m in messages)
    return f"[steering — multiple messages]\n{lines}"


def format_follow_up(messages: list[QueuedMessage]) -> str:
    return "\n\n".join(m.content for m in messages)
