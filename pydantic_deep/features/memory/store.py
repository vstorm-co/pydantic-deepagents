"""Build the harness `Memory` capability from pydantic-deep's memory options.

Memory is `pydantic_ai_harness.Memory` over a `FileStore`: Markdown files in the
run's workspace, `{memory_dir}/{namespace}/{agent_name}/MEMORY.md`, which is the
layout pydantic-deep's own memory used - so existing notebooks are read as they
are. Living in the workspace is what keeps it isolated the way files are: each
user's workspace holds that user's memory, and a forked branch writes into its
own overlay until it is merged.
"""

from __future__ import annotations

import re
import warnings
from collections.abc import Callable
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai_harness import Memory
from pydantic_ai_harness.memory import FileStore

MEMORY_CAPABILITY_ID = "memory"
"""The capability's id - Pydantic AI requires one for `defer_loading`."""

MemoryNamespace = str | Callable[[RunContext[Any]], str]
"""A fixed namespace, or one resolved from each run's context - a user id, say."""

# The harness validates every scope segment against this, at run time.
_SEGMENT = re.compile(r"[A-Za-z0-9_.-]{1,200}")


def sanitize_agent_name(agent_name: str) -> str:
    """`agent_name` as a store path segment the harness accepts.

    The harness checks the segment against `[A-Za-z0-9_.-]{1,200}` when a run
    starts, so a subagent called "code reviewer" built cleanly and failed at its
    first delegation. Runs of other characters become `-`.
    """
    if _SEGMENT.fullmatch(agent_name):
        return agent_name
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", agent_name).strip("-")[:200] or "agent"


def build_memory_capability(
    *,
    memory_dir: str,
    agent_name: str,
    namespace: MemoryNamespace = "",
    defer_loading: bool = False,
    max_lines: int | None = None,
    max_tokens: int | None = None,
    pin_marker: str | None = None,
) -> Memory[Any]:
    """The `Memory` capability one agent remembers with.

    Shared by the main agent and every subagent, so their wiring cannot drift.

    Args:
        memory_dir: Directory in the run's workspace holding every agent's notebook.
        agent_name: The agent's own segment under it; sanitized for the harness.
        namespace: A per-tenant segment above the agent's, fixed or resolved per
            run. The model never sees or chooses it.
        defer_loading: Hide the memory tools until tool search finds them.
        max_lines: Most `MEMORY.md` lines injected; the harness default when `None`.
        max_tokens: Approximate ceiling on the injected section; likewise.
        pin_marker: Accepted only to warn - the harness has no pinned section.
    """
    if pin_marker is not None:
        warnings.warn(
            "memory_pin_marker no longer has an effect: memory is the harness "
            "`Memory` capability, which has no pinned section and keeps the tail of "
            "MEMORY.md when it truncates. Put what must always be seen in the "
            "agent's instructions.",
            DeprecationWarning,
            stacklevel=3,
        )
    return Memory(
        FileStore(memory_dir),
        agent_name=sanitize_agent_name(agent_name),
        namespace=namespace,
        id=MEMORY_CAPABILITY_ID,
        defer_loading=defer_loading,
        # The harness fields are plain ints, so `None` means its own default here.
        max_lines=Memory.max_lines if max_lines is None else max_lines,
        max_tokens=Memory.max_tokens if max_tokens is None else max_tokens,
    )
