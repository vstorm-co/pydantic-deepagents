"""Tests for the large tool output eviction processor."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import RunContext, ToolDefinition
from pydantic_ai.usage import RunUsage
from pydantic_ai_backends import StateBackend, WriteResult

from pydantic_deep import (
    DEFAULT_EVICTION_PATH,
    DEFAULT_TOKEN_LIMIT,
    EVICTION_MESSAGE_TEMPLATE,
    NUM_CHARS_PER_TOKEN,
    DeepAgentDeps,
    EvictionCapability,
    EvictionProcessor,
    create_content_preview,
    create_deep_agent,
    create_eviction_processor,
)
from pydantic_deep.processors.eviction import _content_to_str, _sanitize_id

TEST_MODEL = TestModel()


def _make_ctx(backend: StateBackend | None = None) -> RunContext[DeepAgentDeps]:
    """Create a RunContext with DeepAgentDeps for testing."""
    b = backend or StateBackend()
    deps = DeepAgentDeps(backend=b)
    return RunContext(
        deps=deps,
        model=TEST_MODEL,
        usage=RunUsage(),
    )


def _make_ctx_no_backend() -> RunContext[object]:
    """Create a RunContext with deps that have no backend attribute."""
    return RunContext(
        deps=object(),
        model=TEST_MODEL,
        usage=RunUsage(),
    )


def _make_tool_return(
    content: str | dict[str, str] | list[str],
    tool_name: str = "grep",
    tool_call_id: str = "call_123",
    timestamp: datetime | None = None,
) -> ToolReturnPart:
    """Create a ToolReturnPart for testing."""
    return ToolReturnPart(
        tool_name=tool_name,
        content=content,
        tool_call_id=tool_call_id,
        timestamp=timestamp or datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def _make_request_with_tool_return(
    content: str | dict[str, str] | list[str],
    tool_name: str = "grep",
    tool_call_id: str = "call_123",
) -> ModelRequest:
    """Create a ModelRequest containing a single ToolReturnPart."""
    return ModelRequest(
        parts=[_make_tool_return(content, tool_name, tool_call_id)],
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def _make_large_content(num_lines: int = 100, line_length: int = 100) -> str:
    """Create large content string with specified number of lines."""
    return "\n".join(f"line {i}: {'x' * line_length}" for i in range(num_lines))


class TestCreateContentPreview:
    """Tests for the create_content_preview helper."""

    def test_short_content_no_truncation(self):
        """Content shorter than head+tail lines returns unchanged."""
        content = "line 1\nline 2\nline 3"
        result = create_content_preview(content)
        assert result == content

    def test_exact_boundary_no_truncation(self):
        """Content with exactly head_lines + tail_lines returns unchanged."""
        lines = [f"line {i}" for i in range(10)]
        content = "\n".join(lines)
        result = create_content_preview(content, head_lines=5, tail_lines=5)
        assert result == content

    def test_long_content_truncated(self):
        """Content longer than head+tail shows head, truncation marker, and tail."""
        lines = [f"line {i}" for i in range(20)]
        content = "\n".join(lines)
        result = create_content_preview(content, head_lines=3, tail_lines=3)

        assert "line 0" in result
        assert "line 1" in result
        assert "line 2" in result
        assert "line 17" in result
        assert "line 18" in result
        assert "line 19" in result
        assert "14 lines truncated" in result

    def test_custom_head_tail(self):
        """Custom head_lines and tail_lines are respected."""
        lines = [f"line {i}" for i in range(30)]
        content = "\n".join(lines)
        result = create_content_preview(content, head_lines=2, tail_lines=2)

        assert "line 0" in result
        assert "line 1" in result
        assert "line 28" in result
        assert "line 29" in result
        assert "26 lines truncated" in result

    def test_single_line_no_truncation(self):
        """Single line content returns unchanged."""
        content = "single line content"
        result = create_content_preview(content)
        assert result == content

    def test_empty_content(self):
        """Empty content returns unchanged."""
        result = create_content_preview("")
        assert result == ""


class TestContentToStr:
    """Tests for the _content_to_str helper."""

    def test_str_passthrough(self):
        """String content returns unchanged."""
        assert _content_to_str("hello") == "hello"

    def test_dict_to_json(self):
        """Dict content is JSON serialized."""
        result = _content_to_str({"key": "value"})
        assert result == '{"key": "value"}'

    def test_list_to_json(self):
        """List content is JSON serialized."""
        result = _content_to_str(["a", "b", "c"])
        assert result == '["a", "b", "c"]'

    def test_nested_structure(self):
        """Nested structures are JSON serialized."""
        data = {"items": [1, 2, 3], "nested": {"a": True}}
        result = _content_to_str(data)
        assert '"items"' in result
        assert '"nested"' in result

    def test_non_serializable_falls_back_to_str(self):
        """Non-JSON-serializable content falls back to str()."""
        obj = object()
        result = _content_to_str(obj)
        assert "object" in result

    def test_circular_reference_falls_back_to_str(self):
        """Circular reference in dict triggers ValueError, falls back to str()."""
        circular: dict[str, object] = {}
        circular["self"] = circular
        result = _content_to_str(circular)
        # str() of a dict with circular reference still works
        assert isinstance(result, str)


class TestSanitizeId:
    """Tests for the _sanitize_id helper."""

    def test_clean_id_passthrough(self):
        """Clean alphanumeric ID returns unchanged."""
        assert _sanitize_id("call_abc123") == "call_abc123"

    def test_special_chars_replaced(self):
        """Special characters are replaced with underscores."""
        assert _sanitize_id("call/abc.123!@#") == "call_abc_123___"

    def test_hyphens_preserved(self):
        """Hyphens are preserved in the sanitized ID."""
        assert _sanitize_id("call-abc-123") == "call-abc-123"

    def test_empty_string(self):
        """Empty string returns empty."""
        assert _sanitize_id("") == ""


class TestEvictionProcessor:
    """Tests for the EvictionProcessor dataclass."""

    def test_default_values(self):
        """Default values are set correctly."""
        backend = StateBackend()
        processor = EvictionProcessor(backend=backend)
        assert processor.token_limit == DEFAULT_TOKEN_LIMIT
        assert processor.eviction_path == DEFAULT_EVICTION_PATH
        assert processor.head_lines == 5
        assert processor.tail_lines == 5

    @pytest.mark.anyio
    async def test_small_content_unchanged(self):
        """Content below threshold is not modified."""
        backend = StateBackend()
        processor = EvictionProcessor(backend=backend, token_limit=100)
        ctx = _make_ctx(backend)

        # 100 tokens * 4 chars = 400 chars threshold
        small_content = "x" * 300
        messages: list[ModelMessage] = [_make_request_with_tool_return(small_content)]

        result = await processor(ctx, messages)
        assert len(result) == 1
        assert isinstance(result[0], ModelRequest)
        tool_part = result[0].parts[0]
        assert isinstance(tool_part, ToolReturnPart)
        assert tool_part.content == small_content

    @pytest.mark.anyio
    async def test_large_content_evicted(self):
        """Content above threshold is evicted to backend."""
        backend = StateBackend()
        processor = EvictionProcessor(backend=backend, token_limit=10)  # 40 chars threshold
        ctx = _make_ctx(backend)

        large_content = _make_large_content(20)
        messages: list[ModelMessage] = [_make_request_with_tool_return(large_content)]

        result = await processor(ctx, messages)
        assert len(result) == 1
        assert isinstance(result[0], ModelRequest)
        tool_part = result[0].parts[0]
        assert isinstance(tool_part, ToolReturnPart)

        # Content should be replaced with eviction message
        assert "Tool result too large" in str(tool_part.content)
        assert "/large_tool_results/" in str(tool_part.content)
        assert "read_file" in str(tool_part.content)

        # File should be written to backend
        evicted_content = backend._read_bytes("/large_tool_results/call_123")
        assert evicted_content == large_content.encode()

    @pytest.mark.anyio
    async def test_eviction_preserves_metadata(self):
        """Evicted ToolReturnPart preserves metadata and timestamp."""
        backend = StateBackend()
        processor = EvictionProcessor(backend=backend, token_limit=10)
        ctx = _make_ctx(backend)

        ts = datetime(2024, 6, 15, tzinfo=timezone.utc)
        tool_return = ToolReturnPart(
            tool_name="execute",
            content="x" * 500,
            tool_call_id="call_meta",
            metadata={"custom": "data"},
            timestamp=ts,
        )
        messages: list[ModelMessage] = [
            ModelRequest(parts=[tool_return], timestamp=ts),
        ]

        result = await processor(ctx, messages)
        tool_part = result[0].parts[0]
        assert isinstance(tool_part, ToolReturnPart)
        assert tool_part.tool_name == "execute"
        assert tool_part.tool_call_id == "call_meta"
        assert tool_part.metadata == {"custom": "data"}
        assert tool_part.timestamp == ts

    @pytest.mark.anyio
    async def test_write_failure_keeps_original(self):
        """On write failure, original content is preserved."""
        mock_backend = MagicMock()
        mock_backend.write.return_value = WriteResult(error="disk full")

        processor = EvictionProcessor(backend=mock_backend, token_limit=10)
        # ctx.deps.backend will be from DeepAgentDeps, but we want to test
        # with a mock that fails. Use a ctx with the mock backend.
        deps = MagicMock()
        deps.backend = mock_backend
        ctx: RunContext[object] = RunContext(deps=deps, model=TEST_MODEL, usage=RunUsage())

        large_content = "x" * 500
        messages: list[ModelMessage] = [_make_request_with_tool_return(large_content)]

        result = await processor(ctx, messages)
        tool_part = result[0].parts[0]
        assert isinstance(tool_part, ToolReturnPart)
        assert tool_part.content == large_content

    @pytest.mark.anyio
    async def test_non_str_content_evicted(self):
        """Dict/list content is converted to string and evicted."""
        backend = StateBackend()
        processor = EvictionProcessor(backend=backend, token_limit=10)
        ctx = _make_ctx(backend)

        # Dict content that serializes to >40 chars
        large_dict: dict[str, str] = {"data": "x" * 500}
        messages: list[ModelMessage] = [
            _make_request_with_tool_return(large_dict, tool_call_id="call_dict")
        ]

        result = await processor(ctx, messages)
        tool_part = result[0].parts[0]
        assert isinstance(tool_part, ToolReturnPart)
        assert "Tool result too large" in str(tool_part.content)

    @pytest.mark.anyio
    async def test_skips_non_model_request(self):
        """ModelResponse messages pass through unchanged."""
        backend = StateBackend()
        processor = EvictionProcessor(backend=backend, token_limit=10)
        ctx = _make_ctx(backend)

        response = ModelResponse(
            parts=[TextPart(content="Hello")],
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        messages: list[ModelMessage] = [response]

        result = await processor(ctx, messages)
        assert result == messages

    @pytest.mark.anyio
    async def test_skips_non_tool_return_parts(self):
        """UserPromptPart and other parts pass through unchanged."""
        backend = StateBackend()
        processor = EvictionProcessor(backend=backend, token_limit=10)
        ctx = _make_ctx(backend)

        request = ModelRequest(
            parts=[
                UserPromptPart(content="What is this?"),
                _make_tool_return("short", tool_call_id="call_short"),
            ],
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        messages: list[ModelMessage] = [request]

        result = await processor(ctx, messages)
        assert len(result) == 1
        assert isinstance(result[0], ModelRequest)
        assert isinstance(result[0].parts[0], UserPromptPart)
        assert result[0].parts[0].content == "What is this?"

    @pytest.mark.anyio
    async def test_mixed_parts_only_large_evicted(self):
        """In a request with multiple tool returns, only large ones are evicted."""
        backend = StateBackend()
        processor = EvictionProcessor(backend=backend, token_limit=10)
        ctx = _make_ctx(backend)

        small_return = _make_tool_return("small", tool_call_id="call_small")
        large_return = _make_tool_return("x" * 500, tool_call_id="call_large")

        request = ModelRequest(
            parts=[small_return, large_return],
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        messages: list[ModelMessage] = [request]

        result = await processor(ctx, messages)
        assert isinstance(result[0], ModelRequest)
        parts = result[0].parts

        # Small one unchanged
        assert isinstance(parts[0], ToolReturnPart)
        assert parts[0].content == "small"

        # Large one evicted
        assert isinstance(parts[1], ToolReturnPart)
        assert "Tool result too large" in str(parts[1].content)

    @pytest.mark.anyio
    async def test_idempotent_no_re_eviction(self):
        """Already-evicted tool outputs are not re-evicted on subsequent calls."""
        backend = StateBackend()
        processor = EvictionProcessor(backend=backend, token_limit=10)
        ctx = _make_ctx(backend)

        large_content = "x" * 500
        messages: list[ModelMessage] = [
            _make_request_with_tool_return(large_content, tool_call_id="call_idem")
        ]

        # First call: evicts
        result1 = await processor(ctx, messages)
        evicted_part = result1[0].parts[0]
        assert isinstance(evicted_part, ToolReturnPart)
        assert "Tool result too large" in str(evicted_part.content)

        # Second call with evicted message: should NOT re-evict
        result2 = await processor(ctx, result1)
        second_part = result2[0].parts[0]
        assert isinstance(second_part, ToolReturnPart)
        # Content should be the same eviction message, not double-evicted
        assert second_part.content == evicted_part.content

    @pytest.mark.anyio
    async def test_custom_token_limit(self):
        """Custom token_limit is respected."""
        backend = StateBackend()
        processor = EvictionProcessor(backend=backend, token_limit=1000)
        ctx = _make_ctx(backend)

        # 1000 tokens * 4 = 4000 chars threshold
        content_under = "x" * 3999
        content_over = "x" * 4001

        messages_under: list[ModelMessage] = [
            _make_request_with_tool_return(content_under, tool_call_id="under")
        ]
        messages_over: list[ModelMessage] = [
            _make_request_with_tool_return(content_over, tool_call_id="over")
        ]

        result_under = await processor(ctx, messages_under)
        result_over = await processor(ctx, messages_over)

        under_part = result_under[0].parts[0]
        over_part = result_over[0].parts[0]
        assert isinstance(under_part, ToolReturnPart)
        assert isinstance(over_part, ToolReturnPart)
        assert under_part.content == content_under
        assert "Tool result too large" in str(over_part.content)

    @pytest.mark.anyio
    async def test_custom_eviction_path(self):
        """Custom eviction_path is used for file storage."""
        backend = StateBackend()
        processor = EvictionProcessor(
            backend=backend, token_limit=10, eviction_path="/custom/evicted"
        )
        ctx = _make_ctx(backend)

        large_content = "x" * 500
        messages: list[ModelMessage] = [
            _make_request_with_tool_return(large_content, tool_call_id="call_custom")
        ]

        result = await processor(ctx, messages)
        tool_part = result[0].parts[0]
        assert isinstance(tool_part, ToolReturnPart)
        assert "/custom/evicted/" in str(tool_part.content)

        # Check file was written to custom path
        evicted = backend._read_bytes("/custom/evicted/call_custom")
        assert evicted == large_content.encode()

    @pytest.mark.anyio
    async def test_custom_head_tail_lines(self):
        """Custom head_lines and tail_lines are used in preview."""
        backend = StateBackend()
        processor = EvictionProcessor(backend=backend, token_limit=10, head_lines=2, tail_lines=2)
        ctx = _make_ctx(backend)

        large_content = _make_large_content(20)
        messages: list[ModelMessage] = [
            _make_request_with_tool_return(large_content, tool_call_id="call_ht")
        ]

        result = await processor(ctx, messages)
        tool_part = result[0].parts[0]
        assert isinstance(tool_part, ToolReturnPart)
        content_str = str(tool_part.content)
        assert "16 lines truncated" in content_str

    @pytest.mark.anyio
    async def test_preserves_request_timestamp(self):
        """Evicted ModelRequest preserves the original timestamp."""
        backend = StateBackend()
        processor = EvictionProcessor(backend=backend, token_limit=10)
        ctx = _make_ctx(backend)

        ts = datetime(2024, 3, 15, 10, 30, tzinfo=timezone.utc)
        request = ModelRequest(
            parts=[_make_tool_return("x" * 500, tool_call_id="call_ts")],
            timestamp=ts,
        )
        messages: list[ModelMessage] = [request]

        result = await processor(ctx, messages)
        assert isinstance(result[0], ModelRequest)
        assert result[0].timestamp == ts

    @pytest.mark.anyio
    async def test_preserves_request_instructions(self):
        """Evicted ModelRequest preserves the original instructions."""
        backend = StateBackend()
        processor = EvictionProcessor(backend=backend, token_limit=10)
        ctx = _make_ctx(backend)

        request = ModelRequest(
            parts=[_make_tool_return("x" * 500, tool_call_id="call_instr")],
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            instructions="Be helpful",
        )
        messages: list[ModelMessage] = [request]

        result = await processor(ctx, messages)
        assert isinstance(result[0], ModelRequest)
        assert result[0].instructions == "Be helpful"

    @pytest.mark.anyio
    async def test_multiple_messages_mixed(self):
        """Processes multiple messages correctly, only evicting large tool outputs."""
        backend = StateBackend()
        processor = EvictionProcessor(backend=backend, token_limit=10)
        ctx = _make_ctx(backend)

        messages: list[ModelMessage] = [
            ModelRequest(
                parts=[UserPromptPart(content="Hello")],
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            ),
            ModelResponse(
                parts=[TextPart(content="Hi there")],
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            ),
            _make_request_with_tool_return("x" * 500, tool_call_id="call_big"),
            _make_request_with_tool_return("small", tool_call_id="call_tiny"),
        ]

        result = await processor(ctx, messages)
        assert len(result) == 4

        # First: UserPrompt unchanged
        assert isinstance(result[0], ModelRequest)
        assert isinstance(result[0].parts[0], UserPromptPart)

        # Second: ModelResponse unchanged
        assert isinstance(result[1], ModelResponse)

        # Third: Large tool output evicted
        assert isinstance(result[2], ModelRequest)
        big_part = result[2].parts[0]
        assert isinstance(big_part, ToolReturnPart)
        assert "Tool result too large" in str(big_part.content)

        # Fourth: Small tool output unchanged
        assert isinstance(result[3], ModelRequest)
        small_part = result[3].parts[0]
        assert isinstance(small_part, ToolReturnPart)
        assert small_part.content == "small"

    @pytest.mark.anyio
    async def test_empty_messages(self):
        """Empty message list returns empty."""
        backend = StateBackend()
        processor = EvictionProcessor(backend=backend)
        ctx = _make_ctx(backend)
        result = await processor(ctx, [])
        assert result == []

    @pytest.mark.anyio
    async def test_unmodified_request_not_reconstructed(self):
        """Requests with no evictions return the original object."""
        backend = StateBackend()
        processor = EvictionProcessor(backend=backend, token_limit=10000)
        ctx = _make_ctx(backend)

        original = _make_request_with_tool_return("small content")
        messages: list[ModelMessage] = [original]

        result = await processor(ctx, messages)
        assert result[0] is original  # Same object reference


class TestResolveBackend:
    """Tests for runtime backend resolution."""

    @pytest.mark.anyio
    async def test_uses_runtime_deps_backend(self):
        """Processor uses ctx.deps.backend (runtime) not self.backend (creation)."""
        creation_backend = StateBackend()
        runtime_backend = StateBackend()

        processor = EvictionProcessor(backend=creation_backend, token_limit=10)
        ctx = _make_ctx(runtime_backend)

        large_content = "x" * 500
        messages: list[ModelMessage] = [
            _make_request_with_tool_return(large_content, tool_call_id="call_rt")
        ]

        await processor(ctx, messages)

        # File should be in RUNTIME backend, not creation backend
        evicted = runtime_backend._read_bytes("/large_tool_results/call_rt")
        assert evicted == large_content.encode()

        # Creation backend should NOT have the file
        assert creation_backend._read_bytes("/large_tool_results/call_rt") == b""

    @pytest.mark.anyio
    async def test_falls_back_to_self_backend(self):
        """Falls back to self.backend when deps has no backend attribute."""
        creation_backend = StateBackend()
        processor = EvictionProcessor(backend=creation_backend, token_limit=10)
        ctx = _make_ctx_no_backend()

        large_content = "x" * 500
        messages: list[ModelMessage] = [
            _make_request_with_tool_return(large_content, tool_call_id="call_fb")
        ]

        await processor(ctx, messages)

        # File should be in creation (fallback) backend
        evicted = creation_backend._read_bytes("/large_tool_results/call_fb")
        assert evicted == large_content.encode()


class TestCreateEvictionProcessor:
    """Tests for the create_eviction_processor factory function."""

    def test_default_params(self):
        """Factory creates processor with default parameters."""
        backend = StateBackend()
        processor = create_eviction_processor(backend)
        assert isinstance(processor, EvictionProcessor)
        assert processor.backend is backend
        assert processor.token_limit == DEFAULT_TOKEN_LIMIT
        assert processor.eviction_path == DEFAULT_EVICTION_PATH

    def test_custom_params(self):
        """Factory creates processor with custom parameters."""
        backend = StateBackend()
        processor = create_eviction_processor(
            backend,
            token_limit=5000,
            eviction_path="/custom",
            head_lines=10,
            tail_lines=3,
        )
        assert processor.token_limit == 5000
        assert processor.eviction_path == "/custom"
        assert processor.head_lines == 10
        assert processor.tail_lines == 3

    def test_on_eviction_forwarded(self):
        """Factory forwards on_eviction callback."""
        backend = StateBackend()
        cb = MagicMock()
        processor = create_eviction_processor(backend, on_eviction=cb)
        assert processor.on_eviction is cb


class TestOnEvictionCallback:
    """Tests for the on_eviction callback on EvictionProcessor."""

    @pytest.mark.anyio
    async def test_sync_callback_invoked(self):
        """Sync on_eviction callback is called on eviction."""
        backend = StateBackend()
        calls: list[tuple[str, str, int, int]] = []

        def on_eviction(tool_name: str, file_path: str, orig: int, preview: int) -> None:
            calls.append((tool_name, file_path, orig, preview))

        processor = EvictionProcessor(backend=backend, token_limit=10, on_eviction=on_eviction)
        ctx = _make_ctx(backend)

        large_content = _make_large_content(20)
        messages: list[ModelMessage] = [_make_request_with_tool_return(large_content)]
        await processor(ctx, messages)

        assert len(calls) == 1
        assert calls[0][0] == "grep"
        assert "/large_tool_results/" in calls[0][1]
        assert calls[0][2] == len(large_content)
        assert calls[0][3] > 0

    @pytest.mark.anyio
    async def test_async_callback_invoked(self):
        """Async on_eviction callback is awaited."""
        backend = StateBackend()
        calls: list[str] = []

        async def on_eviction(tool_name: str, file_path: str, orig: int, preview: int) -> None:
            calls.append(tool_name)

        processor = EvictionProcessor(backend=backend, token_limit=10, on_eviction=on_eviction)
        ctx = _make_ctx(backend)

        large_content = _make_large_content(20)
        messages: list[ModelMessage] = [_make_request_with_tool_return(large_content)]
        await processor(ctx, messages)

        assert len(calls) == 1
        assert calls[0] == "grep"

    @pytest.mark.anyio
    async def test_no_callback_when_not_evicted(self):
        """on_eviction is NOT called when content is small."""
        backend = StateBackend()
        cb = MagicMock()
        processor = EvictionProcessor(backend=backend, token_limit=100, on_eviction=cb)
        ctx = _make_ctx(backend)

        messages: list[ModelMessage] = [_make_request_with_tool_return("small")]
        await processor(ctx, messages)

        cb.assert_not_called()


class TestExports:
    """Tests for module exports and constants."""

    def test_num_chars_per_token(self):
        """NUM_CHARS_PER_TOKEN is 4."""
        assert NUM_CHARS_PER_TOKEN == 4

    def test_default_token_limit(self):
        """DEFAULT_TOKEN_LIMIT is 20000."""
        assert DEFAULT_TOKEN_LIMIT == 20_000

    def test_default_eviction_path(self):
        """DEFAULT_EVICTION_PATH is /large_tool_results."""
        assert DEFAULT_EVICTION_PATH == "/large_tool_results"

    def test_eviction_message_template(self):
        """EVICTION_MESSAGE_TEMPLATE contains expected placeholders."""
        assert "{file_path}" in EVICTION_MESSAGE_TEMPLATE
        assert "{content_sample}" in EVICTION_MESSAGE_TEMPLATE
        assert "read_file" in EVICTION_MESSAGE_TEMPLATE


class TestAgentIntegration:
    """Tests for integration with create_deep_agent."""

    def test_agent_without_eviction(self):
        """Agent without eviction_token_limit has no eviction processor."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            include_subagents=False,
            include_skills=False,
        )
        # No eviction processor added
        assert agent is not None

    def test_agent_with_eviction(self):
        """Agent with eviction_token_limit gets eviction processor."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            eviction_token_limit=20000,
            include_subagents=False,
            include_skills=False,
        )
        assert agent is not None

    def test_agent_eviction_with_summarization(self):
        """Agent with both eviction and summarization gets both processors."""
        from pydantic_deep import create_summarization_processor

        summarization = create_summarization_processor(
            trigger=("messages", 50),
            keep=("messages", 10),
        )

        agent = create_deep_agent(
            model=TEST_MODEL,
            eviction_token_limit=20000,
            history_processors=[summarization],
            include_subagents=False,
            include_skills=False,
        )
        assert agent is not None

    @pytest.mark.anyio
    async def test_agent_run_with_eviction(self):
        """Agent with eviction can run successfully."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            eviction_token_limit=100,
            include_todo=False,
            include_filesystem=False,
            include_subagents=False,
            include_skills=False,
            web_search=False,
            web_fetch=False,
        )

        deps = DeepAgentDeps(backend=StateBackend())
        result = await agent.run("Hello", deps=deps)
        assert result.output is not None


