"""Tool search — defer the situational tool surface so the model isn't loaded
with every tool schema upfront.

A deep agent wires in a large tool surface (filesystem, todos, subagents,
skills, memory, teams, MCP servers, …). Sending every schema on every request
costs input tokens and dilutes the model's attention. This slice wraps Pydantic
AI's [`ToolSearch`][pydantic_ai.capabilities.ToolSearch] capability: the core
read/edit/run/track loop stays always-loaded, and the rest of the surface is
marked `defer_loading=True` — hidden from the model until discovered on demand
via tool search.

On Anthropic and OpenAI the discovery rides the provider's native tool-search
surface, so it is cheap and prompt-cache friendly. Elsewhere it falls back to a
local `search_tools` function tool. There is zero behavioral change when no
toolset is deferred, so this is safe to leave off by default and opt into.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic_ai.capabilities import ToolSearch

# Toolset ids kept always-loaded: the core read / edit / run / track loop the
# agent reaches for on essentially every turn. Deferring these would only add a
# discovery round-trip before the first useful action.
DEFAULT_ALWAYS_LOADED_TOOLSET_IDS: frozenset[str] = frozenset(
    {
        "deep-console",  # ls / read / write / edit / glob / grep / execute
        "deep-todo",  # task tracking
    }
)


def defer_situational_toolsets(
    toolsets: Sequence[Any],
    *,
    always_loaded_ids: frozenset[str] = DEFAULT_ALWAYS_LOADED_TOOLSET_IDS,
) -> list[Any]:
    """Return a new toolset list with every non-core toolset deferred.

    A toolset is kept loaded when its ``id`` is in ``always_loaded_ids``;
    everything else is wrapped with
    [`defer_loading()`][pydantic_ai.toolsets.AbstractToolset.defer_loading] so
    its tools stay hidden until discovered via tool search. Toolsets without an
    ``id`` are treated as situational and deferred.
    """
    deferred: list[Any] = []
    for toolset in toolsets:
        toolset_id = getattr(toolset, "id", None)
        if toolset_id in always_loaded_ids:
            deferred.append(toolset)
        else:
            deferred.append(toolset.defer_loading())
    return deferred


__all__ = [
    "DEFAULT_ALWAYS_LOADED_TOOLSET_IDS",
    "ToolSearch",
    "defer_situational_toolsets",
]
