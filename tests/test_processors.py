"""Tests for history processors."""

import pytest
from pydantic import BaseModel
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.test import TestModel

from pydantic_deep import (
    DeepAgentDeps,
    StateBackend,
    SummarizationProcessor,
    create_deep_agent,
    create_summarization_processor,
)
from pydantic_deep.processors.summarization import (
    _count_tokens_approximately,
    _format_messages_for_summary,
)

TEST_MODEL = TestModel()


class TestTokenCounting:
    """Tests for token counting utilities."""

    def test_count_tokens_empty(self):
        """Test counting tokens in empty message list."""
        assert _count_tokens_approximately([]) == 0

    def test_count_tokens_user_prompt(self):
        """Test counting tokens in user prompt."""
        messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart(content="Hello world")])]
        tokens = _count_tokens_approximately(messages)
        # "Hello world" = 11 chars / 4 = ~2-3 tokens
        assert tokens > 0

    def test_count_tokens_user_prompt_multipart(self):
        """Test counting tokens in multipart user prompt."""
        messages: list[ModelMessage] = [
            ModelRequest(
                parts=[
                    UserPromptPart(
                        content=[
                            {"type": "text", "text": "Hello"},
                            {"type": "text", "text": "World"},
                        ]
                    )
                ]
            )
        ]
        tokens = _count_tokens_approximately(messages)
        assert tokens > 0

    def test_count_tokens_system_prompt(self):
        """Test counting tokens in system prompt."""
        messages: list[ModelMessage] = [
            ModelRequest(parts=[SystemPromptPart(content="You are helpful")])
        ]
        tokens = _count_tokens_approximately(messages)
        assert tokens > 0

    def test_count_tokens_ai_response(self):
        """Test counting tokens in AI response."""
        messages: list[ModelMessage] = [
            ModelResponse(parts=[TextPart(content="This is a test response")])
        ]
        tokens = _count_tokens_approximately(messages)
        assert tokens > 0

    def test_count_tokens_tool_messages(self):
        """Test counting tokens in tool messages."""
        messages: list[ModelMessage] = [
            ModelResponse(
                parts=[ToolCallPart(tool_name="test_tool", args={"key": "value"}, tool_call_id="1")]
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(tool_name="test_tool", content="Tool result", tool_call_id="1")
                ]
            ),
        ]
        tokens = _count_tokens_approximately(messages)
        assert tokens > 0


class TestFormatMessages:
    """Tests for message formatting."""

    def test_format_user_message(self):
        """Test formatting user messages."""
        messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart(content="Hello")])]
        formatted = _format_messages_for_summary(messages)
        assert "User: Hello" in formatted

    def test_format_user_message_multipart(self):
        """Test formatting multipart user messages."""
        messages: list[ModelMessage] = [
            ModelRequest(
                parts=[
                    UserPromptPart(
                        content=[
                            {"type": "text", "text": "Hello"},
                            {"type": "text", "text": "World"},
                        ]
                    )
                ]
            )
        ]
        formatted = _format_messages_for_summary(messages)
        assert "User: Hello World" in formatted

    def test_format_user_message_multipart_empty(self):
        """Test formatting multipart user messages with no text."""
        messages: list[ModelMessage] = [
            ModelRequest(parts=[UserPromptPart(content=[{"type": "image", "data": "..."}])])
        ]
        formatted = _format_messages_for_summary(messages)
        assert formatted == ""

    def test_format_ai_response(self):
        """Test formatting AI responses."""
        messages: list[ModelMessage] = [ModelResponse(parts=[TextPart(content="Hi there")])]
        formatted = _format_messages_for_summary(messages)
        assert "Assistant: Hi there" in formatted

    def test_format_system_prompt(self):
        """Test formatting system prompts."""
        messages: list[ModelMessage] = [
            ModelRequest(parts=[SystemPromptPart(content="You are helpful")])
        ]
        formatted = _format_messages_for_summary(messages)
        assert "System: You are helpful" in formatted

    def test_format_tool_messages(self):
        """Test formatting tool call and return messages."""
        messages: list[ModelMessage] = [
            ModelResponse(
                parts=[ToolCallPart(tool_name="search", args={"q": "test"}, tool_call_id="1")]
            ),
            ModelRequest(
                parts=[
                    ToolReturnPart(tool_name="search", content="Found 5 results", tool_call_id="1")
                ]
            ),
        ]
        formatted = _format_messages_for_summary(messages)
        assert "Tool Call [search]" in formatted
        assert "Tool [search]: Found 5 results" in formatted

    def test_format_tool_return_truncation(self):
        """Test that long tool returns are truncated."""
        long_content = "x" * 600
        messages: list[ModelMessage] = [
            ModelRequest(
                parts=[ToolReturnPart(tool_name="search", content=long_content, tool_call_id="1")]
            ),
        ]
        formatted = _format_messages_for_summary(messages)
        assert "..." in formatted
        assert len(formatted) < len(long_content)


