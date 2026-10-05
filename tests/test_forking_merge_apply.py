"""Overlay apply-to-parent on merge.

`merge_or_select("pick:<id>")` flushes the winner's
:class:`BranchOverlay` writes onto the parent workspace; discarded
branches' overlays are released without flush — only the winner's
writes propagate.

The tests construct coordinators directly with a stub agent that writes
to the workspace its run is given during `agent.run`. This sidesteps TestModel
to keep the per-branch behaviour fully deterministic.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import patch

from pydantic_ai.workspaces import Workspace

from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.features.forking.coordinator import ForkCoordinator
from pydantic_deep.features.forking.isolation import BranchOverlay
from pydantic_deep.features.forking.store import InMemoryForkStateStore
from pydantic_deep.features.forking.types import BranchIsolation, BranchSpec, FlushError
from tests.workspaces import Document, as_workspace


class _StubResult:
    """Minimal stand-in for pydantic-ai `AgentRunResult`."""

    def all_messages(self) -> list[Any]:
        return []


class _StubAgent:
    """Agent stub whose `run` writes to the branch's workspace deterministically.

    The branch `steer` text drives the per-branch payload — each branch
    writes `cat.md` and `dog.md` with branch-specific content so we
    can tell who wrote what after the merge.
    """

    model = "anthropic:claude-sonnet-4-6"
    _root_capability = None

    async def run(
        self, steer: str, *, message_history: Any = None, deps: Any = None, workspace: Any = None
    ) -> _StubResult:
        await workspace.write_text("cat.md", f"{steer} wrote cat")
        await workspace.write_text("dog.md", f"{steer} wrote dog")
        return _StubResult()


class _NoWriteStubAgent(_StubAgent):
    """Variant that performs no overlay writes — for the no-writes test."""

    async def run(
        self, steer: str, *, message_history: Any = None, deps: Any = None, workspace: Any = None
    ) -> _StubResult:
        return _StubResult()


def _workspace(parent: Document | BranchOverlay) -> Workspace:
    return Workspace(parent) if isinstance(parent, BranchOverlay) else as_workspace(parent)


def _make_coord(
    agent: Any,
    parent: Document | BranchOverlay,
    tmp_path: Path,
    *,
    keep_artifacts: bool = False,
) -> ForkCoordinator:
    deps = DeepAgentDeps()
    return ForkCoordinator(
        agent=agent,
        parent_deps=deps,
        max_branches=2,
        max_depth=1,
        store=InMemoryForkStateStore(),
        materializer_root=tmp_path / "forks",
        keep_artifacts=keep_artifacts,
    )


# ---------------------------------------------------------------------------
# Test A — Default apply: pick:<id> flushes the winner's writes.
# ---------------------------------------------------------------------------


async def test_pick_default_flushes_winner_writes_to_parent(tmp_path: Path) -> None:
    parent = Document()
    parent.write("cat.md", "original cat")
    parent.write("dog.md", "original dog")
    coord = _make_coord(_StubAgent(), parent, tmp_path)

    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha"), BranchSpec(label="beta", steer="beta")],
        workspace=_workspace(parent),
        parent_history=[],
        isolation=BranchIsolation(),
    )
    await asyncio.gather(*[rt.task for rt in coord.branches.values()])
    winner = handle.branches[0]
    result = await coord.merge_or_select(f"pick:{winner}")

    assert sorted(result.applied_paths) == ["/cat.md", "/dog.md"]
    assert result.applied_changes == 2  # one write per file
    assert result.errors == []
    assert parent.read_bytes("cat.md") == b"alpha wrote cat"
    assert parent.read_bytes("dog.md") == b"alpha wrote dog"


# ---------------------------------------------------------------------------
# Test B — Discarded branches' writes never reach the parent.
# ---------------------------------------------------------------------------


async def test_discarded_branches_do_not_propagate(tmp_path: Path) -> None:
    parent = Document()
    parent.write("cat.md", "original")
    coord = _make_coord(_StubAgent(), parent, tmp_path)

    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha"), BranchSpec(label="beta", steer="beta")],
        workspace=_workspace(parent),
        parent_history=[],
        isolation=BranchIsolation(),
    )
    await asyncio.gather(*[rt.task for rt in coord.branches.values()])
    # Pick alpha → only alpha's writes should propagate.
    winner = handle.branches[0]
    await coord.merge_or_select(f"pick:{winner}")
    assert parent.read_bytes("cat.md") == b"alpha wrote cat"
    # beta's content is never on disk.
    assert b"beta" not in parent.read_bytes("cat.md")


# ---------------------------------------------------------------------------
# Test C — No writes, no notification noise.
# ---------------------------------------------------------------------------


async def test_no_writes_yields_empty_applied_paths(tmp_path: Path) -> None:
    parent = Document()
    parent.write("cat.md", "original")
    coord = _make_coord(_NoWriteStubAgent(), parent, tmp_path)

    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha"), BranchSpec(label="beta", steer="beta")],
        workspace=_workspace(parent),
        parent_history=[],
        isolation=BranchIsolation(),
    )
    await asyncio.gather(*[rt.task for rt in coord.branches.values()])
    result = await coord.merge_or_select(f"pick:{handle.branches[0]}")
    assert result.applied_paths == []
    assert result.applied_changes == 0
    assert result.conflicts == []
    assert result.errors == []
    assert parent.read_bytes("cat.md") == b"original"


# ---------------------------------------------------------------------------
# Test D — Conflict surfacing (parent modified by a third actor).
# ---------------------------------------------------------------------------


async def test_conflict_surfaced_when_parent_modified_between_fork_and_merge(
    tmp_path: Path,
) -> None:
    parent = Document()
    parent.write("cat.md", "v1")
    coord = _make_coord(_StubAgent(), parent, tmp_path)

    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha"), BranchSpec(label="beta", steer="beta")],
        workspace=_workspace(parent),
        parent_history=[],
        isolation=BranchIsolation(),
    )
    await asyncio.gather(*[rt.task for rt in coord.branches.values()])

    # Third-actor modification between fork resolution and merge.
    parent.write("cat.md", "third_actor_v2")

    result = await coord.merge_or_select(f"pick:{handle.branches[0]}")
    # Non-destructive: the third actor's newer content is preserved, NOT clobbered
    # by the winning branch's version.
    assert parent.read_bytes("cat.md") == b"third_actor_v2"
    # The conflict surfaces in the report and the path is not counted as applied.
    assert "/cat.md" in result.conflicts
    assert "/cat.md" not in result.applied_paths


# ---------------------------------------------------------------------------
# Test D2 — Conflict surfacing (parent path deleted by a third actor).
# ---------------------------------------------------------------------------


async def test_conflict_surfaced_when_parent_path_deleted_between_fork_and_merge(
    tmp_path: Path,
) -> None:
    parent = Document()
    parent.write("cat.md", "v1")
    coord = _make_coord(_StubAgent(), parent, tmp_path)

    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha"), BranchSpec(label="beta", steer="beta")],
        workspace=_workspace(parent),
        parent_history=[],
        isolation=BranchIsolation(),
    )
    await asyncio.gather(*[rt.task for rt in coord.branches.values()])

    # Simulate a third-actor deletion: monkey-patch read_bytes to raise for
    # this one path. flush_to should detect the conflict (snapshot had bytes,
    # parent now lacks the file) and NOT replay the branch's write over it.
    real_read_bytes = parent.read_bytes

    def read_bytes_with_deletion(path: str) -> bytes:
        if path == "/cat.md":
            raise FileNotFoundError(path)
        result: bytes = real_read_bytes(path)
        return result

    with patch.object(parent, "read_bytes", side_effect=read_bytes_with_deletion):
        result = await coord.merge_or_select(f"pick:{handle.branches[0]}")

    assert "/cat.md" in result.conflicts
    assert "/cat.md" not in result.applied_paths
    # Non-destructive: the conflicting path was skipped, so the branch's write did
    # not clobber it (the pre-existing parent content remains).
    assert parent.read_bytes("cat.md") == b"v1"


# ---------------------------------------------------------------------------
# Test F — Materializer round-trip: branch snapshot matches flushed parent.
# ---------------------------------------------------------------------------


async def test_materializer_branch_snapshot_matches_flushed_parent(tmp_path: Path) -> None:
    # Covers addendum test plan item 5 (PyCharm-diff'd file matches picked
    # branch after merge): asserts the disk-mirror snapshot the IDE sees is
    # the same bytes that land on the parent backend.
    parent = Document()
    parent.write("cat.md", "original")
    coord = _make_coord(_StubAgent(), parent, tmp_path, keep_artifacts=True)

    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha"), BranchSpec(label="beta", steer="beta")],
        workspace=_workspace(parent),
        parent_history=[],
        isolation=BranchIsolation(),
    )
    await asyncio.gather(*[rt.task for rt in coord.branches.values()])

    winner_id = handle.branches[0]
    winner_label = coord.branches[winner_id].spec.label
    mirror = tmp_path / "forks" / handle.fork_id / "branches" / winner_label / "cat.md"

    await coord.merge_or_select(f"pick:{winner_id}")

    # `keep_artifacts=True` keeps the on-disk snapshot intact AFTER merge.
    assert mirror.exists()
    assert mirror.read_bytes() == parent.read_bytes("cat.md")


# ---------------------------------------------------------------------------
# Test G — Cleanup default vs keep_artifacts.
# ---------------------------------------------------------------------------


async def test_cleanup_runs_by_default_on_merge(tmp_path: Path) -> None:
    parent = Document()
    parent.write("cat.md", "original")
    coord = _make_coord(_StubAgent(), parent, tmp_path)

    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha"), BranchSpec(label="beta", steer="beta")],
        workspace=_workspace(parent),
        parent_history=[],
        isolation=BranchIsolation(),
    )
    await asyncio.gather(*[rt.task for rt in coord.branches.values()])

    fork_dir = tmp_path / "forks" / handle.fork_id
    assert fork_dir.exists()
    await coord.merge_or_select(f"pick:{handle.branches[0]}")
    assert not fork_dir.exists()


async def test_keep_artifacts_skips_cleanup_but_still_flushes(tmp_path: Path) -> None:
    parent = Document()
    parent.write("cat.md", "original")
    coord = _make_coord(_StubAgent(), parent, tmp_path, keep_artifacts=True)

    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha"), BranchSpec(label="beta", steer="beta")],
        workspace=_workspace(parent),
        parent_history=[],
        isolation=BranchIsolation(),
    )
    await asyncio.gather(*[rt.task for rt in coord.branches.values()])
    await coord.merge_or_select(f"pick:{handle.branches[0]}")

    fork_dir = tmp_path / "forks" / handle.fork_id
    assert fork_dir.exists()  # artefacts preserved
    # Apply still happened — keep_artifacts is independent of apply.
    assert parent.read_bytes("cat.md") == b"alpha wrote cat"


# ---------------------------------------------------------------------------
# Test N — Per-write error surfacing: flush_to does NOT abort on failure.
# ---------------------------------------------------------------------------


async def test_per_write_error_is_surfaced_and_does_not_abort(tmp_path: Path) -> None:
    parent = Document()
    coord = _make_coord(_StubAgent(), parent, tmp_path)

    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha"), BranchSpec(label="beta", steer="beta")],
        workspace=_workspace(parent),
        parent_history=[],
        isolation=BranchIsolation(),
    )
    await asyncio.gather(*[rt.task for rt in coord.branches.values()])

    # Stub parent.write to fail for `cat.md` only — `dog.md` should
    # still flush successfully and the failure must appear in MergeResult.errors.
    real_write = parent.write_bytes

    def _write_with_failure(path: str, data: bytes) -> None:
        if path == "/cat.md":
            raise PermissionError("permission denied")
        real_write(path, data)

    with patch.object(parent, "write_bytes", side_effect=_write_with_failure):
        result = await coord.merge_or_select(f"pick:{handle.branches[0]}")

    assert "/cat.md" not in result.applied_paths
    assert "/dog.md" in result.applied_paths
    assert any(
        isinstance(e, FlushError) and e.path == "/cat.md" and "permission denied" in e.message
        for e in result.errors
    )


async def test_per_write_exception_is_caught_and_does_not_abort(tmp_path: Path) -> None:
    parent = Document()
    coord = _make_coord(_StubAgent(), parent, tmp_path)

    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha"), BranchSpec(label="beta", steer="beta")],
        workspace=_workspace(parent),
        parent_history=[],
        isolation=BranchIsolation(),
    )
    await asyncio.gather(*[rt.task for rt in coord.branches.values()])

    real_write = parent.write_bytes

    def _write_raising(path: str, data: bytes) -> None:
        if path == "/cat.md":
            raise RuntimeError("disk full")
        real_write(path, data)

    with patch.object(parent, "write_bytes", side_effect=_write_raising):
        result = await coord.merge_or_select(f"pick:{handle.branches[0]}")

    assert "/cat.md" not in result.applied_paths
    assert "/dog.md" in result.applied_paths
    assert any(e.path == "/cat.md" and "disk full" in e.message for e in result.errors)


# ---------------------------------------------------------------------------
# Test O — Nested fork: writes propagate up one level on merge.
# ---------------------------------------------------------------------------


async def test_nested_fork_flush_up_one_level(tmp_path: Path) -> None:
    """Inner fork's winner flushes into the outer branch's overlay.

    The outer branch is itself wrapped in a :class:`BranchOverlay` (its
    backend is the outer fork's overlay). Flushing into that overlay is
    indistinguishable from any other parent backend — no special
    handling required.
    """
    root_parent = Document()
    outer_overlay = BranchOverlay(as_workspace(root_parent))
    # Pretend `outer_overlay` is the parent backend of the inner fork.
    inner_coord = _make_coord(_StubAgent(), outer_overlay, tmp_path)
    inner_handle = await inner_coord.fork(
        [BranchSpec(label="alpha", steer="alpha"), BranchSpec(label="beta", steer="beta")],
        workspace=_workspace(outer_overlay),
        parent_history=[],
        isolation=BranchIsolation(),
    )
    await asyncio.gather(*[rt.task for rt in inner_coord.branches.values()])
    await inner_coord.merge_or_select(f"pick:{inner_handle.branches[0]}")

    # Winner's writes propagated to the OUTER overlay, not the root yet.
    assert await outer_overlay.read_bytes("/cat.md") == b"alpha wrote cat"
    # The root parent is still untouched because the outer overlay
    # hasn't been flushed yet.
    assert not root_parent.exists("cat.md")


# ---------------------------------------------------------------------------
def test_materializer_does_not_overwrite_existing_manifest(tmp_path: Path) -> None:
    """Second instantiation against an existing root preserves the manifest file."""
    from pydantic_deep.features.forking.materializer import ForkMaterializer

    root = tmp_path / "fork1"
    m1 = ForkMaterializer(root=root, fork_id="fork1")
    # Write a sentinel into the manifest then re-instantiate.
    manifest_path = m1.manifest_path()
    manifest_path.write_text('{"fork_id":"fork1","branches":[],"sentinel":true}', encoding="utf-8")

    ForkMaterializer(root=root, fork_id="fork1")
    # Second construction must NOT overwrite — the sentinel survives.
    import json

    data = json.loads(manifest_path.read_text())
    assert data.get("sentinel") is True


async def test_fork_with_share_readonly_workspace_skips_materializer_attach(
    tmp_path: Path,
) -> None:
    """`workspace='share_readonly'` skips overlay creation → no materializer hook."""
    parent = Document()
    parent.write("cat.md", "shared")
    coord = _make_coord(_NoWriteStubAgent(), parent, tmp_path)
    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha"), BranchSpec(label="beta", steer="beta")],
        workspace=_workspace(parent),
        parent_history=[],
        isolation=BranchIsolation(workspace="share_readonly"),
    )
    await asyncio.gather(*[rt.task for rt in coord.branches.values()])
    # No overlay → no per-branch disk mirror.
    for rt in coord.branches.values():
        assert rt.overlay is None
    # merge_or_select still resolves cleanly even without overlays.
    result = await coord.merge_or_select(f"pick:{handle.branches[0]}")
    assert result.applied_paths == []


# ---------------------------------------------------------------------------
# flush_to — delete-op propagation to the parent backend
# ---------------------------------------------------------------------------


async def test_coordinator_merge_propagates_deleted_paths_into_result(
    tmp_path: Path,
) -> None:
    """End-to-end: agent deletes a file mid-branch; merge result lists the path."""

    class _DeletingAgent(_StubAgent):
        async def run(
            self,
            steer: str,
            *,
            message_history: Any = None,
            deps: Any = None,
            workspace: Any = None,
        ) -> _StubResult:
            await workspace.remove("doomed.py")
            return _StubResult()

    parent = Document()
    parent.write("doomed.py", "v0")
    coord = _make_coord(_DeletingAgent(), parent, tmp_path)
    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha"), BranchSpec(label="beta", steer="beta")],
        workspace=_workspace(parent),
        parent_history=[],
        isolation=BranchIsolation(),
    )
    await asyncio.gather(*[rt.task for rt in coord.branches.values()])
    result = await coord.merge_or_select(f"pick:{handle.branches[0]}")

    assert result.deleted_paths == ["/doomed.py"]
    assert not parent.exists("doomed.py")
