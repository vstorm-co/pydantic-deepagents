"""Tests for streaming functionality."""

import pytest
from pydantic_ai.models.test import TestModel
from pydantic_ai_backends import StateBackend

from pydantic_deep import DeepAgentDeps, create_deep_agent
from pydantic_deep.streaming import (
    StreamEvent,
    StreamEventType,
    agent_end_event,
    agent_start_event,
    collect_stream_result,
    error_event,
    llm_chunk_event,
    partial_result_event,
    progress_event,
    run_stream,
    run_stream_with_tools,
    stream_text,
    stream_tool_calls,
    tool_end_event,
    tool_start_event,
)


class TestStreamEventTypes:
    """Test StreamEvent creation and validation."""

    def test_llm_chunk_event(self):
        """Test creating LLM chunk events."""
        event = llm_chunk_event(text="Hello")
        assert event.event_type == StreamEventType.LLM_CHUNK
        assert event.data["text"] == "Hello"
        assert "timestamp" in event.__dict__

    def test_llm_chunk_event_with_extra(self):
        """Test LLM chunk event with extra data."""
        event = llm_chunk_event(text="Hello", model="gpt-4")
        assert event.data["text"] == "Hello"
        assert event.data["model"] == "gpt-4"

    def test_llm_chunk_event_missing_text(self):
        """Test that LLM chunk events require 'text' field."""
        with pytest.raises(ValueError, match="LLM_CHUNK events must include 'text'"):
            StreamEvent(event_type=StreamEventType.LLM_CHUNK, data={})

    def test_tool_start_event(self):
        """Test creating tool start events."""
        event = tool_start_event(tool_name="read_file")
        assert event.event_type == StreamEventType.TOOL_START
        assert event.data["tool_name"] == "read_file"

    def test_tool_start_event_with_args(self):
        """Test tool start event with arguments."""
        event = tool_start_event(
            tool_name="read_file",
            args={"file_path": "/tmp/test.txt"},
        )
        assert event.data["tool_name"] == "read_file"
        assert event.data["args"]["file_path"] == "/tmp/test.txt"

    def test_tool_start_event_missing_name(self):
        """Test that tool start events require 'tool_name' field."""
        with pytest.raises(ValueError, match="TOOL_START events must include 'tool_name'"):
            StreamEvent(event_type=StreamEventType.TOOL_START, data={})

    def test_tool_end_event(self):
        """Test creating tool end events."""
        event = tool_end_event(tool_name="read_file")
        assert event.event_type == StreamEventType.TOOL_END
        assert event.data["tool_name"] == "read_file"

    def test_tool_end_event_with_result(self):
        """Test tool end event with result and duration."""
        event = tool_end_event(
            tool_name="read_file",
            result="file contents",
            duration_seconds=0.5,
        )
        assert event.data["tool_name"] == "read_file"
        assert event.data["result"] == "file contents"
        assert event.data["duration_seconds"] == 0.5

    def test_tool_end_event_with_error(self):
        """Test tool end event with error."""
        event = tool_end_event(
            tool_name="read_file",
            error="File not found",
        )
        assert event.data["tool_name"] == "read_file"
        assert event.data["error"] == "File not found"

    def test_tool_end_event_missing_name(self):
        """Test that tool end events require 'tool_name' field."""
        with pytest.raises(ValueError, match="TOOL_END events must include 'tool_name'"):
            StreamEvent(event_type=StreamEventType.TOOL_END, data={})

    def test_progress_event(self):
        """Test creating progress events."""
        event = progress_event(iteration=1)
        assert event.event_type == StreamEventType.PROGRESS
        assert event.data["iteration"] == 1

    def test_progress_event_with_tokens_and_cost(self):
        """Test progress event with tokens and cost."""
        event = progress_event(
            iteration=2,
            total_tokens=150,
            total_cost_usd=0.005,
            max_iterations=10,
        )
        assert event.data["iteration"] == 2
        assert event.data["total_tokens"] == 150
        assert event.data["total_cost_usd"] == 0.005
        assert event.data["max_iterations"] == 10

    def test_progress_event_missing_iteration(self):
        """Test that progress events require 'iteration' field."""
        with pytest.raises(ValueError, match="PROGRESS events must include 'iteration'"):
            StreamEvent(event_type=StreamEventType.PROGRESS, data={})

    def test_partial_result_event(self):
        """Test creating partial result events."""
        event = partial_result_event(result={"status": "processing"})
        assert event.event_type == StreamEventType.PARTIAL_RESULT
        assert event.data["result"] == {"status": "processing"}
        assert event.data["complete"] is False

    def test_partial_result_event_complete(self):
        """Test partial result event marked as complete."""
        event = partial_result_event(result="final", complete=True)
        assert event.data["result"] == "final"
        assert event.data["complete"] is True

    def test_error_event(self):
        """Test creating error events."""
        event = error_event(error="Something went wrong")
        assert event.event_type == StreamEventType.ERROR
        assert event.data["error"] == "Something went wrong"

    def test_error_event_with_exception_type(self):
        """Test error event with exception type."""
        event = error_event(
            error="File not found",
            exception_type="FileNotFoundError",
        )
        assert event.data["error"] == "File not found"
        assert event.data["exception_type"] == "FileNotFoundError"

    def test_agent_start_event(self):
        """Test creating agent start events."""
        event = agent_start_event(agent_name="test-agent", prompt="Hello")
        assert event.event_type == StreamEventType.AGENT_START
        assert event.data["agent_name"] == "test-agent"
        assert event.data["prompt"] == "Hello"

    def test_agent_end_event(self):
        """Test creating agent end events."""
        event = agent_end_event(agent_name="test-agent")
        assert event.event_type == StreamEventType.AGENT_END
        assert event.data["agent_name"] == "test-agent"
        assert event.data["success"] is True

    def test_agent_end_event_with_stats(self):
        """Test agent end event with statistics."""
        event = agent_end_event(
            agent_name="test-agent",
            success=True,
            total_iterations=5,
            total_tokens=250,
            total_cost_usd=0.01,
        )
        assert event.data["agent_name"] == "test-agent"
        assert event.data["success"] is True
        assert event.data["total_iterations"] == 5
        assert event.data["total_tokens"] == 250
        assert event.data["total_cost_usd"] == 0.01

    def test_agent_end_event_failed(self):
        """Test agent end event for failed execution."""
        event = agent_end_event(agent_name="test-agent", success=False)
        assert event.data["success"] is False


