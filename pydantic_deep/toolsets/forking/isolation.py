"""Per-branch isolation primitives — :class:`BranchOverlay` and :func:`clone_for_branch`.

The overlay wraps a parent :class:`BackendProtocol` so a branch's writes
land in an isolated layer while reads of untouched paths fall through to
the parent. Every overlay write is recorded in
:attr:`BranchOverlay._changes` — the temporally-ordered list returned by
:meth:`BranchOverlay.changes`, which is the data spine consumed by Stage 2's
diff, Stage 5's materializer, and Stage 6's judge.

``clone_for_branch`` produces a fresh :class:`DeepAgentDeps` for a branch
based on a :class:`BranchIsolation` policy.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from pydantic_ai_backends import (
    BackendProtocol,
    EditResult,
    FileInfo,
    GrepMatch,
    StateBackend,
    WriteResult,
)

from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.types import BranchIsolation, FileChange

if TYPE_CHECKING:
    from pydantic_deep.capabilities.message_queue import MessageQueue


class BranchOverlay:
    """Copy-on-write backend overlay for a single branch.

    Reads consult the overlay first; if a path has not been written in
    this branch, the read falls through to the parent backend. Writes go
    to the overlay only and are logged to ``_changes`` for downstream
    consumers (Stage 2/5/6).

    The overlay is intentionally minimal in Stage 1 — it implements the
    subset of :class:`BackendProtocol` exercised by the kernel test plan
    (read, write, edit, ``ls_info``, ``glob_info``, ``grep_raw``,
    ``read_bytes``). Forwarding for the latter three merges overlay and
    parent results with the overlay taking precedence.
    """

    def __init__(self, parent: BackendProtocol) -> None:
        self._parent = parent
        self._overlay = StateBackend()
        self._changes: list[FileChange] = []

    @property
    def parent(self) -> BackendProtocol:
        return self._parent

    def changes(self) -> list[FileChange]:
        """Return the temporal-ordered list of writes recorded in this overlay."""
        return list(self._changes)

    def _has(self, path: str) -> bool:
        """Check whether a file lives in THIS overlay (not parent)."""
        return bool(self._overlay.exists(path))

    def exists(self, path: str) -> bool:
        """Public ``BackendProtocol`` predicate — overlay first, fall through to parent.

        A branch "sees" any file present in either layer, mirroring the
        copy-on-write read semantics: written-by-this-branch files take
        precedence, otherwise the parent backend answers.
        """
        return bool(self._overlay.exists(path) or self._parent.exists(path))

    def read(self, path: str, offset: int = 0, limit: int = 2000) -> str:
        if self._has(path):
            result: str = self._overlay.read(path, offset, limit)
            return result
        return str(self._parent.read(path, offset, limit))

    def read_bytes(self, path: str) -> bytes:
        if self._has(path):
            data: bytes = self._overlay.read_bytes(path)
            return data
        parent_data: bytes = self._parent.read_bytes(path)
        return parent_data

    def write(self, path: str, content: str | bytes) -> WriteResult:
        result = self._overlay.write(path, content)
        if not result.error:
            self._changes.append(
                FileChange(path=path, op="write", timestamp=datetime.now(timezone.utc))
            )
        return result

    def edit(
        self,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        # If the file lives only in the parent, materialize it into the overlay
        # first so edits don't leak back to the parent.
        if not self._has(path):
            try:
                parent_bytes = self._parent.read_bytes(path)
            except (FileNotFoundError, KeyError):  # pragma: no cover - defensive
                # File doesn't exist in parent either — let overlay.edit surface
                # the not-found error to the caller via EditResult.error.
                return self._overlay.edit(path, old_string, new_string, replace_all)
            self._overlay.write(path, parent_bytes)
        result = self._overlay.edit(path, old_string, new_string, replace_all)
        if not result.error:
            self._changes.append(
                FileChange(path=path, op="edit", timestamp=datetime.now(timezone.utc))
            )
        return result

    @staticmethod
    def _merge_entries(
        parent_entries: list[FileInfo], overlay_entries: list[FileInfo]
    ) -> list[FileInfo]:
        """Merge two ``FileInfo`` lists keyed by ``path`` — overlay wins on conflicts."""
        seen: dict[str, FileInfo] = {entry["path"]: entry for entry in parent_entries}
        for entry in overlay_entries:
            seen[entry["path"]] = entry
        return list(seen.values())

    def ls_info(self, path: str) -> list[FileInfo]:
        return self._merge_entries(self._parent.ls_info(path), self._overlay.ls_info(path))

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        return self._merge_entries(
            self._parent.glob_info(pattern, path),
            self._overlay.glob_info(pattern, path),
        )

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        **kwargs: Any,
    ) -> list[GrepMatch] | str:
        # Stage 1: forward to parent. Overlay grep is a Stage 2 concern when
        # diff_branches needs cross-overlay grep — punt for now.
        result: list[GrepMatch] | str = self._parent.grep_raw(pattern, path, **kwargs)
        return result


def clone_for_branch(deps: DeepAgentDeps, isolation: BranchIsolation) -> DeepAgentDeps:
    """Clone ``DeepAgentDeps`` for a branch according to ``isolation``.

    See :class:`BranchIsolation` for per-flag semantics. Memory isolation
    in Stage 1 follows the backend (memory lives at
    ``{memory_dir}/{agent_name}/MEMORY.md`` inside the backend); the
    ``memory`` flag is recorded for forward-compat but has no separate
    effect here. ``team_bus`` is a no-op when the teams capability is not
    enabled on the parent run; when enabled it propagates the parent bus
    reference by default.
    """

    new_backend: BackendProtocol = (
        BranchOverlay(deps.backend) if isolation.backend == "copy" else deps.backend
    )

    new_todos = [] if isolation.todos == "copy" else deps.todos

    new_message_queue: MessageQueue | None
    if isolation.message_queue == "isolated":
        from pydantic_deep.capabilities.message_queue import MessageQueue as _MQ

        new_message_queue = _MQ()
    else:
        new_message_queue = deps.message_queue

    return replace(
        deps,
        backend=new_backend,
        files={},  # Fresh file cache; branch backend is independent
        todos=new_todos,
        subagents={},
        message_queue=new_message_queue,
        fork_coordinator=None,
        _fork_depth=deps._fork_depth + 1,
    )


__all__ = ["BranchOverlay", "clone_for_branch"]
