"""Tool search feature — defer the situational tool surface for faster, leaner
requests.

A lifecycle-only slice: re-exports Pydantic AI's `ToolSearch` capability plus
`defer_situational_toolsets`, the helper that marks every non-core toolset for
deferred loading. No model-callable tools of its own.
"""

from pydantic_deep.features.tool_search.capability import (
    DEFAULT_ALWAYS_LOADED_TOOLSET_IDS,
    ToolSearch,
    defer_situational_toolsets,
)

__all__ = [
    "DEFAULT_ALWAYS_LOADED_TOOLSET_IDS",
    "ToolSearch",
    "defer_situational_toolsets",
]