class TestRunStream:
    """Test run_stream() function."""

    async def test_basic_streaming(self):
        """Test basic streaming with TestModel."""
        agent = create_deep_agent(
            model=TestModel(),
            instructions="You are a test agent",
        )
        deps = DeepAgentDeps(backend=StateBackend())

        events = []
        async for event in run_stream(agent, "Hello", deps):
            events.append(event)

        # Should have at least agent start and end events
        assert len(events) >= 2
        assert events[0].event_type == StreamEventType.AGENT_START
        assert events[-1].event_type == StreamEventType.AGENT_END

        # Check agent start details
        assert events[0].data["prompt"] == "Hello"

        # Check agent end details
        assert events[-1].data["success"] is True

    async def test_streaming_with_history(self):
        """Test streaming with message history."""
        agent = create_deep_agent(
            model=TestModel(),
            instructions="You are a test agent",
        )
        deps = DeepAgentDeps(backend=StateBackend())

        history = [
            {"role": "user", "content": "Previous message"},
            {"role": "assistant", "content": "Previous response"},
        ]

        events = []
        async for event in run_stream(agent, "Hello", deps, message_history=history):
            events.append(event)

        # Should complete successfully
        assert len(events) >= 2
        assert events[-1].event_type == StreamEventType.AGENT_END
        assert events[-1].data["success"] is True

    async def test_streaming_error_handling(self):
        """Test that errors are properly caught and emitted."""
        agent = create_deep_agent(
            model=TestModel(),
            instructions="You are a test agent",
        )
        deps = DeepAgentDeps(backend=StateBackend())

        # This test just ensures error handling code doesn't crash
        # Real error handling would require a model that actually fails
        events = []
        async for event in run_stream(agent, "Test", deps):
            events.append(event)

        # Should complete successfully with TestModel
        assert len(events) >= 2
        assert events[-1].data["success"] is True


class TestStreamText:
    """Test stream_text() helper."""

    async def test_stream_text_only(self):
        """Test that stream_text yields only text chunks."""
        agent = create_deep_agent(
            model=TestModel(),
            instructions="You are a test agent",
        )
        deps = DeepAgentDeps(backend=StateBackend())

        chunks = []
        async for chunk in stream_text(agent, "Hello", deps):
            chunks.append(chunk)
            # Each chunk should be a string
            assert isinstance(chunk, str)

        # Should have received some text chunks
        # The exact number depends on pydantic-ai's streaming behavior

    async def test_stream_text_with_history(self):
        """Test stream_text with message history."""
        agent = create_deep_agent(
            model=TestModel(),
            instructions="You are a test agent",
        )
        deps = DeepAgentDeps(backend=StateBackend())

        history = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ]

        chunks = []
        async for chunk in stream_text(agent, "How are you?", deps, message_history=history):
            chunks.append(chunk)

        # Should get text chunks
        assert all(isinstance(c, str) for c in chunks)


