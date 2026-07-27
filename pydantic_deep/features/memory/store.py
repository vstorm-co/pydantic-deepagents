"""Construct a `pydantic-ai-harness` memory store from pydantic-deep options.

The harness `Memory` capability persists to its own `MemoryStore`, independent
of the agent's `deps.backend`. This module is the single place that maps our
`memory_dir` option onto a concrete store, so the wiring in `agent.py` stays
declarative.
"""

from __future__ import annotations

import re
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai_harness.memory import FileStore, InMemoryStore, Memory, MemoryStore

# Mirrors the harness' `_VALID_SEGMENT_RE`: an agent_name becomes a path segment
# in the store, and the harness rejects anything outside this class at run time.
_VALID_AGENT_NAME_RE = re.compile(r"[A-Za-z0-9_.-]{1,200}")

MEMORY_CAPABILITY_ID = "memory"
"""Stable capability id, required for `defer_loading` (tool_search) to work."""


def resolve_memory_dir(memory_dir: str, *, base_dir: str | Path | None = None) -> Path:
    """Resolve `memory_dir` to an absolute **host** filesystem path.

    `memory_dir` used to name a path inside `deps.backend`; the harness store is
    independent of the backend, so it is now a real host path. Relative values
    are anchored to `base_dir` (the caller's working directory) rather than the
    process CWD, so memory follows the working directory the way backend files
    do instead of drifting with wherever the process happened to start.

    Args:
        memory_dir: Directory for on-disk memory, absolute or relative.
        base_dir: Directory relative paths are resolved against. Defaults to the
            process CWD.
    """
    path = Path(memory_dir).expanduser()
    if path.is_absolute():
        return path
    return (Path(base_dir).expanduser() if base_dir else Path.cwd()) / path


def build_memory_store(
    memory_dir: str | None, *, base_dir: str | Path | None = None
) -> MemoryStore:
    """Build a harness `MemoryStore` from a directory path.

    Returns a `FileStore` rooted at `memory_dir` when a directory is given, so
    memory files land at ``{memory_dir}/{agent_name}/MEMORY.md`` (matching the
    historical layout). With no directory an ephemeral `InMemoryStore` is used,
    which persists only for the process lifetime.

    The directory is created eagerly so an unusable `memory_dir` fails here with
    an actionable message. Without that, the harness defers the error to the
    first write, and — because `Memory` defaults to ``injection_errors="ignore"``
    — the read side swallows it entirely and the agent silently runs with no
    memory.

    Args:
        memory_dir: Host directory for on-disk memory, or ``None`` for an
            ephemeral in-memory store.
        base_dir: Directory relative `memory_dir` values resolve against.

    Raises:
        ValueError: `memory_dir` cannot be created or written to.
    """
    if not memory_dir:
        return InMemoryStore()
    root = resolve_memory_dir(memory_dir, base_dir=base_dir)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(
            f"memory_dir={memory_dir!r} is not a usable directory: {exc}. "
            "memory_dir is a host filesystem path (the harness memory store is "
            "independent of deps.backend), so backend-only paths such as "
            "'/.deep/memory' no longer work — pass a writable host directory, "
            "or pass memory_store= with an explicit harness store."
        ) from exc
    return FileStore(root)


def sanitize_agent_name(agent_name: str) -> str:
    """Coerce `agent_name` into a store path segment the harness will accept.

    The harness validates the scope segment against ``[A-Za-z0-9_.-]{1,200}``
    and raises at *run* time, so an agent name that was legal when memory was a
    backend path (``/.deep/memory/code reviewer/MEMORY.md``) would otherwise
    break the first delegation rather than agent construction. Offending runs of
    characters collapse to ``-`` so previously working names keep working.
    """
    if _VALID_AGENT_NAME_RE.fullmatch(agent_name):
        return agent_name
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", agent_name).strip("-")[:200]
    return cleaned or "agent"


def deps_store_resolver(
    default: MemoryStore,
) -> Callable[[RunContext[Any]], MemoryStore]:
    """Return a `Memory.store_resolver` that lets `deps` own the memory scope.

    Memory used to live in `deps.backend`, so per-run deps decided what an agent
    could remember: a per-user backend isolated tenants, and a forked branch's
    `BranchOverlay` contained (and could roll back) its memory writes. Binding a
    single store to the agent at construction time took both away.

    Resolution order is `deps.memory_store` first, then the agent's own store.
    When deps carry nothing, the agent's store is written back onto deps: the
    fork machinery clones deps, not the agent, so `clone_for_branch` needs a
    parent store reachable from deps to wrap. Mutating `ctx.deps` follows what
    `LiveForkCapability` already does with `fork_coordinator`.
    """

    def resolve(ctx: RunContext[Any]) -> MemoryStore:
        existing: MemoryStore | None = getattr(ctx.deps, "memory_store", None)
        if existing is not None:
            return existing
        # `deps` may be any type; only seed containers that declare the field.
        if hasattr(ctx.deps, "memory_store"):
            ctx.deps.memory_store = default
        return default

    return resolve


def build_memory_capability(
    *,
    store: MemoryStore,
    agent_name: str,
    namespace: str = "",
    defer_loading: bool = False,
    max_lines: int | None = None,
    max_tokens: int | None = None,
    pin_marker: str | None = None,
) -> Memory:
    """Build the harness `Memory` capability for one agent.

    Shared by the main agent and every subagent so their wiring cannot drift.
    `None` tuning values are dropped rather than forwarded: the harness fields
    are plain `int`s validated with ``value <= 0``, so passing `None` raises
    instead of falling back to the default.

    Args:
        store: Fallback store, used when `deps.memory_store` is unset. Shared
            across the main agent and its subagents.
        agent_name: Scope segment; sanitized via `sanitize_agent_name`.
        namespace: Per-tenant namespace isolating users on a shared store.
        defer_loading: Hide the memory tools until tool search discovers them.
        max_lines: Maximum `MEMORY.md` lines considered for injection.
        max_tokens: Approximate token ceiling for the injected section.
        pin_marker: Accepted only to warn — the harness has no pin concept.
    """
    if pin_marker is not None:
        warnings.warn(
            "memory_pin_marker is no longer supported: the harness `Memory` "
            "capability has no pinning concept, and its truncation keeps the "
            "tail of MEMORY.md, so a pinned header is the first thing dropped. "
            "Move must-keep content into the agent's instructions instead.",
            DeprecationWarning,
            stacklevel=3,
        )
    kwargs: dict[str, Any] = {}
    if max_lines is not None:
        kwargs["max_lines"] = max_lines
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    return Memory(
        store=store,
        # Resolved per run so `deps` can override the scope (per-tenant stores,
        # branch-local fork memory) instead of it being fixed at build time.
        store_resolver=deps_store_resolver(store),
        agent_name=sanitize_agent_name(agent_name),
        namespace=namespace,
        # `id` is required by pydantic-ai whenever `defer_loading` is set.
        id=MEMORY_CAPABILITY_ID,
        defer_loading=defer_loading,
        **kwargs,
    )