class TestEvictionPreviewFormat:
    """Tests for the format of evicted content preview."""

    @pytest.mark.anyio
    async def test_preview_contains_head_and_tail(self):
        """Eviction preview shows head and tail lines of original content."""
        backend = StateBackend()
        processor = EvictionProcessor(backend=backend, token_limit=10, head_lines=3, tail_lines=3)
        ctx = _make_ctx(backend)

        lines = [f"line_{i}" for i in range(20)]
        large_content = "\n".join(lines)
        messages: list[ModelMessage] = [
            _make_request_with_tool_return(large_content, tool_call_id="call_preview")
        ]

        result = await processor(ctx, messages)
        tool_part = result[0].parts[0]
        assert isinstance(tool_part, ToolReturnPart)
        content_str = str(tool_part.content)

        # Head lines
        assert "line_0" in content_str
        assert "line_1" in content_str
        assert "line_2" in content_str
        # Tail lines
        assert "line_17" in content_str
        assert "line_18" in content_str
        assert "line_19" in content_str
        # Truncation marker
        assert "14 lines truncated" in content_str

    @pytest.mark.anyio
    async def test_evicted_file_readable(self):
        """Evicted file content matches the original tool output."""
        backend = StateBackend()
        processor = EvictionProcessor(backend=backend, token_limit=10)
        ctx = _make_ctx(backend)

        original_content = _make_large_content(50)
        messages: list[ModelMessage] = [
            _make_request_with_tool_return(original_content, tool_call_id="call_read")
        ]

        await processor(ctx, messages)

        # Read back from backend
        stored = backend._read_bytes("/large_tool_results/call_read")
        assert stored.decode() == original_content


