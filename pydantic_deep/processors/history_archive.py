"""Conversation history search tool with BM25 ranking.

Provides a ``search_conversation_history`` tool that searches through
the persistent ``messages.json`` file maintained by
:class:`~pydantic_ai_summarization.ContextManagerMiddleware`.

The middleware saves every message continuously. This module only *reads*
the file — it never writes. The search tool is useful after context
compression, when older messages have been replaced by a summary.

Search uses BM25 ranking (the same algorithm behind Elasticsearch/Lucene)
for relevance-scored results. Multi-word queries are tokenized — each word
is scored independently, and rare words (high IDF) contribute more than
common ones.

Example:
    ```python
    from pydantic_deep import create_deep_agent

    # History search is enabled by default when context_manager=True
    agent = create_deep_agent(include_history_archive=True)
    ```
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.toolsets import FunctionToolset

SEARCH_HISTORY_DESCRIPTION = """\
Search through the full conversation history, including messages that \
were compressed away to save context space.

When the conversation is compressed, older messages are replaced by a \
summary in the active context. But the full history is saved to a file. \
Use this tool to find specific details from earlier in the conversation.

Results are ranked by relevance using BM25 — rare terms and exact matches \
score higher. Multi-word queries search for each word independently.

When to use:
- You need to recall exact details from earlier in the conversation
- The conversation summary doesn't have enough detail for the current task
- You need to find specific code, file paths, or decisions from before compression

