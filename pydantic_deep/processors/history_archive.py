"""Conversation history search tool.

Provides a ``search_conversation_history`` tool that searches through
the persistent ``messages.json`` file maintained by
:class:`~pydantic_ai_summarization.ContextManagerMiddleware`.

The middleware saves every message continuously. This module only *reads*
the file — it never writes. The search tool is useful after context
compression, when older messages have been replaced by a summary.

Example:
    ```python
    from pydantic_deep import create_deep_agent

    # History search is enabled by default when context_manager=True
    agent = create_deep_agent(include_history_archive=True)
    ```
"""

from __future__ import annotations

import json
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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEARCH_HISTORY_DESCRIPTION = """\
Search through the full conversation history, including messages that \
were compressed away to save context space.

When the conversation is compressed, older messages are replaced by a \
summary in the active context. But the full history is saved to a file. \
Use this tool to find specific details from earlier in the conversation.

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


# ---------------------------------------------------------------------------
# Search toolset
# ---------------------------------------------------------------------------


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
        """Search the full conversation history for a keyword or phrase.

        Args:
            query: Text to search for (case-insensitive).
        """
        messages = _load_messages(messages_path)

        if not messages:
            return (
                "No conversation history saved yet. "
                "History is saved automatically as the conversation progresses."
            )

        # Format all messages into searchable text
        formatted_lines = _format_messages(messages)
        query_lower = query.lower()
        results: list[str] = []

        for i, line in enumerate(formatted_lines):
            if query_lower in line.lower() and len(results) < _MAX_MATCHES:
                # Show context around match
                start = max(0, i - _CONTEXT_LINES)
                end = min(len(formatted_lines), i + _CONTEXT_LINES + 1)
                excerpt = "\n".join(formatted_lines[start:end])
                results.append(excerpt)

        if not results:
            return f"No matches for '{query}' in {len(messages)} archived messages."

        header = (
            f"Found {len(results)} match(es) for '{query}' "
            f"in {len(messages)} archived messages:\n\n"
        )
        return header + "\n\n---\n\n".join(results)

    return toolset


__all__ = [
    "SEARCH_HISTORY_DESCRIPTION",
    "create_history_search_toolset",
]
