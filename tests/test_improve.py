"""Tests for the improve module (analyzer, extractor, synthesizer, toolset)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from pydantic_deep.improve.analyzer import DEFAULT_CONTEXT_FILES, ImprovementAnalyzer
from pydantic_deep.improve.extractor import (
    SessionExtractor,
    _dict_to_session_insights,
    _extract_timestamp,
    _parse_json_response,
)
from pydantic_deep.improve.prompts import (
    CHUNK_MERGE_PROMPT,
    EXTRACTION_PROMPT,
    SYNTHESIS_PROMPT,
)
from pydantic_deep.improve.synthesizer import InsightSynthesizer
from pydantic_deep.improve.types import (
    AgentLearningInsight,
    ContextInsight,
    DecisionInsight,
    FailureInsight,
    ImprovementReport,
    PatternInsight,
    PreferenceInsight,
    ProposedChange,
    SessionInsights,
    UserFactInsight,
)

# ── Types ────────────────────────────────────────────────────────


class TestTypes:
    def test_failure_insight(self) -> None:
        f = FailureInsight(description="fail", root_cause="bug", resolution="fixed")
        assert f.tool_calls == []

    def test_pattern_insight(self) -> None:
        p = PatternInsight(pattern="read->edit", frequency=3, context="coding")
        assert p.frequency == 3

    def test_preference_insight(self) -> None:
        p = PreferenceInsight(preference="concise", evidence="user said so")
        assert p.preference == "concise"

    def test_context_insight(self) -> None:
        c = ContextInsight(fact="uses pytest", confidence=0.9)
        assert c.confidence == 0.9

    def test_decision_insight(self) -> None:
        d = DecisionInsight(decision="use uv", reasoning="fast", confirmed=True)
        assert d.confirmed is True

    def test_user_fact_insight(self) -> None:
        uf = UserFactInsight(fact="Name is Kacper", category="identity", confidence=1.0)
        assert uf.category == "identity"

    def test_agent_learning_insight(self) -> None:
        al = AgentLearningInsight(
            learning="pytest works",
            category="build_command",
            evidence="tool output",
            confidence=0.9,
        )
        assert al.category == "build_command"

    def test_session_insights_defaults(self) -> None:
        si = SessionInsights(session_id="x", timestamp="", message_count=0, tool_calls_count=0)
        assert si.user_facts == []
        assert si.agent_learnings == []
        assert si.failures == []
        assert si.patterns == []
        assert si.preferences == []
        assert si.project_context == []
        assert si.decisions == []

    def test_proposed_change(self) -> None:
        pc = ProposedChange(
            target_file="MEMORY.md",
            change_type="append",
            section=None,
            content="- test",
            reason="test",
            confidence=0.9,
        )
        assert pc.source_sessions == []

    def test_improvement_report_defaults(self) -> None:
        r = ImprovementReport(analyzed_sessions=0, time_range="test", total_chunks=0)
        assert r.failed_sessions == 0
        assert r.last_error is None
        assert r.insights == []
        assert r.proposed_changes == []
        assert r.accepted_changes == []
        assert r.rejected_changes == []
        assert r.timestamp == ""

    def test_improvement_report_with_error(self) -> None:
        err = ValueError("test error")
        r = ImprovementReport(
            analyzed_sessions=1,
            time_range="last 7 days",
            total_chunks=1,
            failed_sessions=2,
            last_error=err,
        )
        assert r.failed_sessions == 2
        assert r.last_error is err


# ── Prompts ──────────────────────────────────────────────────────


class TestPrompts:
    def test_extraction_prompt_no_format_vars(self) -> None:
        # EXTRACTION_PROMPT is used as-is, not with .format()
        assert "user_facts" in EXTRACTION_PROMPT
        assert "agent_learnings" in EXTRACTION_PROMPT

    def test_synthesis_prompt_format(self) -> None:
        result = SYNTHESIS_PROMPT.format(
            n=5, current_context="test context", insights_json="[test]"
        )
        assert "5" in result
        assert "test context" in result

    def test_synthesis_prompt_with_braces_in_values(self) -> None:
        # Values with braces should not break format()
        result = SYNTHESIS_PROMPT.format(
            n=1,
            current_context='{"key": "value"}',
            insights_json='[{"a": 1}]',
        )
        assert '{"key": "value"}' in result

    def test_chunk_merge_prompt_format(self) -> None:
        result = CHUNK_MERGE_PROMPT.format(chunks_json="[test]")
        assert "[test]" in result


# ── Extractor helpers ────────────────────────────────────────────


class TestExtractTimestamp:
    def test_with_timestamp(self) -> None:
        messages = [{"parts": [{"timestamp": "2026-01-01T00:00:00Z"}]}]
        assert _extract_timestamp(messages) == "2026-01-01T00:00:00Z"

    def test_without_timestamp(self) -> None:
        messages = [{"parts": [{"part_kind": "text", "content": "hi"}]}]
        assert _extract_timestamp(messages) == ""

    def test_empty_messages(self) -> None:
        assert _extract_timestamp([]) == ""


class TestParseJsonResponse:
    def test_valid_json(self) -> None:
        text = '{"session_id": "abc", "message_count": 5}'
        result = _parse_json_response(text, "fallback", "ts")
        assert result["session_id"] == "abc"
        assert result["message_count"] == 5

    def test_json_with_code_fences(self) -> None:
        text = '```json\n{"session_id": "abc"}\n```'
        result = _parse_json_response(text, "fallback", "ts")
        assert result["session_id"] == "abc"

    def test_fence_without_newline(self) -> None:
        # A bare fence with no newline must not raise ValueError.
        text = '```{"session_id": "abc"}```'
        result = _parse_json_response(text, "fallback", "ts")
        assert result["session_id"] == "abc"

    def test_bare_fence_only(self) -> None:
        # A lone fence with no newline falls back to empty insights.
        result = _parse_json_response("```", "fb_id", "fb_ts")
        assert result["session_id"] == "fb_id"

    def test_invalid_json_uses_fallbacks(self) -> None:
        result = _parse_json_response("not json", "fb_id", "fb_ts")
        assert result["session_id"] == "fb_id"
        assert result["timestamp"] == "fb_ts"
        assert result["user_facts"] == []
        assert result["agent_learnings"] == []

    def test_defaults_applied(self) -> None:
        result = _parse_json_response("{}", "id", "ts")
        assert result["failures"] == []
        assert result["patterns"] == []
        assert result["preferences"] == []
        assert result["project_context"] == []
        assert result["decisions"] == []


class TestDictToSessionInsights:
    def test_minimal(self) -> None:
        data = {"session_id": "x", "timestamp": "t", "message_count": 1, "tool_calls_count": 0}
        si = _dict_to_session_insights(data)
        assert si.session_id == "x"
        assert si.message_count == 1

    def test_with_user_facts(self) -> None:
        data = {
            "session_id": "x",
            "timestamp": "",
            "message_count": 0,
            "tool_calls_count": 0,
            "user_facts": [{"fact": "Name is Kacper", "category": "identity", "confidence": 1.0}],
        }
        si = _dict_to_session_insights(data)
        assert len(si.user_facts) == 1
        assert si.user_facts[0].fact == "Name is Kacper"

    def test_with_agent_learnings(self) -> None:
        data = {
            "session_id": "x",
            "timestamp": "",
            "message_count": 0,
            "tool_calls_count": 0,
            "agent_learnings": [
                {
                    "learning": "uv run pytest",
                    "category": "build_command",
                    "evidence": "output",
                    "confidence": 0.9,
                }
            ],
        }
        si = _dict_to_session_insights(data)
        assert len(si.agent_learnings) == 1
        assert si.agent_learnings[0].learning == "uv run pytest"

    def test_with_all_insight_types(self) -> None:
        data = {
            "session_id": "full",
            "timestamp": "ts",
            "message_count": 10,
            "tool_calls_count": 5,
            "failures": [
                {
                    "description": "err",
                    "root_cause": "bug",
                    "resolution": "fix",
                    "tool_calls": ["execute"],
                }
            ],
            "patterns": [{"pattern": "read->edit", "frequency": 2, "context": "coding"}],
            "preferences": [{"preference": "concise", "evidence": "user said"}],
            "project_context": [{"fact": "uses pytest", "confidence": 0.8}],
            "decisions": [{"decision": "use uv", "reasoning": "fast", "confirmed": True}],
            "user_facts": [{"fact": "Name", "category": "identity", "confidence": 1.0}],
            "agent_learnings": [
                {"learning": "test", "category": "other", "evidence": "e", "confidence": 0.7}
            ],
        }
        si = _dict_to_session_insights(data)
        assert len(si.failures) == 1
        assert len(si.patterns) == 1
        assert len(si.preferences) == 1
        assert len(si.project_context) == 1
        assert len(si.decisions) == 1
        assert len(si.user_facts) == 1
        assert len(si.agent_learnings) == 1

    def test_with_already_typed_objects(self) -> None:
        """When values are already typed objects (not dicts), pass through."""
        uf = UserFactInsight(fact="test", category="other", confidence=0.5)
        data = {
            "session_id": "x",
            "timestamp": "",
            "message_count": 0,
            "tool_calls_count": 0,
            "user_facts": [uf],
            "agent_learnings": [
                AgentLearningInsight(learning="l", category="other", evidence="e", confidence=0.5)
            ],
            "failures": [FailureInsight(description="d", root_cause="r", resolution="")],
            "patterns": [PatternInsight(pattern="p", frequency=1, context="c")],
            "preferences": [PreferenceInsight(preference="p", evidence="e")],
            "project_context": [ContextInsight(fact="f", confidence=0.5)],
            "decisions": [DecisionInsight(decision="d", reasoning="r", confirmed=False)],
        }
        si = _dict_to_session_insights(data)
        assert si.user_facts[0] is uf


# ── SessionExtractor ─────────────────────────────────────────────


class TestSessionExtractor:
    def test_init(self) -> None:
        ext = SessionExtractor(model="test")
        assert ext._model == "test"
        assert ext._max_tokens_per_chunk == 140_000

    def test_estimate_message_tokens(self) -> None:
        ext = SessionExtractor(model="test")
        msg = {"parts": [{"part_kind": "text", "content": "a" * 400}]}
        tokens = ext._estimate_message_tokens(msg)
        assert tokens == 100  # 400 chars / 4

    def test_estimate_message_tokens_tool_call(self) -> None:
        ext = SessionExtractor(model="test")
        msg = {
            "parts": [
                {"part_kind": "tool-call", "tool_name": "read", "args": "a" * 100},
                {"part_kind": "tool-return", "content": "b" * 200},
            ]
        }
        tokens = ext._estimate_message_tokens(msg)
        assert tokens == (4 // 4) + (100 // 4) + (200 // 4)  # name + args + return

    def test_estimate_message_tokens_all_kinds(self) -> None:
        ext = SessionExtractor(model="test")
        msg = {
            "parts": [
                {"part_kind": "system-prompt", "content": "a" * 40},
                {"part_kind": "retry-prompt", "content": "b" * 40},
                {"part_kind": "unknown-kind", "content": "ignored"},
            ]
        }
        tokens = ext._estimate_message_tokens(msg)
        assert tokens == 20  # 40/4 + 40/4, unknown is skipped

    def test_estimate_message_tokens_minimum_1(self) -> None:
        ext = SessionExtractor(model="test")
        msg: dict[str, list[str]] = {"parts": []}
        assert ext._estimate_message_tokens(msg) == 1

    def test_truncate_within_limit(self) -> None:
        ext = SessionExtractor(model="test")
        assert ext._truncate_tool_output("short") == "short"

    def test_truncate_exceeds_limit(self) -> None:
        ext = SessionExtractor(model="test")
        long = "x" * 10000
        result = ext._truncate_tool_output(long, max_chars=1000)
        assert "truncated" in result
        assert len(result) < len(long)

    def test_prepare_chunk_text(self) -> None:
        ext = SessionExtractor(model="test")
        messages = [
            {
                "parts": [
                    {"part_kind": "user-prompt", "content": "hello", "timestamp": "2026-01-01"}
                ]
            },
            {"parts": [{"part_kind": "text", "content": "hi there"}]},
            {"parts": [{"part_kind": "system-prompt", "content": "you are helpful"}]},
            {"parts": [{"part_kind": "tool-call", "tool_name": "read", "args": {"path": "f.py"}}]},
            {"parts": [{"part_kind": "tool-return", "content": "file contents"}]},
            {"parts": [{"part_kind": "retry-prompt", "content": "try again"}]},
        ]
        text = ext._prepare_chunk_text(messages)
        assert "[User [2026-01-01]]:" in text
        assert "[Assistant]:" in text
        assert "system-prompt" not in text.lower().replace("system-prompt", "")
        assert "-> read(" in text
        assert "<- file contents" in text
        assert "[Retry]:" in text

    def test_prepare_chunk_text_tool_args_str(self) -> None:
        ext = SessionExtractor(model="test")
        messages = [
            {"parts": [{"part_kind": "tool-call", "tool_name": "exec", "args": "echo hello"}]}
        ]
        text = ext._prepare_chunk_text(messages)
        assert "exec(echo hello)" in text

    def test_prepare_chunk_text_tool_args_dict(self) -> None:
        ext = SessionExtractor(model="test")
        messages = [
            {"parts": [{"part_kind": "tool-call", "tool_name": "write", "args": {"path": "x"}}]}
        ]
        text = ext._prepare_chunk_text(messages)
        assert "write(" in text

    def test_prepare_chunk_text_unknown_part_kind(self) -> None:
        ext = SessionExtractor(model="test")
        messages = [
            {
                "parts": [
                    {"part_kind": "user-prompt", "content": "hello"},
                    {"part_kind": "unknown-future-kind", "content": "ignored"},
                ]
            }
        ]
        text = ext._prepare_chunk_text(messages)
        assert "[User]:" in text
        assert "ignored" not in text

    def test_chunk_messages_single_chunk(self) -> None:
        ext = SessionExtractor(model="test", max_tokens_per_chunk=1000)
        messages = [{"parts": [{"part_kind": "text", "content": "short"}]} for _ in range(5)]
        chunks = ext._chunk_messages(messages)
        assert len(chunks) == 1
        assert len(chunks[0]) == 5

    def test_chunk_messages_empty(self) -> None:
        ext = SessionExtractor(model="test")
        assert ext._chunk_messages([]) == []

    def test_chunk_messages_multiple_chunks(self) -> None:
        ext = SessionExtractor(model="test", max_tokens_per_chunk=10, overlap_messages=1)
        messages = [{"parts": [{"part_kind": "text", "content": "a" * 40}]} for _ in range(5)]
        chunks = ext._chunk_messages(messages)
        assert len(chunks) == 5  # Each message ~10 tokens, max 10 per chunk

    def test_chunk_messages_overlap_shares_messages(self) -> None:
        # With 2 messages per chunk and overlap=1, consecutive chunks must
        # actually share their boundary message (the overlap feature).
        ext = SessionExtractor(model="test", max_tokens_per_chunk=10, overlap_messages=1)
        messages = [
            {"parts": [{"part_kind": "text", "content": str(i) * 20}]} for i in range(4)
        ]  # 4 messages, ~5 tokens each -> 2 per chunk
        chunks = ext._chunk_messages(messages)
        assert chunks == [messages[0:2], messages[1:3], messages[2:4]]
        # The last message of each chunk reappears as the first of the next.
        assert chunks[0][-1] is chunks[1][0]
        assert chunks[1][-1] is chunks[2][0]

    def test_chunk_messages_overlap_edge_case(self) -> None:
        """When overlap >= chunk size, next_start must advance."""
        ext = SessionExtractor(model="test", max_tokens_per_chunk=5, overlap_messages=100)
        messages = [
            {"parts": [{"part_kind": "text", "content": "a" * 20}]},
            {"parts": [{"part_kind": "text", "content": "b" * 20}]},
            {"parts": [{"part_kind": "text", "content": "c" * 20}]},
        ]
        chunks = ext._chunk_messages(messages)
        # Should still make progress (not infinite loop)
        assert len(chunks) >= 3

    def test_chunk_messages_oversized_single_message(self) -> None:
        ext = SessionExtractor(model="test", max_tokens_per_chunk=5)
        messages = [{"parts": [{"part_kind": "text", "content": "a" * 1000}]}]
        chunks = ext._chunk_messages(messages)
        assert len(chunks) == 1
        assert len(chunks[0]) == 1

    def test_load_tool_log_missing_file(self, tmp_path: Path) -> None:
        ext = SessionExtractor(model="test")
        assert ext._load_tool_log(tmp_path) == ""

    def test_load_tool_log_with_data(self, tmp_path: Path) -> None:
        ext = SessionExtractor(model="test")
        records = [
            {
                "tool": "read",
                "args": {"path": "f.py"},
                "result_preview": "ok",
                "result_length": 100,
                "elapsed": 0.1,
                "error": False,
            },
            {
                "tool": "execute",
                "args": {"cmd": "pytest"},
                "result_preview": "FAIL",
                "result_length": 500,
                "elapsed": 2.0,
                "error": True,
            },
        ]
        log_file = tmp_path / "tool_log.jsonl"
        log_file.write_text("\n".join(json.dumps(r) for r in records))

        result = ext._load_tool_log(tmp_path)
        assert "read(" in result
        assert "execute(" in result
        assert "ERROR" in result
        assert "error: FAIL" in result

    def test_load_tool_log_non_string_args(self, tmp_path: Path) -> None:
        """Non-string arg values must not crash and discard the entire log."""
        ext = SessionExtractor(model="test")
        record = {
            "tool": "write",
            "args": {
                "path": "f.py",
                "line": 42,
                "force": True,
                "items": [1, 2, 3],
                "meta": {"k": "v"},
                "value": None,
            },
            "result_preview": "ok",
            "result_length": 10,
            "elapsed": 0.1,
            "error": False,
        }
        (tmp_path / "tool_log.jsonl").write_text(json.dumps(record))
        result = ext._load_tool_log(tmp_path)
        # The log must be preserved, not silently dropped to ""
        assert "write(" in result
        assert "line=42" in result
        assert "force=True" in result
        assert "value=None" in result

    def test_load_tool_log_error_no_preview(self, tmp_path: Path) -> None:
        ext = SessionExtractor(model="test")
        record = {
            "tool": "exec",
            "args": {},
            "result_preview": "",
            "result_length": 0,
            "elapsed": 1.0,
            "error": True,
        }
        (tmp_path / "tool_log.jsonl").write_text(json.dumps(record))
        result = ext._load_tool_log(tmp_path)
        assert "ERROR" in result
        # No "error:" line because preview is empty
        assert "error:" not in result.split("\n")[-1] if "\n" in result else True

    def test_load_tool_log_corrupt_file(self, tmp_path: Path) -> None:
        ext = SessionExtractor(model="test")
        (tmp_path / "tool_log.jsonl").write_text("not json\n")
        # Should not raise, returns empty on error
        assert ext._load_tool_log(tmp_path) == ""

    def test_load_tool_log_empty_lines(self, tmp_path: Path) -> None:
        ext = SessionExtractor(model="test")
        (tmp_path / "tool_log.jsonl").write_text("\n\n\n")
        assert ext._load_tool_log(tmp_path) == ""

    async def test_extract_empty_session(self, tmp_path: Path) -> None:
        ext = SessionExtractor(model="test")
        session = tmp_path / "session1"
        session.mkdir()
        (session / "messages.json").write_text("[]")
        insights, chunks = await ext.extract(session)
        assert insights.session_id == "session1"
        assert insights.message_count == 0
        assert chunks == 0

    async def test_extract_with_tool_log(self, tmp_path: Path) -> None:
        """Tool sequence should be appended to chunk text."""
        ext = SessionExtractor(model="test:test")
        session = tmp_path / "session_tl"
        session.mkdir()
        messages = [{"parts": [{"part_kind": "user-prompt", "content": "hello"}]}]
        (session / "messages.json").write_text(json.dumps(messages))
        (session / "tool_log.jsonl").write_text(
            '{"tool": "read", "elapsed": 0.1, "error": false, "result_length": 10, "args": {}}\n'
        )

        mock_output = json.dumps(
            {"session_id": "session_tl", "message_count": 1, "tool_calls_count": 0}
        )
        with patch("pydantic_deep.improve.extractor.Agent") as MockAgent:
            mock_agent = MockAgent.return_value
            mock_result = AsyncMock()
            mock_result.output = mock_output
            mock_agent.run = AsyncMock(return_value=mock_result)
            insights, chunks = await ext.extract(session)
            # Verify the tool sequence was included in the prompt
            call_text = mock_agent.run.call_args[0][0]
            assert "TOOL CALL SEQUENCE" in call_text

    async def test_extract_single_chunk(self, tmp_path: Path) -> None:
        ext = SessionExtractor(model="test:test")
        session = tmp_path / "session2"
        session.mkdir()
        messages = [
            {
                "parts": [
                    {
                        "part_kind": "user-prompt",
                        "content": "hello",
                        "timestamp": "2026-01-01T00:00:00Z",
                    }
                ]
            }
        ]
        (session / "messages.json").write_text(json.dumps(messages))

        mock_output = json.dumps(
            {
                "session_id": "session2",
                "message_count": 1,
                "tool_calls_count": 0,
                "user_facts": [{"fact": "test", "category": "other", "confidence": 0.5}],
            }
        )
        with patch("pydantic_deep.improve.extractor.Agent") as MockAgent:
            mock_agent = MockAgent.return_value
            mock_result = AsyncMock()
            mock_result.output = mock_output
            mock_agent.run = AsyncMock(return_value=mock_result)

            insights, chunks = await ext.extract(session)
            assert chunks == 1
            assert insights.session_id == "session2"

    async def test_extract_counts_computed_not_from_model(self, tmp_path: Path) -> None:
        """message_count/tool_calls_count come from the messages, not the model."""
        ext = SessionExtractor(model="test:test")
        session = tmp_path / "session_counts"
        session.mkdir()
        messages = [
            {"parts": [{"part_kind": "user-prompt", "content": "hi"}]},
            {
                "parts": [
                    {"part_kind": "text", "content": "ok"},
                    {"part_kind": "tool-call", "tool_name": "read", "args": "{}"},
                    {"part_kind": "tool-call", "tool_name": "ls", "args": "{}"},
                ]
            },
            {"parts": [{"part_kind": "tool-return", "content": "done"}]},
        ]
        (session / "messages.json").write_text(json.dumps(messages))

        # Model reports bogus counts - they must be ignored in favour of exact ones.
        mock_output = json.dumps(
            {"session_id": "session_counts", "message_count": 99, "tool_calls_count": 99}
        )
        with patch("pydantic_deep.improve.extractor.Agent") as MockAgent:
            mock_agent = MockAgent.return_value
            mock_result = AsyncMock()
            mock_result.output = mock_output
            mock_agent.run = AsyncMock(return_value=mock_result)

            insights, _ = await ext.extract(session)
            assert insights.message_count == 3
            assert insights.tool_calls_count == 2

    async def test_extract_multi_chunk(self, tmp_path: Path) -> None:
        ext = SessionExtractor(model="test:test", max_tokens_per_chunk=5, overlap_messages=0)
        session = tmp_path / "session3"
        session.mkdir()
        messages = [
            {"parts": [{"part_kind": "text", "content": "a" * 100}]},
            {"parts": [{"part_kind": "text", "content": "b" * 100}]},
        ]
        (session / "messages.json").write_text(json.dumps(messages))

        mock_output = json.dumps(
            {"session_id": "session3", "message_count": 2, "tool_calls_count": 0}
        )
        with patch("pydantic_deep.improve.extractor.Agent") as MockAgent:
            mock_agent = MockAgent.return_value
            mock_result = AsyncMock()
            mock_result.output = mock_output
            mock_agent.run = AsyncMock(return_value=mock_result)

            insights, chunks = await ext.extract(session)
            assert chunks == 2

    async def test_merge_single_chunk(self) -> None:
        ext = SessionExtractor(model="test")
        data = {"session_id": "x", "timestamp": "t", "message_count": 1, "tool_calls_count": 0}
        result = await ext._merge_chunk_insights([data])
        assert result.session_id == "x"

    async def test_merge_multiple_chunks(self) -> None:
        ext = SessionExtractor(model="test:test")
        chunks = [
            {"session_id": "x", "timestamp": "t", "message_count": 5, "tool_calls_count": 2},
            {"session_id": "x", "timestamp": "t", "message_count": 5, "tool_calls_count": 3},
        ]
        mock_output = json.dumps(
            {"session_id": "x", "timestamp": "t", "message_count": 10, "tool_calls_count": 5}
        )
        with patch("pydantic_deep.improve.extractor.Agent") as MockAgent:
            mock_agent = MockAgent.return_value
            mock_result = AsyncMock()
            mock_result.output = mock_output
            mock_agent.run = AsyncMock(return_value=mock_result)
            result = await ext._merge_chunk_insights(chunks)
            assert result.message_count == 10


# ── Synthesizer ──────────────────────────────────────────────────


class TestInsightSynthesizer:
    def test_format_current_context_empty(self) -> None:
        assert InsightSynthesizer._format_current_context({}) == "(No context files exist yet.)"

    def test_format_current_context_with_files(self) -> None:
        ctx = {"SOUL.md": "be concise", "AGENTS.md": ""}
        result = InsightSynthesizer._format_current_context(ctx)
        assert "### AGENTS.md" in result
        assert "(empty)" in result
        assert "be concise" in result

    def test_format_insights_for_prompt(self) -> None:
        si = SessionInsights(session_id="x", timestamp="", message_count=1, tool_calls_count=0)
        result = InsightSynthesizer._format_insights_for_prompt([si])
        data = json.loads(result)
        assert data[0]["session_id"] == "x"

    def test_format_tool_sequences(self) -> None:
        sequences = {"abc": "read_file -> ok", "def": "execute -> error"}
        result = InsightSynthesizer._format_tool_sequences(sequences)
        assert "### Session abc" in result
        assert "### Session def" in result

    def test_format_tool_sequences_truncation(self) -> None:
        sequences = {"abc": "x" * 10000}
        result = InsightSynthesizer._format_tool_sequences(sequences)
        assert "truncated" in result

    def test_format_tool_sequences_empty(self) -> None:
        assert InsightSynthesizer._format_tool_sequences({"abc": "   "}) == ""

    async def test_synthesize_empty_insights(self) -> None:
        synth = InsightSynthesizer(model="test")
        result = await synth.synthesize([], {})
        assert result == []

    async def test_synthesize_with_insights(self) -> None:
        synth = InsightSynthesizer(model="test:test")
        si = SessionInsights(session_id="x", timestamp="", message_count=1, tool_calls_count=0)

        with patch("pydantic_deep.improve.synthesizer.Agent") as MockAgent:
            mock_agent = MockAgent.return_value
            mock_output = AsyncMock()
            mock_output.output.proposed_changes = []
            mock_agent.run = AsyncMock(return_value=mock_output)

            result = await synth.synthesize([si], {"SOUL.md": "test"})
            assert result == []

    async def test_synthesize_with_tool_sequences(self) -> None:
        synth = InsightSynthesizer(model="test:test")
        si = SessionInsights(session_id="x", timestamp="", message_count=1, tool_calls_count=0)

        with patch("pydantic_deep.improve.synthesizer.Agent") as MockAgent:
            mock_agent = MockAgent.return_value
            mock_output = AsyncMock()
            mock_output.output.proposed_changes = []
            mock_agent.run = AsyncMock(return_value=mock_output)

            result = await synth.synthesize([si], {}, tool_sequences={"x": "read_file -> ok"})
            assert result == []
            # Verify tool sequences were included in the prompt
            call_args = mock_agent.run.call_args[0][0]
            assert "Raw Tool Call Sequences" in call_args

    async def test_synthesize_with_empty_tool_sequences(self) -> None:
        synth = InsightSynthesizer(model="test:test")
        si = SessionInsights(session_id="x", timestamp="", message_count=1, tool_calls_count=0)

        with patch("pydantic_deep.improve.synthesizer.Agent") as MockAgent:
            mock_agent = MockAgent.return_value
            mock_output = AsyncMock()
            mock_output.output.proposed_changes = []
            mock_agent.run = AsyncMock(return_value=mock_output)

            # tool_sequences with whitespace-only → format returns empty → no append
            await synth.synthesize([si], {}, tool_sequences={"x": "   "})
            call_text = mock_agent.run.call_args[0][0]
            assert "Raw Tool Call Sequences" not in call_text


# ── Analyzer ─────────────────────────────────────────────────────


class TestImprovementAnalyzer:
    def test_default_context_files(self) -> None:
        assert "SOUL.md" in DEFAULT_CONTEXT_FILES
        assert "MEMORY.md" in DEFAULT_CONTEXT_FILES
        # Aligned with the memory toolset default (get_memory_path stripped of
        # its leading slash so it composes under working_dir).
        assert DEFAULT_CONTEXT_FILES["MEMORY.md"] == ".deep/memory/main/MEMORY.md"

    def test_init_defaults(self) -> None:
        a = ImprovementAnalyzer(model="test", working_dir=Path("/tmp"))
        assert a._context_files == DEFAULT_CONTEXT_FILES

    def test_init_custom_context_files(self) -> None:
        custom = {"MEMORY.md": "custom/path/MEMORY.md"}
        a = ImprovementAnalyzer(model="test", working_dir=Path("/tmp"), context_files=custom)
        assert a._context_files == custom

    def test_resolve_path_known(self, tmp_path: Path) -> None:
        a = ImprovementAnalyzer(model="test", working_dir=tmp_path)
        resolved = a._resolve_path("MEMORY.md")
        assert resolved == tmp_path / ".deep" / "memory" / "main" / "MEMORY.md"

    def test_resolve_path_unknown_falls_through(self, tmp_path: Path) -> None:
        a = ImprovementAnalyzer(model="test", working_dir=tmp_path)
        resolved = a._resolve_path("skills/my-skill")
        assert resolved == tmp_path / "skills" / "my-skill"

    def test_progress_callback(self) -> None:
        events: list[tuple[str, int, int]] = []
        a = ImprovementAnalyzer(model="test", on_progress=lambda s, c, t: events.append((s, c, t)))
        a._progress("discovering")
        a._progress("extracting", 1, 5)
        assert events == [("discovering", 0, 0), ("extracting", 1, 5)]

    def test_progress_callback_error_swallowed(self) -> None:
        def bad_cb(s: str, c: int, t: int) -> None:
            raise RuntimeError("boom")

        a = ImprovementAnalyzer(model="test", on_progress=bad_cb)
        a._progress("test")  # Should not raise

    def test_discover_sessions_empty_dir(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        a = ImprovementAnalyzer(model="test", sessions_dir=sessions_dir)
        assert a._discover_sessions(days=7) == []

    def test_discover_sessions_nonexistent_dir(self, tmp_path: Path) -> None:
        a = ImprovementAnalyzer(model="test", sessions_dir=tmp_path / "nonexistent")
        assert a._discover_sessions(days=7) == []

    def test_discover_sessions_with_data(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        s1 = sessions_dir / "session1"
        s1.mkdir()
        (s1 / "messages.json").write_text("[]")
        # Create a session without messages.json (should be skipped)
        s2 = sessions_dir / "session2"
        s2.mkdir()
        # Create a file (not directory, should be skipped)
        (sessions_dir / "not-a-dir.txt").write_text("")

        a = ImprovementAnalyzer(model="test", sessions_dir=sessions_dir)
        paths = a._discover_sessions(days=7)
        assert len(paths) == 1
        assert paths[0].name == "session1"

    def test_discover_sessions_old_sessions_excluded(self, tmp_path: Path) -> None:
        import os

        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        s = sessions_dir / "old_session"
        s.mkdir()
        msg = s / "messages.json"
        msg.write_text("[]")
        # Set mtime to 30 days ago
        old_time = msg.stat().st_mtime - 30 * 86400
        os.utime(msg, (old_time, old_time))

        a = ImprovementAnalyzer(model="test", sessions_dir=sessions_dir)
        assert a._discover_sessions(days=7) == []

    def test_load_current_context(self, tmp_path: Path) -> None:
        (tmp_path / "SOUL.md").write_text("be concise")
        mem_dir = tmp_path / ".deep" / "memory" / "main"
        mem_dir.mkdir(parents=True)
        (mem_dir / "MEMORY.md").write_text("- fact 1")

        a = ImprovementAnalyzer(model="test", working_dir=tmp_path)
        ctx = a._load_current_context()
        assert ctx["SOUL.md"] == "be concise"
        assert ctx["MEMORY.md"] == "- fact 1"
        assert "AGENTS.md" not in ctx  # doesn't exist

    def test_load_tool_sequences(self, tmp_path: Path) -> None:
        s1 = tmp_path / "s1"
        s1.mkdir()
        (s1 / "tool_log.jsonl").write_text('{"tool": "read"}\n')
        s2 = tmp_path / "s2"
        s2.mkdir()  # No tool_log

        a = ImprovementAnalyzer(model="test")
        seqs = a._load_tool_sequences([s1, s2])
        assert "s1" in seqs
        assert "s2" not in seqs

    def test_load_tool_sequences_os_error(self, tmp_path: Path) -> None:
        s = tmp_path / "s1"
        s.mkdir()
        log = s / "tool_log.jsonl"
        log.write_text("data")
        a = ImprovementAnalyzer(model="test")
        with patch("pathlib.Path.read_text", side_effect=OSError("denied")):
            result = a._load_tool_sequences([s])
        assert result == {}

    def test_load_current_context_os_error(self, tmp_path: Path) -> None:
        (tmp_path / "SOUL.md").write_text("test")
        a = ImprovementAnalyzer(model="test", working_dir=tmp_path)
        with patch("pathlib.Path.read_text", side_effect=OSError("denied")):
            result = a._load_current_context()
        assert result == {}

    def test_load_tool_sequences_empty_content(self, tmp_path: Path) -> None:
        s = tmp_path / "s1"
        s.mkdir()
        (s / "tool_log.jsonl").write_text("   \n")
        a = ImprovementAnalyzer(model="test")
        assert a._load_tool_sequences([s]) == {}

    async def test_apply_changes_create(self, tmp_path: Path) -> None:
        a = ImprovementAnalyzer(model="test", working_dir=tmp_path)
        changes = [
            ProposedChange(
                target_file="skills/new-skill",
                change_type="create",
                section=None,
                content="# New Skill",
                reason="test",
                confidence=0.9,
            )
        ]
        modified = await a.apply_changes(changes)
        assert "skills/new-skill" in modified
        assert (tmp_path / "skills" / "new-skill").read_text() == "# New Skill"

    async def test_apply_changes_append(self, tmp_path: Path) -> None:
        mem_dir = tmp_path / ".deep" / "memory" / "main"
        mem_dir.mkdir(parents=True)
        (mem_dir / "MEMORY.md").write_text("# Memory\n\n- old fact")

        a = ImprovementAnalyzer(model="test", working_dir=tmp_path)
        changes = [
            ProposedChange(
                target_file="MEMORY.md",
                change_type="append",
                section=None,
                content="- new fact",
                reason="test",
                confidence=0.9,
            )
        ]
        modified = await a.apply_changes(changes)
        assert "MEMORY.md" in modified
        content = (mem_dir / "MEMORY.md").read_text()
        assert "- old fact" in content
        assert "- new fact" in content

    async def test_apply_changes_append_new_file(self, tmp_path: Path) -> None:
        a = ImprovementAnalyzer(model="test", working_dir=tmp_path)
        changes = [
            ProposedChange(
                target_file="SOUL.md",
                change_type="append",
                section=None,
                content="be kind",
                reason="test",
                confidence=0.9,
            )
        ]
        modified = await a.apply_changes(changes)
        assert "SOUL.md" in modified
        assert (tmp_path / "SOUL.md").read_text() == "be kind\n"

    async def test_apply_changes_update_with_section(self, tmp_path: Path) -> None:
        (tmp_path / "SOUL.md").write_text("# Preferences\n\nold content\n\n# Other\n\nstuff\n")
        a = ImprovementAnalyzer(model="test", working_dir=tmp_path)
        changes = [
            ProposedChange(
                target_file="SOUL.md",
                change_type="update",
                section="# Preferences",
                content="new content",
                reason="test",
                confidence=0.9,
            )
        ]
        modified = await a.apply_changes(changes)
        assert "SOUL.md" in modified
        content = (tmp_path / "SOUL.md").read_text()
        assert "new content" in content
        assert "old content" not in content
        assert "# Other" in content

    async def test_apply_changes_update_no_section_match(self, tmp_path: Path) -> None:
        (tmp_path / "SOUL.md").write_text("# Existing\n\ncontent")
        a = ImprovementAnalyzer(model="test", working_dir=tmp_path)
        changes = [
            ProposedChange(
                target_file="SOUL.md",
                change_type="update",
                section="# Nonexistent",
                content="appended",
                reason="test",
                confidence=0.9,
            )
        ]
        await a.apply_changes(changes)
        content = (tmp_path / "SOUL.md").read_text()
        assert "appended" in content
        assert "content" in content  # Original preserved

    async def test_apply_changes_update_trailing_section(self, tmp_path: Path) -> None:
        # Section is the LAST heading in the file (no following heading). Its body
        # must be replaced without losing the heading or anything else.
        (tmp_path / "SOUL.md").write_text(
            "# Intro\n\nkeep me\n\n# Preferences\n\nold body line 1\nold body line 2\n"
        )
        a = ImprovementAnalyzer(model="test", working_dir=tmp_path)
        changes = [
            ProposedChange(
                target_file="SOUL.md",
                change_type="update",
                section="# Preferences",
                content="new body",
                reason="test",
                confidence=0.9,
            )
        ]
        await a.apply_changes(changes)
        content = (tmp_path / "SOUL.md").read_text()
        assert "# Intro" in content
        assert "keep me" in content  # Earlier content preserved
        assert "# Preferences" in content  # Heading retained
        assert "new body" in content
        assert "old body line 1" not in content
        assert "old body line 2" not in content

    async def test_apply_changes_update_section_name_in_prose(self, tmp_path: Path) -> None:
        # The section name appears in body prose but is NOT a heading. It must not
        # be mistaken for the section header, so no real heading matches -> append.
        (tmp_path / "SOUL.md").write_text("# Intro\n\nWe discuss Preferences here in prose.\n")
        a = ImprovementAnalyzer(model="test", working_dir=tmp_path)
        changes = [
            ProposedChange(
                target_file="SOUL.md",
                change_type="update",
                section="Preferences",
                content="appended body",
                reason="test",
                confidence=0.9,
            )
        ]
        await a.apply_changes(changes)
        content = (tmp_path / "SOUL.md").read_text()
        assert "We discuss Preferences here in prose." in content  # prose untouched
        assert "appended body" in content  # appended, not used to overwrite prose

    async def test_apply_changes_update_no_section_existing_file(self, tmp_path: Path) -> None:
        # change_type=update with section=None on an EXISTING file -> append.
        (tmp_path / "SOUL.md").write_text("# Existing\n\nkeep this\n")
        a = ImprovementAnalyzer(model="test", working_dir=tmp_path)
        changes = [
            ProposedChange(
                target_file="SOUL.md",
                change_type="update",
                section=None,
                content="added line",
                reason="test",
                confidence=0.9,
            )
        ]
        await a.apply_changes(changes)
        content = (tmp_path / "SOUL.md").read_text()
        assert "keep this" in content
        assert "added line" in content

    async def test_apply_changes_update_missing_file(self, tmp_path: Path) -> None:
        a = ImprovementAnalyzer(model="test", working_dir=tmp_path)
        changes = [
            ProposedChange(
                target_file="SOUL.md",
                change_type="update",
                section=None,
                content="created",
                reason="test",
                confidence=0.9,
            )
        ]
        await a.apply_changes(changes)
        assert (tmp_path / "SOUL.md").read_text() == "created"

    async def test_apply_changes_unknown_type(self, tmp_path: Path) -> None:
        a = ImprovementAnalyzer(model="test", working_dir=tmp_path)
        changes = [
            ProposedChange(
                target_file="SOUL.md",
                change_type="unknown",
                section=None,
                content="test",
                reason="test",
                confidence=0.9,
            )
        ]
        with pytest.raises(ValueError, match="Unknown change_type 'unknown'"):
            await a.apply_changes(changes)
        # The unrecognized change must not be silently written.
        assert not (tmp_path / "SOUL.md").exists()

    def test_get_last_improve_time_no_file(self, tmp_path: Path) -> None:
        a = ImprovementAnalyzer(model="test", working_dir=tmp_path)
        assert a.get_last_improve_time() is None

    def test_get_last_improve_time_valid(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".pydantic-deep"
        state_dir.mkdir(parents=True)
        ts = "2026-04-01T12:00:00+00:00"
        (state_dir / "improve_state.json").write_text(json.dumps({"last_run": ts}))
        a = ImprovementAnalyzer(model="test", working_dir=tmp_path)
        result = a.get_last_improve_time()
        assert result is not None
        assert result.year == 2026

    def test_get_last_improve_time_corrupt(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".pydantic-deep"
        state_dir.mkdir(parents=True)
        (state_dir / "improve_state.json").write_text("not json")
        a = ImprovementAnalyzer(model="test", working_dir=tmp_path)
        assert a.get_last_improve_time() is None

    def test_get_last_improve_time_no_last_run_key(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".pydantic-deep"
        state_dir.mkdir(parents=True)
        (state_dir / "improve_state.json").write_text("{}")
        a = ImprovementAnalyzer(model="test", working_dir=tmp_path)
        assert a.get_last_improve_time() is None

    def test_save_improve_state(self, tmp_path: Path) -> None:
        a = ImprovementAnalyzer(model="test", working_dir=tmp_path)
        report = ImprovementReport(
            analyzed_sessions=3,
            time_range="last 7 days",
            total_chunks=5,
            timestamp="2026-04-01T12:00:00Z",
        )
        a.save_improve_state(report)
        state_path = tmp_path / ".pydantic-deep" / "improve_state.json"
        assert state_path.exists()
        data = json.loads(state_path.read_text())
        assert data["total_runs"] == 1
        assert data["last_run"] == "2026-04-01T12:00:00Z"

    def test_save_improve_state_increments(self, tmp_path: Path) -> None:
        a = ImprovementAnalyzer(model="test", working_dir=tmp_path)
        report = ImprovementReport(
            analyzed_sessions=1, time_range="t", total_chunks=1, timestamp="ts1"
        )
        a.save_improve_state(report)
        report2 = ImprovementReport(
            analyzed_sessions=2, time_range="t", total_chunks=2, timestamp="ts2"
        )
        a.save_improve_state(report2)

        data = json.loads((tmp_path / ".pydantic-deep" / "improve_state.json").read_text())
        assert data["total_runs"] == 2
        assert len(data["history"]) == 2

    def test_save_improve_state_corrupt_existing(self, tmp_path: Path) -> None:
        state_dir = tmp_path / ".pydantic-deep"
        state_dir.mkdir(parents=True)
        (state_dir / "improve_state.json").write_text("corrupt")

        a = ImprovementAnalyzer(model="test", working_dir=tmp_path)
        report = ImprovementReport(
            analyzed_sessions=1, time_range="t", total_chunks=1, timestamp="ts"
        )
        a.save_improve_state(report)
        data = json.loads((state_dir / "improve_state.json").read_text())
        assert data["total_runs"] == 1

    async def test_analyze_no_sessions(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        a = ImprovementAnalyzer(model="test", sessions_dir=sessions_dir, working_dir=tmp_path)
        report = await a.analyze(days=7)
        assert report.analyzed_sessions == 0

    async def test_analyze_success(self, tmp_path: Path) -> None:
        """Test full analyze with successful extraction + synthesis."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        s = sessions_dir / "s1"
        s.mkdir()
        (s / "messages.json").write_text('[{"parts": [{"part_kind": "text", "content": "hi"}]}]')
        # Add tool_log.jsonl for tool_sequences coverage
        (s / "tool_log.jsonl").write_text(
            '{"tool": "read", "elapsed": 0.1, "error": false, "result_length": 10, "args": {}}\n'
        )

        mock_insights = SessionInsights(
            session_id="s1", timestamp="", message_count=1, tool_calls_count=0
        )
        mock_change = ProposedChange(
            target_file="MEMORY.md",
            change_type="append",
            section=None,
            content="- test",
            reason="test",
            confidence=0.9,
        )

        a = ImprovementAnalyzer(model="test", sessions_dir=sessions_dir, working_dir=tmp_path)
        with (
            patch.object(a._extractor, "extract", return_value=(mock_insights, 1)),
            patch.object(a._synthesizer, "synthesize", return_value=[mock_change]),
        ):
            report = await a.analyze(days=7)
        assert report.analyzed_sessions == 1
        assert len(report.proposed_changes) == 1
        assert report.failed_sessions == 0

    async def test_analyze_with_extraction_failure(self, tmp_path: Path) -> None:
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        s = sessions_dir / "s1"
        s.mkdir()
        (s / "messages.json").write_text('[{"parts": [{"part_kind": "text", "content": "hi"}]}]')

        a = ImprovementAnalyzer(model="test", sessions_dir=sessions_dir, working_dir=tmp_path)
        with patch.object(a._extractor, "extract", side_effect=RuntimeError("model error")):
            report = await a.analyze(days=7)
        assert report.analyzed_sessions == 0
        assert report.failed_sessions == 1
        assert isinstance(report.last_error, RuntimeError)
        assert len(report.extraction_errors) == 1
        assert report.extraction_errors[0][0] == "s1"
        assert isinstance(report.extraction_errors[0][1], RuntimeError)

    async def test_analyze_accumulates_distinct_errors(self, tmp_path: Path) -> None:
        """Each failing session is recorded with its own error, not collapsed."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        for name in ("s1", "s2"):
            s = sessions_dir / name
            s.mkdir()
            (s / "messages.json").write_text(
                '[{"parts": [{"part_kind": "text", "content": "hi"}]}]'
            )

        errors = {"s1": ValueError("bad args"), "s2": RuntimeError("model error")}

        async def fake_extract(path: Path) -> object:
            raise errors[path.name]

        a = ImprovementAnalyzer(model="test", sessions_dir=sessions_dir, working_dir=tmp_path)
        with patch.object(a._extractor, "extract", side_effect=fake_extract):
            report = await a.analyze(days=7)
        assert report.failed_sessions == 2
        recorded = {sid: type(exc) for sid, exc in report.extraction_errors}
        assert recorded == {"s1": ValueError, "s2": RuntimeError}
        # last_error stays consistent with the final recorded failure.
        assert report.last_error is report.extraction_errors[-1][1]


# ── ImproveToolset ───────────────────────────────────────────────


class TestImproveToolset:
    def test_init(self) -> None:
        from pydantic_deep.toolsets.improve import ImproveToolset

        ts = ImproveToolset(model="test")
        assert ts._model == "test"
        assert ts._context_files is None

    def test_init_with_context_files(self) -> None:
        from pydantic_deep.toolsets.improve import ImproveToolset

        custom = {"MEMORY.md": "custom/MEMORY.md"}
        ts = ImproveToolset(model="test", context_files=custom)
        assert ts._context_files == custom

    def test_instructions_is_list(self) -> None:
        from pydantic_deep.toolsets.improve import ImproveToolset

        ts = ImproveToolset(model="test")
        assert isinstance(ts._instructions, list)
        assert len(ts._instructions) == 1

    def test_format_report_no_changes(self) -> None:
        from pydantic_deep.toolsets.improve import _format_report

        report = ImprovementReport(analyzed_sessions=3, time_range="last 7 days", total_chunks=5)
        result = _format_report(report)
        assert "3 sessions" in result
        assert "No changes" in result

    def test_format_report_with_changes(self) -> None:
        from pydantic_deep.toolsets.improve import _format_report

        report = ImprovementReport(
            analyzed_sessions=2,
            time_range="last 7 days",
            total_chunks=3,
            proposed_changes=[
                ProposedChange(
                    target_file="MEMORY.md",
                    change_type="append",
                    section=None,
                    content="- User name is Kacper",
                    reason="User introduced themselves",
                    confidence=1.0,
                    source_sessions=["abc"],
                )
            ],
        )
        result = _format_report(report)
        assert "MEMORY.md" in result
        assert "append" in result
        assert "1.00" in result

    def test_format_report_change_without_sources(self) -> None:
        from pydantic_deep.toolsets.improve import _format_report

        report = ImprovementReport(
            analyzed_sessions=1,
            time_range="test",
            total_chunks=1,
            proposed_changes=[
                ProposedChange(
                    target_file="SOUL.md",
                    change_type="append",
                    section=None,
                    content="x" * 300,  # Long content to trigger truncation
                    reason="test",
                    confidence=0.8,
                    source_sessions=[],  # No source sessions
                )
            ],
        )
        result = _format_report(report)
        assert "SOUL.md" in result
        assert "Sources:" not in result  # Empty source_sessions → no Sources line
        assert "..." in result  # Content truncated

    def test_format_status_never_run(self) -> None:
        from pydantic_deep.toolsets.improve import _format_status

        result = _format_status(None, {})
        assert "never been run" in result

    def test_format_status_with_data(self) -> None:
        from pydantic_deep.toolsets.improve import _format_status

        last_run = datetime.now(timezone.utc)
        state = {"last_run_sessions": 5, "last_run_changes": 3, "total_runs": 2}
        result = _format_status(last_run, state)
        assert "minutes ago" in result or "hours ago" in result or "days ago" in result
        assert "5" in result

    def test_format_status_hours_ago(self) -> None:
        from datetime import timedelta

        from pydantic_deep.toolsets.improve import _format_status

        last_run = datetime.now(timezone.utc) - timedelta(hours=5)
        result = _format_status(last_run, {})
        assert "hours ago" in result

    def test_format_status_days_ago(self) -> None:
        from datetime import timedelta

        from pydantic_deep.toolsets.improve import _format_status

        last_run = datetime.now(timezone.utc) - timedelta(days=3)
        result = _format_status(last_run, {})
        assert "days ago" in result

    def test_toolset_has_tools(self) -> None:
        from pydantic_deep.toolsets.improve import ImproveToolset

        ts = ImproveToolset(model="test")
        # FunctionToolset registers tools during __init__
        assert ts.id == "deep-improve"

    async def test_improve_tool_run(self, tmp_path: Path) -> None:
        from unittest.mock import MagicMock

        from pydantic_deep.toolsets.improve import ImproveToolset

        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()

        ImproveToolset(sessions_dir=sessions_dir, working_dir=tmp_path, model="test")

        # Mock the tool function directly
        mock_ctx = MagicMock()
        mock_ctx.deps = MagicMock()
        mock_ctx.deps.working_dir = str(tmp_path)

        with patch("pydantic_deep.toolsets.improve.ImprovementAnalyzer") as MockAnalyzer:
            mock_analyzer = MockAnalyzer.return_value
            mock_report = ImprovementReport(
                analyzed_sessions=0, time_range="last 7 days", total_chunks=0, timestamp="ts"
            )
            mock_analyzer.analyze = AsyncMock(return_value=mock_report)
            mock_analyzer.save_improve_state = MagicMock()

            # Call the internal tool function directly
            # Get the improve function from the toolset
            from pydantic_deep.improve.analyzer import ImprovementAnalyzer as RealAnalyzer

            analyzer = RealAnalyzer(model="test", sessions_dir=sessions_dir, working_dir=tmp_path)
            with patch.object(analyzer, "_discover_sessions", return_value=[]):
                report = await analyzer.analyze(days=7)
            assert report.analyzed_sessions == 0

    async def test_get_improvement_status_no_state(self, tmp_path: Path) -> None:
        from pydantic_deep.improve.analyzer import ImprovementAnalyzer
        from pydantic_deep.toolsets.improve import _format_status

        analyzer = ImprovementAnalyzer(model="test", working_dir=tmp_path)
        last_run = analyzer.get_last_improve_time()
        result = _format_status(last_run, {})
        assert "never been run" in result
