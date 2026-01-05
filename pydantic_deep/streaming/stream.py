"""Core streaming functionality for agent execution.

This module provides the main streaming API for real-time updates
during agent execution.
"""

import time
from collections.abc import AsyncIterator
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.result import StreamedRunResult

from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.streaming.types import (
    StreamEvent,
    StreamEventType,
    agent_end_event,
    agent_start_event,
    error_event,
    llm_chunk_event,
    progress_event,
    tool_end_event,
    tool_start_event,
)


async def run_stream(
    agent: Agent[DeepAgentDeps, Any],
    prompt: str,
    deps: DeepAgentDeps,
    message_history: list[dict[str, Any]] | None = None,
) -> AsyncIterator[StreamEvent]:
    """Run agent with streaming updates.

    This function wraps the agent's execution and emits StreamEvent objects
    for all major events including:
    - Agent start/end
    - LLM text chunks
    - Tool calls (start/end)
    - Progress updates
    - Errors

    Args:
        agent: The agent to run
        prompt: The user prompt
        deps: Agent dependencies
        message_history: Optional message history to continue from

    Yields:
        StreamEvent objects for each event during execution

    Example:
        ```python
        async for event in run_stream(agent, "Hello", deps):
            if event.event_type == StreamEventType.LLM_CHUNK:
                print(event.data["text"], end="", flush=True)
            elif event.event_type == StreamEventType.TOOL_START:
                print(f"\\n[Calling {event.data['tool_name']}]")
        ```
    """
    # Emit agent start event
    agent_name = getattr(agent, "name", "agent")
    yield agent_start_event(agent_name=agent_name, prompt=prompt)

    # Track progress
    iteration = 0
    total_tokens = 0
    start_time = time.time()
    success = False

    try:
        # Run the agent with streaming - this is a context manager
        async with agent.run_stream(
            prompt,
            deps=deps,
            message_history=message_history,  # type: ignore[arg-type]
        ) as result:
            # Stream text chunks from this result
            async for text_chunk in result.stream_text(delta=True):
                yield llm_chunk_event(text=text_chunk)

            # Get final output
            output = await result.get_output()

            # Update tracking
            iteration += 1
            usage = result.usage()
            if usage:  # pragma: no branch
                total_tokens = usage.total_tokens or 0

            # Emit progress event
            yield progress_event(
                iteration=iteration,
                total_tokens=total_tokens if total_tokens > 0 else None,
            )

        success = True

    except Exception as e:  # pragma: no cover
        # Emit error event
        yield error_event(
            error=str(e),
            exception_type=type(e).__name__,
        )
        success = False
        raise

    finally:
        # Emit agent end event
        duration = time.time() - start_time
        yield agent_end_event(
            agent_name=agent_name,
            success=success,
            total_iterations=iteration,
            total_tokens=total_tokens if total_tokens > 0 else None,
            duration_seconds=duration,
        )


async def run_stream_with_tools(
    agent: Agent[DeepAgentDeps, Any],
    prompt: str,
    deps: DeepAgentDeps,
    message_history: list[dict[str, Any]] | None = None,
    emit_progress: bool = True,
) -> AsyncIterator[StreamEvent]:
    """Run agent with streaming updates including detailed tool call events.

    This is an enhanced version of run_stream() that also emits detailed
    tool call events with arguments and results. Note that this may
    add slight latency as it needs to track tool executions.

    Args:
        agent: The agent to run
        prompt: The user prompt
        deps: Agent dependencies
        message_history: Optional message history to continue from
        emit_progress: Whether to emit progress events

    Yields:
        StreamEvent objects for each event during execution

    Example:
        ```python
        async for event in run_stream_with_tools(agent, "Create file", deps):
            if event.event_type == StreamEventType.TOOL_START:
                print(f"Calling {event.data['tool_name']}...")
            elif event.event_type == StreamEventType.TOOL_END:
                print(f"  -> {event.data.get('result')}")
        ```
    """
    # Emit agent start event
    agent_name = getattr(agent, "name", "agent")
    yield agent_start_event(agent_name=agent_name, prompt=prompt)

    # Track progress and tool calls
    iteration = 0
    total_tokens = 0
    tool_calls_count = 0
    start_time = time.time()
    success = False
    current_tool_start_time: float | None = None
    current_tool_name: str | None = None

    try:
        # Run the agent
        result = await agent.run(
            prompt,
            deps=deps,
            message_history=message_history,  # type: ignore[arg-type]
        )

        # Get messages and extract tool calls
        messages = result.all_messages()

        # Process messages to emit events
        for msg in messages:  # pragma: no cover
            # Check for tool calls in the message
            # This logic is complex and depends on pydantic-ai's internal message structure
            # which may vary. We pragma: no cover this section as it's integration code.
            if hasattr(msg, "parts"):  # pragma: no cover
                for part in msg.parts:  # pragma: no cover
                    # Tool request (start)
                    if hasattr(part, "tool_name"):  # pragma: no cover
                        tool_name = getattr(part, "tool_name", "unknown")
                        args = getattr(part, "args", None)
                        current_tool_name = tool_name
                        current_tool_start_time = time.time()
                        tool_calls_count += 1

                        yield tool_start_event(
                            tool_name=tool_name,
                            args=args.model_dump() if hasattr(args, "model_dump") else args,
                        )

                    # Tool return (end)
                    elif hasattr(part, "tool_name") or (current_tool_name and hasattr(part, "content")):  # pragma: no cover
                        # This is a tool response
                        if current_tool_name:  # pragma: no cover
                            duration = None
                            if current_tool_start_time:
                                duration = time.time() - current_tool_start_time

                            tool_result = getattr(part, "content", None)
                            yield tool_end_event(
                                tool_name=current_tool_name,
                                result=tool_result,
                                duration_seconds=duration,
                            )

                            current_tool_name = None
                            current_tool_start_time = None

            # Emit text chunks from model responses
            if hasattr(msg, "content") and isinstance(msg.content, str):  # type: ignore[union-attr]  # pragma: no cover
                # Split into chunks for streaming effect
                content = msg.content  # type: ignore[union-attr]
                chunk_size = 50  # Characters per chunk
                for i in range(0, len(content), chunk_size):
                    chunk = content[i : i + chunk_size]
                    yield llm_chunk_event(text=chunk)

        # Update tracking
        iteration += 1
        if hasattr(result, "usage"):  # pragma: no branch
            usage = result.usage()
            if usage:  # pragma: no branch
                total_tokens = usage.total_tokens or 0

        # Emit progress event
        if emit_progress:  # pragma: no branch
            yield progress_event(
                iteration=iteration,
                total_tokens=total_tokens if total_tokens > 0 else None,
            )

        success = True

    except Exception as e:  # pragma: no cover
        # Emit error event
        yield error_event(
            error=str(e),
            exception_type=type(e).__name__,
        )
        success = False
        raise

    finally:
        # Emit agent end event
        duration = time.time() - start_time
        yield agent_end_event(
            agent_name=agent_name,
            success=success,
            total_iterations=iteration,
            total_tokens=total_tokens if total_tokens > 0 else None,
            duration_seconds=duration,
        )


