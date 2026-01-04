"""Trace context for collecting and managing trace events."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from pydantic_deep.tracing.types import (
    AgentRunEndEvent,
    AgentRunStartEvent,
    ErrorEvent,
    EventType,
    LLMRequestEvent,
    LLMResponseEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    TraceEvent,
    TraceExporterProtocol,
)


class TraceContext:
    """Context for collecting trace events during agent execution.

    This class manages the lifecycle of trace events and coordinates
    with exporters to send events to backends.
    """

    def __init__(self, exporters: list[TraceExporterProtocol] | None = None) -> None:
        """Initialize trace context.

        Args:
            exporters: List of trace exporters to send events to.
        """
        self.exporters = exporters or []
        self.events: list[TraceEvent] = []
        self._current_parent_id: str | None = None

    def _generate_event_id(self) -> str:
        """Generate unique event ID."""
        return str(uuid.uuid4())

    def _emit(self, event: TraceEvent) -> None:
        """Emit event to all exporters and store locally."""
        self.events.append(event)
        for exporter in self.exporters:
            exporter.export_event(event)

    @contextmanager
    def agent_run(
        self, agent_name: str, prompt: str, model: str
    ) -> Iterator[str]:
        """Context manager for tracing an agent run.

        Args:
            agent_name: Name of the agent.
            prompt: User prompt/query.
            model: Model being used.

        Yields:
            Event ID for this agent run.
        """
        event_id = self._generate_event_id()
        start_time = datetime.now()

        start_event = AgentRunStartEvent(
            event_id=event_id,
            parent_id=self._current_parent_id,
            timestamp=start_time,
            event_type=EventType.AGENT_RUN_START,
            agent_name=agent_name,
            prompt=prompt,
            model=model,
        )
        self._emit(start_event)

        # Set as parent for nested events
        prev_parent = self._current_parent_id
        self._current_parent_id = event_id

        try:
            yield event_id
        except Exception as e:
            # Emit error event
            error_event = ErrorEvent(
                event_id=self._generate_event_id(),
                parent_id=event_id,
                timestamp=datetime.now(),
                event_type=EventType.ERROR,
                error_type=type(e).__name__,
                error_message=str(e),
            )
            self._emit(error_event)

            # Still emit end event with failure
            end_event = AgentRunEndEvent(
                event_id=self._generate_event_id(),
                parent_id=self._current_parent_id,
                timestamp=datetime.now(),
                event_type=EventType.AGENT_RUN_END,
                agent_name=agent_name,
                output="",
                duration_seconds=(datetime.now() - start_time).total_seconds(),
                success=False,
            )
            self._emit(end_event)
            raise
        finally:  # pragma: no cover
            # Restore previous parent
            self._current_parent_id = prev_parent

    def agent_run_end(
        self,
        agent_name: str,
        output: str | dict[str, Any],
        start_time: datetime,
        total_tokens: int | None = None,
    ) -> None:
        """Record agent run completion.

        Args:
            agent_name: Name of the agent.
            output: Agent output.
            start_time: When the run started.
            total_tokens: Total tokens used.
        """
        duration = (datetime.now() - start_time).total_seconds()
        event = AgentRunEndEvent(
            event_id=self._generate_event_id(),
            parent_id=self._current_parent_id,
            timestamp=datetime.now(),
            event_type=EventType.AGENT_RUN_END,
            agent_name=agent_name,
            output=output,
            duration_seconds=duration,
            total_tokens=total_tokens,
            success=True,
        )
        self._emit(event)

    def llm_request(self, model: str, messages_count: int, tools_count: int) -> str:
        """Record LLM request.

        Args:
            model: Model being called.
            messages_count: Number of messages in the request.
            tools_count: Number of tools available.

        Returns:
            Event ID for this request (use for matching with response).
        """
        event_id = self._generate_event_id()
        event = LLMRequestEvent(
            event_id=event_id,
            parent_id=self._current_parent_id,
            timestamp=datetime.now(),
            event_type=EventType.LLM_REQUEST,
            model=model,
            messages_count=messages_count,
            tools_count=tools_count,
        )
        self._emit(event)
        return event_id

    def llm_response(
        self,
        model: str,
        start_time: datetime,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        finish_reason: str | None = None,
        request_event_id: str | None = None,
    ) -> None:
        """Record LLM response.

        Args:
            model: Model that responded.
            start_time: When the request started.
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.
            finish_reason: Finish reason from the model.
            request_event_id: ID of the corresponding request event.
        """
        duration = (datetime.now() - start_time).total_seconds()
        total_tokens = None
        if input_tokens is not None and output_tokens is not None:  # pragma: no branch
            total_tokens = input_tokens + output_tokens

        event = LLMResponseEvent(
            event_id=self._generate_event_id(),
            parent_id=request_event_id or self._current_parent_id,
            timestamp=datetime.now(),
            event_type=EventType.LLM_RESPONSE,
            model=model,
            duration_seconds=duration,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            finish_reason=finish_reason,
        )
        self._emit(event)

    @contextmanager
    def tool_call(self, tool_name: str, args: dict[str, Any]) -> Iterator[str]:
        """Context manager for tracing a tool call.

        Args:
            tool_name: Name of the tool.
            args: Tool arguments.

        Yields:
            Event ID for this tool call.
        """
        event_id = self._generate_event_id()
        start_time = datetime.now()

        start_event = ToolCallStartEvent(
            event_id=event_id,
            parent_id=self._current_parent_id,
            timestamp=start_time,
            event_type=EventType.TOOL_CALL_START,
            tool_name=tool_name,
            args=args,
        )
        self._emit(start_event)

        # Set as parent for nested events
        prev_parent = self._current_parent_id
        self._current_parent_id = event_id

        error_occurred = False
        try:
            yield event_id
        except Exception as e:
            error_occurred = True
            # Emit error event
            error_event = ErrorEvent(
                event_id=self._generate_event_id(),
                parent_id=event_id,
                timestamp=datetime.now(),
                event_type=EventType.ERROR,
                error_type=type(e).__name__,
                error_message=str(e),
            )
            self._emit(error_event)

            # Emit end event with failure
            duration = (datetime.now() - start_time).total_seconds()
            end_event = ToolCallEndEvent(
                event_id=self._generate_event_id(),
                parent_id=prev_parent,
                timestamp=datetime.now(),
                event_type=EventType.TOOL_CALL_END,
                tool_name=tool_name,
                duration_seconds=duration,
                error=str(e),
                success=False,
            )
            self._emit(end_event)
            raise
        finally:  # pragma: no cover
            # Restore previous parent
            self._current_parent_id = prev_parent  # pragma: no cover

            # If no error occurred, the tool must call tool_call_end explicitly
            # to provide the result

    def tool_call_end(
        self, tool_name: str, start_time: datetime, result: Any = None
    ) -> None:
        """Record successful tool call completion.

        Args:
            tool_name: Name of the tool.
            start_time: When the call started.
            result: Tool result.
        """
        duration = (datetime.now() - start_time).total_seconds()
        event = ToolCallEndEvent(
            event_id=self._generate_event_id(),
            parent_id=self._current_parent_id,
            timestamp=datetime.now(),
            event_type=EventType.TOOL_CALL_END,
            tool_name=tool_name,
            duration_seconds=duration,
            result=result,
            success=True,
        )
        self._emit(event)

    def flush(self) -> None:
        """Flush all exporters."""
        for exporter in self.exporters:
            exporter.flush()

    def get_summary(self) -> dict[str, Any]:
        """Get summary statistics from collected events.

        Returns:
            Dictionary with summary metrics (total_duration, tool_calls, etc.).
        """
        summary: dict[str, Any] = {
            "total_events": len(self.events),
            "tool_calls": 0,
            "llm_requests": 0,
            "total_tokens": 0,
            "errors": 0,
        }

        for event in self.events:
            if isinstance(event, ToolCallEndEvent):
                summary["tool_calls"] += 1
            elif isinstance(event, LLMResponseEvent):
                summary["llm_requests"] += 1
                if event.total_tokens:  # pragma: no branch
                    summary["total_tokens"] += event.total_tokens
            elif isinstance(event, ErrorEvent):
                summary["errors"] += 1

        return summary