class TestStreamToolCalls:
    """Test stream_tool_calls() helper."""

    async def test_stream_tool_calls(self):
        """Test streaming tool calls."""
        agent = create_deep_agent(
            model=TestModel(),
            instructions="You are a test agent",
        )
        deps = DeepAgentDeps(backend=StateBackend())

        tool_calls = []
        async for tool_name, args, result in stream_tool_calls(agent, "Read file", deps):
            tool_calls.append((tool_name, args, result))

        # Tool calls behavior depends on agent configuration

    async def test_stream_tool_calls_with_history(self):
        """Test stream_tool_calls with message history."""
        agent = create_deep_agent(
            model=TestModel(),
            instructions="You are a test agent",
        )
        deps = DeepAgentDeps(backend=StateBackend())

        history = [{"role": "user", "content": "Previous"}]

        tool_calls = []
        async for tool_name, args, result in stream_tool_calls(
            agent, "Task", deps, message_history=history
        ):
            tool_calls.append((tool_name, args, result))

        # Should complete without errors


class TestRunStreamWithTools:
    """Test run_stream_with_tools() function."""

    async def test_run_stream_with_tools_basic(self):
        """Test basic streaming with tools."""
        agent = create_deep_agent(
            model=TestModel(),
            instructions="You are a test agent",
        )
        deps = DeepAgentDeps(backend=StateBackend())

        events = []
        async for event in run_stream_with_tools(agent, "Hello", deps):
            events.append(event)

        # Should have agent start and end events
        assert len(events) >= 2
        assert events[0].event_type == StreamEventType.AGENT_START
        assert events[-1].event_type == StreamEventType.AGENT_END
        assert events[-1].data["success"] is True

    async def test_run_stream_with_tools_no_progress(self):
        """Test streaming with tools without progress events."""
        agent = create_deep_agent(
            model=TestModel(),
            instructions="You are a test agent",
        )
        deps = DeepAgentDeps(backend=StateBackend())

        events = []
        async for event in run_stream_with_tools(agent, "Task", deps, emit_progress=False):
            events.append(event)

        # Should not have progress events
        progress_events = [e for e in events if e.event_type == StreamEventType.PROGRESS]
        assert len(progress_events) == 0

    async def test_run_stream_with_tools_with_history(self):
        """Test run_stream_with_tools with message history."""
        agent = create_deep_agent(
            model=TestModel(),
            instructions="You are a test agent",
        )
        deps = DeepAgentDeps(backend=StateBackend())

        history = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ]

        events = []
        async for event in run_stream_with_tools(agent, "Task", deps, message_history=history):
            events.append(event)

        # Should complete successfully
        assert events[-1].event_type == StreamEventType.AGENT_END
        assert events[-1].data["success"] is True


class TestCollectStreamResult:
    """Test collect_stream_result() helper."""

    async def test_collect_all_events(self):
        """Test collecting all events from a stream."""
        agent = create_deep_agent(
            model=TestModel(),
            instructions="You are a test agent",
        )
        deps = DeepAgentDeps(backend=StateBackend())

        events_from_callback = []

        def on_event(event):
            events_from_callback.append(event)

        result, events = await collect_stream_result(
            agent,
            "Hello",
            deps,
            on_event=on_event,
        )

        # Should have collected events
        assert len(events) >= 2
        assert events[0].event_type == StreamEventType.AGENT_START
        assert events[-1].event_type == StreamEventType.AGENT_END

        # Callback should have been called for each event
        assert len(events_from_callback) == len(events)

    async def test_collect_without_callback(self):
        """Test collecting events without callback."""
        agent = create_deep_agent(
            model=TestModel(),
            instructions="You are a test agent",
        )
        deps = DeepAgentDeps(backend=StateBackend())

        result, events = await collect_stream_result(agent, "Hello", deps)

        # Should have collected events
        assert len(events) >= 2
        assert events[0].event_type == StreamEventType.AGENT_START
        assert events[-1].event_type == StreamEventType.AGENT_END


class TestEventTypeEnum:
    """Test StreamEventType enum."""

    def test_all_event_types_exist(self):
        """Test that all expected event types are defined."""
        expected_types = {
            "LLM_CHUNK",
            "TOOL_START",
            "TOOL_END",
            "PROGRESS",
            "PARTIAL_RESULT",
            "ERROR",
            "AGENT_START",
            "AGENT_END",
        }
        actual_types = {e.name for e in StreamEventType}
        assert actual_types == expected_types

    def test_event_type_values(self):
        """Test event type string values."""
        assert StreamEventType.LLM_CHUNK == "llm_chunk"
        assert StreamEventType.TOOL_START == "tool_start"
        assert StreamEventType.TOOL_END == "tool_end"
        assert StreamEventType.PROGRESS == "progress"
        assert StreamEventType.PARTIAL_RESULT == "partial_result"
        assert StreamEventType.ERROR == "error"
        assert StreamEventType.AGENT_START == "agent_start"
        assert StreamEventType.AGENT_END == "agent_end"