When NOT to use:
- The information is still in current conversation context
- You need external/real-time information (use web tools instead)"""

_CONTEXT_LINES = 5
"""Number of context lines to show around each search match."""

_MAX_MATCHES = 10
"""Maximum number of matching excerpts to return."""

# BM25 parameters (standard values used by Elasticsearch/Lucene)
_BM25_K1 = 1.5
"""Term frequency saturation parameter."""

_BM25_B = 0.75
"""Document length normalization parameter."""

_TOKENIZE_RE = re.compile(r"[a-zA-Z0-9]+")
"""Regex for tokenizing text into words (splits on non-alphanumeric including underscores)."""


# ---------------------------------------------------------------------------
# BM25 implementation
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> list[str]:
    """Split text into lowercase tokens."""
    return [m.group().lower() for m in _TOKENIZE_RE.finditer(text)]


def _compute_idf(term: str, doc_tokens: list[list[str]]) -> float:
    """Compute inverse document frequency for a term.

    Uses the standard BM25 IDF formula:
        IDF(q) = ln((N - n(q) + 0.5) / (n(q) + 0.5) + 1)
    where N = total docs, n(q) = docs containing the term.
    """
    n = len(doc_tokens)
    df = sum(1 for tokens in doc_tokens if term in set(tokens))
    if df == 0:
        return 0.0
    return math.log((n - df + 0.5) / (df + 0.5) + 1.0)


def _bm25_score(
    query_tokens: list[str],
    doc_tokens: list[str],
    idf_scores: dict[str, float],
    avgdl: float,
) -> float:
    """Compute BM25 score for a single document against query tokens."""
    dl = len(doc_tokens)
    if dl == 0 or avgdl == 0:
        return 0.0

    score = 0.0
    tf_map: dict[str, int] = {}
    for token in doc_tokens:
        tf_map[token] = tf_map.get(token, 0) + 1

    for qt in query_tokens:
        tf = tf_map.get(qt, 0)
        if tf == 0:
            continue
        idf = idf_scores.get(qt, 0.0)
        numerator = tf * (_BM25_K1 + 1.0)
        denominator = tf + _BM25_K1 * (1.0 - _BM25_B + _BM25_B * dl / avgdl)
        score += idf * numerator / denominator

    return score


def _bm25_rank(
    query: str,
    documents: list[str],
) -> list[tuple[int, float]]:
    """Rank documents by BM25 relevance to query.

    Args:
        query: Search query string.
        documents: List of document strings.

    Returns:
        List of (doc_index, score) tuples sorted by descending score.
        Only documents with score > 0 are included.
    """
    query_tokens = _tokenize(query)
    if not query_tokens or not documents:
        return []

    doc_tokens = [_tokenize(doc) for doc in documents]
    avgdl = sum(len(t) for t in doc_tokens) / len(doc_tokens) if doc_tokens else 0.0

    # Pre-compute IDF for each query term
    unique_query_tokens = list(dict.fromkeys(query_tokens))
    idf_scores = {qt: _compute_idf(qt, doc_tokens) for qt in unique_query_tokens}

    results: list[tuple[int, float]] = []
    for i, tokens in enumerate(doc_tokens):
        score = _bm25_score(unique_query_tokens, tokens, idf_scores, avgdl)
        if score > 0:
            results.append((i, score))

    results.sort(key=lambda x: x[1], reverse=True)
    return results


# ---------------------------------------------------------------------------
# Message formatting (for search results)
# ---------------------------------------------------------------------------


def _format_message(msg: ModelMessage) -> str:
    """Format a single ModelMessage into readable text."""
    lines: list[str] = []

    if isinstance(msg, ModelRequest):
        for part in msg.parts:
            if isinstance(part, UserPromptPart):
                lines.append(f"User: {part.content}")
            elif isinstance(part, SystemPromptPart):
                content = str(part.content)
                if content.startswith("Summary of previous conversation"):
                    lines.append("[Compression summary]")
                else:
                    lines.append(f"System: {content[:200]}")
            elif isinstance(part, ToolReturnPart):
                content = str(part.content)
                if len(content) > 500:
                    content = content[:500] + "..."
                lines.append(f"Tool [{part.tool_name}]: {content}")
    elif isinstance(msg, ModelResponse):  # pragma: no branch
        for part in msg.parts:  # type: ignore[assignment]
            if isinstance(part, TextPart):
                lines.append(f"Assistant: {part.content}")
            elif isinstance(part, ToolCallPart):
                args = json.dumps(part.args_as_dict(), ensure_ascii=False)
                if len(args) > 200:
                    args = args[:200] + "..."
                lines.append(f"Tool Call [{part.tool_name}]: {args}")

    return "\n".join(lines)


def _format_messages(messages: list[ModelMessage]) -> list[str]:
    """Format a list of messages into numbered readable lines."""
    lines: list[str] = []
    for i, msg in enumerate(messages):
        formatted = _format_message(msg)
        if formatted:
            lines.append(f"[{i}] {formatted}")
    return lines


def _load_messages(messages_path: str) -> list[ModelMessage]:
    """Load messages from a JSON file."""
    path = Path(messages_path)
    if not path.exists():
        return []
    try:
        raw = path.read_bytes()
        if raw:
            return list(ModelMessagesTypeAdapter.validate_json(raw))
    except Exception:  # pragma: no cover
        pass
    return []


def create_history_search_toolset(
    messages_path: str,
    *,
    id: str = "deep-history-search",
) -> FunctionToolset[Any]:
    """Create a toolset with the ``search_conversation_history`` tool.

    Args:
        messages_path: Absolute path to the messages.json file
            (same file the middleware writes to).
        id: Toolset identifier.

    Returns:
        FunctionToolset with the search tool registered.
    """
    toolset: FunctionToolset[Any] = FunctionToolset(id=id)

    @toolset.tool(description=SEARCH_HISTORY_DESCRIPTION)
    async def search_conversation_history(ctx: RunContext[Any], query: str) -> str:
        """Search the full conversation history using BM25 ranking.

        Args:
            query: Text to search for. Multi-word queries search each word
                independently — rare terms score higher than common ones.
        """
        messages = _load_messages(messages_path)

        if not messages:
            return (
                "No conversation history saved yet. "
                "History is saved automatically as the conversation progresses."
            )

        # Format all messages into searchable text
        formatted_lines = _format_messages(messages)

        # Rank lines by BM25 relevance
        ranked = _bm25_rank(query, formatted_lines)

        if not ranked:
            return f"No matches for '{query}' in {len(messages)} archived messages."

        # Take top matches and show context around each
        results: list[str] = []
        shown_indices: set[int] = set()

        for doc_idx, score in ranked[:_MAX_MATCHES]:
            if doc_idx in shown_indices:  # pragma: no cover
                continue  # pragma: no cover

            start = max(0, doc_idx - _CONTEXT_LINES)
            end = min(len(formatted_lines), doc_idx + _CONTEXT_LINES + 1)

            shown_indices.add(doc_idx)
            excerpt = "\n".join(formatted_lines[start:end])
            results.append(f"[score: {score:.1f}]\n{excerpt}")

        if not results:  # pragma: no cover
            return f"No matches for '{query}' in {len(messages)} archived messages."  # pragma: no cover

        header = (
            f"Found {len(results)} match(es) for '{query}' "
            f"in {len(messages)} archived messages:\n\n"
        )
        return header + "\n\n---\n\n".join(results)

    return toolset


__all__ = [
    "SEARCH_HISTORY_DESCRIPTION",
    "_bm25_rank",
    "_compute_idf",
    "_tokenize",
    "create_history_search_toolset",
]