class TestEdgeCases:
    """Edge case tests for the eviction processor."""

    @pytest.mark.anyio
    async def test_tool_call_id_with_special_chars(self):
        """Tool call IDs with special characters are sanitized in file paths."""
        backend = StateBackend()
        processor = EvictionProcessor(backend=backend, token_limit=10)
        ctx = _make_ctx(backend)

        messages: list[ModelMessage] = [
            _make_request_with_tool_return("x" * 500, tool_call_id="call/abc.123!@#$%")
        ]

        result = await processor(ctx, messages)
        tool_part = result[0].parts[0]
        assert isinstance(tool_part, ToolReturnPart)
        # Should use sanitized ID in path
        assert "call_abc_123_____" in str(tool_part.content)

    @pytest.mark.anyio
    async def test_content_exactly_at_threshold(self):
        """Content exactly at the threshold is NOT evicted (uses <=)."""
        backend = StateBackend()
        processor = EvictionProcessor(backend=backend, token_limit=10)  # 40 chars
        ctx = _make_ctx(backend)

        exact_content = "x" * 40  # Exactly at threshold
        messages: list[ModelMessage] = [
            _make_request_with_tool_return(exact_content, tool_call_id="call_exact")
        ]

        result = await processor(ctx, messages)
        tool_part = result[0].parts[0]
        assert isinstance(tool_part, ToolReturnPart)
        assert tool_part.content == exact_content

    @pytest.mark.anyio
    async def test_content_one_over_threshold(self):
        """Content one char over the threshold IS evicted."""
        backend = StateBackend()
        processor = EvictionProcessor(backend=backend, token_limit=10)  # 40 chars
        ctx = _make_ctx(backend)

        over_content = "x" * 41  # One over threshold
        messages: list[ModelMessage] = [
            _make_request_with_tool_return(over_content, tool_call_id="call_over")
        ]

        result = await processor(ctx, messages)
        tool_part = result[0].parts[0]
        assert isinstance(tool_part, ToolReturnPart)
        assert "Tool result too large" in str(tool_part.content)

    @pytest.mark.anyio
    async def test_request_with_only_user_prompt(self):
        """Request with only UserPromptPart passes through unchanged."""
        backend = StateBackend()
        processor = EvictionProcessor(backend=backend, token_limit=10)
        ctx = _make_ctx(backend)

        request = ModelRequest(
            parts=[UserPromptPart(content="Hello world")],
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        messages: list[ModelMessage] = [request]

        result = await processor(ctx, messages)
        assert result[0] is request

    @pytest.mark.anyio
    async def test_model_response_with_tool_call(self):
        """ModelResponse containing ToolCallPart is not processed (not ModelRequest)."""
        backend = StateBackend()
        processor = EvictionProcessor(backend=backend, token_limit=10)
        ctx = _make_ctx(backend)

        response = ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="grep",
                    args={"pattern": "test"},
                    tool_call_id="call_resp",
                )
            ],
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        messages: list[ModelMessage] = [response]

        result = await processor(ctx, messages)
        assert result[0] is response


