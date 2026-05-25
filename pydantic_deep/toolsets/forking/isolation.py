"""Per-branch isolation primitives — :class:`BranchOverlay` and :func:`clone_for_branch`.

The overlay wraps a parent :class:`BackendProtocol` so a branch's writes
land in an isolated layer while reads of untouched paths fall through to
the parent. Every overlay write is recorded in
:attr:`BranchOverlay._changes` — the temporally-ordered list returned by
:meth:`BranchOverlay.changes`, which is the data spine consumed by the diff
builder, disk materializer, and judge.

``clone_for_branch`` produces a fresh :class:`DeepAgentDeps` for a branch
based on a :class:`BranchIsolation` policy.
"""

from __future__ import annotations

import logging
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
from pydantic_deep.types import BranchIsolation, FileChange, FlushError, FlushReport

if TYPE_CHECKING:
    from pydantic_deep.capabilities.message_queue import MessageQueue
    from pydantic_deep.toolsets.forking.materializer import ForkMaterializer


logger = logging.getLogger(__name__)


class BranchOverlay:
    """Copy-on-write backend overlay for a single branch.

    Reads consult the overlay first; if a path has not been written in
    this branch, the read falls through to the parent backend. Writes go
    to the overlay only and are logged to ``_changes`` for downstream
    consumers (diff builder, materializer, judge).

    The overlay implements the subset of :class:`BackendProtocol` exercised
    by branch operations (read, write, edit, ``ls_info``, ``glob_info``,
    ``grep_raw``, ``read_bytes``). Forwarding for the latter three merges
    overlay and parent results with the overlay taking precedence.
    """

    def __init__(self, parent: BackendProtocol) -> None:
        self._parent = parent
        self._overlay = StateBackend()
        self._changes: list[FileChange] = []
        self._materializer: ForkMaterializer | None = None
        self._branch_label: str | None = None

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
        self._snapshot_parent_on_first_touch(path)
        result = self._overlay.write(path, content)
        if not result.error:
            change = FileChange(path=path, op="write", timestamp=datetime.now(timezone.utc))
            self._changes.append(change)
            self._mirror_to_disk(change)
        return result

    def edit(
        self,
        path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        self._snapshot_parent_on_first_touch(path)
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
            change = FileChange(path=path, op="edit", timestamp=datetime.now(timezone.utc))
            self._changes.append(change)
            self._mirror_to_disk(change)
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

    @property
    def execute_enabled(self) -> bool:  # pragma: no cover - transparent forward to parent
        enabled = getattr(self._parent, "execute_enabled", None)
        return bool(enabled) if enabled is not None else False

    def execute(
        self, command: str, timeout: int | None = None
    ) -> Any:  # pragma: no cover - transparent forward to parent
        return self._parent.execute(command, timeout)  # pyright: ignore[reportAttributeAccessIssue]

    async def async_execute(
        self, command: str, timeout: int | None = None
    ) -> Any:  # pragma: no cover - transparent forward to parent
        return await self._parent.async_execute(  # pyright: ignore[reportAttributeAccessIssue]
            command, timeout
        )

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        **kwargs: Any,
    ) -> list[GrepMatch] | str:
        # Forward to parent. Overlay grep (cross-branch grep in diff_branches)
        # is not yet implemented — punt for now.
        result: list[GrepMatch] | str = self._parent.grep_raw(pattern, path, **kwargs)
        return result

    def attach_materializer(self, materializer: ForkMaterializer, branch_label: str) -> None:
        """Wire a :class:`ForkMaterializer` into this overlay.

        After this call every successful ``write`` / ``edit`` is mirrored
        to disk under the materializer's ``branches/{branch_label}/``
        subtree, and the parent backend's pre-fork bytes for each touched
        path are captured lazily on first touch via
        :meth:`ForkMaterializer.snapshot_parent_path`.
        """
        self._materializer = materializer
        self._branch_label = branch_label

    def _snapshot_parent_on_first_touch(self, path: str) -> None:
        """Capture the parent's pre-fork bytes for ``path`` the first time it's written.

        No-op when no materializer is attached. The materializer itself
        de-dupes repeat calls for the same path, so this is safe to call
        from both ``write`` and ``edit``.
        """
        materializer = self._materializer
        if materializer is None:
            return
        try:
            parent_bytes: bytes | None = self._parent.read_bytes(path)
        except (FileNotFoundError, KeyError):
            parent_bytes = None
        materializer.snapshot_parent_path(path, parent_bytes)

    def _mirror_to_disk(self, change: FileChange) -> None:
        """Mirror one ``FileChange`` to the on-disk branch directory."""
        materializer = self._materializer
        branch_label = self._branch_label
        if materializer is None or branch_label is None:
            return
        content = self._overlay.read_bytes(change.path)
        try:
            materializer.flush_change(branch_label, change, content)
        except OSError:
            logger.warning(
                "materializer flush_change failed for branch %s path %s",
                branch_label,
                change.path,
                exc_info=True,
            )

    def flush_to(
        self,
        parent: BackendProtocol,
        pre_flush_snapshot: dict[str, bytes | None] | None = None,
    ) -> FlushReport:
        """Replay this overlay's writes onto ``parent``.

        Args:
            parent: Destination backend. Usually the parent run's backend;
                for fork-of-fork it is the OUTER branch's overlay (which
                is itself a :class:`BranchOverlay`) — propagation up one
                level works without special casing.
            pre_flush_snapshot: Optional mapping of ``path → parent bytes
                at fork time`` (or ``None`` for "did not exist"). When
                supplied, ``flush_to`` compares each touched path's
                current parent bytes against the snapshot and records a
                conflict for divergent paths. Both modified-by-third-actor
                and deleted-by-third-actor cases land in ``conflicts``.

        Returns:
            A :class:`FlushReport` with ``applied_paths`` (one entry per
            successfully-replayed path, last-write-wins), ``applied_changes``
            (every replayed op — ≥ ``len(applied_paths)``), ``conflicts``
            (divergent paths), and ``errors`` (per-write failures —
            ``flush_to`` never aborts on the first failure).

        Order: writes are replayed in :attr:`_changes` order (temporal),
        so a sequence ``write A → edit A → write B`` results in
        ``parent`` reflecting the final overlay state for both A and B.
        """
        applied_paths: list[str] = []
        applied_set: set[str] = set()
        errors: list[FlushError] = []
        conflicts: list[str] = self._detect_conflicts(parent, pre_flush_snapshot)
        applied_changes = 0

        for change in self._changes:
            content = self._overlay.read_bytes(change.path)
            try:
                write_result = parent.write(change.path, content)
            except Exception as exc:
                errors.append(FlushError(path=change.path, op=change.op, message=str(exc)))
                if change.path in applied_set:
                    applied_set.discard(change.path)
                    applied_paths = [p for p in applied_paths if p != change.path]
                continue
            if write_result.error:
                errors.append(
                    FlushError(path=change.path, op=change.op, message=write_result.error)
                )
                if change.path in applied_set:
                    applied_set.discard(change.path)
                    applied_paths = [p for p in applied_paths if p != change.path]
                continue
            applied_changes += 1
            if change.path not in applied_set:
                applied_set.add(change.path)
                applied_paths.append(change.path)

        return FlushReport(
            applied_paths=applied_paths,
            applied_changes=applied_changes,
            conflicts=conflicts,
            errors=errors,
        )

    def _detect_conflicts(
        self,
        parent: BackendProtocol,
        pre_flush_snapshot: dict[str, bytes | None] | None,
    ) -> list[str]:
        """Compare each touched path's current parent bytes to the snapshot.

        Handles both modified-by-third-actor (snapshot bytes ≠ current
        parent bytes) and deleted-by-third-actor (snapshot had bytes,
        parent now lacks the file) cases. Returns paths sorted for
        deterministic test output.
        """
        if pre_flush_snapshot is None:
            return []
        touched_paths = {c.path for c in self._changes}
        conflicts: list[str] = []
        for path in touched_paths:
            if path not in pre_flush_snapshot:
                continue
            snapshot_bytes = pre_flush_snapshot[path]
            try:
                current_bytes: bytes | None = parent.read_bytes(path)
            except (FileNotFoundError, KeyError):
                current_bytes = None
            if current_bytes != snapshot_bytes:
                conflicts.append(path)
        return sorted(conflicts)


def clone_for_branch(deps: DeepAgentDeps, isolation: BranchIsolation) -> DeepAgentDeps:
    """Clone ``DeepAgentDeps`` for a branch according to ``isolation``.

    See :class:`BranchIsolation` for per-flag semantics. Memory isolation
    follows the backend (memory lives at
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
