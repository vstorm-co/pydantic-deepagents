"""Asyncio-safe dual-priority message queue for mid-run delivery to agents.

Two delivery semantics:
- steering: injected before the next LLM request (interrupt-style)
- follow_up: delivered when the agent would otherwise stop (queue-style)

Messages carry free-form `metadata`. The `source` key is the one the queue reads
itself: it names the external channel a message came from (`"slack"`,
`"monitor"`, …), reaches logs and span attributes on delivery, and is rendered
into the label the model sees.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections import deque
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Literal

from opentelemetry import trace
from pydantic_ai import Agent
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import ModelRequest, UserPromptPart

from pydantic_deep.deps import DeepAgentDeps

if TYPE_CHECKING:
    from collections.abc import Callable

    from pydantic_ai.models import ModelRequestContext
    from pydantic_ai.tools import RunContext

logger = logging.getLogger(__name__)

DeliveryMode = Literal["one_at_a_time", "all"]
Priority = Literal["steering", "follow_up"]

DEFAULT_MAX_PENDING = 100
"""Default cap on pending messages per priority."""

_SOURCE_DISALLOWED = re.compile(r"[^\w.:-]+")
_SOURCE_MAX_LEN = 32


class QueueFullError(RuntimeError):
    """Raised when a message cannot be queued because that priority is at capacity.

    Enqueueing fails loudly rather than dropping: an external bridge needs to know
    a submission did not land so it can report that back to whoever sent it.
    """


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

    Args:
        max_pending: Cap on pending messages per priority. `None` removes the cap.
            Enqueueing past the cap raises :class:`QueueFullError`.
    """

    def __init__(self, *, max_pending: int | None = DEFAULT_MAX_PENDING) -> None:
        self._steering: deque[QueuedMessage] = deque()
        self._follow_up: deque[QueuedMessage] = deque()
        self._lock = asyncio.Lock()
        self._max_pending = max_pending

    async def steer(
        self,
        content: str,
        *,
        delivery_mode: DeliveryMode = "one_at_a_time",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Queue a steering message (delivered before the next LLM call).

        Raises:
            QueueFullError: When `max_pending` steering messages already wait.
        """
        await self._put(
            self._steering, QueuedMessage(content, "steering", delivery_mode, metadata or {})
        )

    async def follow_up(
        self,
        content: str,
        *,
        delivery_mode: DeliveryMode = "one_at_a_time",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Queue a follow-up message (delivered when the agent would otherwise stop).

        Raises:
            QueueFullError: When `max_pending` follow-up messages already wait.
        """
        await self._put(
            self._follow_up, QueuedMessage(content, "follow_up", delivery_mode, metadata or {})
        )

    async def drain_steering(self) -> list[QueuedMessage]:
        """Return queued steering messages and remove them from the queue."""
        async with self._lock:
            return self._drain(self._steering)

    async def drain_follow_up(self) -> list[QueuedMessage]:
        """Return queued follow-up messages and remove them from the queue."""
        async with self._lock:
            return self._drain(self._follow_up)

    async def discard_follow_up(
        self, *, keep: Callable[[QueuedMessage], bool] | None = None
    ) -> list[QueuedMessage]:
        """Remove every pending follow-up and return the removed ones.

        Messages for which `keep` returns True stay queued, in order. Callers use
        this to prune follow-ups that a cancelled run made stale while sparing the
        ones no longer tied to it — an externally submitted message was never about
        the cancelled task, and dropping it reads to its sender as being ignored.

        Args:
            keep: Predicate deciding which pending messages survive. `None`
                discards all of them.

        Returns:
            The messages removed from the queue, in submission order.
        """
        async with self._lock:
            kept: deque[QueuedMessage] = deque()
            removed: list[QueuedMessage] = []
            for message in self._follow_up:
                if keep is not None and keep(message):
                    kept.append(message)
                else:
                    removed.append(message)
            self._follow_up = kept
        for message in removed:
            logger.info(
                "discarded %s message from %s",
                message.priority,
                queued_source(message) or "local",
            )
        return removed

    def has_follow_up(self) -> bool:
        """Return True if there are pending follow-up messages (without the lock, display only)."""
        return bool(self._follow_up)

    def pending_count(self) -> tuple[int, int]:
        """Return `(steering_count, follow_up_count)` without the lock (display only)."""
        return len(self._steering), len(self._follow_up)

    async def _put(self, dq: deque[QueuedMessage], message: QueuedMessage) -> None:
        """Append `message` to `dq` under the lock, enforcing `max_pending`."""
        async with self._lock:
            if self._max_pending is not None and len(dq) >= self._max_pending:
                raise QueueFullError(
                    f"{message.priority} queue is full "
                    f"({self._max_pending} pending) - the agent is not consuming "
                    f"messages fast enough to accept more"
                )
            dq.append(message)
            pending = len(dq)
        logger.info(
            "queued %s message from %s (pending=%d)",
            message.priority,
            queued_source(message) or "local",
            pending,
        )

    @staticmethod
    def _drain(dq: deque[QueuedMessage]) -> list[QueuedMessage]:
        """Drain a batch from `dq` respecting each message's `delivery_mode`.

        A `one_at_a_time` head is delivered alone. An `all` head batches the
        contiguous leading run of `all` messages, stopping before the first
        `one_at_a_time` - so a head marked `all` never overrides the mode of
        a later message that asked to be delivered separately.
        """
        if not dq:
            return []
        if dq[0].delivery_mode != "all":
            return [dq.popleft()]
        drained: list[QueuedMessage] = []
        while dq and dq[0].delivery_mode == "all":
            drained.append(dq.popleft())
        return drained


@dataclass
class MessageQueueCapability(AbstractCapability[DeepAgentDeps]):
    """Injects queued steering messages before each model request.

    Register via `create_deep_agent(message_queue=queue)` or directly::

        capability = MessageQueueCapability(queue=queue)
        agent = Agent(model, capabilities=[capability])
    """

    queue: MessageQueue

    async def before_model_request(
        self,
        ctx: RunContext[DeepAgentDeps],
        request_context: ModelRequestContext,
    ) -> ModelRequestContext:
        queued = await self.queue.drain_steering()
        if queued:
            _record_delivery(queued, "steering")
            steering_part = UserPromptPart(content=format_steering(queued))

            # Reassign a fresh list rather than mutating request_context.messages
            # in place - it is the shared run history seen by later capabilities.
            msgs = list(request_context.messages)
            for i in range(len(msgs) - 1, -1, -1):
                if isinstance(msgs[i], ModelRequest):
                    existing: ModelRequest = msgs[i]  # type: ignore[assignment]
                    msgs[i] = replace(existing, parts=[*existing.parts, steering_part])
                    break
            else:
                # No existing ModelRequest (e.g. very first call with empty history).
                msgs.append(ModelRequest(parts=[steering_part]))
            request_context.messages = msgs

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
        queue: The shared `MessageQueue` instance.
        message_history: Existing conversation history (passed through to agent.run).
        **run_kwargs: Extra keyword arguments forwarded to `agent.run()`.

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
        if pending:
            # Follow-ups re-enter the loop. Any steering still queued is left in
            # place so MessageQueueCapability injects it during the re-run.
            _record_delivery(pending, "follow_up")
            current_prompt = format_follow_up(pending)
            continue
        # No follow-ups: the loop is about to exit. Steering enqueued after this
        # run's final model request was never injected (there is no further
        # request to inject into), so deliver it on a fresh turn rather than
        # leaving it in the queue forever.
        leftover = await queue.drain_steering()
        current_prompt = format_steering(leftover) if leftover else None

    assert final is not None
    return final


def queued_source(message: QueuedMessage) -> str | None:
    """Return the `metadata["source"]` label of `message`, or None when it has none.

    The value is written by whoever enqueued the message and is interpolated into
    the label the model reads, so it is reduced to word characters plus `.`, `:`
    and `-` and truncated. A message with no source was submitted locally.
    """
    raw = message.metadata.get("source")
    if raw is None:
        return None
    return _SOURCE_DISALLOWED.sub("-", str(raw))[:_SOURCE_MAX_LEN].strip("-") or None


def format_steering(messages: list[QueuedMessage]) -> str:
    if not messages:
        return ""
    if len(messages) == 1:
        return f"{_tag(messages[0], 'steering')} {messages[0].content}"
    lines = "\n".join(f"- {_inline_source(m)}{m.content}" for m in messages)
    return f"[steering - multiple messages]\n{lines}"


def format_follow_up(messages: list[QueuedMessage]) -> str:
    return "\n\n".join(
        f"{_tag(m, 'follow-up')} {m.content}" if queued_source(m) else m.content for m in messages
    )


def _tag(message: QueuedMessage, kind: str) -> str:
    """Return the bracketed delivery label, naming the source when there is one."""
    source = queued_source(message)
    return f"[{kind} via {source}]" if source else f"[{kind}]"


def _inline_source(message: QueuedMessage) -> str:
    """Return a `[via x] ` prefix for one line of a batched delivery."""
    source = queued_source(message)
    return f"[via {source}] " if source else ""


def _record_delivery(messages: list[QueuedMessage], kind: Priority) -> None:
    """Log a delivered batch and attach its sources to the enclosing span."""
    sources = sorted({queued_source(m) or "local" for m in messages})
    logger.info("delivering %d %s message(s) from %s", len(messages), kind, ", ".join(sources))
    span = trace.get_current_span()
    span.set_attribute(f"pydantic_deep.message_queue.{kind}.count", len(messages))
    span.set_attribute(f"pydantic_deep.message_queue.{kind}.sources", sources)