# ---------------------------------------------------------------------------
# EvictionCapability (after_tool_execute hook)
# ---------------------------------------------------------------------------


def _cap_call(name: str = "grep", call_id: str = "call_cap") -> ToolCallPart:
    return ToolCallPart(tool_name=name, args={}, tool_call_id=call_id)


def _cap_td(name: str = "grep") -> ToolDefinition:
    return ToolDefinition(name=name, description="")


class TestEvictionCapability:
    """Tests for EvictionCapability (after_tool_execute hook)."""

    @pytest.mark.anyio
    async def test_small_result_unchanged(self):
        """Results below threshold pass through unchanged."""
        backend = StateBackend()
        cap = EvictionCapability(backend=backend, token_limit=100)
        ctx = _make_ctx(backend)

        result = await cap.after_tool_execute(
            ctx,
            call=_cap_call(),
            tool_def=_cap_td(),
            args={},
            result="small result",
        )
        assert result == "small result"

    @pytest.mark.anyio
    async def test_large_result_evicted(self):
        """Results above threshold are saved to file and replaced with preview."""
        backend = StateBackend()
        cap = EvictionCapability(backend=backend, token_limit=10)  # 40 chars
        ctx = _make_ctx(backend)

        large = _make_large_content(20)
        result = await cap.after_tool_execute(
            ctx,
            call=_cap_call(call_id="call_big"),
            tool_def=_cap_td(),
            args={},
            result=large,
        )

        assert "Tool result too large" in result
        assert "/large_tool_results/call_big" in result
        # File was written
        evicted = backend._read_bytes("/large_tool_results/call_big")
        assert evicted == large.encode()

    @pytest.mark.anyio
    async def test_uses_deps_backend(self):
        """Resolves backend from ctx.deps over fallback."""
        fallback = StateBackend()
        deps_backend = StateBackend()
        cap = EvictionCapability(backend=fallback, token_limit=10)
        ctx = _make_ctx(deps_backend)

        large = "x" * 500
        await cap.after_tool_execute(
            ctx,
            call=_cap_call(call_id="call_deps"),
            tool_def=_cap_td(),
            args={},
            result=large,
        )

        # Written to deps_backend, not fallback
        assert deps_backend._read_bytes("/large_tool_results/call_deps") not in (None, b"")
        assert fallback._read_bytes("/large_tool_results/call_deps") in (None, b"")

    @pytest.mark.anyio
    async def test_no_backend_passes_through(self):
        """No backend available — returns result unchanged."""
        cap = EvictionCapability(backend=None, token_limit=10)
        ctx = _make_ctx_no_backend()

        large = "x" * 500
        result = await cap.after_tool_execute(
            ctx,
            call=_cap_call(),
            tool_def=_cap_td(),
            args={},
            result=large,
        )
        assert result == large

    @pytest.mark.anyio
    async def test_on_eviction_callback(self):
        """on_eviction callback is invoked on eviction."""
        backend = StateBackend()
        callback = MagicMock()
        cap = EvictionCapability(backend=backend, token_limit=10, on_eviction=callback)
        ctx = _make_ctx(backend)

        await cap.after_tool_execute(
            ctx,
            call=_cap_call("execute", "call_cb"),
            tool_def=_cap_td("execute"),
            args={},
            result="x" * 500,
        )

        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == "execute"  # tool_name
        assert "call_cb" in args[1]  # file_path

    @pytest.mark.anyio
    async def test_write_failure_returns_original(self):
        """When backend write fails, original result is returned unchanged."""
        backend = StateBackend()
        # Monkey-patch write to return an error

        def failing_write(path: str, content: str | bytes) -> WriteResult:
            return WriteResult(path=path, error="disk full")

        backend.write = failing_write
        cap = EvictionCapability(backend=backend, token_limit=10)
        ctx = _make_ctx(backend)

        large = "x" * 500
        result = await cap.after_tool_execute(
            ctx,
            call=_cap_call(call_id="call_fail"),
            tool_def=_cap_td(),
            args={},
            result=large,
        )
        assert result == large

    @pytest.mark.anyio
    async def test_async_on_eviction_callback(self):
        """Async on_eviction callback is awaited."""
        backend = StateBackend()
        called_with: list[tuple[str, str, int, int]] = []

        async def async_cb(tool_name: str, file_path: str, orig: int, preview: int) -> None:
            called_with.append((tool_name, file_path, orig, preview))

        cap = EvictionCapability(backend=backend, token_limit=10, on_eviction=async_cb)
        ctx = _make_ctx(backend)

        await cap.after_tool_execute(
            ctx,
            call=_cap_call("mytool", "call_async"),
            tool_def=_cap_td("mytool"),
            args={},
            result="x" * 500,
        )

        assert len(called_with) == 1
        assert called_with[0][0] == "mytool"
        assert "call_async" in called_with[0][1]

    @pytest.mark.anyio
    async def test_dict_result_evicted(self):
        """Non-string results (dicts) are also evicted when large."""
        backend = StateBackend()
        cap = EvictionCapability(backend=backend, token_limit=10)
        ctx = _make_ctx(backend)

        large_dict = {"data": "x" * 500}
        result = await cap.after_tool_execute(
            ctx,
            call=_cap_call(call_id="call_dict"),
            tool_def=_cap_td(),
            args={},
            result=large_dict,
        )

        assert "Tool result too large" in result

    def test_exportable(self):
        """EvictionCapability is importable from pydantic_deep."""
        from pydantic_deep import EvictionCapability as Imported

        assert Imported is EvictionCapability


