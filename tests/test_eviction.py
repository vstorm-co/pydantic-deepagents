"""Tests for the large tool output eviction processor."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import RunContext, ToolDefinition
from pydantic_ai.usage import RunUsage
from pydantic_ai_backends import StateBackend, WriteResult, ensure_async

from pydantic_deep import (
    DEFAULT_EVICTION_PATH,
    DEFAULT_TOKEN_LIMIT,
    EVICTION_MESSAGE_TEMPLATE,
    NUM_CHARS_PER_TOKEN,
    DeepAgentDeps,
    EvictionCapability,
    create_content_preview,
    create_deep_agent,
)
from pydantic_deep.features.eviction.capability import _content_to_str, _sanitize_id

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

    def test_single_line_huge_content_capped_by_chars(self):
        """A single line with no newlines (minified JSON / base64) must still be
        shrunk by the character cap - the line logic alone would return it whole."""
        content = '{"k":"' + "x" * 100_000 + '"}'  # one logical line, no '\n'
        result = create_content_preview(content, max_chars=2_000)
        assert len(result) < len(content)
        assert len(result) <= 2_000 + 100  # cap + marker overhead
        assert "chars truncated" in result
        # Head and tail of the payload are preserved.
        assert result.startswith('{"k":"')
        assert result.endswith('"}')

    def test_multiline_preview_also_char_capped(self):
        """Few long lines whose head/tail join still exceeds the cap get clipped."""
        lines = [("a" * 1_000) for _ in range(20)]
        content = "\n".join(lines)
        result = create_content_preview(content, head_lines=3, tail_lines=3, max_chars=500)
        assert len(result) <= 500 + 100
        assert "chars truncated" in result

    def test_char_cap_not_applied_to_small_content(self):
        """Content already under the cap is returned without a char marker."""
        content = "line 1\nline 2\nline 3"
        result = create_content_preview(content, max_chars=2_000)
        assert result == content
        assert "chars truncated" not in result


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
        """Lossy sanitization gets a disambiguating hash suffix (B8)."""
        out = _sanitize_id("call/abc.123!@#")
        assert out.startswith("call_abc_123___-")

    def test_lossy_ids_do_not_collide(self):
        """Distinct ids that sanitize to the same prefix stay distinct files (B8)."""
        a = _sanitize_id("a/b")
        b = _sanitize_id("a:b")
        assert a != b
        assert a.startswith("a_b-") and b.startswith("a_b-")

    def test_hyphens_preserved(self):
        """Hyphens are preserved in the sanitized ID."""
        assert _sanitize_id("call-abc-123") == "call-abc-123"

    def test_empty_string(self):
        """Empty string returns empty."""
        assert _sanitize_id("") == ""


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
        cap = EvictionCapability(backend=ensure_async(backend), token_limit=100)
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
        cap = EvictionCapability(backend=ensure_async(backend), token_limit=10)  # 40 chars
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
        evicted = backend.read_bytes("/large_tool_results/call_big")
        assert evicted == large.encode()

    @pytest.mark.anyio
    async def test_uses_deps_backend(self):
        """Resolves backend from ctx.deps over fallback."""
        fallback = StateBackend()
        deps_backend = StateBackend()
        cap = EvictionCapability(backend=ensure_async(fallback), token_limit=10)
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
        assert deps_backend.read_bytes("/large_tool_results/call_deps") not in (None, b"")
        assert fallback.read_bytes("/large_tool_results/call_deps") in (None, b"")

    @pytest.mark.anyio
    async def test_no_backend_passes_through(self):
        """No backend available - returns result unchanged."""
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
        cap = EvictionCapability(
            backend=ensure_async(backend), token_limit=10, on_eviction=callback
        )
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
    async def test_write_failure_returns_truncated_preview(self):
        """B4: when the backend write fails, return a truncated preview, not the full blob."""
        backend = StateBackend()

        def failing_write(path: str, content: str | bytes) -> WriteResult:
            return WriteResult(path=path, error="disk full")

        backend.write = failing_write
        cap = EvictionCapability(backend=ensure_async(backend), token_limit=10)
        ctx = _make_ctx(backend)

        large = _make_large_content(100)  # well over the 2 000-char preview cap
        result = await cap.after_tool_execute(
            ctx,
            call=_cap_call(call_id="call_fail"),
            tool_def=_cap_td(),
            args={},
            result=large,
        )
        assert result != large  # full oversized payload not re-admitted
        assert len(result) < len(large)

    def test_non_positive_token_limit_rejected(self):
        """B10: token_limit <= 0 would evict everything; reject it at construction."""
        with pytest.raises(ValueError, match="token_limit must be positive"):
            EvictionCapability(token_limit=0)
        with pytest.raises(ValueError, match="token_limit must be positive"):
            EvictionCapability(token_limit=-5)

    @pytest.mark.anyio
    async def test_on_eviction_exception_does_not_abort(self):
        """B10: a raising on_eviction callback is swallowed, eviction still completes."""
        backend = StateBackend()

        def boom(tool_name: str, file_path: str, original: int, preview: int) -> None:
            raise RuntimeError("callback blew up")

        cap = EvictionCapability(backend=ensure_async(backend), token_limit=10, on_eviction=boom)
        ctx = _make_ctx(backend)
        result = await cap.after_tool_execute(
            ctx,
            call=_cap_call(call_id="call_cbboom"),
            tool_def=_cap_td(),
            args={},
            result=_make_large_content(20),
        )
        assert "Tool result too large" in result  # eviction still happened

    @pytest.mark.anyio
    async def test_async_on_eviction_callback(self):
        """Async on_eviction callback is awaited."""
        backend = StateBackend()
        called_with: list[tuple[str, str, int, int]] = []

        async def async_cb(tool_name: str, file_path: str, orig: int, preview: int) -> None:
            called_with.append((tool_name, file_path, orig, preview))

        cap = EvictionCapability(
            backend=ensure_async(backend), token_limit=10, on_eviction=async_cb
        )
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
        cap = EvictionCapability(backend=ensure_async(backend), token_limit=10)
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
    """Tests for `EvictionCapability` handling of `ToolReturn` results."""

    @pytest.mark.anyio
    async def test_toolreturn_preserves_binary_content(self):
        """ToolReturn with BinaryContent in `content` is not collapsed by text eviction."""
        from pydantic_ai.messages import BinaryContent, ToolReturn

        backend = StateBackend()
        cap = EvictionCapability(backend=ensure_async(backend), token_limit=10)
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
        assert backend.read_bytes("/large_tool_results/call_screenshot") in (None, b"")

    @pytest.mark.anyio
    async def test_toolreturn_evicts_only_return_value(self):
        """Large ToolReturn.return_value is evicted but content is preserved."""
        from pydantic_ai.messages import BinaryContent, ToolReturn

        backend = StateBackend()
        cap = EvictionCapability(backend=ensure_async(backend), token_limit=10)  # 40 chars
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
        assert backend.read_bytes("/large_tool_results/call_big_tr") == large_text.encode()

    @pytest.mark.anyio
    async def test_toolreturn_small_passes_through(self):
        """Small ToolReturn passes through unchanged (same instance)."""
        from pydantic_ai.messages import BinaryContent, ToolReturn

        backend = StateBackend()
        cap = EvictionCapability(backend=ensure_async(backend), token_limit=1000)
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

    @pytest.mark.anyio
    async def test_bare_binary_content_returned_unchanged(self):
        """A bare BinaryContent result (not wrapped in ToolReturn) must be
        returned as-is - never coerced into its ~100KB text repr."""
        from pydantic_ai.messages import BinaryContent

        backend = StateBackend()
        cap = EvictionCapability(backend=ensure_async(backend), token_limit=10)  # 40-char threshold
        ctx = _make_ctx(backend)

        image = BinaryContent(data=b"\x89PNG" + b"\x00" * 100_000, media_type="image/png")
        result = await cap.after_tool_execute(
            ctx,
            call=_cap_call(call_id="call_bare_img"),
            tool_def=_cap_td(),
            args={},
            result=image,
        )

        # Same object back: bytes preserved, no text eviction.
        assert result is image
        assert isinstance(result, BinaryContent)
        # Nothing was written to the eviction path.
        assert backend.read_bytes("/large_tool_results/call_bare_img") in (None, b"")

    @pytest.mark.anyio
    async def test_list_with_binary_content_returned_unchanged(self):
        """A list mixing text and BinaryContent must be returned as-is so the
        binary is not lost to text eviction."""
        from pydantic_ai.messages import BinaryContent

        backend = StateBackend()
        cap = EvictionCapability(backend=ensure_async(backend), token_limit=10)
        ctx = _make_ctx(backend)

        image = BinaryContent(data=b"\xff\xd8" + b"x" * 100_000, media_type="image/jpeg")
        original = ["here is the screenshot", image]
        result = await cap.after_tool_execute(
            ctx,
            call=_cap_call(call_id="call_list_img"),
            tool_def=_cap_td(),
            args={},
            result=original,
        )

        assert result is original
        assert backend.read_bytes("/large_tool_results/call_list_img") in (None, b"")


# ---------------------------------------------------------------------------
# Binary content retention (before_model_request)
# ---------------------------------------------------------------------------


class _FakeRequestContext:
    """Minimal stand-in for `ModelRequestContext` used in tests."""

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
    """Tests for `EvictionCapability.before_model_request` binary pruning."""

    @pytest.mark.anyio
    async def test_keeps_most_recent_binaries(self):
        """The N most recent binaries are kept; older ones are pruned and stored."""
        from pydantic_ai.messages import BinaryContent

        backend = StateBackend()
        cap = EvictionCapability(backend=ensure_async(backend), max_binary_content=2)
        ctx = _make_ctx(backend)

        # 4 messages, each with one image - newest last
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
                    items = part.content if isinstance(part.content, list) else [part.content]
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
        assert backend.read_bytes(path) == b"image-0-bytes" * 8

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
        cap = EvictionCapability(backend=ensure_async(backend), max_binary_content=3)
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
        """`max_binary_content=None` keeps every binary in history."""
        from pydantic_ai.messages import BinaryContent

        backend = StateBackend()
        cap = EvictionCapability(backend=ensure_async(backend), max_binary_content=None)
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
        """Binary parts inside `ToolReturnPart.content` are also pruned and stored."""
        from pydantic_ai.messages import BinaryContent

        backend = StateBackend()
        cap = EvictionCapability(backend=ensure_async(backend), max_binary_content=1)
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
        assert any(isinstance(x, str) and "Binary content omitted" in x for x in old_part.content)

        assert isinstance(new_part.content, list)
        assert any(isinstance(x, BinaryContent) for x in new_part.content)

        # Stored bytes match the original BinaryContent.data
        old_bin = BinaryContent(data=old_bytes, media_type="image/jpeg")
        path = f"/large_tool_results/binary_{old_bin.identifier}.jpg"
        assert backend.read_bytes(path) == old_bytes

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
        cap = EvictionCapability(backend=ensure_async(backend), max_binary_content=1)
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
    """`max_binary_content` plumbing through `create_deep_agent`."""

    def _eviction_capabilities(self, agent: object) -> list[EvictionCapability]:
        root = getattr(agent, "_root_capability", None)
        if root is None:
            return []
        return [c for c in getattr(root, "capabilities", []) if isinstance(c, EvictionCapability)]

    def test_agent_accepts_max_binary_content(self):
        """`create_deep_agent` accepts `max_binary_content` and forwards it."""
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
        """Default `max_binary_content` is 3 when not specified."""
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
        """`max_binary_content=None` disables pruning."""
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
    """Tests for the `_extension_for_media_type` helper."""

    def test_known_media_type_uses_mapping(self):
        from pydantic_deep.features.eviction.capability import _extension_for_media_type

        assert _extension_for_media_type("image/jpeg") == "jpg"
        assert _extension_for_media_type("image/png") == "png"

    def test_unknown_media_type_uses_subtype(self):
        from pydantic_deep.features.eviction.capability import _extension_for_media_type

        assert _extension_for_media_type("image/x-foo") == "x-foo"
        assert _extension_for_media_type("application/x-custom; charset=utf-8") == "x-custom"

    def test_subtype_special_chars_sanitized(self):
        from pydantic_deep.features.eviction.capability import _extension_for_media_type

        assert _extension_for_media_type("image/foo.bar") == "foo_bar"

    def test_no_slash_falls_back_to_bin(self):
        from pydantic_deep.features.eviction.capability import _extension_for_media_type

        assert _extension_for_media_type("weirdmediatype") == "bin"

    def test_empty_subtype_falls_back_to_bin(self):
        from pydantic_deep.features.eviction.capability import _extension_for_media_type

        assert _extension_for_media_type("image/") == "bin"


class TestBinaryRetentionEdgeCases:
    """Edge cases for `before_model_request` binary pruning."""

    @pytest.mark.anyio
    async def test_bare_binary_in_toolreturn_content_pruned(self):
        """Bare `BinaryContent` (not in a list) on `ToolReturnPart.content` is pruned."""
        from pydantic_ai.messages import BinaryContent

        backend = StateBackend()
        cap = EvictionCapability(backend=ensure_async(backend), max_binary_content=1)
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
        assert backend.read_bytes(path) == old_bytes

    @pytest.mark.anyio
    async def test_bare_binary_under_limit_unchanged(self):
        """Bare `BinaryContent` under the limit is left untouched."""
        from pydantic_ai.messages import BinaryContent

        backend = StateBackend()
        cap = EvictionCapability(backend=ensure_async(backend), max_binary_content=3)
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
        """A failed backend write leaves a bare `BinaryContent` untouched."""
        from pydantic_ai.messages import BinaryContent

        backend = StateBackend()

        def failing_write(path: str, content: str | bytes) -> WriteResult:
            return WriteResult(path=path, error="disk full")

        backend.write = failing_write
        cap = EvictionCapability(backend=ensure_async(backend), max_binary_content=1)
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
        cap = EvictionCapability(backend=ensure_async(backend), max_binary_content=1)
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
        """Non user/tool-return parts (e.g. `RetryPromptPart`) are passed over."""
        from pydantic_ai.messages import RetryPromptPart

        backend = StateBackend()
        cap = EvictionCapability(backend=ensure_async(backend), max_binary_content=1)
        ctx = _make_ctx(backend)

        retry_msg = ModelRequest(
            parts=[RetryPromptPart(content="please retry")],
            timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )

        rc = _FakeRequestContext([retry_msg])
        result_rc = await cap.before_model_request(ctx, rc)

        # Same instance - nothing to prune
        assert result_rc.messages[0] is retry_msg

    @pytest.mark.anyio
    async def test_non_list_non_binary_toolreturn_content_unchanged(self):
        """Scalar non-binary `ToolReturnPart.content` (e.g. a dict) is left as-is."""
        from pydantic_ai.messages import BinaryContent

        backend = StateBackend()
        cap = EvictionCapability(backend=ensure_async(backend), max_binary_content=1)
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
