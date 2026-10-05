"""Per-branch isolation - :class:`BranchOverlay` and :func:`branch_workspace`.

A branch works in its own view of the parent's workspace. :class:`BranchOverlay`
is a Pydantic AI workspace backend layered over the parent run's
:class:`~pydantic_ai.workspaces.Workspace`: a branch's writes land in an
isolated layer while reads of untouched paths fall through to the parent. Every
write is recorded in :attr:`BranchOverlay._changes` - the temporally-ordered list
returned by :meth:`BranchOverlay.changes`, which is the data spine consumed by
the diff builder, disk materializer, and judge.

A branch over a :class:`~pydantic_ai.workspaces.LocalWorkspaceBackend` can also
run commands: :class:`LocalBranchOverlay` runs each one in a throwaway copy of
the parent directory with the branch's changes applied, and records what the
command changed. A branch over any other workspace works on files only, since
running a command in the parent's environment would change the parent.

:func:`clone_for_branch` produces a fresh :class:`DeepAgentDeps` for a branch,
and :func:`branch_workspace` the workspace it runs in, from a
:class:`BranchIsolation` policy.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import os
import posixpath
import re
import shutil
import tempfile
from collections.abc import Generator, Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic_ai.workspaces import (
    CommandResult,
    FileEntry,
    LocalWorkspaceBackend,
    ReadOnlyWorkspace,
    Workspace,
    WorkspaceCommand,
    WorkspaceRef,
)
from pydantic_ai_backends import StateBackend

from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.features.forking.types import (
    BranchIsolation,
    FileChange,
    FileChangeOp,
    FlushError,
    FlushReport,
)
from pydantic_deep.features.message_queue import MessageQueue

if TYPE_CHECKING:
    from pydantic_deep.features.forking.materializer import ForkMaterializer


logger = logging.getLogger(__name__)

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


def _populate_snapshot(
    parent_root: Path,
    overlay: StateBackend,
    changes: list[FileChange],
    deleted: set[str],
    tmp: Path,
) -> None:
    """Fill *tmp* with the branch's view of *parent_root*.

    - Parent files → detached file copies (reading works; in-place writes land
      on the copy, never the real parent file).
    - Overlay writes and directories → real files and directories, so the
      branch's in-progress content is visible to the command.
    - Removed paths → absent.
    """
    _copy_tree(parent_root, tmp)

    for change in changes:
        if change.op != "mkdir" or change.path in deleted:
            continue
        (tmp / _rel_under(parent_root, change.path)).mkdir(parents=True, exist_ok=True)

    # Overlay writes (last write wins) override the copied parent files.
    for path in {c.path for c in changes if c.op == "write"} - deleted:
        if not overlay.is_file(path):
            continue
        dst = tmp / _rel_under(parent_root, path)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        dst.write_bytes(overlay.read_bytes(path))

    for path in deleted:
        dst = tmp / _rel_under(parent_root, path)
        if dst.is_dir() and not dst.is_symlink():
            shutil.rmtree(dst)
        elif dst.is_symlink() or dst.exists():
            dst.unlink()


@contextlib.contextmanager
def _branch_snapshot(
    parent_root: Path,
    overlay: StateBackend,
    changes: list[FileChange],
    deleted: set[str],
) -> Generator[str, None, None]:
    """Yield a temp directory holding the branch's view, deleted on exit."""
    with tempfile.TemporaryDirectory(prefix="branch-snap-") as tmp_dir:
        _populate_snapshot(parent_root, overlay, changes, deleted, Path(tmp_dir))
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