# ---------------------------------------------------------------------------
# ToolReturn preservation (after_tool_execute)
# ---------------------------------------------------------------------------


class TestEvictionCapabilityToolReturn:
    """Tests for ``EvictionCapability`` handling of ``ToolReturn`` results."""

    @pytest.mark.anyio
    async def test_toolreturn_preserves_binary_content(self):
        """ToolReturn with BinaryContent in `content` is not collapsed by text eviction."""
        from pydantic_ai.messages import BinaryContent, ToolReturn

        backend = StateBackend()
        cap = EvictionCapability(backend=backend, token_limit=10)
        ctx = _make_ctx(backend)

        screenshot = BinaryContent(data=b"\xff\xd8" + b"x" * 1024, media_type="image/jpeg")
        original = ToolReturn(
            return_value="Page screenshot at https://example.com",
            content=["Page screenshot at https://example.com", screenshot],
        )

        result = await cap.after_tool_execute(
            ctx,
            call=_cap_call(call_id="call_screenshot"),
            tool_def=_cap_td(),
            args={},
            result=original,
        )

        assert isinstance(result, ToolReturn)
        # return_value is small so it stays unchanged
        assert result.return_value == original.return_value
        # content (with the BinaryContent) is preserved as-is
        assert result.content == original.content
        # Backend was not asked to store anything (no eviction)
        assert backend._read_bytes("/large_tool_results/call_screenshot") in (None, b"")

    @pytest.mark.anyio
    async def test_toolreturn_evicts_only_return_value(self):
        """Large ToolReturn.return_value is evicted but content is preserved."""
        from pydantic_ai.messages import BinaryContent, ToolReturn

        backend = StateBackend()
        cap = EvictionCapability(backend=backend, token_limit=10)  # 40 chars
        ctx = _make_ctx(backend)

        large_text = _make_large_content(20)
        screenshot = BinaryContent(data=b"image-bytes", media_type="image/png")
        original = ToolReturn(
            return_value=large_text,
            content=["caption", screenshot],
            metadata={"trace_id": "abc"},
        )

        result = await cap.after_tool_execute(
            ctx,
            call=_cap_call(call_id="call_big_tr"),
            tool_def=_cap_td(),
            args={},
            result=original,
        )

        assert isinstance(result, ToolReturn)
        assert isinstance(result.return_value, str)
        assert "Tool result too large" in result.return_value
        assert "/large_tool_results/call_big_tr" in result.return_value
        # content (with the BinaryContent) is preserved as-is
        assert result.content == original.content
        # metadata is preserved
        assert result.metadata == {"trace_id": "abc"}
        # The text value was actually written to the backend
        assert backend._read_bytes("/large_tool_results/call_big_tr") == large_text.encode()

    @pytest.mark.anyio
    async def test_toolreturn_small_passes_through(self):
        """Small ToolReturn passes through unchanged (same instance)."""
        from pydantic_ai.messages import BinaryContent, ToolReturn

        backend = StateBackend()
        cap = EvictionCapability(backend=backend, token_limit=1000)
        ctx = _make_ctx(backend)

        screenshot = BinaryContent(data=b"x" * 32, media_type="image/jpeg")
        original = ToolReturn(return_value="ok", content=["caption", screenshot])

        result = await cap.after_tool_execute(
            ctx,
            call=_cap_call(call_id="call_small_tr"),
            tool_def=_cap_td(),
            args={},
            result=original,
        )

        assert result is original


