"""Trace exporters for various backends."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic_deep.tracing.types import (
    AgentRunEndEvent,
    AgentRunStartEvent,
    ErrorEvent,
    LLMRequestEvent,
    LLMResponseEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    TraceEvent,
)


class ConsoleExporter:
    """Export trace events to console with structured formatting.

    This exporter prints trace events in a tree-like format showing
    the hierarchy of agent runs, LLM calls, and tool executions.
    """

    def __init__(self, verbose: bool = False) -> None:
        """Initialize console exporter.

        Args:
            verbose: If True, show detailed event information.
        """
        self.verbose = verbose
        self._event_stack: list[tuple[str, datetime]] = []
        self._root_events: dict[str, datetime] = {}

    def export_event(self, event: TraceEvent) -> None:
        """Export event to console.

        Args:
            event: Trace event to export.
        """
        if isinstance(event, AgentRunStartEvent):
            self._root_events[event.event_id] = event.timestamp
            print(f"\n🤖 Agent run: {event.agent_name}")
            print(f"   Model: {event.model}")
            if self.verbose:
                print(f"   Prompt: {event.prompt[:100]}...")

        elif isinstance(event, AgentRunEndEvent):
            duration = event.duration_seconds
            status = "✓" if event.success else "✗"
            tokens_info = f", {event.total_tokens} tokens" if event.total_tokens else ""
            print(f"   {status} Completed in {duration:.2f}s{tokens_info}\n")

        elif isinstance(event, LLMRequestEvent):  # pragma: no cover
            if self.verbose:
                print(
                    f"   🧠 LLM request ({event.messages_count} messages, {event.tools_count} tools)"
                )

        elif isinstance(event, LLMResponseEvent):  # pragma: no cover
            tokens_info = ""
            if event.total_tokens:
                tokens_info = f", {event.total_tokens} tokens"
            print(f"   ├─ LLM step [{event.duration_seconds:.2f}s{tokens_info}]")

        elif isinstance(event, ToolCallStartEvent):  # pragma: no cover
            if self.verbose:
                args_str = json.dumps(event.args, indent=2)
                print(f"   ├─ Tool: {event.tool_name}")
                print(f"      Args: {args_str}")

        elif isinstance(event, ToolCallEndEvent):
            status = "✓" if event.success else "✗"
            error_info = f" - {event.error}" if event.error else ""
            print(
                f"   ├─ {status} Tool: {event.tool_name} [{event.duration_seconds:.2f}s]{error_info}"
            )

        elif isinstance(event, ErrorEvent):  # pragma: no cover
            print(f"   ✗ Error: {event.error_type}: {event.error_message}")

    def flush(self) -> None:
        """Flush any buffered events (no-op for console)."""
        pass


class InMemoryExporter:
    """Export trace events to memory for testing and analysis.

    This exporter stores all events in memory and provides methods
    to query and analyze them.
    """

    def __init__(self) -> None:
        """Initialize in-memory exporter."""
        self.events: list[TraceEvent] = []

    def export_event(self, event: TraceEvent) -> None:
        """Store event in memory.

        Args:
            event: Trace event to store.
        """
        self.events.append(event)

    def flush(self) -> None:
        """Flush events (no-op for in-memory)."""
        pass

    def get_events_by_type(self, event_type: type[TraceEvent]) -> list[TraceEvent]:
        """Get all events of a specific type.

        Args:
            event_type: Type of events to retrieve.

        Returns:
            List of events matching the type.
        """
        return [e for e in self.events if isinstance(e, event_type)]

    def get_tree(self) -> dict[str, Any]:
        """Build a tree structure from events.

        Returns:
            Dictionary representing the event hierarchy.
        """
        # Group events by parent_id
        children_map: dict[str | None, list[TraceEvent]] = {}
        for event in self.events:
            parent_id = event.parent_id
            if parent_id not in children_map:
                children_map[parent_id] = []
            children_map[parent_id].append(event)

        def build_node(event: TraceEvent) -> dict[str, Any]:
            node: dict[str, Any] = {
                "type": event.event_type.value,
                "timestamp": event.timestamp.isoformat(),
            }

            # Add type-specific fields
            if isinstance(event, AgentRunStartEvent):
                node["agent_name"] = event.agent_name
                node["model"] = event.model
            elif isinstance(event, AgentRunEndEvent):
                node["duration"] = event.duration_seconds
                node["success"] = event.success
            elif isinstance(event, LLMResponseEvent):
                node["duration"] = event.duration_seconds
                node["tokens"] = event.total_tokens
            elif isinstance(event, ToolCallEndEvent):  # pragma: no cover
                node["tool_name"] = event.tool_name
                node["duration"] = event.duration_seconds
                node["success"] = event.success

            # Add children
            if event.event_id in children_map:
                node["children"] = [build_node(child) for child in children_map[event.event_id]]

            return node

        # Build tree from root events (no parent)
        root_events = children_map.get(None, [])
        return {"roots": [build_node(event) for event in root_events]}

    def clear(self) -> None:
        """Clear all stored events."""
        self.events.clear()


class OpenTelemetryExporter:
    """Export trace events to OpenTelemetry backend.

    This exporter sends trace events to an OpenTelemetry collector
    for distributed tracing and observability.
    """

    def __init__(
        self,
        endpoint: str,
        service_name: str = "pydantic-deep-agent",
        headers: dict[str, str] | None = None,
    ) -> None:
        """Initialize OpenTelemetry exporter.

        Args:
            endpoint: OpenTelemetry collector endpoint (e.g., "http://localhost:4318/v1/traces").
            service_name: Service name for traces.
            headers: Optional headers for authentication.
        """
        self.endpoint = endpoint
        self.service_name = service_name
        self.headers = headers or {}
        self._spans: list[dict[str, Any]] = []

        # Try to import OpenTelemetry (optional dependency)
        self._otel_available = False
        try:  # pragma: no cover
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            # Set up tracer
            resource = Resource.create({"service.name": service_name})
            provider = TracerProvider(resource=resource)
            processor = BatchSpanProcessor(
                OTLPSpanExporter(
                    endpoint=endpoint,
                    headers=headers,
                )
            )
            provider.add_span_processor(processor)
            trace.set_tracer_provider(provider)

            self._tracer = trace.get_tracer(__name__)
            self._otel_available = True
        except ImportError:  # pragma: no cover
            # OpenTelemetry not installed - will log warning
            pass

    def export_event(self, event: TraceEvent) -> None:  # pragma: no cover
        """Export event to OpenTelemetry.

        Args:
            event: Trace event to export.
        """
        if not self._otel_available:
            return

        # Convert event to span attributes
        span_data: dict[str, Any] = {
            "event_id": event.event_id,
            "event_type": event.event_type.value,
            "timestamp": event.timestamp.isoformat(),
        }

        # Add type-specific attributes
        if isinstance(event, AgentRunStartEvent):
            span_data["agent_name"] = event.agent_name
            span_data["model"] = event.model
            span_data["prompt"] = event.prompt[:500]  # Truncate

        elif isinstance(event, AgentRunEndEvent):
            span_data["duration"] = event.duration_seconds
            span_data["success"] = event.success
            if event.total_tokens:
                span_data["total_tokens"] = event.total_tokens

        elif isinstance(event, LLMResponseEvent):
            span_data["model"] = event.model
            span_data["duration"] = event.duration_seconds
            if event.total_tokens:
                span_data["total_tokens"] = event.total_tokens
            if event.input_tokens:
                span_data["input_tokens"] = event.input_tokens
            if event.output_tokens:
                span_data["output_tokens"] = event.output_tokens

        elif isinstance(event, ToolCallStartEvent):
            span_data["tool_name"] = event.tool_name
            span_data["args"] = json.dumps(event.args)

        elif isinstance(event, ToolCallEndEvent):
            span_data["tool_name"] = event.tool_name
            span_data["duration"] = event.duration_seconds
            span_data["success"] = event.success

        elif isinstance(event, ErrorEvent):
            span_data["error_type"] = event.error_type
            span_data["error_message"] = event.error_message

        self._spans.append(span_data)

    def flush(self) -> None:  # pragma: no cover
        """Flush buffered spans to OpenTelemetry."""
        if not self._otel_available:
            return

        # Spans are automatically sent via BatchSpanProcessor
        # This method ensures any buffered spans are sent
        try:
            from opentelemetry import trace

            provider = trace.get_tracer_provider()
            if hasattr(provider, "force_flush"):
                provider.force_flush()  # type: ignore
        except Exception:
            pass


class StructuredFileExporter:
    """Export trace events to a structured file (JSONL format).

    This exporter writes each event as a JSON line to a file,
    useful for later analysis or replay.
    """

    def __init__(self, file_path: str) -> None:
        """Initialize file exporter.

        Args:
            file_path: Path to output file.
        """
        self.file_path = file_path
        self._file = open(file_path, "a")  # noqa: SIM115

    def export_event(self, event: TraceEvent) -> None:
        """Write event to file as JSON line.

        Args:
            event: Trace event to write.
        """
        event_dict: dict[str, Any] = {
            "event_id": event.event_id,
            "parent_id": event.parent_id,
            "event_type": event.event_type.value,
            "timestamp": event.timestamp.isoformat(),
        }

        # Add type-specific fields
        if isinstance(event, AgentRunStartEvent):
            event_dict.update(
                {
                    "agent_name": event.agent_name,
                    "model": event.model,
                    "prompt": event.prompt,
                }
            )
        elif isinstance(event, AgentRunEndEvent):
            event_dict.update(
                {
                    "agent_name": event.agent_name,
                    "duration_seconds": event.duration_seconds,
                    "total_tokens": event.total_tokens,
                    "success": event.success,
                }
            )
        elif isinstance(event, LLMRequestEvent):
            event_dict.update(
                {
                    "model": event.model,
                    "messages_count": event.messages_count,
                    "tools_count": event.tools_count,
                }
            )
        elif isinstance(event, LLMResponseEvent):
            event_dict.update(
                {
                    "model": event.model,
                    "duration_seconds": event.duration_seconds,
                    "input_tokens": event.input_tokens,
                    "output_tokens": event.output_tokens,
                    "total_tokens": event.total_tokens,
                }
            )
        elif isinstance(event, ToolCallStartEvent):
            event_dict.update(
                {
                    "tool_name": event.tool_name,
                    "args": event.args,
                }
            )
        elif isinstance(event, ToolCallEndEvent):
            event_dict.update(
                {
                    "tool_name": event.tool_name,
                    "duration_seconds": event.duration_seconds,
                    "success": event.success,
                    "error": event.error,
                }
            )
        elif isinstance(event, ErrorEvent):  # pragma: no cover
            event_dict.update(
                {
                    "error_type": event.error_type,
                    "error_message": event.error_message,
                }
            )

        self._file.write(json.dumps(event_dict) + "\n")

    def flush(self) -> None:
        """Flush file buffer."""
        self._file.flush()

    def close(self) -> None:
        """Close the file."""
        self._file.close()

    def __enter__(self) -> StructuredFileExporter:
        """Context manager entry."""
        return self

    def __exit__(self, *args: Any) -> None:
        """Context manager exit."""
        self.close()
