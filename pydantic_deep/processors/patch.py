"""Fix orphaned tool calls in message history.

When a conversation is interrupted (user cancellation, tool crash, incomplete
checkpoint) or context management evicts messages, the history may contain:

1. **Orphaned tool calls**: ModelResponse with ToolCallParts that have no
   corresponding ToolReturnPart in the next ModelRequest.
2. **Orphaned tool results**: ModelRequest with ToolReturnParts that have no
   matching ToolCallPart in the preceding ModelResponse.

Both cases cause errors with most LLM APIs. `patch_tool_calls_processor` is the
pure repair function (reused by the CLI on resume); `PatchToolCallsCapability`
is the lifecycle adapter wired into agents via `patch_tool_calls=True`.

Example:
    ```python
    from pydantic_deep import create_deep_agent

    agent = create_deep_agent(
        patch_tool_calls=True,  # Enables PatchToolCallsCapability
    )
    ```
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
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
            # Skip falsy ids so phases 1 and 2 treat them consistently (B11):
            # phase 2 filters `if part.tool_call_id`, so a blank id here would
            # otherwise get a synthetic return phase 2 never strips.
            if isinstance(part, ToolCallPart) and part.tool_call_id:
                tool_calls[part.tool_call_id] = part

        if not tool_calls:
            continue

        # Check next message for matching ToolReturnParts
        next_msg = messages[i + 1] if i + 1 < len(messages) else None
        answered_ids: set[str] = set()

        if isinstance(next_msg, ModelRequest):
            for req_part in next_msg.parts:
                # A `RetryPromptPart` carries the original `tool_call_id` when a tool raises
                # `ModelRetry` (see pydantic-ai `_tool_manager._wrap_error_as_retry`), so it
                # counts as an answer to the call - otherwise we'd inject a synthetic
                # `ToolReturnPart` with the same id and trip strict providers like Bedrock.
                if (
                    isinstance(req_part, (ToolReturnPart, RetryPromptPart))
                    and req_part.tool_call_id in tool_calls
                ):
                    answered_ids.add(req_part.tool_call_id)

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
            for resp_part in prev_msg.parts:
                if isinstance(resp_part, ToolCallPart):
                    called_ids.add(resp_part.tool_call_id)

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
    `history_processors` parameter.

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
                # replace() preserves instructions/timestamp/run_id/etc. that a bare
                # ModelRequest(parts=...) would silently drop (B3).
                patched.append(replace(next_msg, parts=patched_parts))
                skip_indices.add(next_idx)
            else:
                # No next ModelRequest - create one with just synthetic parts
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

            # Filter out orphaned ToolReturnParts from this ModelRequest.
            # Orphaned results are only ever recorded against ModelRequest
            # messages (see _find_orphaned_results), but guard explicitly so
            # the invariant holds even under `python -O` (which strips asserts).
            if not isinstance(msg, ModelRequest):
                patched2.append(msg)  # pragma: no cover
                continue  # pragma: no cover

            ids_to_strip = strip_by_index[i]
            remaining_parts = [
                part
                for part in msg.parts
                if not (isinstance(part, ToolReturnPart) and part.tool_call_id in ids_to_strip)
            ]

            if remaining_parts:
                patched2.append(replace(msg, parts=remaining_parts))
            elif i == len(messages) - 1:
                patched2.append(replace(msg, parts=[]))
            # Otherwise the request is interior; dropping it is safe.

        messages = patched2

    return messages


@dataclass
class PatchToolCallsCapability(AbstractCapability[Any]):
    """Capability that fixes orphaned tool calls/results via `before_model_request`.

    Repairs two cases before each model request:

    1. **Orphaned tool calls** - `ToolCallPart` without a matching
       `ToolReturnPart` → injects a synthetic return with
       `"Tool call was cancelled."`.
    2. **Orphaned tool results** - `ToolReturnPart` without a matching
       `ToolCallPart` → removes the orphaned return.

    This replaces the `patch_tool_calls_processor` history processor with a
    capability hook that runs at the same lifecycle point but integrates with
    the pydantic-ai capabilities system.
    """

    async def before_model_request(
        self,
        ctx: RunContext[Any],
        request_context: Any,
    ) -> Any:
        """Patch orphaned tool calls/results before each model request."""
        request_context.messages = patch_tool_calls_processor(request_context.messages)
        return request_context


__all__ = [
    "CANCELLED_MESSAGE",
    "PatchToolCallsCapability",
    "patch_tool_calls_processor",
]