# ---------------------------------------------------------------------------
# Binary content retention (before_model_request)
# ---------------------------------------------------------------------------


class _FakeRequestContext:
    """Minimal stand-in for ``ModelRequestContext`` used in tests."""

    def __init__(self, messages: list[ModelMessage]) -> None:
        self.messages = messages


def _user_with_image(
    image_bytes: bytes,
    media_type: str = "image/jpeg",
    text: str = "image",
    timestamp: datetime | None = None,
) -> ModelRequest:
    from pydantic_ai.messages import BinaryContent

    return ModelRequest(
        parts=[
            UserPromptPart(
                content=[text, BinaryContent(data=image_bytes, media_type=media_type)],
                timestamp=timestamp or datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        ],
        timestamp=timestamp or datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def _toolreturn_with_image(
    image_bytes: bytes,
    *,
    media_type: str = "image/jpeg",
    text: str = "Page screenshot",
    tool_call_id: str = "call_img",
) -> ModelRequest:
    from pydantic_ai.messages import BinaryContent

    return ModelRequest(
        parts=[
            ToolReturnPart(
                tool_name="browser_screenshot",
                content=[text, BinaryContent(data=image_bytes, media_type=media_type)],
                tool_call_id=tool_call_id,
                timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
            )
        ],
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


class TestBinaryContentRetention:
    """Tests for ``EvictionCapability.before_model_request`` binary pruning."""

    @pytest.mark.anyio
    async def test_keeps_most_recent_binaries(self):
        """The N most recent binaries are kept; older ones are pruned and stored."""
        from pydantic_ai.messages import BinaryContent

        backend = StateBackend()
        cap = EvictionCapability(backend=backend, max_binary_content=2)
        ctx = _make_ctx(backend)

        # 4 messages, each with one image — newest last
        messages: list[ModelMessage] = [
            _user_with_image(b"image-0-bytes" * 8, text="img0"),
            _user_with_image(b"image-1-bytes" * 8, text="img1"),
            _user_with_image(b"image-2-bytes" * 8, text="img2"),
            _user_with_image(b"image-3-bytes" * 8, text="img3"),
        ]
        rc = _FakeRequestContext(messages)

        result_rc = await cap.before_model_request(ctx, rc)

        new_messages = result_rc.messages
        assert len(new_messages) == 4

        def _binary_count(msg: ModelMessage) -> int:
            count = 0
            for part in msg.parts:
                if isinstance(part, UserPromptPart):
                    items = (
                        part.content if isinstance(part.content, list) else [part.content]
                    )
                    count += sum(1 for x in items if isinstance(x, BinaryContent))
            return count

        # Two oldest messages have their binary replaced with a text reference
        assert _binary_count(new_messages[0]) == 0
        assert _binary_count(new_messages[1]) == 0
        assert _binary_count(new_messages[2]) == 1
        assert _binary_count(new_messages[3]) == 1

        # Pruned binaries were stored to backend with deterministic paths
        first_bin = BinaryContent(data=b"image-0-bytes" * 8, media_type="image/jpeg")
        path = f"/large_tool_results/binary_{first_bin.identifier}.jpg"
        assert backend._read_bytes(path) == b"image-0-bytes" * 8

        # Older messages now contain the text reference
        first_part = new_messages[0].parts[0]
        assert isinstance(first_part, UserPromptPart)
        assert isinstance(first_part.content, list)
        text_replacements = [x for x in first_part.content if isinstance(x, str)]
        assert any("Binary content omitted" in t for t in text_replacements)
        assert any("read_file" in t for t in text_replacements)

    @pytest.mark.anyio
    async def test_under_limit_unchanged(self):
        """When binaries are at or under the limit, messages pass through unchanged."""
        backend = StateBackend()
        cap = EvictionCapability(backend=backend, max_binary_content=3)
        ctx = _make_ctx(backend)

        messages: list[ModelMessage] = [
            _user_with_image(b"a" * 32, text="img0"),
            _user_with_image(b"b" * 32, text="img1"),
        ]
        rc = _FakeRequestContext(messages)

        result_rc = await cap.before_model_request(ctx, rc)

        # Same list, same message instances
        assert result_rc.messages is rc.messages
        assert result_rc.messages[0] is messages[0]
        assert result_rc.messages[1] is messages[1]

    @pytest.mark.anyio
    async def test_none_disables_pruning(self):
        """``max_binary_content=None`` keeps every binary in history."""
        from pydantic_ai.messages import BinaryContent

        backend = StateBackend()
        cap = EvictionCapability(backend=backend, max_binary_content=None)
        ctx = _make_ctx(backend)

        messages: list[ModelMessage] = [
            _user_with_image(b"img-%d" % i, text=f"i{i}") for i in range(5)
        ]
        rc = _FakeRequestContext(messages)

        result_rc = await cap.before_model_request(ctx, rc)

        for msg in result_rc.messages:
            part = msg.parts[0]
            assert isinstance(part, UserPromptPart)
            items = part.content if isinstance(part.content, list) else [part.content]
            assert any(isinstance(x, BinaryContent) for x in items)

    @pytest.mark.anyio
    async def test_prunes_binary_in_toolreturn_part(self):
        """Binary parts inside ``ToolReturnPart.content`` are also pruned and stored."""
        from pydantic_ai.messages import BinaryContent

        backend = StateBackend()
        cap = EvictionCapability(backend=backend, max_binary_content=1)
        ctx = _make_ctx(backend)

        old_bytes = b"old-image-bytes" * 4
        new_bytes = b"new-image-bytes" * 4

        messages: list[ModelMessage] = [
            _toolreturn_with_image(old_bytes, tool_call_id="call_old"),
            _toolreturn_with_image(new_bytes, tool_call_id="call_new"),
        ]
        rc = _FakeRequestContext(messages)

        result_rc = await cap.before_model_request(ctx, rc)

        # Newest preserved, oldest pruned
        old_msg = result_rc.messages[0]
        new_msg = result_rc.messages[1]

        old_part = old_msg.parts[0]
        new_part = new_msg.parts[0]
        assert isinstance(old_part, ToolReturnPart)
        assert isinstance(new_part, ToolReturnPart)

        assert isinstance(old_part.content, list)
        assert not any(isinstance(x, BinaryContent) for x in old_part.content)
        assert any(
            isinstance(x, str) and "Binary content omitted" in x for x in old_part.content
        )

        assert isinstance(new_part.content, list)
        assert any(isinstance(x, BinaryContent) for x in new_part.content)

        # Stored bytes match the original BinaryContent.data
        old_bin = BinaryContent(data=old_bytes, media_type="image/jpeg")
        path = f"/large_tool_results/binary_{old_bin.identifier}.jpg"
        assert backend._read_bytes(path) == old_bytes

        # ToolReturnPart metadata is preserved
        assert old_part.tool_name == "browser_screenshot"
        assert old_part.tool_call_id == "call_old"

    @pytest.mark.anyio
    async def test_no_backend_skips_pruning(self):
        """With no backend available, binaries are left in place."""
        from pydantic_ai.messages import BinaryContent

        cap = EvictionCapability(backend=None, max_binary_content=1)
        ctx = _make_ctx_no_backend()

        messages: list[ModelMessage] = [
            _user_with_image(b"a" * 16, text="img0"),
            _user_with_image(b"b" * 16, text="img1"),
        ]
        rc = _FakeRequestContext(messages)

        result_rc = await cap.before_model_request(ctx, rc)
        assert result_rc.messages is rc.messages
        for msg in result_rc.messages:
            part = msg.parts[0]
            assert isinstance(part, UserPromptPart)
            items = part.content if isinstance(part.content, list) else [part.content]
            assert any(isinstance(x, BinaryContent) for x in items)

    @pytest.mark.anyio
    async def test_write_failure_keeps_binary(self):
        """A backend write failure keeps the binary in history rather than dropping it."""
        from pydantic_ai.messages import BinaryContent

        backend = StateBackend()

        def failing_write(path: str, content: str | bytes) -> WriteResult:
            return WriteResult(path=path, error="disk full")

        backend.write = failing_write
        cap = EvictionCapability(backend=backend, max_binary_content=1)
        ctx = _make_ctx(backend)

        messages: list[ModelMessage] = [
            _user_with_image(b"old" * 8, text="old"),
            _user_with_image(b"new" * 8, text="new"),
        ]
        rc = _FakeRequestContext(messages)

        result_rc = await cap.before_model_request(ctx, rc)

        # Both binaries still present because the write failed
        for msg in result_rc.messages:
            part = msg.parts[0]
            assert isinstance(part, UserPromptPart)
            items = part.content if isinstance(part.content, list) else [part.content]
            assert any(isinstance(x, BinaryContent) for x in items)


class TestMaxBinaryContentAgentIntegration:
    """``max_binary_content`` plumbing through ``create_deep_agent``."""

    def _eviction_capabilities(self, agent: object) -> list[EvictionCapability]:
        root = getattr(agent, "_root_capability", None)
        if root is None:
            return []
        return [c for c in getattr(root, "capabilities", []) if isinstance(c, EvictionCapability)]

    def test_agent_accepts_max_binary_content(self):
        """``create_deep_agent`` accepts ``max_binary_content`` and forwards it."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            eviction_token_limit=20000,
            max_binary_content=2,
            include_subagents=False,
            include_skills=False,
        )

        caps = self._eviction_capabilities(agent)
        assert len(caps) == 1
        assert caps[0].max_binary_content == 2

    def test_agent_default_max_binary_content(self):
        """Default ``max_binary_content`` is 3 when not specified."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            eviction_token_limit=20000,
            include_subagents=False,
            include_skills=False,
        )

        caps = self._eviction_capabilities(agent)
        assert len(caps) == 1
        assert caps[0].max_binary_content == 3

    def test_agent_max_binary_content_none(self):
        """``max_binary_content=None`` disables pruning."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            eviction_token_limit=20000,
            max_binary_content=None,
            include_subagents=False,
            include_skills=False,
        )

        caps = self._eviction_capabilities(agent)
        assert len(caps) == 1
        assert caps[0].max_binary_content is None


class TestExtensionForMediaType:
    """Tests for the ``_extension_for_media_type`` helper."""

    def test_known_media_type_uses_mapping(self):
        from pydantic_deep.processors.eviction import _extension_for_media_type

        assert _extension_for_media_type("image/jpeg") == "jpg"
        assert _extension_for_media_type("image/png") == "png"

    def test_unknown_media_type_uses_subtype(self):
        from pydantic_deep.processors.eviction import _extension_for_media_type

        assert _extension_for_media_type("image/x-foo") == "x-foo"
        assert _extension_for_media_type("application/x-custom; charset=utf-8") == "x-custom"

    def test_subtype_special_chars_sanitized(self):
        from pydantic_deep.processors.eviction import _extension_for_media_type

        assert _extension_for_media_type("image/foo.bar") == "foo_bar"

    def test_no_slash_falls_back_to_bin(self):
        from pydantic_deep.processors.eviction import _extension_for_media_type

        assert _extension_for_media_type("weirdmediatype") == "bin"

    def test_empty_subtype_falls_back_to_bin(self):
        from pydantic_deep.processors.eviction import _extension_for_media_type

        assert _extension_for_media_type("image/") == "bin"


class TestBinaryRetentionEdgeCases:
    """Edge cases for ``before_model_request`` binary pruning."""

    @pytest.mark.anyio
    async def test_bare_binary_in_toolreturn_content_pruned(self):
        """Bare ``BinaryContent`` (not in a list) on ``ToolReturnPart.content`` is pruned."""
        from pydantic_ai.messages import BinaryContent

        backend = StateBackend()
        cap = EvictionCapability(backend=backend, max_binary_content=1)
        ctx = _make_ctx(backend)

        old_bytes = b"old-bare-binary"
        new_bytes = b"new-bare-binary"

        old_msg = ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="screenshot",
                    content=BinaryContent(data=old_bytes, media_type="image/png"),
                    tool_call_id="call_old_bare",
                    timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                )
            ],
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        new_msg = ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="screenshot",
                    content=BinaryContent(data=new_bytes, media_type="image/png"),
                    tool_call_id="call_new_bare",
                    timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                )
            ],
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )

        rc = _FakeRequestContext([old_msg, new_msg])
        result_rc = await cap.before_model_request(ctx, rc)

        old_part = result_rc.messages[0].parts[0]
        new_part = result_rc.messages[1].parts[0]
        assert isinstance(old_part, ToolReturnPart)
        assert isinstance(new_part, ToolReturnPart)

        # Newest preserved as a BinaryContent, oldest replaced with a text reference
        assert isinstance(new_part.content, BinaryContent)
        assert isinstance(old_part.content, str)
        assert "Binary content omitted" in old_part.content
        assert "read_file" in old_part.content

        # Stored bytes match the original
        old_bin = BinaryContent(data=old_bytes, media_type="image/png")
        path = f"/large_tool_results/binary_{old_bin.identifier}.png"
        assert backend._read_bytes(path) == old_bytes

    @pytest.mark.anyio
    async def test_bare_binary_under_limit_unchanged(self):
        """Bare ``BinaryContent`` under the limit is left untouched."""
        from pydantic_ai.messages import BinaryContent

        backend = StateBackend()
        cap = EvictionCapability(backend=backend, max_binary_content=3)
        ctx = _make_ctx(backend)

        msg = ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="screenshot",
                    content=BinaryContent(data=b"only", media_type="image/png"),
                    tool_call_id="call_only",
                    timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                )
            ],
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        rc = _FakeRequestContext([msg])
        result_rc = await cap.before_model_request(ctx, rc)

        # Same instance, no rebuild
        assert result_rc.messages[0] is msg

    @pytest.mark.anyio
    async def test_bare_binary_write_failure_keeps_binary(self):
        """A failed backend write leaves a bare ``BinaryContent`` untouched."""
        from pydantic_ai.messages import BinaryContent

        backend = StateBackend()

        def failing_write(path: str, content: str | bytes) -> WriteResult:
            return WriteResult(path=path, error="disk full")

        backend.write = failing_write
        cap = EvictionCapability(backend=backend, max_binary_content=1)
        ctx = _make_ctx(backend)

        old_bin = BinaryContent(data=b"old-bare", media_type="image/png")
        new_bin = BinaryContent(data=b"new-bare", media_type="image/png")

        old_msg = ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="screenshot",
                    content=old_bin,
                    tool_call_id="call_old_fail_bare",
                    timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                )
            ],
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        new_msg = ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="screenshot",
                    content=new_bin,
                    tool_call_id="call_new_fail_bare",
                    timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                )
            ],
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )

        rc = _FakeRequestContext([old_msg, new_msg])
        result_rc = await cap.before_model_request(ctx, rc)

        old_part = result_rc.messages[0].parts[0]
        new_part = result_rc.messages[1].parts[0]
        assert isinstance(old_part, ToolReturnPart)
        assert isinstance(new_part, ToolReturnPart)

        # Both still BinaryContent because the write failed
        assert isinstance(old_part.content, BinaryContent)
        assert isinstance(new_part.content, BinaryContent)

    @pytest.mark.anyio
    async def test_list_write_failure_keeps_binary(self):
        """A failed backend write leaves list-form binaries untouched."""
        from pydantic_ai.messages import BinaryContent

        backend = StateBackend()

        def failing_write(path: str, content: str | bytes) -> WriteResult:
            return WriteResult(path=path, error="disk full")

        backend.write = failing_write
        cap = EvictionCapability(backend=backend, max_binary_content=1)
        ctx = _make_ctx(backend)

        msg_old = ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="screenshot",
                    content=["caption", BinaryContent(data=b"old-list", media_type="image/png")],
                    tool_call_id="call_old_list_fail",
                    timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                )
            ],
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        msg_new = ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="screenshot",
                    content=["caption", BinaryContent(data=b"new-list", media_type="image/png")],
                    tool_call_id="call_new_list_fail",
                    timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                )
            ],
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )

        rc = _FakeRequestContext([msg_old, msg_new])
        result_rc = await cap.before_model_request(ctx, rc)

        old_part = result_rc.messages[0].parts[0]
        new_part = result_rc.messages[1].parts[0]
        assert isinstance(old_part, ToolReturnPart)
        assert isinstance(new_part, ToolReturnPart)

        # Both messages still hold their BinaryContent because the write failed
        assert isinstance(old_part.content, list)
        assert isinstance(new_part.content, list)
        assert any(isinstance(x, BinaryContent) for x in old_part.content)
        assert any(isinstance(x, BinaryContent) for x in new_part.content)

    @pytest.mark.anyio
    async def test_other_request_parts_skipped(self):
        """Non user/tool-return parts (e.g. ``RetryPromptPart``) are passed over."""
        from pydantic_ai.messages import RetryPromptPart

        backend = StateBackend()
        cap = EvictionCapability(backend=backend, max_binary_content=1)
        ctx = _make_ctx(backend)

        retry_msg = ModelRequest(
            parts=[RetryPromptPart(content="please retry")],
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )

        rc = _FakeRequestContext([retry_msg])
        result_rc = await cap.before_model_request(ctx, rc)

        # Same instance — nothing to prune
        assert result_rc.messages[0] is retry_msg

    @pytest.mark.anyio
    async def test_non_list_non_binary_toolreturn_content_unchanged(self):
        """Scalar non-binary ``ToolReturnPart.content`` (e.g. a dict) is left as-is."""
        from pydantic_ai.messages import BinaryContent

        backend = StateBackend()
        cap = EvictionCapability(backend=backend, max_binary_content=1)
        ctx = _make_ctx(backend)

        # A dict-form content that should not be touched, alongside a binary
        msg_dict = ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="some_tool",
                    content={"data": "value"},
                    tool_call_id="call_dict_form",
                    timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                )
            ],
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        msg_bin = ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="screenshot",
                    content=BinaryContent(data=b"new-bin", media_type="image/png"),
                    tool_call_id="call_bin",
                    timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
                )
            ],
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )

        rc = _FakeRequestContext([msg_dict, msg_bin])
        result_rc = await cap.before_model_request(ctx, rc)

        # The dict-form message is preserved as the same instance (no modifications)
        assert result_rc.messages[0] is msg_dict
        # Binary is preserved (under the limit of 1)
        bin_part = result_rc.messages[1].parts[0]
        assert isinstance(bin_part, ToolReturnPart)
        assert isinstance(bin_part.content, BinaryContent)