class TestSummarizationProcessor:
    """Tests for SummarizationProcessor."""

    def test_create_with_defaults(self):
        """Test creating processor with default settings."""
        processor = create_summarization_processor()
        assert processor.model == "openai:gpt-4.1"
        assert processor.trigger == ("tokens", 170000)
        assert processor.keep == ("messages", 20)

    def test_create_with_custom_settings(self):
        """Test creating processor with custom settings."""
        processor = create_summarization_processor(
            model="openai:gpt-4",
            trigger=("messages", 50),
            keep=("messages", 10),
        )
        assert processor.model == "openai:gpt-4"
        assert processor.trigger == ("messages", 50)
        assert processor.keep == ("messages", 10)

    def test_create_with_multiple_triggers(self):
        """Test creating processor with multiple triggers."""
        processor = SummarizationProcessor(
            model="openai:gpt-4.1",
            trigger=[("messages", 50), ("tokens", 100000)],
            keep=("messages", 10),
        )
        assert len(processor._trigger_conditions) == 2

    def test_fraction_trigger_requires_max_tokens(self):
        """Test that fraction trigger requires max_input_tokens."""
        with pytest.raises(ValueError, match="max_input_tokens is required"):
            SummarizationProcessor(
                model="openai:gpt-4.1",
                trigger=("fraction", 0.8),
            )

    def test_fraction_trigger_with_max_tokens(self):
        """Test fraction trigger with max_input_tokens provided."""
        processor = SummarizationProcessor(
            model="openai:gpt-4.1",
            trigger=("fraction", 0.8),
            max_input_tokens=200000,
        )
        assert processor._trigger_conditions == [("fraction", 0.8)]

    def test_invalid_fraction_value(self):
        """Test that invalid fraction values are rejected."""
        with pytest.raises(ValueError, match="between 0 and 1"):
            SummarizationProcessor(
                model="openai:gpt-4.1",
                trigger=("fraction", 1.5),
                max_input_tokens=200000,
            )

    def test_invalid_message_threshold(self):
        """Test that invalid message thresholds are rejected."""
        with pytest.raises(ValueError, match="greater than 0"):
            SummarizationProcessor(
                model="openai:gpt-4.1",
                trigger=("messages", -1),
            )

    def test_should_summarize_no_trigger(self):
        """Test that no summarization happens without trigger."""
        processor = SummarizationProcessor(
            model="openai:gpt-4.1",
            trigger=None,
        )
        messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart(content="Hello")])] * 100
        assert not processor._should_summarize(messages, 100000)

    def test_should_summarize_message_trigger(self):
        """Test summarization triggers on message count."""
        processor = SummarizationProcessor(
            model="openai:gpt-4.1",
            trigger=("messages", 10),
        )
        messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart(content="Hello")])] * 15
        assert processor._should_summarize(messages, 100)

    def test_should_summarize_token_trigger(self):
        """Test summarization triggers on token count."""
        processor = SummarizationProcessor(
            model="openai:gpt-4.1",
            trigger=("tokens", 100),
        )
        messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart(content="Hello")])]
        assert processor._should_summarize(messages, 150)

    def test_find_safe_cutoff(self):
        """Test finding safe cutoff point."""
        processor = SummarizationProcessor(
            model="openai:gpt-4.1",
            keep=("messages", 5),
        )
        messages: list[ModelMessage] = [
            ModelRequest(parts=[UserPromptPart(content=f"Message {i}")]) for i in range(20)
        ]
        cutoff = processor._find_safe_cutoff(messages, 5)
        # Should keep last 5, so cutoff at 15
        assert cutoff == 15

    def test_find_safe_cutoff_with_tool_pairs(self):
        """Test that safe cutoff preserves tool call pairs."""
        processor = SummarizationProcessor(
            model="openai:gpt-4.1",
            keep=("messages", 3),
        )
        messages: list[ModelMessage] = [
            ModelRequest(parts=[UserPromptPart(content="Question")]),
            ModelResponse(parts=[ToolCallPart(tool_name="search", args={}, tool_call_id="call_1")]),
            ModelRequest(
                parts=[ToolReturnPart(tool_name="search", content="Result", tool_call_id="call_1")]
            ),
            ModelResponse(parts=[TextPart(content="Answer")]),
            ModelRequest(parts=[UserPromptPart(content="Follow up")]),
        ]
        cutoff = processor._find_safe_cutoff(messages, 3)
        # Should find a safe cutoff point - checking the algorithm finds one
        # that doesn't break the tool call/return sequence
        assert cutoff >= 0
        assert cutoff <= 2  # Should cut before or within the tool pair to keep last 3

    def test_is_safe_cutoff_point(self):
        """Test checking if cutoff point is safe."""
        processor = SummarizationProcessor(
            model="openai:gpt-4.1",
        )
        messages: list[ModelMessage] = [
            ModelResponse(parts=[ToolCallPart(tool_name="test", args={}, tool_call_id="call_1")]),
            ModelRequest(
                parts=[ToolReturnPart(tool_name="test", content="Result", tool_call_id="call_1")]
            ),
        ]
        # Cutting between tool call and return is not safe
        assert not processor._is_safe_cutoff_point(messages, 1)
        # Cutting after both is safe
        assert processor._is_safe_cutoff_point(messages, 2)

    @pytest.mark.anyio
    async def test_call_no_summarization_needed(self):
        """Test processor returns messages unchanged when no summarization needed."""
        processor = SummarizationProcessor(
            model="openai:gpt-4.1",
            trigger=("messages", 100),  # High threshold
        )
        messages: list[ModelMessage] = [
            ModelRequest(parts=[UserPromptPart(content="Hello")]),
            ModelResponse(parts=[TextPart(content="Hi")]),
        ]
        result = await processor(messages)
        assert result == messages

    @pytest.mark.anyio
    async def test_call_below_cutoff_threshold(self):
        """Test processor returns messages when below cutoff."""
        processor = SummarizationProcessor(
            model="openai:gpt-4.1",
            trigger=("messages", 5),
            keep=("messages", 10),  # Keep more than we have
        )
        messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart(content="Hello")])] * 6
        result = await processor(messages)
        # Should return as-is since we can't cut anything
        assert len(result) == 6

    def test_should_summarize_fraction_trigger(self):
        """Test summarization triggers on fraction of max tokens."""
        processor = SummarizationProcessor(
            model="openai:gpt-4.1",
            trigger=("fraction", 0.5),
            max_input_tokens=1000,
        )
        messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart(content="Hello")])]
        # 600 tokens > 0.5 * 1000 = 500 threshold
        assert processor._should_summarize(messages, 600)
        # 400 tokens < 0.5 * 1000 = 500 threshold
        assert not processor._should_summarize(messages, 400)

    def test_determine_cutoff_with_token_keep(self):
        """Test cutoff determination with token-based keep."""
        processor = SummarizationProcessor(
            model="openai:gpt-4.1",
            trigger=("messages", 5),
            keep=("tokens", 100),
        )
        # Create messages with small token footprint
        messages: list[ModelMessage] = [
            ModelRequest(parts=[UserPromptPart(content="x" * 20)]) for _ in range(10)
        ]
        cutoff = processor._determine_cutoff_index(messages)
        assert cutoff >= 0

    def test_determine_cutoff_with_fraction_keep(self):
        """Test cutoff determination with fraction-based keep."""
        processor = SummarizationProcessor(
            model="openai:gpt-4.1",
            trigger=("messages", 5),
            keep=("fraction", 0.5),
            max_input_tokens=1000,
        )
        messages: list[ModelMessage] = [
            ModelRequest(parts=[UserPromptPart(content="x" * 20)]) for _ in range(10)
        ]
        cutoff = processor._determine_cutoff_index(messages)
        assert cutoff >= 0

    def test_find_token_based_cutoff_empty(self):
        """Test token-based cutoff with empty messages."""
        processor = SummarizationProcessor(
            model="openai:gpt-4.1",
        )
        assert processor._find_token_based_cutoff([], 100) == 0

    def test_find_token_based_cutoff_below_limit(self):
        """Test token-based cutoff when already below limit."""
        processor = SummarizationProcessor(
            model="openai:gpt-4.1",
        )
        messages: list[ModelMessage] = [ModelRequest(parts=[UserPromptPart(content="Hi")])]
        assert processor._find_token_based_cutoff(messages, 10000) == 0

    def test_find_token_based_cutoff_needs_cut(self):
        """Test token-based cutoff when cut is needed."""
        processor = SummarizationProcessor(
            model="openai:gpt-4.1",
        )
        # Create messages with substantial content
        messages: list[ModelMessage] = [
            ModelRequest(parts=[UserPromptPart(content="x" * 100)]) for _ in range(20)
        ]
        # Target keeping only ~100 tokens worth
        cutoff = processor._find_token_based_cutoff(messages, 100)
        # Should cut some messages
        assert cutoff > 0

    def test_invalid_context_type(self):
        """Test that invalid context type raises error."""
        with pytest.raises(ValueError, match="Unsupported context size type"):
            SummarizationProcessor(
                model="openai:gpt-4.1",
                trigger=("invalid", 10),
            )

    def test_create_processor_with_custom_token_counter(self):
        """Test creating processor with custom token counter."""

        def custom_counter(messages: list[ModelMessage]) -> int:
            return len(messages) * 100

        processor = create_summarization_processor(token_counter=custom_counter)
        assert processor.token_counter is custom_counter

    def test_create_processor_with_custom_prompt(self):
        """Test creating processor with custom summary prompt."""
        custom_prompt = "Summarize: {messages}"
        processor = create_summarization_processor(summary_prompt=custom_prompt)
        assert processor.summary_prompt == custom_prompt

    def test_create_processor_with_max_input_tokens(self):
        """Test creating processor with max_input_tokens."""
        processor = create_summarization_processor(max_input_tokens=100000)
        assert processor.max_input_tokens == 100000


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
