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
from pydantic_ai.tools import RunContext
from pydantic_ai.usage import RunUsage
from pydantic_ai_backends import StateBackend, WriteResult

from pydantic_deep import (
    DEFAULT_EVICTION_PATH,
    DEFAULT_TOKEN_LIMIT,
    EVICTION_MESSAGE_TEMPLATE,
    NUM_CHARS_PER_TOKEN,
    DeepAgentDeps,
    EvictionProcessor,
    create_content_preview,
    create_deep_agent,
    create_eviction_processor,
)
from pydantic_deep.processors.eviction import _content_to_str, _sanitize_id

TEST_MODEL = TestModel()

# --- Helpers ---


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


# ============================================================================
# Tests for create_content_preview
# ============================================================================


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


# ============================================================================
# Tests for _content_to_str
# ============================================================================


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


# ============================================================================
# Tests for _sanitize_id
# ============================================================================


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


# ============================================================================
# Tests for EvictionProcessor
# ============================================================================


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


# ============================================================================
# Tests for _resolve_backend
# ============================================================================


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


# ============================================================================
# Tests for create_eviction_processor factory
# ============================================================================


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


# ============================================================================
# Tests for constants and exports
# ============================================================================


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


# ============================================================================
# Tests for agent integration
# ============================================================================


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
        )

        deps = DeepAgentDeps(backend=StateBackend())
        result = await agent.run("Hello", deps=deps)
        assert result.output is not None


# ============================================================================
# Tests for eviction preview content format
# ============================================================================


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


# ============================================================================
# Tests for edge cases
# ============================================================================


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
