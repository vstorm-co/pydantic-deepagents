"""Tests for history processors integration with create_deep_agent."""

import pytest
from pydantic import BaseModel
from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.test import TestModel

from pydantic_deep import (
    DeepAgentDeps,
    StateBackend,
    SlidingWindowProcessor,
    SummarizationProcessor,
    create_deep_agent,
    create_sliding_window_processor,
    create_summarization_processor,
)

TEST_MODEL = TestModel()


class TestAgentWithOutputType:
    """Tests for create_deep_agent with output_type."""

    def test_create_agent_with_output_type(self):
        """Test creating agent with structured output type."""

        class TaskResult(BaseModel):
            status: str
            details: str

        agent = create_deep_agent(
            model=TEST_MODEL,
            output_type=TaskResult,
            include_subagents=False,
            include_skills=False,
        )
        assert agent is not None

    def test_create_agent_without_output_type(self):
        """Test creating agent without output_type returns str agent."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            include_subagents=False,
            include_skills=False,
        )
        assert agent is not None

    @pytest.mark.anyio
    async def test_agent_with_output_type_run(self):
        """Test running agent with structured output."""

        class SimpleResult(BaseModel):
            answer: str

        test_model = TestModel(custom_output_args={"answer": "test"})
        agent = create_deep_agent(
            model=test_model,
            output_type=SimpleResult,
            include_todo=False,
            include_filesystem=False,
            include_subagents=False,
            include_skills=False,
        )

        deps = DeepAgentDeps(backend=StateBackend())
        result = await agent.run("Test question", deps=deps)
        assert isinstance(result.output, SimpleResult)
        assert result.output.answer == "test"


class TestAgentWithHistoryProcessors:
    """Tests for create_deep_agent with history_processors."""

    def test_create_agent_with_history_processor(self):
        """Test creating agent with history processor."""

        def simple_processor(messages: list[ModelMessage]) -> list[ModelMessage]:
            return messages

        agent = create_deep_agent(
            model=TEST_MODEL,
            history_processors=[simple_processor],
            include_subagents=False,
            include_skills=False,
        )
        assert agent is not None

    def test_create_agent_with_summarization_processor(self):
        """Test creating agent with summarization processor."""
        processor = create_summarization_processor(
            trigger=("messages", 50),
            keep=("messages", 10),
        )

        agent = create_deep_agent(
            model=TEST_MODEL,
            history_processors=[processor],
            include_subagents=False,
            include_skills=False,
        )
        assert agent is not None

    def test_create_agent_with_sliding_window_processor(self):
        """Test creating agent with sliding window processor."""
        processor = create_sliding_window_processor(
            trigger=("messages", 100),
            keep=("messages", 50),
        )

        agent = create_deep_agent(
            model=TEST_MODEL,
            history_processors=[processor],
            include_subagents=False,
            include_skills=False,
        )
        assert agent is not None

    @pytest.mark.anyio
    async def test_agent_with_history_processor_run(self):
        """Test running agent with history processor."""

        # Simple processor that keeps all messages
        def passthrough_processor(messages: list[ModelMessage]) -> list[ModelMessage]:
            return messages

        agent = create_deep_agent(
            model=TEST_MODEL,
            history_processors=[passthrough_processor],
            include_todo=False,
            include_filesystem=False,
            include_subagents=False,
            include_skills=False,
        )

        deps = DeepAgentDeps(backend=StateBackend())
        result = await agent.run("Hello", deps=deps)
        assert result.output is not None


class TestProcessorImports:
    """Tests that processors are properly exported from pydantic_deep."""

    def test_summarization_processor_exported(self):
        """Test SummarizationProcessor is exported."""
        assert SummarizationProcessor is not None

    def test_sliding_window_processor_exported(self):
        """Test SlidingWindowProcessor is exported."""
        assert SlidingWindowProcessor is not None

    def test_create_summarization_processor_exported(self):
        """Test create_summarization_processor is exported."""
        processor = create_summarization_processor()
        assert processor is not None

    def test_create_sliding_window_processor_exported(self):
        """Test create_sliding_window_processor is exported."""
        processor = create_sliding_window_processor()
        assert processor is not None
