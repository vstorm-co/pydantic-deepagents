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

from pydantic_deep.features.memory.service import DEFAULT_MEMORY_DIR

MEMORY_CAPABILITY_ID = "memory"
"""The capability's id - Pydantic AI requires one for `defer_loading`."""

MemoryNamespace = str | Callable[[RunContext[Any]], str]
"""A fixed namespace, or one resolved from each run's context - a user id, say."""

# The harness checks each scope segment against this, and refuses `..` in one,
# when a run starts.
_SEGMENT = re.compile(r"[A-Za-z0-9_.-]{1,200}")


def _valid_segment(segment: str) -> bool:
    return bool(_SEGMENT.fullmatch(segment)) and ".." not in segment and segment != "."


def sanitize_agent_name(agent_name: str) -> str:
    """`agent_name` as a store path segment the harness accepts.

    The harness checks the segment when a run starts, so a subagent called "code
    reviewer" built cleanly and failed at its first delegation. Runs of other
    characters become `-`, and runs of dots one dot; a name with nothing left - or
    only `.`, which would put its notebook at the store's root - becomes "agent".
    """
    if _valid_segment(agent_name):
        return agent_name
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", agent_name)
    cleaned = re.sub(r"\.{2,}", ".", cleaned).strip("-.")[:200]
    return cleaned if _valid_segment(cleaned) else "agent"


def check_namespace(namespace: str) -> str:
    """`namespace` if the harness will accept it as a store path.

    Checked up front for a fixed namespace, rather than renamed: two tenants whose
    names cleaned up to the same segment would share a notebook. A namespace
    resolved per run is checked by the harness when the run starts.

    Raises:
        ValueError: A segment holds anything but letters, digits, `_`, `-` and
            `.`, or is `.` or contains `..`.
    """
    if namespace and not all(_valid_segment(segment) for segment in namespace.split("/")):
        raise ValueError(
            f"memory_namespace={namespace!r} is not a usable store path: each "
            "'/'-separated part must be 1-200 letters, digits, '_', '-' or '.', and "
            "neither '.' nor contain '..'. Map an id such as an e-mail address to "
            "one first - a hash of it, say."
        )
    return namespace


def build_memory_capability(
    *,
    agent_name: str,
    store: FileStore | None = None,
    memory_dir: str = DEFAULT_MEMORY_DIR,
    namespace: MemoryNamespace = "",
    max_lines: int | None = None,
    max_tokens: int | None = None,
    max_memory_size: int | None = None,
    pin_marker: str | None = None,
) -> Memory[Any]:
    """The `Memory` capability one agent remembers with.

    Shared by the main agent and every subagent, so their wiring cannot drift.

    Args:
        agent_name: The agent's own segment in the store; sanitized for the harness.
        store: The store to remember in. Agents writing to one directory should
            share one: its copies share a lock, which keeps the receipts beside the
            notebooks consistent. A new `FileStore(memory_dir)` when `None`.
        memory_dir: Directory in the run's workspace, when `store` is not given.
        namespace: A per-tenant segment above the agent's, fixed or resolved per
            run. The model never sees or chooses it.
        max_lines: Most `MEMORY.md` lines injected; the harness default when `None`.
        max_tokens: Approximate ceiling on the injected section; likewise.
        max_memory_size: Largest memory file, in characters, the tools will read
            or change; the harness default (65,536) when `None`.
        pin_marker: Accepted only to warn - the harness has no pinned section.

    Raises:
        ValueError: A fixed `namespace` the harness would refuse.
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
        store if store is not None else FileStore(memory_dir),
        agent_name=sanitize_agent_name(agent_name),
        namespace=check_namespace(namespace) if isinstance(namespace, str) else namespace,
        id=MEMORY_CAPABILITY_ID,
        # The harness fields are plain ints, so `None` means its own default here.
        max_lines=Memory.max_lines if max_lines is None else max_lines,
        max_tokens=Memory.max_tokens if max_tokens is None else max_tokens,
        max_memory_size=Memory.max_memory_size if max_memory_size is None else max_memory_size,
    )