async def _propagate_mutations(
    snap: Path,
    parent_root: Path,
    pre: dict[str, tuple[bool, str]],
    post: dict[str, tuple[bool, str]],
    overlay: BranchOverlay,
) -> None:
    """Diff *pre* vs *post* snapshot states and mirror changes into *overlay*.

    - **Deleted** (existed before, absent after): recorded as a delete, so the
      deletion propagates to the parent on merge.
    - **Created** (absent before, exists after) and **modified** (content
      signature changed, or a symlink replaced by a file): recorded as a write.

    Detection is by content signature, not mtime, so a write that preserves
    mtime is still caught. A file that cannot be captured is logged rather
    than dropped silently, since the overlay would otherwise disagree with
    what the command did.
    """
    for rel in sorted(set(pre) | set(post)):
        in_pre = rel in pre
        in_post = rel in post
        if rel.endswith("/"):
            dir_path = str(parent_root / rel.rstrip("/"))
            if not in_pre and in_post:
                await overlay.make_dir(dir_path)
            elif in_pre and not in_post:
                overlay._record_removal(dir_path, op="rmdir")
            continue

        abs_path = str(parent_root / rel)
        if in_pre and not in_post:
            overlay._record_removal(abs_path, op="delete")
            continue
        if in_pre and in_post:
            pre_sym, pre_sig = pre[rel]
            post_sym, post_sig = post[rel]
            if not ((pre_sym and not post_sym) or pre_sig != post_sig):
                continue
        try:
            data = (snap / rel).read_bytes()
        except OSError as exc:
            logger.warning("branch snapshot: failed to capture %s (%s)", abs_path, exc)
            continue
        await overlay.write_bytes(abs_path, data)


def _entry(path: str, *, is_dir: bool, size: int | None) -> FileEntry:
    return FileEntry(name=posixpath.basename(path), path=path, is_dir=is_dir, size=size)