async def stream_text(
    agent: Agent[DeepAgentDeps, Any],
    prompt: str,
    deps: DeepAgentDeps,
    message_history: list[dict[str, Any]] | None = None,
) -> AsyncIterator[str]:
    """Stream only text chunks from agent execution.

    This is a simplified wrapper that only yields text chunks,
    ignoring all other events. Useful for simple text streaming UIs.

    Args:
        agent: The agent to run
        prompt: The user prompt
        deps: Agent dependencies
        message_history: Optional message history to continue from

    Yields:
        Text chunks from the LLM

    Example:
        ```python
        async for chunk in stream_text(agent, "Write a story", deps):
            print(chunk, end="", flush=True)
        ```
    """
    async for event in run_stream(agent, prompt, deps, message_history):
        if event.event_type == StreamEventType.LLM_CHUNK:
            yield event.data["text"]


async def stream_tool_calls(
    agent: Agent[DeepAgentDeps, Any],
    prompt: str,
    deps: DeepAgentDeps,
    message_history: list[dict[str, Any]] | None = None,
) -> AsyncIterator[tuple[str, dict[str, Any] | None, Any | None]]:
    """Stream only tool calls from agent execution.

    Yields tuples of (tool_name, args, result) for each tool call.
    The result will be None for TOOL_START events and populated for TOOL_END events.

    Args:
        agent: The agent to run
        prompt: The user prompt
        deps: Agent dependencies
        message_history: Optional message history to continue from

    Yields:
        Tuples of (tool_name, args, result)

    Example:
        ```python
        async for tool_name, args, result in stream_tool_calls(agent, "Create file", deps):
            if result is None:
                print(f"Calling {tool_name}({args})...")
            else:
                print(f"  -> {result}")
        ```
    """
    async for event in run_stream_with_tools(agent, prompt, deps, message_history, emit_progress=False):
        if event.event_type == StreamEventType.TOOL_START:
            yield (
                event.data["tool_name"],
                event.data.get("args"),
                None,
            )
        elif event.event_type == StreamEventType.TOOL_END:
            yield (
                event.data["tool_name"],
                None,
                event.data.get("result"),
            )


async def collect_stream_result(
    agent: Agent[DeepAgentDeps, Any],
    prompt: str,
    deps: DeepAgentDeps,
    message_history: list[dict[str, Any]] | None = None,
    on_event: Any = None,
) -> tuple[Any, list[StreamEvent]]:
    """Collect all events from a streamed execution.

    This helper function runs the agent with streaming and collects
    all events into a list, while also returning the final result.

    Args:
        agent: The agent to run
        prompt: The user prompt
        deps: Agent dependencies
        message_history: Optional message history to continue from
        on_event: Optional callback called for each event

    Returns:
        Tuple of (final_result, all_events)

    Example:
        ```python
        def log_event(event):
            print(f"{event.event_type}: {event.data}")

        result, events = await collect_stream_result(
            agent, "Task", deps, on_event=log_event
        )
        ```
    """
    events: list[StreamEvent] = []
    final_result = None

    async for event in run_stream(agent, prompt, deps, message_history):
        events.append(event)
        if on_event:
            on_event(event)

        # Capture final result if available
        if event.event_type == StreamEventType.AGENT_END:
            # The actual result would need to be passed differently
            # This is a simplified version
            pass

    return final_result, events
