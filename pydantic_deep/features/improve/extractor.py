"""Session insight extraction with chunking support.

Extracts structured insights from a single conversation session.
Handles sessions larger than the model context by splitting into
overlapping chunks, extracting per chunk, and merging results.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic_ai import Agent

from pydantic_deep.features.improve.prompts import CHUNK_MERGE_PROMPT, EXTRACTION_PROMPT
from pydantic_deep.features.improve.types import SessionInsights

DEFAULT_MAX_TOKENS_PER_CHUNK: int = 140_000
"""Default maximum tokens per chunk (leaves room for system prompt)."""

DEFAULT_OVERLAP_MESSAGES: int = 5
"""Default number of overlapping messages between chunks."""

DEFAULT_MAX_TOOL_OUTPUT_CHARS: int = 5000
"""Default max characters for truncated tool outputs.

Increased from 2000 to 5000 following Meta-Harness insight (Lee et al., 2026):
raw execution traces contain critical diagnostic information that lossy
compression destroys. Tool outputs often contain error messages, file
contents, and command results that reveal behavioral patterns.
"""


class SessionExtractor:
    """Extracts insights from a single session, handling chunking.

    For sessions that fit within the model context, extraction runs in
    a single pass. For larger sessions, the messages are split into
    overlapping chunks, each chunk is analyzed independently, and the
    results are merged with deduplication.
    """

    def __init__(
        self,
        model: str,
        max_tokens_per_chunk: int = DEFAULT_MAX_TOKENS_PER_CHUNK,
        overlap_messages: int = DEFAULT_OVERLAP_MESSAGES,
    ) -> None:
        """Initialize the extractor.

        Args:
            model: Model identifier for the extraction agent
                (e.g., `"openrouter:anthropic/claude-sonnet-4"`).
            max_tokens_per_chunk: Max estimated tokens per chunk.
            overlap_messages: Number of messages to overlap between chunks.
        """
        self._model = model
        self._max_tokens_per_chunk = max_tokens_per_chunk
        self._overlap_messages = overlap_messages

    async def extract(self, session_path: Path) -> tuple[SessionInsights, int]:
        """Extract insights from a session.

        1. Load `messages.json` from the session directory.
        2. Estimate total tokens.
        3. If it fits in one chunk, extract directly.
        4. If too large, chunk with overlap, extract per chunk, merge.

        Args:
            session_path: Path to the session directory containing
                `messages.json`.

        Returns:
            A tuple of (extracted insights, number of chunks processed).

        Raises:
            FileNotFoundError: If `messages.json` does not exist.
            json.JSONDecodeError: If `messages.json` is invalid JSON.
        """
        messages_file = session_path / "messages.json"
        raw = messages_file.read_text(encoding="utf-8")
        messages: list[dict[str, Any]] = json.loads(raw)

        if not messages:
            session_id = session_path.name
            return SessionInsights(
                session_id=session_id,
                timestamp="",
                message_count=0,
                tool_calls_count=0,
            ), 0

        # Estimate total tokens
        total_tokens = sum(self._estimate_message_tokens(m) for m in messages)

        # Compute exact counts from the loaded messages. LLMs are unreliable at
        # counting, so we never trust the model's reported values for these.
        message_count = len(messages)
        tool_calls_count = self._count_tool_calls(messages)

        session_id = session_path.name
        timestamp = _extract_timestamp(messages)

        # Load structured tool log if available (richer than message-embedded traces)
        tool_sequence = self._load_tool_log(session_path)

        if total_tokens <= self._max_tokens_per_chunk:
            # Single chunk extraction
            chunk_text = self._prepare_chunk_text(messages)
            if tool_sequence:
                chunk_text += "\n\n--- TOOL CALL SEQUENCE ---\n\n" + tool_sequence
            insights = await self._extract_chunk(chunk_text, session_id, timestamp)
            chunk_count = 1
        else:
            # Multi-chunk extraction with merge
            chunks = self._chunk_messages(messages)
            chunk_results: list[SessionInsights] = []
            for chunk in chunks:
                chunk_text = self._prepare_chunk_text(chunk)
                result = await self._extract_chunk(chunk_text, session_id, timestamp)
                chunk_results.append(result)
            insights = await self._merge_chunk_insights(chunk_results)
            chunk_count = len(chunks)

        # Identifiers and counts come from the messages, never the model: LLMs are
        # unreliable at counting and have no reason to echo these back accurately.
        insights.session_id = session_id
        insights.timestamp = timestamp
        insights.message_count = message_count
        insights.tool_calls_count = tool_calls_count
        return insights, chunk_count

    def _chunk_messages(self, messages: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        """Split messages into chunks with overlap.

        Uses a greedy approach: accumulate messages until the token
        estimate exceeds the limit, then start a new chunk with
        `overlap_messages` messages carried over.

        Args:
            messages: Full list of session messages.

        Returns:
            List of message sublists, each fitting within the token budget.
        """
        chunks: list[list[dict[str, Any]]] = []
        start = 0

        while start < len(messages):
            chunk_end = start
            token_count = 0
            for i in range(start, len(messages)):
                msg_tokens = self._estimate_message_tokens(messages[i])
                if token_count + msg_tokens > self._max_tokens_per_chunk:
                    break
                token_count += msg_tokens
                chunk_end = i + 1

            # If a single message exceeds the limit, include it anyway
            if chunk_end == start:
                chunk_end = start + 1

            chunks.append(messages[start:chunk_end])

            # Stop once this chunk consumed the remaining messages, otherwise the
            # overlap carry-back would re-chunk the tail forever.
            if chunk_end >= len(messages):
                break

            # Next chunk starts with overlap for continuity. Carry back
            # `overlap_messages` messages while guaranteeing forward progress
            # (`next_start > start`) so the loop always terminates.
            start = max(start + 1, chunk_end - self._overlap_messages)

        return chunks

    def _count_tool_calls(self, messages: list[dict[str, Any]]) -> int:
        """Count tool calls across all messages.

        Counts parts with `part_kind == 'tool-call'` across the full
        message list. Computed directly from the loaded messages rather
        than trusting the model, which is unreliable at counting.

        Args:
            messages: Full list of session messages.

        Returns:
            Total number of tool-call parts.
        """
        return sum(
            1
            for msg in messages
            for part in msg.get("parts", [])
            if part.get("part_kind") == "tool-call"
        )

    def _estimate_message_tokens(self, msg: dict[str, Any]) -> int:
        """Estimate tokens for a message including ALL parts.

        Includes tool call arguments and tool return outputs, which are
        critical for understanding what happened in the session.

        Uses the ~4 chars per token heuristic.

        Args:
            msg: A message dict (pydantic-ai ModelMessage format).

        Returns:
            Estimated token count.
        """
        total = 0
        parts = msg.get("parts", [])
        for part in parts:
            kind = part.get("part_kind", "")

            if kind in ("user-prompt", "text", "system-prompt", "retry-prompt"):
                content = part.get("content", "")
                total += len(str(content)) // 4

            elif kind == "tool-call":
                tool_name = part.get("tool_name", "")
                args = part.get("args", "")
                total += len(str(tool_name)) // 4
                total += len(str(args)) // 4

            elif kind == "tool-return":
                content = part.get("content", "")
                total += len(str(content)) // 4

        return max(total, 1)

    def _truncate_tool_output(
        self, content: str, max_chars: int = DEFAULT_MAX_TOOL_OUTPUT_CHARS
    ) -> str:
        """Truncate large tool outputs preserving head and tail.

        Args:
            content: Tool output content.
            max_chars: Maximum characters to keep.

        Returns:
            Original content if within limit, otherwise head + tail with
            a truncation marker.
        """
        if len(content) <= max_chars:
            return content
        head_size = int(max_chars * 0.7)
        # For tiny budgets `max_chars - head_size - 50` goes negative, and
        # `content[-negative:]` is a forward slice that returns *more* than the
        # input — floor it at 0 (and drop the tail entirely) (B7).
        tail_size = max(0, max_chars - head_size - 50)
        truncated_count = len(content) - head_size - tail_size
        tail = content[-tail_size:] if tail_size > 0 else ""
        return content[:head_size] + f"\n\n... ({truncated_count} chars truncated) ...\n\n" + tail

    def _load_tool_log(self, session_path: Path) -> str:
        """Load tool_log.jsonl and format as a compact tool call sequence.

        This gives the extraction agent a structured view of what tools
        were called, in what order, how long they took, and whether they
        failed - without the noise of full message formatting.

        Returns empty string if no tool log exists.
        """
        log_file = session_path / "tool_log.jsonl"
        if not log_file.exists():
            return ""

        try:
            raw_lines = log_file.read_text(encoding="utf-8").splitlines()
        except OSError:
            return ""

        lines: list[str] = []
        for raw_line in raw_lines:
            if not raw_line.strip():
                continue
            # Per-line guard: one malformed record (bad JSON, non-numeric
            # `elapsed`) must not discard the whole log (B12).
            try:
                record = json.loads(raw_line)
                tool = record.get("tool", "?")
                elapsed = float(record.get("elapsed", 0) or 0)
                error = record.get("error", False)
                result_len = record.get("result_length", 0)
                args = record.get("args", {})

                status = "ERROR" if error else "ok"
                args_brief = (
                    ", ".join(f"{k}={str(v)[:80]}" for k, v in args.items())
                    if isinstance(args, dict) and args
                    else ""
                )
                lines.append(
                    f"  {tool}({args_brief}) -> [{status}, {elapsed:.1f}s, {result_len} chars]"
                )

                # Include result preview for errors (most diagnostic value)
                if error:
                    preview = str(record.get("result_preview", ""))[:500]
                    if preview:
                        lines.append(f"    error: {preview}")
            except Exception:
                continue

        return "\n".join(lines) if lines else ""

    def _prepare_chunk_text(self, messages: list[dict[str, Any]]) -> str:
        """Format messages as readable text for the extraction agent.

        Includes tool calls with arguments AND results so the extraction
        agent has full context about what happened.

        Args:
            messages: List of message dicts to format.

        Returns:
            Human-readable text representation of the messages.
        """
        lines: list[str] = []
        for msg in messages:
            parts = msg.get("parts", [])

            for part in parts:
                part_kind = part.get("part_kind", "")

                if part_kind == "user-prompt":
                    content = part.get("content", "")
                    ts = part.get("timestamp", "")
                    ts_str = f" [{ts}]" if ts else ""
                    # Truncate: a huge pasted prompt sent verbatim would blow the
                    # chunk budget and fail the whole session's extraction (B5).
                    lines.append(
                        f"[User{ts_str}]: {self._truncate_tool_output(str(content), 5000)}"
                    )

                elif part_kind == "system-prompt":
                    # Skip system prompts - not useful for insight extraction
                    continue

                elif part_kind == "text":
                    content = part.get("content", "")
                    lines.append(f"[Assistant]: {content[:5000]}")

                elif part_kind == "tool-call":
                    tool_name = part.get("tool_name", "")
                    args_raw = part.get("args", "")
                    if isinstance(args_raw, str):
                        args_preview = self._truncate_tool_output(args_raw, 1000)
                    else:
                        args_preview = self._truncate_tool_output(
                            json.dumps(args_raw, ensure_ascii=False), 1000
                        )
                    lines.append(f"  -> {tool_name}({args_preview})")

                elif part_kind == "tool-return":
                    content = str(part.get("content", ""))
                    preview = self._truncate_tool_output(content)
                    lines.append(f"  <- {preview}")

                elif part_kind == "retry-prompt":
                    content = part.get("content", "")
                    lines.append(f"[Retry]: {self._truncate_tool_output(str(content), 5000)}")

        return "\n".join(lines)

    async def _extract_chunk(
        self,
        chunk_text: str,
        session_id: str,
        timestamp: str,
    ) -> SessionInsights:
        """Run the extraction agent on a single chunk.

        Args:
            chunk_text: Formatted text of the chunk.
            session_id: Session identifier included in the prompt context.
            timestamp: Session timestamp included in the prompt context.

        Returns:
            The validated `SessionInsights` produced by the model.
        """
        user_prompt = (
            f"Session ID: {session_id}\n"
            f"Timestamp: {timestamp}\n\n"
            f"--- SESSION TRANSCRIPT ---\n\n"
            f"{chunk_text}"
        )

        agent = Agent(
            model=self._model,
            system_prompt=EXTRACTION_PROMPT,
            output_type=SessionInsights,
        )
        result = await agent.run(user_prompt)
        return result.output

    async def _merge_chunk_insights(self, chunks: list[SessionInsights]) -> SessionInsights:
        """Merge insights from multiple chunks, deduplicating overlaps.

        Uses an LLM to intelligently merge and deduplicate insights
        from overlapping chunks of the same session.

        Args:
            chunks: Per-chunk insights to merge.

        Returns:
            Merged SessionInsights for the full session.
        """
        if len(chunks) == 1:
            return chunks[0]

        chunks_json = json.dumps([c.model_dump() for c in chunks], indent=2, ensure_ascii=False)
        prompt = CHUNK_MERGE_PROMPT.format(chunks_json=chunks_json)

        agent = Agent(
            model=self._model,
            system_prompt=prompt,
            output_type=SessionInsights,
        )
        user_prompt = (
            f"Merge these {len(chunks)} chunk insights for session {chunks[0].session_id}."
        )
        result = await agent.run(user_prompt)
        return result.output


def _extract_timestamp(messages: list[dict[str, Any]]) -> str:
    """Extract timestamp from the first message with a timestamp part.

    Args:
        messages: List of message dicts.

    Returns:
        ISO timestamp string, or empty string if not found.
    """
    for msg in messages:
        for part in msg.get("parts", []):
            ts = part.get("timestamp")
            if ts:
                return str(ts)
    return ""