class BranchOverlay:
    """Copy-on-write workspace backend for a single branch.

    Reads consult the overlay first and fall through to the parent workspace
    for paths this branch has not written. Writes, directories and removals
    go to the overlay only and are logged to `_changes` for downstream
    consumers (diff builder, materializer, judge); :meth:`flush_to` replays
    them onto a workspace on merge.

    Files only: see :class:`LocalBranchOverlay` for a branch that runs commands.

    Args:
        parent: The workspace the branch was forked from.
    """

    def __init__(self, parent: Workspace) -> None:
        self._parent = parent
        self._overlay = StateBackend()
        self._changes: list[FileChange] = []
        self._deleted: set[str] = set()
        self._materializer: ForkMaterializer | None = None
        self._branch_label: str | None = None

    @property
    def parent(self) -> Workspace:
        return self._parent

    @property
    def ref(self) -> WorkspaceRef | None:
        """None: a branch's view is not an environment of its own to come back to."""
        return None

    async def working_dir(self) -> str:
        return await self._parent.working_dir()

    def changes(self) -> list[FileChange]:
        """Return the temporal-ordered list of changes recorded in this overlay."""
        return list(self._changes)

    def deleted(self) -> set[str]:
        """Paths the branch has removed.

        Returns a copy so callers can't mutate the overlay's internal
        tombstone set. Mirrors :meth:`changes` - same convention.
        """
        return set(self._deleted)

    def overlay_bytes(self, path: str) -> bytes:
        """What this branch wrote at `path`, for the diff builder and materializer."""
        # Annotated: pydantic-ai-backend ships no py.typed, so mypy reads it as Any.
        data: bytes = self._overlay.read_bytes(path)
        return data

    # -- reads -------------------------------------------------------------

    def _is_deleted(self, path: str) -> bool:
        """Check if `path` or any of its parent directories has been removed."""
        if path in self._deleted:
            return True
        return any(path.startswith(d.rstrip("/") + "/") for d in self._deleted)

    async def exists(self, path: str) -> bool:
        if self._is_deleted(path):
            return False
        return self._overlay.exists(path) or await self._parent.exists(path)

    async def read_bytes(self, path: str) -> bytes:
        if self._is_deleted(path):
            raise FileNotFoundError(path)
        if self._overlay.is_file(path):
            return self.overlay_bytes(path)
        return await self._parent.read_bytes(path)

    async def stat(self, path: str) -> FileEntry:
        if self._is_deleted(path):
            raise FileNotFoundError(path)
        if self._overlay.is_file(path):
            return _entry(path, is_dir=False, size=self._overlay.size(path))
        if self._overlay.is_dir(path) and path != "/":
            return _entry(path, is_dir=True, size=None)
        return await self._parent.stat(path)

    async def list_dir(self, path: str) -> Sequence[FileEntry]:
        if self._is_deleted(path):
            raise FileNotFoundError(path)
        merged: dict[str, FileEntry] = {}
        try:
            merged = {entry.path: entry for entry in await self._parent.list_dir(path)}
        except FileNotFoundError:
            if not self._overlay.is_dir(path):
                raise
        if self._overlay.is_dir(path):
            for name, is_dir in self._overlay.list_dir(path):
                child = posixpath.join(path, name)
                size = None if is_dir else self._overlay.size(child)
                merged[child] = _entry(child, is_dir=is_dir, size=size)
        return [entry for entry in merged.values() if not self._is_deleted(entry.path)]

    # -- writes ------------------------------------------------------------

    def _undelete(self, path: str) -> None:
        """Remove `path` and any deleted-parent-directory entry covering it."""
        self._deleted.discard(path)
        self._deleted -= {d for d in self._deleted if path.startswith(d.rstrip("/") + "/")}

    def _record(self, path: str, op: FileChangeOp) -> None:
        change = FileChange(path=path, op=op, timestamp=datetime.now(timezone.utc))
        self._changes.append(change)
        self._mirror_to_disk(change)

    async def write_bytes(self, path: str, data: bytes) -> None:
        if self._overlay.is_dir(path) or (
            await self.exists(path) and (await self.stat(path)).is_dir
        ):
            raise IsADirectoryError(path)
        self._undelete(path)
        await self._snapshot_parent_on_first_touch(path)
        self._overlay.write_bytes(path, data)
        self._record(path, "write")

    async def make_dir(self, path: str) -> None:
        self._undelete(path)
        if await self.exists(path):
            if (await self.stat(path)).is_dir:
                return
            raise FileExistsError(path)
        self._overlay.make_dir(path)
        self._record(path, "mkdir")

    async def remove(self, path: str) -> None:
        if not await self.exists(path):
            raise FileNotFoundError(path)
        is_dir = (await self.stat(path)).is_dir
        await self._snapshot_parent_on_first_touch(path)
        self._record_removal(path, op="rmdir" if is_dir else "delete")

    def _record_removal(self, path: str, *, op: Literal["delete", "rmdir"]) -> None:
        """Hide `path` in this branch and record it for :meth:`flush_to`."""
        if self._overlay.exists(path):
            self._overlay.remove(path)
        self._deleted.add(path)
        self._record(path, op)

    # -- materializer ------------------------------------------------------

    def attach_materializer(self, materializer: ForkMaterializer, branch_label: str) -> None:
        """Wire a :class:`ForkMaterializer` into this overlay.

        After this call every successful write is mirrored to disk under the
        materializer's `branches/{branch_label}/` subtree, and the parent's
        bytes for each touched path are captured lazily on first touch via
        :meth:`ForkMaterializer.snapshot_parent_path`. Note this is a
        first-touch snapshot, not a fork-time one - see the limitation in
        :meth:`_snapshot_parent_on_first_touch` for the conflict-detection
        gap when a third actor writes a path before this branch touches it.
        """
        self._materializer = materializer
        self._branch_label = branch_label

    async def _snapshot_parent_on_first_touch(self, path: str) -> None:
        """Capture the parent's bytes for `path` the first time it's touched.

        No-op when no materializer is attached. The materializer itself
        de-dupes repeat calls for the same path.

        Limitation - this captures the parent's bytes as of *first touch*,
        not strictly fork time. If a third actor (e.g. the outer branch in a
        fork-of-fork, or a concurrently-running parent) modifies `path` after
        the fork but before this branch first touches it, the captured bytes
        are the third actor's, so :meth:`flush_to` finds them equal and does
        NOT flag a conflict - this branch silently overwrites the third
        actor's change. Closing the gap would need an eager full-parent
        snapshot at fork time, deliberately avoided for cost.
        """
        materializer = self._materializer
        if materializer is None:
            return
        try:
            parent_bytes: bytes | None = await self._parent.read_bytes(path)
        except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
            parent_bytes = None
        materializer.snapshot_parent_path(path, parent_bytes)

    def _mirror_to_disk(self, change: FileChange) -> None:
        """Mirror one `FileChange` to the on-disk branch directory."""
        materializer = self._materializer
        branch_label = self._branch_label
        if materializer is None or branch_label is None:
            return
        if change.op in ("mkdir", "rmdir"):
            return
        try:
            if change.op == "delete":
                materializer.flush_delete(branch_label, change)
            else:
                materializer.flush_change(
                    branch_label, change, self._overlay.read_bytes(change.path)
                )
        except OSError:
            logger.warning(
                "materializer mirror failed for branch %s path %s",
                branch_label,
                change.path,
                exc_info=True,
            )

    # -- merge -------------------------------------------------------------

    async def flush_to(
        self,
        parent: Workspace,
        pre_flush_snapshot: dict[str, bytes | None] | None = None,
    ) -> FlushReport:
        """Replay this overlay's changes onto `parent`.

        Args:
            parent: Destination workspace. Usually the parent run's; for a
                fork-of-fork it is the OUTER branch's workspace, an overlay
                itself, so propagation up one level needs no special casing.
            pre_flush_snapshot: Optional mapping of `path → parent bytes
                snapshotted when this branch first touched the path` (or
                `None` for "did not exist"). When supplied, each touched
                path's current parent bytes are compared against it and a
                divergent path is recorded as a conflict and not replayed, so
                the newer parent content is preserved - *except* when the
                third actor wrote it before this branch's first touch (see
                :meth:`_snapshot_parent_on_first_touch`).

        Returns:
            A :class:`FlushReport` with `applied_paths` (one entry per
            successfully-replayed path, last-write-wins), `applied_changes`
            (every replayed op), `conflicts`, `errors` (per-change failures -
            the flush never aborts on the first one) and `deleted_paths`.

        Changes are replayed in :attr:`_changes` order (temporal), so
        `write A → write A → write B` leaves `parent` with the final content
        of both A and B.
        """
        applied_paths: list[str] = []
        deleted_paths: list[str] = []
        errors: list[FlushError] = []
        conflicts = await self._detect_conflicts(parent, pre_flush_snapshot)
        conflict_set = set(conflicts)
        applied_changes = 0

        for change in self._changes:
            # A path a third actor changed since the fork stays in `conflicts`
            # for manual resolution; replaying it would clobber the newer content.
            if change.path in conflict_set:
                continue
            try:
                if change.op in ("delete", "rmdir"):
                    with contextlib.suppress(FileNotFoundError):
                        await parent.remove(change.path)
                elif change.op == "mkdir":
                    await parent.make_dir(change.path)
                else:
                    await parent.write_bytes(change.path, self._overlay.read_bytes(change.path))
            except Exception as exc:
                errors.append(FlushError(path=change.path, op=change.op, message=str(exc)))
                if change.path in applied_paths:
                    applied_paths.remove(change.path)
                continue
            applied_changes += 1
            if change.op in ("delete", "rmdir"):
                if change.path in applied_paths:
                    applied_paths.remove(change.path)
                if change.path not in deleted_paths:
                    deleted_paths.append(change.path)
            else:
                if change.path not in applied_paths:
                    applied_paths.append(change.path)
                # A write resurrects a path the branch removed earlier.
                if change.path in deleted_paths:
                    deleted_paths.remove(change.path)

        return FlushReport(
            applied_paths=applied_paths,
            applied_changes=applied_changes,
            conflicts=conflicts,
            errors=errors,
            deleted_paths=deleted_paths,
        )

    async def _detect_conflicts(
        self,
        parent: Workspace,
        pre_flush_snapshot: dict[str, bytes | None] | None,
    ) -> list[str]:
        """Touched paths whose parent content differs from the snapshot, sorted.

        Covers both modified-by-third-actor and deleted-by-third-actor.
        """
        if pre_flush_snapshot is None:
            return []
        conflicts: list[str] = []
        for path in {c.path for c in self._changes}:
            if path not in pre_flush_snapshot:
                continue
            try:
                current: bytes | None = await parent.read_bytes(path)
            except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
                current = None
            if current != pre_flush_snapshot[path]:
                conflicts.append(path)
        return sorted(conflicts)


