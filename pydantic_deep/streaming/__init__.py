"""Streaming updates for agent execution.

This module provides real-time streaming updates during agent execution,
including text chunks, tool calls, progress tracking, and error events.

Example:
    ```python
    from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend
    from pydantic_deep.streaming import run_stream, StreamEventType

    agent = create_deep_agent(model="openai:gpt-4o")
    deps = DeepAgentDeps(backend=StateBackend())

    # Stream all events
    async for event in run_stream(agent, "Write a story", deps):
        if event.event_type == StreamEventType.LLM_CHUNK:
            print(event.data["text"], end="", flush=True)
        elif event.event_type == StreamEventType.TOOL_START:
            print(f"\\n[Calling {event.data['tool_name']}]")

    # Or just stream text
    from pydantic_deep.streaming import stream_text

    async for chunk in stream_text(agent, "Hello", deps):
        print(chunk, end="", flush=True)
    ```
"""

from pydantic_deep.streaming.stream import (
    collect_stream_result,
    run_stream,
    run_stream_with_tools,
    stream_text,
    stream_tool_calls,
)
from pydantic_deep.streaming.types import (
    StreamEvent,
    StreamEventType,
    agent_end_event,
    agent_start_event,
    error_event,
    llm_chunk_event,
    partial_result_event,
    progress_event,
    tool_end_event,
    tool_start_event,
)

__all__ = [
    # Main streaming functions
    "run_stream",
    "run_stream_with_tools",
    "stream_text",
    "stream_tool_calls",
    "collect_stream_result",
    # Types
    "StreamEvent",
    "StreamEventType",
    # Event factories
    "llm_chunk_event",
    "tool_start_event",
    "tool_end_event",
    "progress_event",
    "partial_result_event",
    "error_event",
    "agent_start_event",
    "agent_end_event",
]
