"""PatchToolCallsProcessor: fix orphaned tool calls in message history.

When a conversation is interrupted (user cancellation, tool crash, incomplete
checkpoint) or context management evicts messages, the history may contain:

1. **Orphaned tool calls**: ModelResponse with ToolCallParts that have no
   corresponding ToolReturnPart in the next ModelRequest.
2. **Orphaned tool results**: ModelRequest with ToolReturnParts that have no
   matching ToolCallPart in the preceding ModelResponse.

Both cases cause errors with most LLM APIs. This processor fixes both.

Example:
    ```python
    from pydantic_deep import create_deep_agent

    agent = create_deep_agent(
        patch_tool_calls=True,  # Enables PatchToolCallsProcessor
    )
    ```
"""

from __future__ import annotations

from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    ToolReturnPart,
)

CANCELLED_MESSAGE = "Tool call was cancelled."


def _find_orphaned_calls(messages: list[ModelMessage]) -> dict[int, list[ToolReturnPart]]:
    """Identify orphaned tool calls and build synthetic ToolReturnParts.

    Returns a mapping of response_index -> list of synthetic ToolReturnParts.
    """
    orphans: dict[int, list[ToolReturnPart]] = {}

    for i, msg in enumerate(messages):
        if not isinstance(msg, ModelResponse):
            continue

        # Collect tool_call_ids from this response
        tool_calls: dict[str, ToolCallPart] = {}
        for part in msg.parts:
            if isinstance(part, ToolCallPart):
                tool_calls[part.tool_call_id] = part

        if not tool_calls:
            continue

        # Check next message for matching ToolReturnParts
        next_msg = messages[i + 1] if i + 1 < len(messages) else None
        answered_ids: set[str] = set()

        if isinstance(next_msg, ModelRequest):
            for part in next_msg.parts:
                if isinstance(part, ToolReturnPart) and part.tool_call_id in tool_calls:
                    answered_ids.add(part.tool_call_id)

        # Find orphaned tool calls
        orphaned_ids = set(tool_calls.keys()) - answered_ids
        if orphaned_ids:
            synthetic = [
                ToolReturnPart(
                    tool_name=tool_calls[call_id].tool_name,
                    content=CANCELLED_MESSAGE,
                    tool_call_id=call_id,
                )
                for call_id in sorted(orphaned_ids)  # sorted for deterministic order
            ]
            orphans[i] = synthetic

    return orphans


def _find_orphaned_results(messages: list[ModelMessage]) -> set[tuple[int, str]]:
    """Identify orphaned tool results (ToolReturnParts without matching ToolCallParts).

    Returns a set of (message_index, tool_call_id) tuples to remove.
    """
    orphaned: set[tuple[int, str]] = set()

    for i, msg in enumerate(messages):
        if not isinstance(msg, ModelRequest):
            continue

        # Collect tool_call_ids in ToolReturnParts of this request
        return_ids: dict[str, ToolReturnPart] = {}
        for part in msg.parts:
            if isinstance(part, ToolReturnPart) and part.tool_call_id:
                return_ids[part.tool_call_id] = part

        if not return_ids:
            continue

        # Check preceding message for matching ToolCallParts
        prev_msg = messages[i - 1] if i > 0 else None
        called_ids: set[str] = set()

        if isinstance(prev_msg, ModelResponse):
            for part in prev_msg.parts:
                if isinstance(part, ToolCallPart):
                    called_ids.add(part.tool_call_id)

        # Find orphaned tool results
        for call_id in return_ids:
            if call_id not in called_ids:
                orphaned.add((i, call_id))

    return orphaned


def patch_tool_calls_processor(
    messages: list[ModelMessage],
) -> list[ModelMessage]:
    """Fix orphaned tool calls AND orphaned tool results.

    Handles two cases:
    1. ModelResponse with ToolCallParts not followed by matching ToolReturnParts
       → injects synthetic ToolReturnParts with "Tool call was cancelled."
    2. ModelRequest with ToolReturnParts not preceded by matching ToolCallParts
       → removes the orphaned ToolReturnParts from the ModelRequest

    This is a HistoryProcessor compatible with pydantic-ai's
    ``history_processors`` parameter.

    Args:
        messages: List of model messages (conversation history).

    Returns:
        Patched message list.
    """
    if not messages:
        return messages

    # Phase 1: Fix orphaned tool calls (missing results)
    orphaned_calls = _find_orphaned_calls(messages)

    if orphaned_calls:
        patched: list[ModelMessage] = []
        skip_indices: set[int] = set()

        for i, msg in enumerate(messages):
            if i in skip_indices:
                continue

            patched.append(msg)

            if i not in orphaned_calls:
                continue

            synthetic_parts = orphaned_calls[i]
            next_idx = i + 1
            next_msg = messages[next_idx] if next_idx < len(messages) else None

            if isinstance(next_msg, ModelRequest):
                # Prepend synthetic parts to existing ModelRequest
                patched_parts = list(synthetic_parts) + list(next_msg.parts)
                patched.append(ModelRequest(parts=patched_parts))
                skip_indices.add(next_idx)
            else:
                # No next ModelRequest — create one with just synthetic parts
                patched.append(ModelRequest(parts=synthetic_parts))

        messages = patched

    # Phase 2: Fix orphaned tool results (missing calls)
    orphaned_results = _find_orphaned_results(messages)

    if orphaned_results:
        # Build set of (index, call_id) to strip
        strip_by_index: dict[int, set[str]] = {}
        for idx, call_id in orphaned_results:
            strip_by_index.setdefault(idx, set()).add(call_id)

        patched2: list[ModelMessage] = []
        for i, msg in enumerate(messages):
            if i not in strip_by_index:
                patched2.append(msg)
                continue

            # Filter out orphaned ToolReturnParts from this ModelRequest
            ids_to_strip = strip_by_index[i]
            assert isinstance(msg, ModelRequest)
            remaining_parts = [
                part
                for part in msg.parts
                if not (isinstance(part, ToolReturnPart) and part.tool_call_id in ids_to_strip)
            ]

            if remaining_parts:
                patched2.append(ModelRequest(parts=remaining_parts))
            # If no parts remain, skip the message entirely

        messages = patched2

    return messages


__all__ = [
    "CANCELLED_MESSAGE",
    "patch_tool_calls_processor",
]