class LocalBranchOverlay(BranchOverlay):
    """A branch over a local directory: files, and commands run in a copy of it.

    Each command runs in a temporary directory holding detached copies of the
    parent's files with this branch's changes applied (see :func:`_copy_tree`),
    so an in-place write lands on the copy and never on a parent file. What the
    command changed is recorded in the overlay afterwards, including when it
    fails or times out.

    Args:
        parent: The workspace the branch was forked from; its backend is a
            :class:`~pydantic_ai.workspaces.LocalWorkspaceBackend`.
    """

    @contextlib.contextmanager
    def snapshot(
        self,
        parent_root: Path,
        *,
        include_venv: bool = False,
    ) -> Generator[str, None, None]:
        """Yield a tempdir presenting this branch's view of `parent_root`.

        When `include_venv=True` and `parent_root / ".venv"` exists, a symlink
        to it is added: `.venv` is normally skipped to keep the copy lean, but
        a test runner (`pytest`, `uv run`) needs it on `PATH`.
        """
        with _branch_snapshot(parent_root, self._overlay, self._changes, self._deleted) as tmp:
            if include_venv:
                venv_src = parent_root / ".venv"
                venv_dst = Path(tmp) / ".venv"
                if venv_src.exists() and not venv_dst.exists():
                    venv_dst.symlink_to(venv_src)
            yield tmp

    async def run(
        self,
        command: WorkspaceCommand,
        *,
        shell: bool = False,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> CommandResult:
        """Run `command` in a copy of the branch, then record what it changed.

        Absolute references to the parent directory are rewritten to the copy,
        so `rm /abs/path/file.py` stays inside it too.
        """
        parent_root = Path(await self._parent.working_dir())
        with tempfile.TemporaryDirectory(prefix="branch-snap-") as tmp:
            await asyncio.to_thread(
                _populate_snapshot,
                parent_root,
                self._overlay,
                self._changes,
                self._deleted,
                Path(tmp),
            )
            local = LocalWorkspaceBackend(tmp)
            snap = Path(await local.working_dir())
            pre = await asyncio.to_thread(_snapshot_state, snap)
            if isinstance(command, str):
                rewritten: WorkspaceCommand = _rewrite_parent_root(
                    command, str(parent_root), str(snap)
                )
            else:
                rewritten = [
                    _rewrite_parent_root(arg, str(parent_root), str(snap)) for arg in command
                ]
            try:
                return await local.run(rewritten, shell=shell, env=env, timeout=timeout)
            finally:
                # Mirror what the command changed before it returned, failed or
                # timed out, so a partly-completed command is not lost on merge.
                post = await asyncio.to_thread(_snapshot_state, snap)
                await _propagate_mutations(snap, parent_root, pre, post, self)


def local_root(workspace: Workspace) -> Path | None:
    """The directory a workspace works in when it is a local one, else `None`.

    Wrappers such as `ReadOnlyWorkspace` are looked through: they restrict the
    API, not where the files are.
    """
    backend: object = workspace
    while isinstance(backend, Workspace):
        backend = backend.backend
    if isinstance(backend, LocalWorkspaceBackend):
        return Path(backend._working_dir)  # pyright: ignore[reportPrivateUsage]
    return None


def branch_overlay(parent: Workspace) -> BranchOverlay:
    """An overlay for a branch of `parent`: one that runs commands when `parent` is local."""
    if local_root(parent) is not None:
        return LocalBranchOverlay(parent)
    return BranchOverlay(parent)


def branch_workspace(
    parent: Workspace, isolation: BranchIsolation
) -> tuple[Workspace, BranchOverlay | None]:
    """The workspace a branch runs in, and its overlay when it has one.

    `"copy"` gives the branch an overlay of its own; `"share_readonly"` the
    parent's workspace behind `ReadOnlyWorkspace`; `"share"` the parent's.
    """
    if isolation.workspace == "copy":
        overlay = branch_overlay(parent)
        return Workspace(overlay), overlay
    if isolation.workspace == "share_readonly":
        return ReadOnlyWorkspace(parent), None
    return parent, None


def clone_for_branch(deps: DeepAgentDeps, isolation: BranchIsolation) -> DeepAgentDeps:
    """Clone `DeepAgentDeps` for a branch according to `isolation`.

    See :class:`BranchIsolation` for per-flag semantics. Files and memory are
    not part of deps: they live in the workspace :func:`branch_workspace`
    gives the branch. `team_bus` is a no-op when the teams capability is not
    enabled on the parent run; when enabled it propagates the parent bus
    reference by default.
    """
    # "copy" → independent copy so branch todo edits stay local; "share" → same list.
    new_todos = list(deps.todos) if isolation.todos == "copy" else deps.todos

    new_message_queue: MessageQueue | None
    if isolation.message_queue == "isolated":
        new_message_queue = MessageQueue()
    else:
        new_message_queue = deps.message_queue

    return replace(
        deps,
        todos=new_todos,
        subagents={},
        message_queue=new_message_queue,
        fork_coordinator=None,
        _fork_depth=deps._fork_depth + 1,
    )


__all__ = [
    "BranchOverlay",
    "LocalBranchOverlay",
    "branch_overlay",
    "branch_workspace",
    "clone_for_branch",
    "local_root",
]
