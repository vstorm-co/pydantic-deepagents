"""Per-branch isolation primitives - :class:`BranchOverlay` and :func:`clone_for_branch`.

The overlay wraps a parent :class:`BackendProtocol` so a branch's writes
land in an isolated layer while reads of untouched paths fall through to
the parent. Every overlay write is recorded in
:attr:`BranchOverlay._changes` - the temporally-ordered list returned by
:meth:`BranchOverlay.changes`, which is the data spine consumed by the diff
builder, disk materializer, and judge.

`clone_for_branch` produces a fresh :class:`DeepAgentDeps` for a branch
based on a :class:`BranchIsolation` policy.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from collections.abc import Generator
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic_ai_backends import (
    BackendProtocol,
    EditResult,
    ExecuteResponse,
    FileInfo,
    GrepMatch,
    StateBackend,
    WriteResult,
)

from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.features.forking.types import (
    BranchIsolation,
    FileChange,
    FlushError,
    FlushReport,
)
from pydantic_deep.features.message_queue import MessageQueue

if TYPE_CHECKING:
    from pydantic_deep.features.forking.materializer import ForkMaterializer


logger = logging.getLogger(__name__)


def _read_backend_bytes(backend: Any, path: str) -> bytes:
    """Read bytes from a sync backend.

    Uses ``read_bytes`` when available, falls back to ``_read_bytes``
    (some backends like ``LocalBackend`` only expose the private method).
    """
    reader: Any = getattr(backend, "read_bytes", None)
    if reader is None:
        reader = backend._read_bytes
    return bytes(reader(path))


#: Heavy/ephemeral dirs - skipped to keep snapshot creation fast.
_SNAP_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".venv",
        ".git",
        "__pycache__",
        "node_modules",
        ".tox",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "htmlcov",
        ".eggs",
        "dist",
        "build",
    }
)

#: Max characters returned from a branch execute call.
_EXEC_MAX_CHARS: int = 100_000

#: Default timeout (seconds) for a branch `execute` when the caller passes `None`.
_EXEC_DEFAULT_TIMEOUT_S: int = 120

#: Matches the POSIX `timeout(1)` convention for killed-by-timeout commands.
_EXIT_TIMEOUT: int = 124


def _rel_under(parent_root: Path, path: str) -> Path:
    """Return `path` relative to `parent_root`, falling back to lstripped.

    `Path.relative_to` raises `ValueError` when `path` is not under
    `parent_root` - for those (uncommon) paths we strip the leading
    `/` so the result still lives inside the snapshot directory.
    """
    try:
        return Path(path).relative_to(parent_root)
    except ValueError:
        return Path(path.lstrip("/"))


def _rewrite_parent_root(command: str, parent_root: str, snap: str) -> str:
    """Rewrite absolute `parent_root` references in `command` to `snap`.

    Only path-boundary matches are rewritten - `parent_root` must be followed
    by a path separator, the end of the string, or a shell token boundary
    (whitespace or a quote). A naive `str.replace` would mangle a sibling path
    that merely shares the prefix (`/home/u/proj` rewriting inside
    `/home/u/proj_backup/x`) or the root appearing inside an unrelated literal.
    """
    if not parent_root:
        return command
    pattern = re.escape(parent_root) + r"(?=/|$|[\s'\"])"
    return re.sub(pattern, lambda _m: snap, command)


def _copy_tree(src: Path, dst: Path) -> None:
    """Recursively COPY *src* into *dst* (copy-on-write at the file level).

    Directories are recreated; files are copied as real, independent files.
    Entries whose name is in :data:`_SNAP_SKIP_DIRS` are silently skipped so
    the snapshot stays lean even on large projects.

    Copying (rather than symlinking) is the core isolation guarantee: the
    branch runs `sh -c <cmd>` against this snapshot with no write
    interception - only a post-hoc diff. An in-place write (`echo x >>
    file`, `sed -i`, a truncating rewrite, a non-atomic editor) modifies
    the snapshot's own copy and can no longer follow a symlink straight onto
    the real parent file, so a losing branch's side effects never leak into
    the parent before merge/winner selection.
    """
    with os.scandir(src) as it:
        for entry in it:
            if entry.name in _SNAP_SKIP_DIRS:
                continue
            target = dst / entry.name
            if entry.is_dir(follow_symlinks=False):
                target.mkdir(exist_ok=True)
                _copy_tree(Path(entry.path), target)
            else:
                # Copy (follow symlinks) so the snapshot is a detached, writable copy.
                try:
                    shutil.copy2(entry.path, target, follow_symlinks=True)
                except OSError as exc:
                    # Skip an unreadable entry (e.g. a dangling symlink) rather than abort.
                    logger.warning(
                        "branch snapshot: failed to copy %s into snapshot (%s); skipping",
                        entry.path,
                        exc,
                    )


@contextlib.contextmanager
def _branch_snapshot(
    parent_root: Path,
    overlay: StateBackend,
    changes: list[Any],
    deleted: set[str],
) -> Generator[str, None, None]:
    """Yield a temp directory that presents an isolated view of the branch.

    Layout:
    - Parent files → detached file copies (reading works; in-place writes
      land on the copy, never the real parent file).
    - Overlay writes → real files (the branch's in-progress content is
      visible to the subprocess).
    - Deleted paths → corresponding file removed.

    The temp directory is deleted when the context exits regardless of
    exceptions.  The caller should rewrite any absolute references to
    *parent_root* in the command string to *tmp_dir* before execution so
    that path-explicit commands (`rm /abs/path/file.py`) also stay
    inside the snapshot.
    """
    with tempfile.TemporaryDirectory(prefix="branch-snap-") as tmp_dir:
        tmp = Path(tmp_dir)

        _copy_tree(parent_root, tmp)

        # Overlay writes (last write wins) override the copied parent files.
        touched = {c.path for c in changes if c.op in ("write", "edit")} - deleted

        for path in touched:
            try:
                content = overlay.read_bytes(path)
            except (FileNotFoundError, KeyError, OSError) as exc:
                logger.warning(
                    "branch snapshot: cannot read overlay path %s (%s); skipping",
                    path,
                    exc,
                )
                continue
            dst = tmp / _rel_under(parent_root, path)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.is_symlink() or dst.exists():
                dst.unlink()
            dst.write_bytes(content)

        # Branch-deleted paths are removed from the snapshot.
        for path in deleted:
            dst = tmp / _rel_under(parent_root, path)
            if dst.is_symlink() or dst.exists():
                dst.unlink()

        yield tmp_dir


def _file_signature(path: str) -> str:
    """Return a content signature (`size:sha256`) for the file at `path`.

    Follows symlinks so the signature reflects the bytes actually exposed.
    A content hash - not mtime - is used so an in-place rewrite within the
    filesystem's coarse mtime tick, or a tool that preserves mtime
    (`cp -p`, `touch -r`, some formatters), is still detected as a
    change. Returns `""` when the file can't be read.
    """
    try:
        digest = hashlib.sha256()
        size = 0
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                size += len(chunk)
                digest.update(chunk)
        return f"{size}:{digest.hexdigest()}"
    except OSError:
        return ""


def _snapshot_state(snap: Path) -> dict[str, tuple[bool, str]]:
    """Return `{rel_path: (is_symlink, content_signature)}` for every file in *snap*.

    Uses :func:`os.scandir` recursively with `followlinks=False` so
    symlinked directories are not traversed (they remain as single
    symlink entries in the parent directory scan, not as trees).
    Directories in :data:`_SNAP_SKIP_DIRS` are skipped. The signature is a
    size + content hash (see :func:`_file_signature`) so a change is
    detected by content, not mtime.
    """
    state: dict[str, tuple[bool, str]] = {}
    _collect_state(snap, snap, state)
    return state


def _collect_state(root: Path, current: Path, out: dict[str, tuple[bool, str]]) -> None:
    try:
        entries = list(os.scandir(current))
    except (PermissionError, OSError):
        return
    for entry in entries:
        if entry.name in _SNAP_SKIP_DIRS:
            continue
        p = Path(entry.path)
        rel = str(p.relative_to(root))
        if entry.is_symlink():
            out[rel] = (True, _file_signature(entry.path))
        elif entry.is_file(follow_symlinks=False):
            out[rel] = (False, _file_signature(entry.path))
        elif entry.is_dir(follow_symlinks=False):
            child_count = len(out)
            _collect_state(root, p, out)
            if len(out) == child_count:
                out[rel + "/"] = (False, "")


def _capture_overlay_write(overlay: Any, abs_path: str, snap_file: Path) -> None:
    """Mirror a snapshot file into the branch overlay.

    Wraps the `overlay.write` call so all four call sites in
    :func:`_propagate_mutations` share the same existence guard and
    failure surfacing. Failures are logged at WARNING - silently
    swallowing them would leave the overlay disagreeing with the
    snapshot the user just saw.
    """
    if not snap_file.exists():
        return
    try:
        overlay.write(abs_path, snap_file.read_bytes())
    except OSError as exc:
        logger.warning(
            "branch snapshot: failed to capture %s into overlay (%s)",
            abs_path,
            exc,
        )


def _capture_overlay_delete(overlay: Any, abs_path: str) -> None:
    """Mirror a snapshot deletion into the branch overlay (logged on failure)."""
    try:
        overlay.delete(abs_path)
    except OSError as exc:
        logger.warning(
            "branch snapshot: failed to record delete of %s in overlay (%s)",
            abs_path,
            exc,
        )


def _propagate_mutations(
    snap: Path,
    parent_root: Path,
    pre: dict[str, tuple[bool, str]],
    post: dict[str, tuple[bool, str]],
    overlay: Any,
) -> None:
    """Diff *pre* vs *post* snapshot states and mirror changes into *overlay*.

    Three cases are handled:

    - **Deleted** (existed before, absent after): `overlay.delete(abs_path)`
      so the deletion propagates to the parent on merge.
    - **Created** (absent before, exists after): `overlay.write(abs_path, content)`
      so the new file is part of the branch diff.
    - **Modified** (symlink replaced by real file, or content signature
      changed): `overlay.write(abs_path, new_content)` to capture the update.

    Files whose content signature is unchanged are skipped - they need no
    overlay entry. Detection is by content signature, not mtime, so a write
    that preserves mtime is still caught.
    """
    all_paths = set(pre) | set(post)
    for rel in all_paths:
        in_pre = rel in pre
        in_post = rel in post
        is_dir = rel.endswith("/")

        if is_dir:
            dir_path = str(parent_root / rel.rstrip("/"))
            if not in_pre and in_post:
                overlay.record_mkdir(dir_path)
            elif in_pre and not in_post:
                overlay.record_rmdir(dir_path)
            continue

        abs_path = str(parent_root / rel)
        snap_file = snap / rel

        if in_pre and not in_post:
            _capture_overlay_delete(overlay, abs_path)
            continue

        if not in_pre and in_post:
            _capture_overlay_write(overlay, abs_path, snap_file)
            continue

        pre_sym, pre_sig = pre[rel]
        post_sym, post_sig = post[rel]

        symlink_replaced_by_file = pre_sym and not post_sym
        real_file_changed = not post_sym and pre_sig != post_sig
        symlink_target_changed = pre_sym and post_sym and pre_sig != post_sig

        if symlink_replaced_by_file or real_file_changed or symlink_target_changed:
            _capture_overlay_write(overlay, abs_path, snap_file)


class BranchOverlay:
    """Copy-on-write backend overlay for a single branch.

    Reads consult the overlay first; if a path has not been written in
    this branch, the read falls through to the parent backend. Writes go
    to the overlay only and are logged to `_changes` for downstream
    consumers (diff builder, materializer, judge).

    The overlay implements the subset of :class:`BackendProtocol` exercised
    by branch operations (read, write, edit, `ls_info`, `glob_info`,
    `grep_raw`, `read_bytes`). Forwarding for the latter three merges
    overlay and parent results with the overlay taking precedence.
    """

    def __init__(self, parent: BackendProtocol) -> None:
        self._parent = parent
        self._overlay = StateBackend()
        self._changes: list[FileChange] = []
        self._deleted: set[str] = set()
        self._materializer: ForkMaterializer | None = None
        self._branch_label: str | None = None

    @property
    def parent(self) -> BackendProtocol:
        return self._parent

    def changes(self) -> list[FileChange]:
        """Return the temporal-ordered list of writes recorded in this overlay."""
        return list(self._changes)

    def deleted(self) -> set[str]:
        """Paths the branch has explicitly removed via :meth:`delete`.

        Returns a copy so callers can't mutate the overlay's internal
        tombstone set. Mirrors :meth:`changes` - same convention.
        """
        return set(self._deleted)

    @contextlib.contextmanager
    def snapshot(
        self,
        parent_root: Path,
        *,
        include_venv: bool = False,
    ) -> Generator[str, None, None]:
        """Yield a tempdir presenting an isolated, branch-flavoured view of `parent_root`.

        Parent files are detached file-level copies (the subprocess reads
        and may rewrite them in place without ever touching the real parent
        file - copying is the core isolation guarantee, see :func:`_copy_tree`);
        overlay writes are materialised as real files; deletions remove the
        corresponding entry. The directory is cleaned up on context exit
        regardless of how the body returns.

        `parent_root` is taken explicitly rather than read off
        :attr:`_parent` because not every backend has a `root_dir`
        (`StateBackend` does not); the caller decides whether
        snapshotting is meaningful before invoking this.

        When `include_venv=True` and `parent_root / ".venv"` exists, a
        symlink to it is added to the snapshot. `.venv` is normally in
        :data:`_SNAP_SKIP_DIRS` to keep snapshot creation lean, but a test
        runner (`pytest`, `uv run`, etc.) typically needs the virtual
        environment on `PATH` - opting in restores it without copying.
        Off by default so the existing `execute` consumer keeps the
        slim layout.
        """
        with _branch_snapshot(parent_root, self._overlay, self._changes, self._deleted) as tmp:
            if include_venv:
                venv_src = parent_root / ".venv"
                venv_dst = Path(tmp) / ".venv"
                if venv_src.exists() and not venv_dst.exists():
                    venv_dst.symlink_to(venv_src)
            yield tmp

    def delete(self, path: str) -> None:
        """Mark `path` deleted in this branch - propagated on merge.

        After this returns, `exists` / `read` / `read_bytes` for
        `path` behave as if the file is gone, even when `path` lives
        in the parent backend. A `FileChange(op="delete")` is appended
        to :attr:`_changes` so :meth:`flush_to` can replay the deletion
        onto the parent. The parent's bytes are snapshotted on first
        touch so third-actor-delete conflict detection works - subject to
        the first-touch (not fork-time) limitation documented in
        :meth:`_snapshot_parent_on_first_touch`.

        Writing the same path afterwards "un-deletes" it (see :meth:`write`).
        """
        self._snapshot_parent_on_first_touch(path)
        self._deleted.add(path)
        change = FileChange(path=path, op="delete", timestamp=datetime.now(timezone.utc))
        self._changes.append(change)
        self._mirror_to_disk(change)

    def record_mkdir(self, path: str) -> None:
        """Record a directory creation detected by `_propagate_mutations`."""
        change = FileChange(path=path, op="mkdir", timestamp=datetime.now(timezone.utc))
        self._changes.append(change)

    def record_rmdir(self, path: str) -> None:
        """Record a directory deletion detected by `_propagate_mutations`."""
        self._deleted.add(path)
        change = FileChange(path=path, op="rmdir", timestamp=datetime.now(timezone.utc))
        self._changes.append(change)

    def _has(self, path: str) -> bool:
        """Check whether a file lives in THIS overlay (not parent)."""
        return bool(self._overlay.exists(path))

    def exists(self, path: str) -> bool:
        """Public `BackendProtocol` predicate - overlay first, fall through to parent.

        A branch "sees" any file present in either layer, mirroring the
        copy-on-write read semantics: written-by-this-branch files take
        precedence, otherwise the parent backend answers. Paths the
        branch has deleted via :meth:`delete` - or that live inside a
        deleted directory - are hidden regardless of parent presence.
        """
        if self._is_deleted(path):
            return False
        return bool(self._overlay.exists(path) or self._parent.exists(path))

    def read(self, path: str, offset: int = 0, limit: int = 2000) -> str:
        if self._is_deleted(path):
            raise FileNotFoundError(path)
        if self._has(path):
            result: str = self._overlay.read(path, offset, limit)
            return result
        return str(self._parent.read(path, offset, limit))

    def read_bytes(self, path: str) -> bytes:
        if self._is_deleted(path):
            raise FileNotFoundError(path)
        if self._has(path):
            data: bytes = self._overlay.read_bytes(path)
            return data
        parent_data: bytes = _read_backend_bytes(self._parent, path)
        return parent_data

    def _undelete(self, path: str) -> None:
        """Remove `path` and any deleted-parent-directory entry covering it."""
        self._deleted.discard(path)
        self._deleted -= {d for d in self._deleted if path.startswith(d.rstrip("/") + "/")}

    def write(self, path: str, content: str | bytes) -> WriteResult:
        self._undelete(path)
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
        self._undelete(path)
        self._snapshot_parent_on_first_touch(path)
        # If the file lives only in the parent, materialize it into the overlay
        # first so edits don't leak back to the parent.
        if not self._has(path):
            try:
                parent_bytes = _read_backend_bytes(self._parent, path)
            except (FileNotFoundError, KeyError):  # pragma: no cover - defensive
                # File doesn't exist in parent either - let overlay.edit surface
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
        """Merge two `FileInfo` lists keyed by `path` - overlay wins on conflicts."""
        seen: dict[str, FileInfo] = {entry["path"]: entry for entry in parent_entries}
        for entry in overlay_entries:
            seen[entry["path"]] = entry
        return list(seen.values())

    def _is_deleted(self, path: str) -> bool:
        """Check if `path` or any of its parent directories has been deleted."""
        if path in self._deleted:
            return True
        return any(path.startswith(d.rstrip("/") + "/") for d in self._deleted)

    def ls_info(self, path: str) -> list[FileInfo]:
        merged = self._merge_entries(self._parent.ls_info(path), self._overlay.ls_info(path))
        return [e for e in merged if not self._is_deleted(e["path"])]

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        merged = self._merge_entries(
            self._parent.glob_info(pattern, path),
            self._overlay.glob_info(pattern, path),
        )
        return [e for e in merged if not self._is_deleted(e["path"])]

    @property
    def execute_enabled(self) -> bool:  # pragma: no cover - transparent forward to parent
        enabled = getattr(self._parent, "execute_enabled", None)
        return bool(enabled) if enabled is not None else False

    def _run_in_snapshot(self, command: str, timeout: int | None) -> ExecuteResponse:
        """Execute *command* inside an isolated snapshot of the branch state.

        When the parent is a :class:`~pydantic_ai_backends.LocalBackend`
        (i.e. it exposes `root_dir`), a temporary directory is built with:

        - Detached file-level copies of every parent file (see
          :func:`_copy_tree`) - reading works normally and an in-place
          rewrite lands on the copy, leaving the real parent file untouched.
        - Overlay-written files as real files - branch in-progress content
          is visible to the command.
        - Deleted paths removed - absent in the snapshot as in the overlay.

        Absolute references to the parent root in *command* are rewritten
        to the snapshot path so commands like `rm /abs/path/file.py` also
        stay inside the snapshot.

        If the parent has no `root_dir` (e.g. :class:`StateBackend` in
        tests), the call is forwarded as-is - StateBackend doesn't support
        real shell execution anyway.
        """
        parent_root: Path | None = getattr(self._parent, "root_dir", None)

        if parent_root is None:
            return self._parent.execute(command, timeout)  # pyright: ignore[reportAttributeAccessIssue]

        parent_root = Path(parent_root)
        timeout_s = timeout if timeout is not None else _EXEC_DEFAULT_TIMEOUT_S

        with _branch_snapshot(parent_root, self._overlay, self._changes, self._deleted) as snap:
            snap_path = Path(snap)
            pre = _snapshot_state(snap_path)
            cmd = _rewrite_parent_root(command, str(parent_root), snap)
            try:
                try:
                    proc = subprocess.run(
                        ["sh", "-c", cmd],
                        cwd=snap,
                        capture_output=True,
                        text=True,
                        timeout=timeout_s,
                    )
                    output = proc.stdout + proc.stderr
                except subprocess.TimeoutExpired:
                    return ExecuteResponse(
                        output="Error: Command timed out", exit_code=_EXIT_TIMEOUT
                    )
                except Exception as exc:
                    return ExecuteResponse(output=f"Error: {exc}", exit_code=1)
                truncated = len(output) > _EXEC_MAX_CHARS
                if truncated:
                    output = output[:_EXEC_MAX_CHARS]
                return ExecuteResponse(
                    output=output, exit_code=proc.returncode, truncated=truncated
                )
            finally:
                # Mirror any filesystem mutations made before the command
                # returned, crashed, or timed out back into the overlay so a
                # partially-completed command's changes are not lost from
                # changes()/merge.
                post = _snapshot_state(snap_path)
                _propagate_mutations(snap_path, parent_root, pre, post, self)

    def execute(self, command: str, timeout: int | None = None) -> ExecuteResponse:
        return self._run_in_snapshot(command, timeout)

    async def async_execute(self, command: str, timeout: int | None = None) -> ExecuteResponse:
        return await asyncio.to_thread(self._run_in_snapshot, command, timeout)

    def grep_raw(
        self,
        pattern: str,
        path: str | None = None,
        **kwargs: Any,
    ) -> list[GrepMatch] | str:
        # Forward to parent. Overlay grep (cross-branch grep in diff_branches)
        # is not yet implemented - punt for now.
        result: list[GrepMatch] | str = self._parent.grep_raw(pattern, path, **kwargs)
        return result

    def attach_materializer(self, materializer: ForkMaterializer, branch_label: str) -> None:
        """Wire a :class:`ForkMaterializer` into this overlay.

        After this call every successful `write` / `edit` is mirrored
        to disk under the materializer's `branches/{branch_label}/`
        subtree, and the parent backend's bytes for each touched path are
        captured lazily on first touch via
        :meth:`ForkMaterializer.snapshot_parent_path`. Note this is a
        first-touch snapshot, not a fork-time one - see the limitation in
        :meth:`_snapshot_parent_on_first_touch` for the conflict-detection
        gap when a third actor writes a path before this branch touches it.
        """
        self._materializer = materializer
        self._branch_label = branch_label

    def _snapshot_parent_on_first_touch(self, path: str) -> None:
        """Capture the parent's bytes for `path` the first time it's touched.

        No-op when no materializer is attached. The materializer itself
        de-dupes repeat calls for the same path, so this is safe to call
        from both `write` and `edit`.

        Limitation - this captures the parent's bytes as of *first touch*,
        not strictly fork time. The two coincide only while nothing else
        writes `path` in between. If a third actor (e.g. the outer branch
        in a fork-of-fork, or a concurrently-running parent) modifies
        `path` after the fork but before this branch first touches it,
        the captured bytes are the third actor's, not the fork-time bytes.
        :meth:`flush_to` then compares the current parent against that
        already-diverged snapshot, finds them equal, and does NOT flag a
        conflict - so this branch silently overwrites the third actor's
        change. Closing this gap would require an eager full-parent
        snapshot at fork time, which is deliberately avoided for cost
        (see :class:`~pydantic_deep.toolsets.forking.materializer.ForkMaterializer`).
        """
        materializer = self._materializer
        if materializer is None:
            return
        try:
            parent_bytes: bytes | None = _read_backend_bytes(self._parent, path)
        except (FileNotFoundError, KeyError):
            parent_bytes = None
        materializer.snapshot_parent_path(path, parent_bytes)

    def _mirror_to_disk(self, change: FileChange) -> None:
        """Mirror one `FileChange` to the on-disk branch directory."""
        materializer = self._materializer
        branch_label = self._branch_label
        if materializer is None or branch_label is None:
            return
        if change.op in ("mkdir", "rmdir"):  # pragma: no cover - no disk mirror for dirs
            return
        if change.op == "delete":
            try:
                materializer.flush_delete(branch_label, change)
            except OSError:
                logger.warning(
                    "materializer flush_delete failed for branch %s path %s",
                    branch_label,
                    change.path,
                    exc_info=True,
                )
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

    def flush_to(  # noqa: C901
        self,
        parent: BackendProtocol,
        pre_flush_snapshot: dict[str, bytes | None] | None = None,
    ) -> FlushReport:
        """Replay this overlay's writes onto `parent`.

        Args:
            parent: Destination backend. Usually the parent run's backend;
                for fork-of-fork it is the OUTER branch's overlay (which
                is itself a :class:`BranchOverlay`) - propagation up one
                level works without special casing.
            pre_flush_snapshot: Optional mapping of `path → parent bytes
                snapshotted when this branch first touched the path` (or
                `None` for "did not exist"). When supplied, `flush_to`
                compares each touched path's current parent bytes against
                the snapshot and records a conflict for divergent paths.
                Both modified-by-third-actor and deleted-by-third-actor
                cases land in `conflicts` - *except* the case where the
                third actor wrote the path between the fork and this
                branch's first touch, since the snapshot already captured
                the third actor's bytes (see the limitation in
                :meth:`_snapshot_parent_on_first_touch`).

        Returns:
            A :class:`FlushReport` with `applied_paths` (one entry per
            successfully-replayed path, last-write-wins), `applied_changes`
            (every replayed op - ≥ `len(applied_paths)`), `conflicts`
            (divergent paths - these are NOT replayed so the newer parent
            content is preserved), and `errors` (per-write failures -
            `flush_to` never aborts on the first failure).

        Order: writes are replayed in :attr:`_changes` order (temporal),
        so a sequence `write A → edit A → write B` results in
        `parent` reflecting the final overlay state for both A and B.
        """
        applied_paths: list[str] = []
        applied_set: set[str] = set()
        deleted_paths: list[str] = []
        deleted_set: set[str] = set()
        errors: list[FlushError] = []
        conflicts: list[str] = self._detect_conflicts(parent, pre_flush_snapshot)
        conflict_set: set[str] = set(conflicts)
        applied_changes = 0

        for change in self._changes:
            # Skip paths a third actor changed since the fork - replaying would clobber
            # the newer parent content. They stay in `conflicts` for manual resolution.
            if change.path in conflict_set:
                continue
            if change.op == "delete":
                if change.path in applied_set:
                    applied_set.discard(change.path)
                    applied_paths = [p for p in applied_paths if p != change.path]
                if self._flush_delete(parent, change, errors, deleted_paths, deleted_set):
                    applied_changes += 1
                continue
            if change.op == "mkdir":
                if self._flush_mkdir(parent, change, errors):
                    applied_changes += 1
                    if change.path not in applied_set:  # pragma: no branch
                        applied_set.add(change.path)
                        applied_paths.append(change.path)
                continue
            if change.op == "rmdir":
                if self._flush_rmdir(parent, change, errors, deleted_paths, deleted_set):
                    applied_changes += 1
                continue
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
            # A write resurrects a path the branch deleted earlier.
            if change.path in deleted_set:
                deleted_set.discard(change.path)
                deleted_paths = [p for p in deleted_paths if p != change.path]

        return FlushReport(
            applied_paths=applied_paths,
            applied_changes=applied_changes,
            conflicts=conflicts,
            errors=errors,
            deleted_paths=deleted_paths,
        )

    @staticmethod
    def _flush_delete(
        parent: BackendProtocol,
        change: FileChange,
        errors: list[FlushError],
        deleted_paths: list[str],
        deleted_set: set[str],
    ) -> bool:
        """Replay one delete op onto `parent`; return `True` on success.

        Three propagation routes, in priority order:
        - `parent.execute_enabled` truthy → issue `rm -f <shlex-quoted>`;
        - `hasattr(parent, "delete")` (e.g. a nested :class:`BranchOverlay`
          in a fork-of-fork) → call the method directly;
        - else (e.g. a plain :class:`StateBackend` in tests) → record a
          :class:`FlushError` so the user-visible `deleted` count stays
          truthful instead of silently lying.
        """
        try:
            if getattr(parent, "execute_enabled", False):
                response = parent.execute(  # pyright: ignore[reportAttributeAccessIssue]
                    f"rm -f {shlex.quote(change.path)}"
                )
                # `rm -f` still reports non-zero on permission/EBUSY/EROFS.
                exit_code = getattr(response, "exit_code", 0)
                if exit_code:
                    errors.append(
                        FlushError(
                            path=change.path,
                            op="delete",
                            message=(
                                f"rm exited {exit_code}: {getattr(response, 'output', '').strip()}"
                            ),
                        )
                    )
                    return False
            elif hasattr(parent, "delete"):
                parent.delete(change.path)  # pyright: ignore[reportAttributeAccessIssue]
            else:
                errors.append(
                    FlushError(
                        path=change.path,
                        op="delete",
                        message="parent backend does not support delete",
                    )
                )
                return False
        except Exception as exc:
            errors.append(FlushError(path=change.path, op="delete", message=str(exc)))
            return False
        if change.path not in deleted_set:
            deleted_set.add(change.path)
            deleted_paths.append(change.path)
        return True

    @staticmethod
    def _flush_mkdir(
        parent: BackendProtocol,
        change: FileChange,
        errors: list[FlushError],
    ) -> bool:
        """Replay a `mkdir` op onto `parent`; return `True` on success."""
        try:
            if getattr(parent, "execute_enabled", False):
                response = parent.execute(  # pyright: ignore[reportAttributeAccessIssue]
                    f"mkdir -p {shlex.quote(change.path)}"
                )
                exit_code = getattr(response, "exit_code", 0)
                if exit_code:
                    errors.append(
                        FlushError(
                            path=change.path,
                            op="mkdir",
                            message=f"mkdir exited {exit_code}",
                        )
                    )
                    return False
            else:
                errors.append(
                    FlushError(
                        path=change.path,
                        op="mkdir",
                        message="parent backend does not support execute",
                    )
                )
                return False
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(FlushError(path=change.path, op="mkdir", message=str(exc)))
            return False
        return True

    @staticmethod
    def _flush_rmdir(
        parent: BackendProtocol,
        change: FileChange,
        errors: list[FlushError],
        deleted_paths: list[str],
        deleted_set: set[str],
    ) -> bool:
        """Replay an `rmdir` op onto `parent`; return `True` on success."""
        try:
            if getattr(parent, "execute_enabled", False):
                response = parent.execute(  # pyright: ignore[reportAttributeAccessIssue]
                    f"rm -rf {shlex.quote(change.path)}"
                )
                exit_code = getattr(response, "exit_code", 0)
                if exit_code:
                    errors.append(
                        FlushError(
                            path=change.path,
                            op="rmdir",
                            message=f"rm -rf exited {exit_code}",
                        )
                    )
                    return False
            else:
                errors.append(
                    FlushError(
                        path=change.path,
                        op="rmdir",
                        message="parent backend does not support execute",
                    )
                )
                return False
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(FlushError(path=change.path, op="rmdir", message=str(exc)))
            return False
        if change.path not in deleted_set:  # pragma: no branch
            deleted_set.add(change.path)
            deleted_paths.append(change.path)
        return True

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
                current_bytes: bytes | None = _read_backend_bytes(parent, path)
            except (FileNotFoundError, KeyError):
                current_bytes = None
            if current_bytes != snapshot_bytes:
                conflicts.append(path)
        return sorted(conflicts)


def clone_for_branch(deps: DeepAgentDeps, isolation: BranchIsolation) -> DeepAgentDeps:
    """Clone `DeepAgentDeps` for a branch according to `isolation`.

    See :class:`BranchIsolation` for per-flag semantics. Memory isolation
    follows the backend (memory lives at
    `{memory_dir}/{agent_name}/MEMORY.md` inside the backend); the
    `memory` flag is recorded for forward-compat but has no separate
    effect here. `team_bus` is a no-op when the teams capability is not
    enabled on the parent run; when enabled it propagates the parent bus
    reference by default.
    """

    from pydantic_deep.deps import unwrap_backend

    # Unwrap async adapter — BranchOverlay operates synchronously on the
    # raw sync backend; the adapter is only needed for async callers.
    raw_backend: Any = unwrap_backend(deps.backend)

    new_backend: Any = BranchOverlay(raw_backend) if isolation.backend == "copy" else deps.backend

    # "copy" → independent copy so branch todo edits stay local; "share" → same list.
    new_todos = list(deps.todos) if isolation.todos == "copy" else deps.todos

    new_message_queue: MessageQueue | None
    if isolation.message_queue == "isolated":
        new_message_queue = MessageQueue()
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
