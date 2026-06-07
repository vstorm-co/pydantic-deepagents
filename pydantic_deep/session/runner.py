"""Drive ``agent.iter()`` and emit a typed :class:`SessionEvent` stream.

This is the single implementation every frontend builds on. It mirrors the
streaming logic proven in the ACP adapter and Textual worker: stream assistant
text as deltas, surface tool-call starts and results, and bracket the turn with
lifecycle events — while staying completely UI-agnostic.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.messages import (
    FinalResultEvent,
    FunctionToolResultEvent,
    ModelMessage,
    PartStartEvent,
    ThinkingPart,
    ThinkingPartDelta,
    ToolCallPart,
)

from pydantic_deep.session.events import (
    RunCancelled,
    RunCompleted,
    RunError,
    RunStarted,
    SessionEvent,
    TextDelta,
    ThinkingDelta,
    ToolCallResult,
    ToolCallStarted,
)
from pydantic_deep.session.mapping import looks_like_tool_error, tool_kind, tool_title

EventSink = Callable[[SessionEvent], Awaitable[None]]


@dataclass
class CancelToken:
    """Cooperative cancellation flag checked at node boundaries."""

    _cancelled: bool = False

    def cancel(self) -> None:
        """Request cancellation of the in-flight run."""
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        """Whether cancellation has been requested."""
        return self._cancelled


@dataclass
class RunOutcome:
    """Result of a single :func:`run_session` call."""

    messages: list[ModelMessage] = field(default_factory=list)
    cancelled: bool = False
    error: str | None = None
    output: Any = None


async def run_session(
    agent: Agent[Any, Any],
    user_text: str,
    *,
    deps: Any,
    message_history: list[ModelMessage] | None = None,
    on_event: EventSink,
    cancel: CancelToken | None = None,
) -> RunOutcome:
    """Run one agent turn, streaming events to ``on_event``.

    Args:
        agent: The configured agent to drive.
        user_text: The user prompt for this turn.
        deps: Runtime dependencies passed to ``agent.iter``.
        message_history: Prior conversation messages (defaults to empty).
        on_event: Async callback invoked for every :class:`SessionEvent`.
        cancel: Optional cooperative cancellation token.

    Returns:
        A :class:`RunOutcome` carrying the full message history, the final
        output text, and cancelled/error flags. Exceptions raised by the agent
        are caught, surfaced as a :class:`RunError` event, and reported in the
        outcome rather than propagated.
    """
    history = message_history or []
    cancel = cancel or CancelToken()

    await on_event(RunStarted())

    try:
        async with agent.iter(user_text, deps=deps, message_history=history) as run:
            async for node in run:
                if cancel.cancelled:
                    await on_event(RunCancelled())
                    return RunOutcome(messages=list(history), cancelled=True)

                if Agent.is_model_request_node(node):
                    async with node.stream(run.ctx) as request_stream:
                        final_found = False
                        async for event in request_stream:
                            part = getattr(event, "part", None)
                            delta = getattr(event, "delta", None)
                            if isinstance(part, ToolCallPart):
                                args = part.args if isinstance(part.args, dict) else {}
                                await on_event(
                                    ToolCallStarted(
                                        id=part.tool_call_id,
                                        name=part.tool_name,
                                        args=args,
                                        title=tool_title(part.tool_name, args),
                                        kind=tool_kind(part.tool_name),
                                    )
                                )
                            elif (
                                isinstance(event, PartStartEvent)
                                and isinstance(part, ThinkingPart)
                                and part.content
                            ):
                                await on_event(ThinkingDelta(part.content))
                            elif isinstance(delta, ThinkingPartDelta) and delta.content_delta:
                                await on_event(ThinkingDelta(delta.content_delta))
                            if isinstance(event, FinalResultEvent):
                                final_found = True
                                break

                        if final_found:
                            prev_len = 0
                            async for cumulative in request_stream.stream_text():
                                await on_event(TextDelta(cumulative[prev_len:]))
                                prev_len = len(cumulative)

                elif Agent.is_call_tools_node(node):
                    async with node.stream(run.ctx) as tool_stream:
                        async for tool_event in tool_stream:
                            if isinstance(tool_event, FunctionToolResultEvent):
                                result = tool_event.part
                                content = str(result.content) if result.content else ""
                                is_error = looks_like_tool_error(content)
                                await on_event(
                                    ToolCallResult(
                                        id=result.tool_call_id,
                                        content=content,
                                        is_error=is_error,
                                        status="error" if is_error else "completed",
                                    )
                                )

            run_result = run.result
            assert run_result is not None  # set once the node loop completes
            await on_event(RunCompleted(output=run_result.output))
            return RunOutcome(
                messages=list(run_result.all_messages()), output=run_result.output
            )

    except Exception as exc:
        await on_event(RunError(str(exc)))
        return RunOutcome(messages=list(history), error=str(exc))


__all__ = ["CancelToken", "RunOutcome", "run_session"]
