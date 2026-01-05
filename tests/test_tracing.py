"""Tests for tracing functionality."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from pydantic_deep.tracing import (
    AgentRunEndEvent,
    AgentRunStartEvent,
    ConsoleExporter,
    ErrorEvent,
    InMemoryExporter,
    LLMRequestEvent,
    LLMResponseEvent,
    OpenTelemetryExporter,
    StructuredFileExporter,
    ToolCallEndEvent,
    ToolCallStartEvent,
    TraceContext,
)
from pydantic_deep.tracing.types import EventType


class TestTraceEvents:
    """Test trace event types."""

    def test_agent_run_start_event(self) -> None:
        """Test AgentRunStartEvent."""
        event = AgentRunStartEvent(
            event_id="test-1",
            parent_id=None,
            timestamp=datetime.now(),
            event_type=EventType.AGENT_RUN_START,
            agent_name="test-agent",
            prompt="Test prompt",
            model="gpt-4",
        )

        assert event.event_type == EventType.AGENT_RUN_START
        assert event.agent_name == "test-agent"
        assert event.prompt == "Test prompt"
        assert event.model == "gpt-4"

    def test_agent_run_end_event(self) -> None:
        """Test AgentRunEndEvent."""
        event = AgentRunEndEvent(
            event_id="test-2",
            parent_id="test-1",
            timestamp=datetime.now(),
            event_type=EventType.AGENT_RUN_END,
            agent_name="test-agent",
            output="Test output",
            duration_seconds=1.5,
            total_tokens=100,
            success=True,
        )

        assert event.event_type == EventType.AGENT_RUN_END
        assert event.duration_seconds == 1.5
        assert event.total_tokens == 100
        assert event.success is True

    def test_llm_request_event(self) -> None:
        """Test LLMRequestEvent."""
        event = LLMRequestEvent(
            event_id="test-3",
            parent_id="test-1",
            timestamp=datetime.now(),
            event_type=EventType.LLM_REQUEST,
            model="gpt-4",
            messages_count=5,
            tools_count=3,
        )

        assert event.event_type == EventType.LLM_REQUEST
        assert event.model == "gpt-4"
        assert event.messages_count == 5
        assert event.tools_count == 3

    def test_llm_response_event(self) -> None:
        """Test LLMResponseEvent."""
        event = LLMResponseEvent(
            event_id="test-4",
            parent_id="test-3",
            timestamp=datetime.now(),
            event_type=EventType.LLM_RESPONSE,
            model="gpt-4",
            duration_seconds=0.8,
            input_tokens=50,
            output_tokens=30,
            total_tokens=80,
        )

        assert event.event_type == EventType.LLM_RESPONSE
        assert event.duration_seconds == 0.8
        assert event.input_tokens == 50
        assert event.output_tokens == 30
        assert event.total_tokens == 80

    def test_tool_call_events(self) -> None:
        """Test tool call events."""
        start_event = ToolCallStartEvent(
            event_id="test-5",
            parent_id="test-1",
            timestamp=datetime.now(),
            event_type=EventType.TOOL_CALL_START,
            tool_name="read_file",
            args={"path": "/test.txt"},
        )

        assert start_event.event_type == EventType.TOOL_CALL_START
        assert start_event.tool_name == "read_file"
        assert start_event.args == {"path": "/test.txt"}

        end_event = ToolCallEndEvent(
            event_id="test-6",
            parent_id="test-1",
            timestamp=datetime.now(),
            event_type=EventType.TOOL_CALL_END,
            tool_name="read_file",
            duration_seconds=0.1,
            result="File content",
            success=True,
        )

        assert end_event.event_type == EventType.TOOL_CALL_END
        assert end_event.duration_seconds == 0.1
        assert end_event.success is True

    def test_error_event(self) -> None:
        """Test ErrorEvent."""
        event = ErrorEvent(
            event_id="test-7",
            parent_id="test-1",
            timestamp=datetime.now(),
            event_type=EventType.ERROR,
            error_type="ValueError",
            error_message="Invalid input",
            traceback="Traceback...",
        )

        assert event.event_type == EventType.ERROR
        assert event.error_type == "ValueError"
        assert event.error_message == "Invalid input"


class TestTraceContext:
    """Test TraceContext."""

    def test_agent_run_context(self) -> None:
        """Test agent run context manager."""
        ctx = TraceContext()

        with ctx.agent_run("test-agent", "Test prompt", "gpt-4") as run_id:
            assert run_id is not None
            # Verify start event was emitted
            assert len(ctx.events) == 1
            assert isinstance(ctx.events[0], AgentRunStartEvent)
            assert ctx.events[0].agent_name == "test-agent"

    def test_agent_run_end(self) -> None:
        """Test agent run end recording."""
        ctx = TraceContext()
        start_time = datetime.now()

        with ctx.agent_run("test-agent", "Test", "gpt-4"):
            pass  # Do nothing

        ctx.agent_run_end("test-agent", "Output", start_time, total_tokens=100)

        # Should have start event + end event
        assert len(ctx.events) == 2
        assert isinstance(ctx.events[1], AgentRunEndEvent)
        assert ctx.events[1].total_tokens == 100

    def test_llm_request_response(self) -> None:
        """Test LLM request/response recording."""
        ctx = TraceContext()

        request_id = ctx.llm_request("gpt-4", 5, 3)
        assert len(ctx.events) == 1

        ctx.llm_response(
            "gpt-4",
            datetime.now(),
            input_tokens=50,
            output_tokens=30,
            request_event_id=request_id,
        )
        assert len(ctx.events) == 2
        assert isinstance(ctx.events[1], LLMResponseEvent)

    def test_tool_call_context(self) -> None:
        """Test tool call context manager."""
        ctx = TraceContext()

        start_time = datetime.now()
        with ctx.tool_call("read_file", {"path": "/test.txt"}):
            # Verify start event
            assert len(ctx.events) == 1
            assert isinstance(ctx.events[0], ToolCallStartEvent)

        # After context, manually record end
        ctx.tool_call_end("read_file", start_time, result="content")
        assert len(ctx.events) == 2
        assert isinstance(ctx.events[1], ToolCallEndEvent)

    def test_tool_call_error_handling(self) -> None:
        """Test tool call error handling."""
        ctx = TraceContext()

        with pytest.raises(ValueError), ctx.tool_call("failing_tool", {}):
            raise ValueError("Tool failed")

        # Should have start + error + end events
        assert len(ctx.events) == 3
        assert isinstance(ctx.events[0], ToolCallStartEvent)
        assert isinstance(ctx.events[1], ErrorEvent)
        assert isinstance(ctx.events[2], ToolCallEndEvent)
        assert ctx.events[2].success is False

    def test_get_summary(self) -> None:
        """Test summary generation."""
        ctx = TraceContext()

        # Simulate some events
        ctx.llm_request("gpt-4", 5, 3)
        ctx.llm_response("gpt-4", datetime.now(), input_tokens=50, output_tokens=30)

        with ctx.tool_call("read_file", {}):
            pass
        ctx.tool_call_end("read_file", datetime.now())

        # Add an error event
        ctx.events.append(
            ErrorEvent(
                event_id="error-1",
                parent_id=None,
                timestamp=datetime.now(),
                event_type=EventType.ERROR,
                error_type="TestError",
                error_message="Test",
            )
        )

        summary = ctx.get_summary()
        assert summary["total_events"] == 5
        assert summary["llm_requests"] == 1
        assert summary["tool_calls"] == 1
        assert summary["total_tokens"] == 80
        assert summary["errors"] == 1


class TestConsoleExporter:
    """Test ConsoleExporter."""

    def test_export_agent_run_events(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test console export of agent run events."""
        exporter = ConsoleExporter()

        start_event = AgentRunStartEvent(
            event_id="1",
            parent_id=None,
            timestamp=datetime.now(),
            event_type=EventType.AGENT_RUN_START,
            agent_name="test-agent",
            prompt="Test",
            model="gpt-4",
        )
        exporter.export_event(start_event)

        captured = capsys.readouterr()
        assert "test-agent" in captured.out
        assert "gpt-4" in captured.out

        end_event = AgentRunEndEvent(
            event_id="2",
            parent_id="1",
            timestamp=datetime.now(),
            event_type=EventType.AGENT_RUN_END,
            agent_name="test-agent",
            output="Done",
            duration_seconds=1.5,
            total_tokens=100,
        )
        exporter.export_event(end_event)

        captured = capsys.readouterr()
        assert "1.5" in captured.out
        assert "100 tokens" in captured.out

    def test_export_tool_events(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test console export of tool events."""
        exporter = ConsoleExporter()

        end_event = ToolCallEndEvent(
            event_id="1",
            parent_id=None,
            timestamp=datetime.now(),
            event_type=EventType.TOOL_CALL_END,
            tool_name="read_file",
            duration_seconds=0.1,
            success=True,
        )
        exporter.export_event(end_event)

        captured = capsys.readouterr()
        assert "read_file" in captured.out
        assert "0.1" in captured.out


class TestInMemoryExporter:
    """Test InMemoryExporter."""

    def test_stores_events(self) -> None:
        """Test that events are stored in memory."""
        exporter = InMemoryExporter()

        event1 = AgentRunStartEvent(
            event_id="1",
            parent_id=None,
            timestamp=datetime.now(),
            event_type=EventType.AGENT_RUN_START,
            agent_name="test",
            prompt="Test",
            model="gpt-4",
        )
        exporter.export_event(event1)

        assert len(exporter.events) == 1
        assert exporter.events[0] == event1

    def test_get_events_by_type(self) -> None:
        """Test filtering events by type."""
        exporter = InMemoryExporter()

        exporter.export_event(
            AgentRunStartEvent(
                event_id="1",
                parent_id=None,
                timestamp=datetime.now(),
                event_type=EventType.AGENT_RUN_START,
                agent_name="test",
                prompt="Test",
                model="gpt-4",
            )
        )
        exporter.export_event(
            ToolCallEndEvent(
                event_id="2",
                parent_id="1",
                timestamp=datetime.now(),
                event_type=EventType.TOOL_CALL_END,
                tool_name="read_file",
                duration_seconds=0.1,
            )
        )

        agent_events = exporter.get_events_by_type(AgentRunStartEvent)
        assert len(agent_events) == 1

        tool_events = exporter.get_events_by_type(ToolCallEndEvent)
        assert len(tool_events) == 1

    def test_get_tree(self) -> None:
        """Test tree building from events."""
        exporter = InMemoryExporter()

        # Create hierarchical events with all types
        exporter.export_event(
            AgentRunStartEvent(
                event_id="run-1",
                parent_id=None,
                timestamp=datetime.now(),
                event_type=EventType.AGENT_RUN_START,
                agent_name="test",
                prompt="Test",
                model="gpt-4",
            )
        )
        exporter.export_event(
            AgentRunEndEvent(
                event_id="run-end-1",
                parent_id="run-1",
                timestamp=datetime.now(),
                event_type=EventType.AGENT_RUN_END,
                agent_name="test",
                output="Done",
                duration_seconds=1.0,
                success=True,
            )
        )
        exporter.export_event(
            LLMResponseEvent(
                event_id="llm-1",
                parent_id="run-1",
                timestamp=datetime.now(),
                event_type=EventType.LLM_RESPONSE,
                model="gpt-4",
                duration_seconds=0.5,
                total_tokens=100,
            )
        )
        exporter.export_event(
            ToolCallEndEvent(
                event_id="tool-1",
                parent_id="run-1",
                timestamp=datetime.now(),
                event_type=EventType.TOOL_CALL_END,
                tool_name="read_file",
                duration_seconds=0.1,
                success=True,
            )
        )

        tree = exporter.get_tree()
        assert "roots" in tree
        assert len(tree["roots"]) == 1
        assert tree["roots"][0]["type"] == "agent_run_start"
        assert "children" in tree["roots"][0]
        assert len(tree["roots"][0]["children"]) == 3

        # Verify child event types are preserved
        child_types = [child["type"] for child in tree["roots"][0]["children"]]
        assert "agent_run_end" in child_types
        assert "llm_response" in child_types
        assert "tool_call_end" in child_types

    def test_clear(self) -> None:
        """Test clearing stored events."""
        exporter = InMemoryExporter()

        exporter.export_event(
            ErrorEvent(
                event_id="1",
                parent_id=None,
                timestamp=datetime.now(),
                event_type=EventType.ERROR,
                error_type="TestError",
                error_message="Test",
            )
        )
        assert len(exporter.events) == 1

        exporter.clear()
        assert len(exporter.events) == 0


class TestStructuredFileExporter:
    """Test StructuredFileExporter."""

    def test_exports_to_file(self) -> None:
        """Test exporting events to JSONL file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = str(Path(tmpdir) / "trace.jsonl")

            with StructuredFileExporter(file_path) as exporter:
                exporter.export_event(
                    AgentRunStartEvent(
                        event_id="1",
                        parent_id=None,
                        timestamp=datetime.now(),
                        event_type=EventType.AGENT_RUN_START,
                        agent_name="test",
                        prompt="Test",
                        model="gpt-4",
                    )
                )
                exporter.export_event(
                    ToolCallEndEvent(
                        event_id="2",
                        parent_id="1",
                        timestamp=datetime.now(),
                        event_type=EventType.TOOL_CALL_END,
                        tool_name="read_file",
                        duration_seconds=0.1,
                    )
                )

            # Read and verify
            with open(file_path) as f:
                lines = f.readlines()

            assert len(lines) == 2

            event1 = json.loads(lines[0])
            assert event1["event_type"] == "agent_run_start"
            assert event1["agent_name"] == "test"

            event2 = json.loads(lines[1])
            assert event2["event_type"] == "tool_call_end"
            assert event2["tool_name"] == "read_file"

    def test_exports_all_event_types(self) -> None:
        """Test exporting all event types to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = str(Path(tmpdir) / "trace.jsonl")

            with StructuredFileExporter(file_path) as exporter:
                events = [
                    AgentRunStartEvent(
                        event_id="1",
                        parent_id=None,
                        timestamp=datetime.now(),
                        event_type=EventType.AGENT_RUN_START,
                        agent_name="test",
                        prompt="Test",
                        model="gpt-4",
                    ),
                    AgentRunEndEvent(
                        event_id="2",
                        parent_id="1",
                        timestamp=datetime.now(),
                        event_type=EventType.AGENT_RUN_END,
                        agent_name="test",
                        output="Done",
                        duration_seconds=1.0,
                        total_tokens=100,
                    ),
                    LLMRequestEvent(
                        event_id="3",
                        parent_id="1",
                        timestamp=datetime.now(),
                        event_type=EventType.LLM_REQUEST,
                        model="gpt-4",
                        messages_count=5,
                        tools_count=3,
                    ),
                    LLMResponseEvent(
                        event_id="4",
                        parent_id="3",
                        timestamp=datetime.now(),
                        event_type=EventType.LLM_RESPONSE,
                        model="gpt-4",
                        duration_seconds=0.5,
                        input_tokens=50,
                        output_tokens=30,
                        total_tokens=80,
                    ),
                    ToolCallStartEvent(
                        event_id="5",
                        parent_id="1",
                        timestamp=datetime.now(),
                        event_type=EventType.TOOL_CALL_START,
                        tool_name="read_file",
                        args={"path": "/test.txt"},
                    ),
                    ToolCallEndEvent(
                        event_id="6",
                        parent_id="1",
                        timestamp=datetime.now(),
                        event_type=EventType.TOOL_CALL_END,
                        tool_name="read_file",
                        duration_seconds=0.1,
                        success=True,
                        error=None,
                    ),
                    ErrorEvent(
                        event_id="7",
                        parent_id="1",
                        timestamp=datetime.now(),
                        event_type=EventType.ERROR,
                        error_type="ValueError",
                        error_message="Test error",
                    ),
                ]

                for event in events:
                    exporter.export_event(event)

                exporter.flush()

            # Read and verify all event types were written
            with open(file_path) as f:
                lines = f.readlines()

            assert len(lines) == 7
            event_types = [json.loads(line)["event_type"] for line in lines]
            assert "agent_run_start" in event_types
            assert "agent_run_end" in event_types
            assert "llm_request" in event_types
            assert "llm_response" in event_types
            assert "tool_call_start" in event_types
            assert "tool_call_end" in event_types
            assert "error" in event_types


class TestTraceContextWithExporters:
    """Test TraceContext with multiple exporters."""

    def test_multiple_exporters(self) -> None:
        """Test that events are sent to all exporters."""
        mem_exporter1 = InMemoryExporter()
        mem_exporter2 = InMemoryExporter()

        ctx = TraceContext(exporters=[mem_exporter1, mem_exporter2])

        with ctx.agent_run("test", "Test", "gpt-4"):
            pass

        # Both exporters should receive the event
        assert len(mem_exporter1.events) == 1
        assert len(mem_exporter2.events) == 1

    def test_flush_calls_all_exporters(self) -> None:
        """Test that flush is called on all exporters."""

        class MockExporter:
            def __init__(self) -> None:
                self.flushed = False

            def export_event(self, event: object) -> None:
                pass

            def flush(self) -> None:
                self.flushed = True

        exporter1 = MockExporter()
        exporter2 = MockExporter()

        ctx = TraceContext(exporters=[exporter1, exporter2])  # type: ignore
        ctx.flush()

        assert exporter1.flushed is True
        assert exporter2.flushed is True

    def test_agent_run_error_handling(self) -> None:
        """Test error handling in agent run context."""
        ctx = TraceContext()

        with pytest.raises(ValueError), ctx.agent_run("test", "Test", "gpt-4"):
            raise ValueError("Test error")

        # Should have start + error + end events
        assert len(ctx.events) == 3
        assert isinstance(ctx.events[0], AgentRunStartEvent)
        assert isinstance(ctx.events[1], ErrorEvent)
        assert isinstance(ctx.events[2], AgentRunEndEvent)


class TestConsoleExporterVerbose:
    """Test ConsoleExporter verbose mode."""

    def test_verbose_mode(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test verbose console output."""
        exporter = ConsoleExporter(verbose=True)

        # Test verbose agent run
        start_event = AgentRunStartEvent(
            event_id="1",
            parent_id=None,
            timestamp=datetime.now(),
            event_type=EventType.AGENT_RUN_START,
            agent_name="test-agent",
            prompt="Test prompt for verbose mode",
            model="gpt-4",
        )
        exporter.export_event(start_event)
        captured = capsys.readouterr()
        assert "Prompt:" in captured.out

        # Test verbose LLM request
        llm_req = LLMRequestEvent(
            event_id="2",
            parent_id="1",
            timestamp=datetime.now(),
            event_type=EventType.LLM_REQUEST,
            model="gpt-4",
            messages_count=5,
            tools_count=3,
        )
        exporter.export_event(llm_req)
        captured = capsys.readouterr()
        assert "LLM request" in captured.out

        # Test verbose tool call start
        tool_start = ToolCallStartEvent(
            event_id="3",
            parent_id="1",
            timestamp=datetime.now(),
            event_type=EventType.TOOL_CALL_START,
            tool_name="read_file",
            args={"path": "/test.txt"},
        )
        exporter.export_event(tool_start)
        captured = capsys.readouterr()
        assert "Tool:" in captured.out
        assert "Args:" in captured.out

    def test_llm_response_without_tokens(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test LLM response without token info."""
        exporter = ConsoleExporter()

        event = LLMResponseEvent(
            event_id="1",
            parent_id=None,
            timestamp=datetime.now(),
            event_type=EventType.LLM_RESPONSE,
            model="gpt-4",
            duration_seconds=0.5,
        )
        exporter.export_event(event)
        captured = capsys.readouterr()
        assert "0.5" in captured.out

    def test_tool_call_with_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test tool call end event with error."""
        exporter = ConsoleExporter()

        event = ToolCallEndEvent(
            event_id="1",
            parent_id=None,
            timestamp=datetime.now(),
            event_type=EventType.TOOL_CALL_END,
            tool_name="failing_tool",
            duration_seconds=0.1,
            error="Something went wrong",
            success=False,
        )
        exporter.export_event(event)
        captured = capsys.readouterr()
        assert "failing_tool" in captured.out
        assert "Something went wrong" in captured.out

    def test_error_event_export(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Test error event export."""
        exporter = ConsoleExporter()

        event = ErrorEvent(
            event_id="1",
            parent_id=None,
            timestamp=datetime.now(),
            event_type=EventType.ERROR,
            error_type="ValueError",
            error_message="Test error",
        )
        exporter.export_event(event)
        captured = capsys.readouterr()
        assert "ValueError" in captured.out
        assert "Test error" in captured.out


class TestOpenTelemetryExporter:
    """Test OpenTelemetryExporter."""

    def test_export_without_otel_installed(self) -> None:
        """Test that exporter handles missing OpenTelemetry gracefully."""
        exporter = OpenTelemetryExporter(
            endpoint="http://localhost:4318/v1/traces",
            service_name="test-service",
        )

        # Should not crash even if OTel is not available
        event = AgentRunStartEvent(
            event_id="1",
            parent_id=None,
            timestamp=datetime.now(),
            event_type=EventType.AGENT_RUN_START,
            agent_name="test",
            prompt="Test",
            model="gpt-4",
        )
        exporter.export_event(event)
        exporter.flush()

        # Verify events are buffered even without OTel
        assert len(exporter._spans) == 1

    def test_export_all_event_types(self) -> None:
        """Test exporting all event types to OTel."""
        exporter = OpenTelemetryExporter(
            endpoint="http://localhost:4318/v1/traces",
            headers={"Authorization": "Bearer token"},
        )

        events = [
            AgentRunStartEvent(
                event_id="1",
                parent_id=None,
                timestamp=datetime.now(),
                event_type=EventType.AGENT_RUN_START,
                agent_name="test",
                prompt="Test",
                model="gpt-4",
            ),
            AgentRunEndEvent(
                event_id="2",
                parent_id="1",
                timestamp=datetime.now(),
                event_type=EventType.AGENT_RUN_END,
                agent_name="test",
                output="Done",
                duration_seconds=1.0,
                total_tokens=100,
            ),
            LLMRequestEvent(
                event_id="3",
                parent_id="1",
                timestamp=datetime.now(),
                event_type=EventType.LLM_REQUEST,
                model="gpt-4",
                messages_count=5,
                tools_count=3,
            ),
            LLMResponseEvent(
                event_id="4",
                parent_id="3",
                timestamp=datetime.now(),
                event_type=EventType.LLM_RESPONSE,
                model="gpt-4",
                duration_seconds=0.5,
                input_tokens=50,
                output_tokens=30,
                total_tokens=80,
            ),
            ToolCallStartEvent(
                event_id="5",
                parent_id="1",
                timestamp=datetime.now(),
                event_type=EventType.TOOL_CALL_START,
                tool_name="read_file",
                args={"path": "/test.txt"},
            ),
            ToolCallEndEvent(
                event_id="6",
                parent_id="1",
                timestamp=datetime.now(),
                event_type=EventType.TOOL_CALL_END,
                tool_name="read_file",
                duration_seconds=0.1,
                success=True,
            ),
            ErrorEvent(
                event_id="7",
                parent_id="1",
                timestamp=datetime.now(),
                event_type=EventType.ERROR,
                error_type="ValueError",
                error_message="Test error",
            ),
        ]

        for event in events:
            exporter.export_event(event)

        assert len(exporter._spans) == 7
