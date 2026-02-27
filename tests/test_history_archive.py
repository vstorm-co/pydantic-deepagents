"""Tests for the conversation history search tool (history_archive module)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    SystemPromptPart,
    TextPart,
    ThinkingPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from pydantic_deep.processors.history_archive import (
    SEARCH_HISTORY_DESCRIPTION,
    _format_message,
    _format_messages,
    _load_messages,
    create_history_search_toolset,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TS = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _mock_ctx() -> object:
    """Minimal mock RunContext-like object."""
    return type("MockCtx", (), {"deps": None})()


def _write_messages(path: Path, messages: list[ModelMessage]) -> None:
    """Write messages to a JSON file using ModelMessagesTypeAdapter."""
    path.write_bytes(ModelMessagesTypeAdapter.dump_json(messages))


# ============================================================================
# Tests for _format_message
# ============================================================================


class TestFormatMessage:
    """Tests for the _format_message helper."""

    # --- ModelRequest parts ---

    def test_user_prompt_part(self) -> None:
        """UserPromptPart is formatted as 'User: ...'."""
        msg = ModelRequest(
            parts=[UserPromptPart(content="Hello there")],
            timestamp=_TS,
        )
        result = _format_message(msg)
        assert result == "User: Hello there"

    def test_system_prompt_part_normal(self) -> None:
        """Normal SystemPromptPart is formatted as 'System: ...' (truncated to 200 chars)."""
        msg = ModelRequest(
            parts=[SystemPromptPart(content="You are a helpful assistant.")],
            timestamp=_TS,
        )
        result = _format_message(msg)
        assert result == "System: You are a helpful assistant."

    def test_system_prompt_part_compression_summary(self) -> None:
        """SystemPromptPart starting with compression prefix becomes '[Compression summary]'."""
        msg = ModelRequest(
            parts=[
                SystemPromptPart(
                    content="Summary of previous conversation: The user asked about Python."
                )
            ],
            timestamp=_TS,
        )
        result = _format_message(msg)
        assert result == "[Compression summary]"

    def test_system_prompt_part_long_truncated_to_200(self) -> None:
        """SystemPromptPart content longer than 200 chars is truncated."""
        long_content = "A" * 300
        msg = ModelRequest(
            parts=[SystemPromptPart(content=long_content)],
            timestamp=_TS,
        )
        result = _format_message(msg)
        # Should be "System: " + first 200 chars
        assert result == f"System: {long_content[:200]}"
        assert len(result) == len("System: ") + 200

    def test_tool_return_part_short(self) -> None:
        """Short ToolReturnPart content is included in full."""
        msg = ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="read_file",
                    content="file contents here",
                    tool_call_id="c1",
                )
            ],
            timestamp=_TS,
        )
        result = _format_message(msg)
        assert result == "Tool [read_file]: file contents here"

    def test_tool_return_part_long_truncated_to_500(self) -> None:
        """ToolReturnPart content longer than 500 chars is truncated with '...'."""
        long_content = "X" * 600
        msg = ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="grep",
                    content=long_content,
                    tool_call_id="c2",
                )
            ],
            timestamp=_TS,
        )
        result = _format_message(msg)
        assert result == f"Tool [grep]: {long_content[:500]}..."
        assert len(result) == len("Tool [grep]: ") + 500 + 3  # 3 for "..."

    def test_tool_return_part_exactly_500(self) -> None:
        """ToolReturnPart content exactly 500 chars is NOT truncated."""
        content = "Y" * 500
        msg = ModelRequest(
            parts=[
                ToolReturnPart(
                    tool_name="execute",
                    content=content,
                    tool_call_id="c3",
                )
            ],
            timestamp=_TS,
        )
        result = _format_message(msg)
        assert result == f"Tool [execute]: {content}"
        assert "..." not in result

    # --- ModelResponse parts ---

    def test_text_part(self) -> None:
        """TextPart is formatted as 'Assistant: ...'."""
        msg = ModelResponse(
            parts=[TextPart(content="Here is the answer.")],
            timestamp=_TS,
        )
        result = _format_message(msg)
        assert result == "Assistant: Here is the answer."

    def test_tool_call_part_short_args(self) -> None:
        """ToolCallPart with short args includes full JSON."""
        msg = ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="read_file",
                    args={"path": "/tmp/test.py"},
                    tool_call_id="tc1",
                )
            ],
            timestamp=_TS,
        )
        result = _format_message(msg)
        assert "Tool Call [read_file]:" in result
        assert '"/tmp/test.py"' in result

    def test_tool_call_part_long_args_truncated_to_200(self) -> None:
        """ToolCallPart with args JSON longer than 200 chars is truncated."""
        long_value = "Z" * 300
        msg = ModelResponse(
            parts=[
                ToolCallPart(
                    tool_name="write_file",
                    args={"content": long_value},
                    tool_call_id="tc2",
                )
            ],
            timestamp=_TS,
        )
        result = _format_message(msg)
        assert "Tool Call [write_file]:" in result
        assert result.endswith("...")
        # The args JSON should be truncated to 200 chars + "..."
        prefix = "Tool Call [write_file]: "
        args_part = result[len(prefix) :]
        assert len(args_part) == 203  # 200 + "..."

    # --- Multiple parts in one message ---

    def test_multiple_parts_in_request(self) -> None:
        """Multiple parts in a single ModelRequest are all formatted."""
        msg = ModelRequest(
            parts=[
                UserPromptPart(content="Do something"),
                ToolReturnPart(
                    tool_name="execute",
                    content="output",
                    tool_call_id="c4",
                ),
            ],
            timestamp=_TS,
        )
        result = _format_message(msg)
        assert "User: Do something" in result
        assert "Tool [execute]: output" in result

    def test_multiple_parts_in_response(self) -> None:
        """Multiple parts in a single ModelResponse are all formatted."""
        msg = ModelResponse(
            parts=[
                TextPart(content="Let me check."),
                ToolCallPart(
                    tool_name="ls",
                    args={"path": "/"},
                    tool_call_id="tc3",
                ),
            ],
            timestamp=_TS,
        )
        result = _format_message(msg)
        assert "Assistant: Let me check." in result
        assert "Tool Call [ls]:" in result

    # --- Unhandled part types (fall-through branches) ---

    def test_retry_prompt_part_ignored(self) -> None:
        """RetryPromptPart in a request is silently ignored."""
        msg = ModelRequest(
            parts=[
                RetryPromptPart(
                    content="Please retry",
                    tool_name="test_tool",
                    tool_call_id="c99",
                ),
            ],
            timestamp=_TS,
        )
        result = _format_message(msg)
        assert result == ""

    def test_thinking_part_ignored(self) -> None:
        """ThinkingPart in a response is silently ignored."""
        msg = ModelResponse(
            parts=[ThinkingPart(content="Let me think...")],
            timestamp=_TS,
        )
        result = _format_message(msg)
        assert result == ""

    # --- Edge cases ---

    def test_empty_request(self) -> None:
        """ModelRequest with empty parts list returns empty string."""
        msg = ModelRequest(parts=[], timestamp=_TS)
        result = _format_message(msg)
        assert result == ""

    def test_empty_response(self) -> None:
        """ModelResponse with empty parts list returns empty string."""
        msg = ModelResponse(parts=[], timestamp=_TS)
        result = _format_message(msg)
        assert result == ""


# ============================================================================
# Tests for _format_messages
# ============================================================================


class TestFormatMessages:
    """Tests for the _format_messages helper."""

    def test_numbered_formatting(self) -> None:
        """Messages are formatted with [index] prefix."""
        messages: list[ModelMessage] = [
            ModelRequest(
                parts=[UserPromptPart(content="Hello")],
                timestamp=_TS,
            ),
            ModelResponse(
                parts=[TextPart(content="Hi!")],
                timestamp=_TS,
            ),
        ]
        lines = _format_messages(messages)
        assert len(lines) == 2
        assert lines[0] == "[0] User: Hello"
        assert lines[1] == "[1] Assistant: Hi!"

    def test_empty_messages_skipped(self) -> None:
        """Messages that produce empty formatted output are skipped."""
        messages: list[ModelMessage] = [
            ModelRequest(parts=[], timestamp=_TS),  # empty, will be skipped
            ModelRequest(
                parts=[UserPromptPart(content="Real message")],
                timestamp=_TS,
            ),
        ]
        lines = _format_messages(messages)
        assert len(lines) == 1
        assert lines[0] == "[1] User: Real message"

    def test_empty_list(self) -> None:
        """Empty message list returns empty line list."""
        assert _format_messages([]) == []


# ============================================================================
# Tests for _load_messages
# ============================================================================


class TestLoadMessages:
    """Tests for the _load_messages helper."""

    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        """Non-existent file returns empty list."""
        path = tmp_path / "nonexistent.json"
        result = _load_messages(str(path))
        assert result == []

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        """Empty file returns empty list."""
        path = tmp_path / "empty.json"
        path.write_text("")
        result = _load_messages(str(path))
        assert result == []

    def test_valid_messages_loaded(self, tmp_path: Path) -> None:
        """Valid JSON messages file is loaded correctly."""
        messages: list[ModelMessage] = [
            ModelRequest(
                parts=[UserPromptPart(content="Test question")],
                timestamp=_TS,
            ),
            ModelResponse(
                parts=[TextPart(content="Test answer")],
                timestamp=_TS,
            ),
        ]
        path = tmp_path / "messages.json"
        _write_messages(path, messages)

        result = _load_messages(str(path))
        assert len(result) == 2
        assert isinstance(result[0], ModelRequest)
        assert isinstance(result[1], ModelResponse)


# ============================================================================
# Tests for create_history_search_toolset
# ============================================================================


class TestCreateHistorySearchToolset:
    """Tests for the create_history_search_toolset factory and search tool."""

    def test_toolset_created_with_search_tool(self) -> None:
        """Toolset contains the search_conversation_history tool."""
        ts = create_history_search_toolset("/tmp/test.json")
        assert "search_conversation_history" in ts.tools

    def test_toolset_custom_id(self) -> None:
        """Custom id is set on the toolset."""
        ts = create_history_search_toolset("/tmp/test.json", id="custom-id")
        assert ts.id == "custom-id"

    def test_toolset_default_id(self) -> None:
        """Default id is 'deep-history-search'."""
        ts = create_history_search_toolset("/tmp/test.json")
        assert ts.id == "deep-history-search"

    @pytest.mark.anyio
    async def test_search_no_history_file(self, tmp_path: Path) -> None:
        """Search returns 'no history' message when file doesn't exist."""
        path = tmp_path / "nonexistent.json"
        ts = create_history_search_toolset(str(path))
        fn = ts.tools["search_conversation_history"].function
        ctx = _mock_ctx()

        result = await fn(ctx, "anything")
        assert "No conversation history saved yet" in result

    @pytest.mark.anyio
    async def test_search_empty_file(self, tmp_path: Path) -> None:
        """Search returns 'no history' message when file is empty."""
        path = tmp_path / "empty.json"
        path.write_text("")
        ts = create_history_search_toolset(str(path))
        fn = ts.tools["search_conversation_history"].function
        ctx = _mock_ctx()

        result = await fn(ctx, "anything")
        assert "No conversation history saved yet" in result

    @pytest.mark.anyio
    async def test_search_no_matches(self, tmp_path: Path) -> None:
        """Search returns 'no matches' when query is not found."""
        messages: list[ModelMessage] = [
            ModelRequest(
                parts=[UserPromptPart(content="Hello world")],
                timestamp=_TS,
            ),
            ModelResponse(
                parts=[TextPart(content="Hi there!")],
                timestamp=_TS,
            ),
        ]
        path = tmp_path / "messages.json"
        _write_messages(path, messages)

        ts = create_history_search_toolset(str(path))
        fn = ts.tools["search_conversation_history"].function
        ctx = _mock_ctx()

        result = await fn(ctx, "nonexistent_query_xyz")
        assert "No matches for 'nonexistent_query_xyz'" in result
        assert "2 archived messages" in result

    @pytest.mark.anyio
    async def test_search_finds_match(self, tmp_path: Path) -> None:
        """Search finds matching messages and returns them with context."""
        messages: list[ModelMessage] = [
            ModelRequest(
                parts=[UserPromptPart(content="Tell me about Python")],
                timestamp=_TS,
            ),
            ModelResponse(
                parts=[TextPart(content="Python is a programming language.")],
                timestamp=_TS,
            ),
        ]
        path = tmp_path / "messages.json"
        _write_messages(path, messages)

        ts = create_history_search_toolset(str(path))
        fn = ts.tools["search_conversation_history"].function
        ctx = _mock_ctx()

        result = await fn(ctx, "Python")
        assert "Found" in result
        assert "match" in result
        assert "Python" in result

    @pytest.mark.anyio
    async def test_search_case_insensitive(self, tmp_path: Path) -> None:
        """Search is case-insensitive."""
        messages: list[ModelMessage] = [
            ModelRequest(
                parts=[UserPromptPart(content="UPPERCASE content")],
                timestamp=_TS,
            ),
        ]
        path = tmp_path / "messages.json"
        _write_messages(path, messages)

        ts = create_history_search_toolset(str(path))
        fn = ts.tools["search_conversation_history"].function
        ctx = _mock_ctx()

        result = await fn(ctx, "uppercase")
        assert "Found" in result
        assert "UPPERCASE" in result

    @pytest.mark.anyio
    async def test_search_multiple_matches(self, tmp_path: Path) -> None:
        """Search returns multiple matching excerpts."""
        messages: list[ModelMessage] = [
            ModelRequest(
                parts=[UserPromptPart(content="First mention of keyword alpha")],
                timestamp=_TS,
            ),
            ModelResponse(
                parts=[TextPart(content="Unrelated response")],
                timestamp=_TS,
            ),
            ModelRequest(
                parts=[UserPromptPart(content="Second mention of keyword alpha")],
                timestamp=_TS,
            ),
        ]
        path = tmp_path / "messages.json"
        _write_messages(path, messages)

        ts = create_history_search_toolset(str(path))
        fn = ts.tools["search_conversation_history"].function
        ctx = _mock_ctx()

        result = await fn(ctx, "alpha")
        assert "Found 2 match(es)" in result
        assert "---" in result  # Separator between excerpts

    @pytest.mark.anyio
    async def test_search_context_lines(self, tmp_path: Path) -> None:
        """Search results include context lines around the match."""
        # Create enough messages so context lines are meaningful
        messages: list[ModelMessage] = []
        for i in range(15):
            if i == 7:
                messages.append(
                    ModelRequest(
                        parts=[UserPromptPart(content="TARGET_KEYWORD here")],
                        timestamp=_TS,
                    )
                )
            else:
                messages.append(
                    ModelRequest(
                        parts=[UserPromptPart(content=f"Message number {i}")],
                        timestamp=_TS,
                    )
                )

        path = tmp_path / "messages.json"
        _write_messages(path, messages)

        ts = create_history_search_toolset(str(path))
        fn = ts.tools["search_conversation_history"].function
        ctx = _mock_ctx()

        result = await fn(ctx, "TARGET_KEYWORD")
        assert "Found 1 match(es)" in result
        # Context should include surrounding messages
        assert "TARGET_KEYWORD" in result
        # Should include some surrounding context lines
        assert "Message number" in result

    @pytest.mark.anyio
    async def test_search_with_all_part_types(self, tmp_path: Path) -> None:
        """Search works across all message part types."""
        messages: list[ModelMessage] = [
            ModelRequest(
                parts=[
                    UserPromptPart(content="user_searchable_content"),
                    SystemPromptPart(content="system_searchable_content"),
                    ToolReturnPart(
                        tool_name="grep",
                        content="tool_return_searchable_content",
                        tool_call_id="c1",
                    ),
                ],
                timestamp=_TS,
            ),
            ModelResponse(
                parts=[
                    TextPart(content="assistant_searchable_content"),
                    ToolCallPart(
                        tool_name="read_file",
                        args={"path": "/tool_call_searchable_content"},
                        tool_call_id="tc1",
                    ),
                ],
                timestamp=_TS,
            ),
        ]
        path = tmp_path / "messages.json"
        _write_messages(path, messages)

        ts = create_history_search_toolset(str(path))
        fn = ts.tools["search_conversation_history"].function
        ctx = _mock_ctx()

        # Search for content from each part type
        for query in [
            "user_searchable",
            "system_searchable",
            "tool_return_searchable",
            "assistant_searchable",
            "tool_call_searchable",
        ]:
            result = await fn(ctx, query)
            assert "Found" in result, f"Expected match for query '{query}'"

    @pytest.mark.anyio
    async def test_search_with_compression_summary(self, tmp_path: Path) -> None:
        """Compression summaries are formatted as '[Compression summary]'."""
        messages: list[ModelMessage] = [
            ModelRequest(
                parts=[
                    SystemPromptPart(
                        content="Summary of previous conversation: discussed Python coding"
                    )
                ],
                timestamp=_TS,
            ),
        ]
        path = tmp_path / "messages.json"
        _write_messages(path, messages)

        ts = create_history_search_toolset(str(path))
        fn = ts.tools["search_conversation_history"].function
        ctx = _mock_ctx()

        # Search for "Compression" which appears in the formatted output
        result = await fn(ctx, "Compression")
        assert "Found" in result
        assert "Compression summary" in result


# ============================================================================
# Tests for SEARCH_HISTORY_DESCRIPTION constant
# ============================================================================


class TestConstants:
    """Tests for module constants."""

    def test_search_description_not_empty(self) -> None:
        """SEARCH_HISTORY_DESCRIPTION is a non-empty string."""
        assert isinstance(SEARCH_HISTORY_DESCRIPTION, str)
        assert len(SEARCH_HISTORY_DESCRIPTION) > 0

    def test_search_description_content(self) -> None:
        """SEARCH_HISTORY_DESCRIPTION contains expected guidance."""
        assert "conversation history" in SEARCH_HISTORY_DESCRIPTION.lower()
        assert "When to use" in SEARCH_HISTORY_DESCRIPTION
        assert "When NOT to use" in SEARCH_HISTORY_DESCRIPTION
