"""Overlay apply-to-parent on merge.

`merge_or_select("pick:<id>")` flushes the winner's
:class:`BranchOverlay` writes onto the parent backend; discarded
branches' overlays are released without flush — only the winner's
writes propagate.

The tests construct coordinators directly with a stub agent that writes
to its (overlay) backend during `agent.run`. This sidesteps TestModel
to keep the per-branch behaviour fully deterministic.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import patch

from pydantic_ai_backends import BackendProtocol, StateBackend, WriteResult

from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.features.forking.coordinator import ForkCoordinator
from pydantic_deep.features.forking.store import InMemoryForkStateStore
from pydantic_deep.features.forking.types import BranchIsolation, BranchSpec, FlushError


class _StubResult:
    """Minimal stand-in for pydantic-ai `AgentRunResult`."""

    def all_messages(self) -> list[Any]:
        return []


class _StubAgent:
    """Agent stub whose `run` writes to the (overlay) backend deterministically.

    The branch `steer` text drives the per-branch payload — each branch
    writes `cat.md` and `dog.md` with branch-specific content so we
    can tell who wrote what after the merge.
    """

    model = "anthropic:claude-sonnet-4-6"
    _root_capability = None

    async def run(
        self, steer: str, *, message_history: Any = None, deps: Any = None
    ) -> _StubResult:
        await deps.backend.write("cat.md", f"{steer} wrote cat")
        await deps.backend.write("dog.md", f"{steer} wrote dog")
        return _StubResult()


class _NoWriteStubAgent(_StubAgent):
    """Variant that performs no overlay writes — for the no-writes test."""

    async def run(
        self, steer: str, *, message_history: Any = None, deps: Any = None
    ) -> _StubResult:
        return _StubResult()


def _make_coord(
    agent: Any,
    parent: BackendProtocol,
    tmp_path: Path,
    *,
    keep_artifacts: bool = False,
) -> ForkCoordinator:
    deps = DeepAgentDeps(backend=parent)
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
    parent = StateBackend()
    parent.write("cat.md", "original cat")
    parent.write("dog.md", "original dog")
    coord = _make_coord(_StubAgent(), parent, tmp_path)

    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha"), BranchSpec(label="beta", steer="beta")],
        parent_history=[],
        isolation=BranchIsolation(),
    )
    await asyncio.gather(*[rt.task for rt in coord.branches.values()])
    winner = handle.branches[0]
    result = await coord.merge_or_select(f"pick:{winner}")

    assert sorted(result.applied_paths) == ["cat.md", "dog.md"]
    assert result.applied_changes == 2  # one write per file
    assert result.errors == []
    assert parent.read_bytes("cat.md") == b"alpha wrote cat"
    assert parent.read_bytes("dog.md") == b"alpha wrote dog"


# ---------------------------------------------------------------------------
# Test B — Discarded branches' writes never reach the parent.
# ---------------------------------------------------------------------------


async def test_discarded_branches_do_not_propagate(tmp_path: Path) -> None:
    parent = StateBackend()
    parent.write("cat.md", "original")
    coord = _make_coord(_StubAgent(), parent, tmp_path)

    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha"), BranchSpec(label="beta", steer="beta")],
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
    parent = StateBackend()
    parent.write("cat.md", "original")
    coord = _make_coord(_NoWriteStubAgent(), parent, tmp_path)

    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha"), BranchSpec(label="beta", steer="beta")],
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
    parent = StateBackend()
    parent.write("cat.md", "v1")
    coord = _make_coord(_StubAgent(), parent, tmp_path)

    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha"), BranchSpec(label="beta", steer="beta")],
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
    assert "cat.md" in result.conflicts
    assert "cat.md" not in result.applied_paths


# ---------------------------------------------------------------------------
# Test D2 — Conflict surfacing (parent path deleted by a third actor).
# ---------------------------------------------------------------------------


async def test_conflict_surfaced_when_parent_path_deleted_between_fork_and_merge(
    tmp_path: Path,
) -> None:
    parent = StateBackend()
    parent.write("cat.md", "v1")
    coord = _make_coord(_StubAgent(), parent, tmp_path)

    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha"), BranchSpec(label="beta", steer="beta")],
        parent_history=[],
        isolation=BranchIsolation(),
    )
    await asyncio.gather(*[rt.task for rt in coord.branches.values()])

    # Simulate a third-actor deletion: monkey-patch read_bytes to raise for
    # this one path. flush_to should detect the conflict (snapshot had bytes,
    # parent now lacks the file) and NOT replay the branch's write over it.
    real_read_bytes = parent.read_bytes

    def read_bytes_with_deletion(path: str) -> bytes:
        if path == "cat.md":
            raise FileNotFoundError(path)
        result: bytes = real_read_bytes(path)
        return result

    with patch.object(parent, "read_bytes", side_effect=read_bytes_with_deletion):
        result = await coord.merge_or_select(f"pick:{handle.branches[0]}")

    assert "cat.md" in result.conflicts
    assert "cat.md" not in result.applied_paths
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
    parent = StateBackend()
    parent.write("cat.md", "original")
    coord = _make_coord(_StubAgent(), parent, tmp_path, keep_artifacts=True)

    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha"), BranchSpec(label="beta", steer="beta")],
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
    parent = StateBackend()
    parent.write("cat.md", "original")
    coord = _make_coord(_StubAgent(), parent, tmp_path)

    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha"), BranchSpec(label="beta", steer="beta")],
        parent_history=[],
        isolation=BranchIsolation(),
    )
    await asyncio.gather(*[rt.task for rt in coord.branches.values()])

    fork_dir = tmp_path / "forks" / handle.fork_id
    assert fork_dir.exists()
    await coord.merge_or_select(f"pick:{handle.branches[0]}")
    assert not fork_dir.exists()


async def test_keep_artifacts_skips_cleanup_but_still_flushes(tmp_path: Path) -> None:
    parent = StateBackend()
    parent.write("cat.md", "original")
    coord = _make_coord(_StubAgent(), parent, tmp_path, keep_artifacts=True)

    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha"), BranchSpec(label="beta", steer="beta")],
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
    parent = StateBackend()
    coord = _make_coord(_StubAgent(), parent, tmp_path)

    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha"), BranchSpec(label="beta", steer="beta")],
        parent_history=[],
        isolation=BranchIsolation(),
    )
    await asyncio.gather(*[rt.task for rt in coord.branches.values()])

    # Stub parent.write to fail for `cat.md` only — `dog.md` should
    # still flush successfully and the failure must appear in MergeResult.errors.
    real_write = parent.write

    def _write_with_failure(path: str, content: Any) -> WriteResult:
        if path == "cat.md":
            return WriteResult(path=path, error="permission denied")
        return real_write(path, content)

    with patch.object(parent, "write", side_effect=_write_with_failure):
        result = await coord.merge_or_select(f"pick:{handle.branches[0]}")

    assert "cat.md" not in result.applied_paths
    assert "dog.md" in result.applied_paths
    assert any(
        isinstance(e, FlushError) and e.path == "cat.md" and "permission denied" in e.message
        for e in result.errors
    )


async def test_per_write_exception_is_caught_and_does_not_abort(tmp_path: Path) -> None:
    parent = StateBackend()
    coord = _make_coord(_StubAgent(), parent, tmp_path)

    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha"), BranchSpec(label="beta", steer="beta")],
        parent_history=[],
        isolation=BranchIsolation(),
    )
    await asyncio.gather(*[rt.task for rt in coord.branches.values()])

    real_write = parent.write

    def _write_raising(path: str, content: Any) -> WriteResult:
        if path == "cat.md":
            raise RuntimeError("disk full")
        return real_write(path, content)

    with patch.object(parent, "write", side_effect=_write_raising):
        result = await coord.merge_or_select(f"pick:{handle.branches[0]}")

    assert "cat.md" not in result.applied_paths
    assert "dog.md" in result.applied_paths
    assert any(e.path == "cat.md" and "disk full" in e.message for e in result.errors)


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
    from pydantic_deep.features.forking.isolation import BranchOverlay

    root_parent = StateBackend()
    outer_overlay = BranchOverlay(root_parent)
    # Pretend `outer_overlay` is the parent backend of the inner fork.
    inner_coord = _make_coord(_StubAgent(), outer_overlay, tmp_path)
    inner_handle = await inner_coord.fork(
        [BranchSpec(label="alpha", steer="alpha"), BranchSpec(label="beta", steer="beta")],
        parent_history=[],
        isolation=BranchIsolation(),
    )
    await asyncio.gather(*[rt.task for rt in inner_coord.branches.values()])
    await inner_coord.merge_or_select(f"pick:{inner_handle.branches[0]}")

    # Winner's writes propagated to the OUTER overlay, not the root yet.
    assert outer_overlay.read_bytes("cat.md") == b"alpha wrote cat"
    # The root parent is still untouched because the outer overlay
    # hasn't been flushed yet.
    assert not root_parent.exists("cat.md")


# ---------------------------------------------------------------------------
# Coverage-completion tests for BranchOverlay.flush_to edge cases.
# ---------------------------------------------------------------------------


def test_flush_to_without_snapshot_skips_conflict_detection(tmp_path: Path) -> None:
    """No pre_flush_snapshot → `conflicts` is empty regardless of parent state."""
    from pydantic_deep.features.forking.isolation import BranchOverlay

    parent = StateBackend()
    parent.write("foo.py", "original")
    overlay = BranchOverlay(parent)
    overlay.write("foo.py", "branch_content")

    report = overlay.flush_to(parent)  # no snapshot kwarg
    assert report.conflicts == []
    assert report.applied_paths == ["foo.py"]


def test_flush_to_replays_multiple_ops_per_path(tmp_path: Path) -> None:
    """Two writes to the same path produce one applied_paths entry but applied_changes=2."""
    from pydantic_deep.features.forking.isolation import BranchOverlay

    parent = StateBackend()
    parent.write("foo.py", "v0")
    overlay = BranchOverlay(parent)
    overlay.write("foo.py", "v1")
    overlay.write("foo.py", "v2")

    report = overlay.flush_to(parent)
    assert report.applied_paths == ["foo.py"]
    assert report.applied_changes == 2
    assert parent.read_bytes("foo.py") == b"v2"


def test_flush_to_error_on_second_write_rolls_back_applied_path(tmp_path: Path) -> None:
    """First write succeeds → path in applied_paths; second write fails → path removed."""
    from pydantic_deep.features.forking.isolation import BranchOverlay

    parent = StateBackend()
    overlay = BranchOverlay(parent)
    overlay.write("foo.py", "v1")
    overlay.write("foo.py", "v2")

    # First call succeeds; second returns WriteResult.error.
    call_count = {"n": 0}
    real_write = parent.write

    def _flaky_write(path: str, content: Any) -> WriteResult:
        call_count["n"] += 1
        if call_count["n"] == 2:
            return WriteResult(path=path, error="second op failed")
        return real_write(path, content)

    with patch.object(parent, "write", side_effect=_flaky_write):
        report = overlay.flush_to(parent)

    # Second op errored → path rolled back out of applied_paths.
    assert report.applied_paths == []
    assert len(report.errors) == 1
    assert report.errors[0].message == "second op failed"


def test_flush_to_exception_on_second_write_rolls_back_applied_path(tmp_path: Path) -> None:
    """Same as above but the parent backend raises rather than returning an error."""
    from pydantic_deep.features.forking.isolation import BranchOverlay

    parent = StateBackend()
    overlay = BranchOverlay(parent)
    overlay.write("foo.py", "v1")
    overlay.write("foo.py", "v2")

    call_count = {"n": 0}
    real_write = parent.write

    def _flaky_write(path: str, content: Any) -> WriteResult:
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("disk full")
        return real_write(path, content)

    with patch.object(parent, "write", side_effect=_flaky_write):
        report = overlay.flush_to(parent)

    assert report.applied_paths == []
    assert any("disk full" in e.message for e in report.errors)


def test_overlay_snapshot_records_none_when_parent_read_raises(tmp_path: Path) -> None:
    """When `parent.read_bytes` raises FileNotFoundError, the snapshot records `None`."""
    from pydantic_deep.features.forking.isolation import BranchOverlay
    from pydantic_deep.features.forking.materializer import ForkMaterializer

    materializer = ForkMaterializer(root=tmp_path / "fork1", fork_id="fork1")
    parent = StateBackend()
    overlay = BranchOverlay(parent)
    overlay.attach_materializer(materializer, "approach_a")

    real_read_bytes = parent.read_bytes

    def _raising_read_bytes(path: str) -> bytes:
        if path == "brand_new.py":
            raise FileNotFoundError(path)
        result: bytes = real_read_bytes(path)
        return result

    with patch.object(parent, "read_bytes", side_effect=_raising_read_bytes):
        overlay.write("brand_new.py", "content")

    assert materializer.pre_flush_snapshot() == {"brand_new.py": None}


def test_overlay_snapshot_records_none_on_keyerror(tmp_path: Path) -> None:
    """`KeyError` from `parent.read_bytes` is treated the same as FileNotFoundError."""
    from pydantic_deep.features.forking.isolation import BranchOverlay
    from pydantic_deep.features.forking.materializer import ForkMaterializer

    materializer = ForkMaterializer(root=tmp_path / "fork1", fork_id="fork1")
    parent = StateBackend()
    overlay = BranchOverlay(parent)
    overlay.attach_materializer(materializer, "approach_a")

    real_read_bytes = parent.read_bytes

    def _raising_read_bytes(path: str) -> bytes:
        if path == "missing.py":
            raise KeyError(path)
        result: bytes = real_read_bytes(path)
        return result

    with patch.object(parent, "read_bytes", side_effect=_raising_read_bytes):
        overlay.write("missing.py", "content")

    assert materializer.pre_flush_snapshot() == {"missing.py": None}


def test_detect_conflicts_skips_path_not_in_snapshot(tmp_path: Path) -> None:
    """`_detect_conflicts` skips paths absent from the supplied snapshot."""
    from pydantic_deep.features.forking.isolation import BranchOverlay

    parent = StateBackend()
    overlay = BranchOverlay(parent)
    overlay.write("unsnapshot.py", "branch_content")

    # Snapshot only covers a different path.
    report = overlay.flush_to(parent, pre_flush_snapshot={"other.py": b"hi"})
    assert report.conflicts == []


def test_detect_conflicts_handles_keyerror_in_parent_read_bytes(tmp_path: Path) -> None:
    """`KeyError` from `parent.read_bytes` is treated as deletion."""
    from pydantic_deep.features.forking.isolation import BranchOverlay

    parent = StateBackend()
    parent.write("foo.py", "v1")
    overlay = BranchOverlay(parent)
    overlay.write("foo.py", "branch_v1")

    real_read_bytes = parent.read_bytes

    def _raise_keyerror(path: str) -> bytes:
        if path == "foo.py":
            raise KeyError(path)
        result: bytes = real_read_bytes(path)
        return result

    with patch.object(parent, "read_bytes", side_effect=_raise_keyerror):
        report = overlay.flush_to(parent, pre_flush_snapshot={"foo.py": b"v1"})

    # Snapshot bytes (b"v1") vs current parent (KeyError → treated as None) differs → conflict.
    assert report.conflicts == ["foo.py"]


# ---------------------------------------------------------------------------
# Coverage-completion tests for ForkMaterializer + ForkCoordinator edges.
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


async def test_fork_with_share_readonly_backend_skips_materializer_attach(
    tmp_path: Path,
) -> None:
    """`backend='share_readonly'` skips overlay creation → no materializer hook."""
    parent = StateBackend()
    parent.write("cat.md", "shared")
    coord = _make_coord(_StubAgent(), parent, tmp_path)
    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha"), BranchSpec(label="beta", steer="beta")],
        parent_history=[],
        isolation=BranchIsolation(backend="share_readonly"),
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


class _DeleteCapturingBackend(StateBackend):  # type: ignore[misc]
    """Test stub: a backend that records `delete(path)` calls."""

    def __init__(self) -> None:
        super().__init__()
        self.deleted: list[str] = []

    def delete(self, path: str) -> None:
        self.deleted.append(path)


class _ExecuteCapturingBackend(StateBackend):  # type: ignore[misc]
    """Test stub: backend with `execute_enabled=True` that captures commands."""

    execute_enabled: bool = True

    def __init__(self) -> None:
        super().__init__()
        self.commands: list[str] = []

    def execute(self, command: str, timeout: int | None = None) -> None:
        self.commands.append(command)


def test_flush_to_propagates_delete_via_parent_delete_method(tmp_path: Path) -> None:
    from pydantic_deep.features.forking.isolation import BranchOverlay

    parent = _DeleteCapturingBackend()
    parent.write("doomed.py", "v0")
    overlay = BranchOverlay(parent)
    overlay.delete("doomed.py")

    report = overlay.flush_to(parent)

    assert parent.deleted == ["doomed.py"]
    assert report.deleted_paths == ["doomed.py"]
    assert report.applied_paths == []
    assert report.errors == []
    assert report.applied_changes == 1


def test_flush_to_propagates_delete_via_execute(tmp_path: Path) -> None:
    from pydantic_deep.features.forking.isolation import BranchOverlay

    parent = _ExecuteCapturingBackend()
    parent.write("doomed.py", "v0")
    overlay = BranchOverlay(parent)
    overlay.delete("doomed.py")

    report = overlay.flush_to(parent)

    assert parent.commands == ["rm -f doomed.py"]
    assert report.deleted_paths == ["doomed.py"]
    assert report.errors == []


def test_flush_to_delete_error_is_surfaced(tmp_path: Path) -> None:
    from pydantic_deep.features.forking.isolation import BranchOverlay

    parent = _DeleteCapturingBackend()
    parent.write("doomed.py", "v0")

    def _raise(path: str) -> None:
        raise PermissionError("read-only volume")

    overlay = BranchOverlay(parent)
    overlay.delete("doomed.py")

    with patch.object(parent, "delete", side_effect=_raise):
        report = overlay.flush_to(parent)

    assert report.deleted_paths == []
    assert len(report.errors) == 1
    assert report.errors[0].path == "doomed.py"
    assert report.errors[0].op == "delete"
    assert "read-only volume" in report.errors[0].message


def test_flush_to_delete_on_state_backend_records_unsupported_error(tmp_path: Path) -> None:
    """`StateBackend` has neither execute_enabled nor delete — surface an error."""
    from pydantic_deep.features.forking.isolation import BranchOverlay

    parent = StateBackend()
    parent.write("doomed.py", "v0")
    overlay = BranchOverlay(parent)
    overlay.delete("doomed.py")

    report = overlay.flush_to(parent)

    assert report.deleted_paths == []
    assert len(report.errors) == 1
    assert report.errors[0].op == "delete"
    assert "does not support delete" in report.errors[0].message


def test_flush_to_delete_via_execute_nonzero_exit_records_error(tmp_path: Path) -> None:
    """`rm -f` exiting non-zero (e.g. permission denied) surfaces as a FlushError."""
    from pydantic_ai_backends import ExecuteResponse

    from pydantic_deep.features.forking.isolation import BranchOverlay

    class _FailingExecuteBackend(StateBackend):  # type: ignore[misc]
        execute_enabled: bool = True

        def execute(self, command: str, timeout: int | None = None) -> ExecuteResponse:
            return ExecuteResponse(
                output="rm: /foo: Permission denied\n",
                exit_code=1,
            )

    parent = _FailingExecuteBackend()
    parent.write("doomed.py", "v0")
    overlay = BranchOverlay(parent)
    overlay.delete("doomed.py")

    report = overlay.flush_to(parent)

    # The delete is rejected: no entry in deleted_paths, one error captured.
    assert report.deleted_paths == []
    assert len(report.errors) == 1
    assert report.errors[0].op == "delete"
    assert report.errors[0].path == "doomed.py"
    assert "rm exited 1" in report.errors[0].message
    assert "Permission denied" in report.errors[0].message


def test_flush_to_write_then_delete_propagates_delete_and_drops_applied(
    tmp_path: Path,
) -> None:
    """`write; delete` sequence ends as a deletion — no spurious applied_paths entry."""
    from pydantic_deep.features.forking.isolation import BranchOverlay

    parent = _DeleteCapturingBackend()
    parent.write("foo.py", "v0")
    overlay = BranchOverlay(parent)
    overlay.write("foo.py", "branch_content")
    overlay.delete("foo.py")

    report = overlay.flush_to(parent)

    assert parent.deleted == ["foo.py"]
    assert report.deleted_paths == ["foo.py"]
    assert report.applied_paths == []  # write was superseded


def test_flush_to_delete_then_write_propagates_write_and_drops_deleted(
    tmp_path: Path,
) -> None:
    """`delete; write` sequence ends as a write — the path leaves `deleted_paths`."""
    from pydantic_deep.features.forking.isolation import BranchOverlay

    parent = _DeleteCapturingBackend()
    parent.write("foo.py", "v0")
    overlay = BranchOverlay(parent)
    overlay.delete("foo.py")
    overlay.write("foo.py", "branch_content")

    report = overlay.flush_to(parent)

    # Delete still propagates, then write puts content back.
    assert parent.deleted == ["foo.py"]
    assert report.applied_paths == ["foo.py"]
    assert report.deleted_paths == []
    assert parent.read_bytes("foo.py") == b"branch_content"


async def test_coordinator_merge_propagates_deleted_paths_into_result(
    tmp_path: Path,
) -> None:
    """End-to-end: agent deletes a file mid-branch; merge result lists the path."""

    class _DeletingAgent(_StubAgent):
        async def run(
            self, steer: str, *, message_history: Any = None, deps: Any = None
        ) -> _StubResult:
            raw = getattr(deps.backend, "unwrap", lambda: deps.backend)()
            raw.delete("doomed.py")
            return _StubResult()

    parent = _DeleteCapturingBackend()
    parent.write("doomed.py", "v0")
    coord = _make_coord(_DeletingAgent(), parent, tmp_path)
    handle = await coord.fork(
        [BranchSpec(label="alpha", steer="alpha"), BranchSpec(label="beta", steer="beta")],
        parent_history=[],
        isolation=BranchIsolation(),
    )
    await asyncio.gather(*[rt.task for rt in coord.branches.values()])
    result = await coord.merge_or_select(f"pick:{handle.branches[0]}")

    assert result.deleted_paths == ["doomed.py"]
    assert "doomed.py" in parent.deleted
