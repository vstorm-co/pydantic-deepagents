"""Disk materializer for Live Run Forking.

Every successful :meth:`BranchOverlay.write` / :meth:`BranchOverlay.edit` is
mirrored to disk under `.pydantic-deep/forks/{fork_id}/branches/{label}/`
in real time, while the parent backend's state is captured under
`.pydantic-deep/forks/{fork_id}/parent/` (per-path, lazily, on the first
overlay write for that path). The on-disk artefacts are the input to the
PyCharm / VS Code diff tools wired in :mod:`pydantic_deep.toolsets.forking.editor`
and to the `flush_to` conflict detection (the
:meth:`pre_flush_snapshot` accessor exposes the snapshotted parent bytes
to :meth:`BranchOverlay.flush_to`).

The snapshot is taken at *first touch*, not strictly at fork time: the two
diverge if a third actor writes a path between the fork and a branch's first
touch of it, in which case that path's conflict goes undetected. This is an
accepted trade-off - an eager full-parent snapshot at fork time would have to
walk and read every parent file up front, which the lazy scheme avoids. See
:meth:`snapshot_parent_path` and
:meth:`~pydantic_deep.toolsets.forking.isolation.BranchOverlay._snapshot_parent_on_first_touch`.

Per project memory: the branch directory is named with `branch.label`
(e.g. `approach_a`), not the UUID `branch.id` - keeps the layout
human-navigable.

The materializer is intentionally synchronous on the write hot path
because the in-memory `StateBackend` parent + `LocalBackend` for real
runs both keep file IO sub-millisecond for typical agent writes. If this
becomes a bottleneck later, the call sites can move to an
`asyncio.create_task` background flush.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic_deep.features.forking.types import BranchStatus, FileChange


@dataclass
class ForkMaterializer:
    """Real-time disk mirror for one fork's overlays.

    Args:
        root: Base directory - typically `.pydantic-deep/forks/{fork_id}`.
        fork_id: The fork identifier; surfaced in the manifest.
        keep_artifacts: When `True`, :meth:`cleanup` is a no-op so the
            disk layout survives the merge for post-hoc inspection.

    The :attr:`root` directory is created on construction along with its
    `parent/` and `branches/` subdirectories. The manifest is written
    eagerly with the initial branch list (whatever the caller passes to
    :meth:`update_manifest` after construction) so the layout is
    discoverable even before any writes happen.
    """

    root: Path
    fork_id: str
    keep_artifacts: bool = False
    _pre_fork_snapshot: dict[str, bytes | None] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "parent").mkdir(exist_ok=True)
        (self.root / "branches").mkdir(exist_ok=True)
        if not self.manifest_path().exists():
            self._write_manifest({"fork_id": self.fork_id, "branches": []})

    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    def parent_path(self, path: str) -> Path:
        """Return on-disk location of the parent snapshot for `path`."""
        return self.root / "parent" / _safe_relative(path)

    def branch_path(self, branch_label: str, path: str) -> Path:
        """Return on-disk location of a branch's materialised `path`."""
        return self.root / "branches" / branch_label / _safe_relative(path)

    def snapshot_parent_path(self, path: str, content: bytes | None) -> None:
        """Capture the parent backend's content for `path` at first touch.

        Called lazily on the *first* overlay write for a path so we don't
        eagerly walk the parent backend at fork time (we don't know which
        paths will be touched until the branch agent writes them).
        `content` is `None` when the path didn't exist in the parent
        at first touch - recorded as a sentinel so the deletion-by-third-actor
        conflict path is detectable later.

        Caveat: because the capture happens at first touch rather than at
        fork time, a path written by a third actor *between* the fork and
        this branch's first touch is snapshotted with the third actor's
        bytes, so :meth:`BranchOverlay.flush_to` cannot flag it as a
        conflict. See
        :meth:`~pydantic_deep.toolsets.forking.isolation.BranchOverlay._snapshot_parent_on_first_touch`.
        """
        if path in self._pre_fork_snapshot:
            return
        self._pre_fork_snapshot[path] = content
        if content is not None:
            target = self.parent_path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            target.chmod(0o444)

    def pre_flush_snapshot(self) -> dict[str, bytes | None]:
        """Return the pre-fork parent snapshot consumed by `flush_to`."""
        return dict(self._pre_fork_snapshot)

    def flush_change(self, branch_label: str, change: FileChange, content: bytes) -> None:
        """Mirror one overlay change to disk under `branches/{label}/`."""
        target = self.branch_path(branch_label, change.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.chmod(0o644)
        target.write_bytes(content)
        target.chmod(0o444)

    def flush_delete(self, branch_label: str, change: FileChange) -> None:
        """Remove the on-disk mirror for a deleted path.

        Mirrors the branch's end-state so external diff tools comparing
        `parent/<path>` against `branches/{label}/<path>` see "file
        removed in branch". A no-op when the path was never materialised
        in this branch.
        """
        target = self.branch_path(branch_label, change.path)
        if target.exists():
            target.chmod(0o644)
            target.unlink()

    def update_manifest(self, statuses: list[BranchStatus]) -> None:
        """Refresh `manifest.json` with the latest per-branch status."""
        payload: dict[str, object] = {
            "fork_id": self.fork_id,
            "branches": [
                {
                    "id": s.id,
                    "label": s.label,
                    "state": s.state,
                    "current_turn": s.current_turn,
                    "error": s.error,
                }
                for s in statuses
            ],
        }
        self._write_manifest(payload)

    def cleanup(self) -> None:
        """Remove the fork directory unless `keep_artifacts` is set."""
        if self.keep_artifacts:
            return
        if self.root.exists():
            shutil.rmtree(self.root, ignore_errors=True)

    def _write_manifest(self, payload: dict[str, object]) -> None:
        self.manifest_path().write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _safe_relative(path: str) -> Path:
    """Return `path` as a :class:`Path` confined under the materializer dirs.

    Strips a leading `/` so absolute-style paths (`/src/foo.py`) land
    under the materializer root instead of escaping to the filesystem root, and
    drops any `..` / `.` components so a crafted path (`../../etc/cron.d/x`)
    cannot resolve outside the materializer root. The result is always relative
    and never traverses above its eventual base directory.
    """
    parts = [
        segment
        for segment in PurePosixPath(path.lstrip("/")).parts
        if segment not in ("", ".", "..")
    ]
    return Path(*parts) if parts else Path()


__all__ = ["ForkMaterializer"]
