"""Patch-tool-calls feature — repair orphaned tool calls on resumed conversations.

A lifecycle-only slice: `capability.py` (PatchToolCallsCapability + the legacy
`patch_tool_calls_processor` function).
"""

from pydantic_deep.features.patch.capability import (
    CANCELLED_MESSAGE,
    PatchToolCallsCapability,
    patch_tool_calls_processor,
)

__all__ = [
    "CANCELLED_MESSAGE",
    "PatchToolCallsCapability",
    "patch_tool_calls_processor",
]
