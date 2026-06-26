""":class:`ForkMaterializer` and disk-mirror tests (issue #106)."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models.test import TestModel
from pydantic_ai_backends import StateBackend

from pydantic_deep import (
    BranchIsolation,
    BranchSpec,
    DeepAgentDeps,
    ForkCoordinator,
    InMemoryForkStateStore,
)
from pydantic_deep.features.forking.isolation import BranchOverlay
from pydantic_deep.features.forking.materializer import ForkMaterializer
from pydantic_deep.features.forking.types import BranchStatus, FileChange


def _seed_history(text: str) -> list[Any]:
    return [ModelRequest(parts=[UserPromptPart(content=text)])]


# ---------------------------------------------------------------------------
# Test 1 — Spawning a fork creates the directory layout.
# ---------------------------------------------------------------------------


async def test_fork_creates_directory_layout(tmp_path: Path) -> None:
    agent = Agent(TestModel(), deps_type=DeepAgentDeps)
    deps = DeepAgentDeps(backend=StateBackend())
    coord = ForkCoordinator(
        agent=agent,
        parent_deps=deps,
        max_branches=2,
        max_depth=1,
        store=InMemoryForkStateStore(),
        materializer_root=tmp_path / "forks",
    )
    handle = await coord.fork(
        [BranchSpec(label="a", steer="A"), BranchSpec(label="b", steer="B")],
        parent_history=_seed_history("seed"),
        isolation=BranchIsolation(),
    )
    fork_dir = tmp_path / "forks" / handle.fork_id
    assert fork_dir.is_dir()
    assert (fork_dir / "manifest.json").is_file()
    assert (fork_dir / "parent").is_dir()
    assert (fork_dir / "branches").is_dir()


# ---------------------------------------------------------------------------
# Test 2 — Real-time flush within 100 ms.
# ---------------------------------------------------------------------------


def test_overlay_write_mirrors_to_disk_within_100ms(tmp_path: Path) -> None:
    materializer = ForkMaterializer(root=tmp_path / "fork1", fork_id="fork1")
    parent = StateBackend()
    overlay = BranchOverlay(parent)
    overlay.attach_materializer(materializer, "approach_a")

    t0 = time.perf_counter()
    overlay.write("foo.py", "print('hello')")
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    mirror = tmp_path / "fork1" / "branches" / "approach_a" / "foo.py"
    assert mirror.exists()
    assert mirror.read_bytes() == b"print('hello')"
    assert elapsed_ms < 100.0, f"flush took {elapsed_ms:.1f}ms, expected <100ms"


# ---------------------------------------------------------------------------
# Test 3 — Parent snapshot is frozen at fork time.
# ---------------------------------------------------------------------------


def test_parent_snapshot_is_frozen(tmp_path: Path) -> None:
    materializer = ForkMaterializer(root=tmp_path / "fork1", fork_id="fork1")
    parent = StateBackend()
    parent.write("foo.py", "v1")
    overlay = BranchOverlay(parent)
    overlay.attach_materializer(materializer, "approach_a")
    # First overlay write triggers the lazy parent snapshot.
    overlay.write("foo.py", "branch_v1")

    snap = tmp_path / "fork1" / "parent" / "foo.py"
    assert snap.read_bytes() == b"v1"

    # Subsequent parent writes do NOT change the on-disk snapshot.
    parent.write("foo.py", "v2_post_fork")
    assert snap.read_bytes() == b"v1"
    # And the materializer's pre_flush_snapshot still echoes the frozen bytes.
    assert materializer.pre_flush_snapshot() == {"foo.py": b"v1"}


# ---------------------------------------------------------------------------
# Test 4 — Manifest updates on every branch status transition.
# ---------------------------------------------------------------------------


async def test_manifest_updates_on_status_transitions(tmp_path: Path) -> None:
    agent = Agent(TestModel(), deps_type=DeepAgentDeps)
    deps = DeepAgentDeps(backend=StateBackend())
    coord = ForkCoordinator(
        agent=agent,
        parent_deps=deps,
        max_branches=2,
        max_depth=1,
        store=InMemoryForkStateStore(),
        materializer_root=tmp_path / "forks",
    )
    handle = await coord.fork(
        [BranchSpec(label="a", steer="A"), BranchSpec(label="b", steer="B")],
        parent_history=_seed_history("seed"),
        isolation=BranchIsolation(),
    )
    manifest_path = tmp_path / "forks" / handle.fork_id / "manifest.json"
    initial = json.loads(manifest_path.read_text())
    assert {b["label"] for b in initial["branches"]} == {"a", "b"}
    assert all(b["state"] == "running" for b in initial["branches"])

    # Force-terminate one branch and verify manifest reflects the transition.
    target = handle.branches[0]
    await coord.terminate_branch(target)
    refreshed = json.loads(manifest_path.read_text())
    states = {b["id"]: b["state"] for b in refreshed["branches"]}
    assert states[target] == "terminated"


# ---------------------------------------------------------------------------
# Test 5 — Cleanup default vs keep_artifacts.
# ---------------------------------------------------------------------------


async def test_cleanup_removes_fork_directory(tmp_path: Path) -> None:
    materializer = ForkMaterializer(root=tmp_path / "fork1", fork_id="fork1")
    assert (tmp_path / "fork1").exists()
    materializer.cleanup()
    assert not (tmp_path / "fork1").exists()


async def test_keep_artifacts_retains_fork_directory(tmp_path: Path) -> None:
    materializer = ForkMaterializer(root=tmp_path / "fork1", fork_id="fork1", keep_artifacts=True)
    materializer.cleanup()
    assert (tmp_path / "fork1").exists()


# ---------------------------------------------------------------------------
# Coverage helpers: flush_change + update_manifest.
# ---------------------------------------------------------------------------


def test_flush_change_writes_to_branch_subtree(tmp_path: Path) -> None:
    m = ForkMaterializer(root=tmp_path / "fork1", fork_id="fork1")
    change = FileChange(path="src/x.py", op="write", timestamp=datetime.now(timezone.utc))
    m.flush_change("approach_a", change, b"content")
    target = tmp_path / "fork1" / "branches" / "approach_a" / "src" / "x.py"
    assert target.read_bytes() == b"content"
    assert not (target.stat().st_mode & 0o200), "branch file must be read-only after flush"


def test_flush_change_overwrites_read_only_file(tmp_path: Path) -> None:
    m = ForkMaterializer(root=tmp_path / "fork1", fork_id="fork1")
    change = FileChange(path="src/x.py", op="write", timestamp=datetime.now(timezone.utc))
    m.flush_change("approach_a", change, b"v1")
    m.flush_change("approach_a", change, b"v2")
    target = tmp_path / "fork1" / "branches" / "approach_a" / "src" / "x.py"
    assert target.read_bytes() == b"v2"
    assert not (target.stat().st_mode & 0o200)


def test_flush_delete_removes_materialised_branch_file(tmp_path: Path) -> None:
    m = ForkMaterializer(root=tmp_path / "fork1", fork_id="fork1")
    write_change = FileChange(path="src/x.py", op="write", timestamp=datetime.now(timezone.utc))
    m.flush_change("approach_a", write_change, b"content")

    delete_change = FileChange(path="src/x.py", op="delete", timestamp=datetime.now(timezone.utc))
    m.flush_delete("approach_a", delete_change)

    target = tmp_path / "fork1" / "branches" / "approach_a" / "src" / "x.py"
    assert not target.exists()


def test_flush_delete_is_noop_when_branch_never_wrote_path(tmp_path: Path) -> None:
    m = ForkMaterializer(root=tmp_path / "fork1", fork_id="fork1")
    delete_change = FileChange(path="absent.py", op="delete", timestamp=datetime.now(timezone.utc))
    # Should not raise — branch directory exists but the file does not.
    m.flush_delete("approach_a", delete_change)


def test_snapshot_parent_path_dedupes_repeat_calls(tmp_path: Path) -> None:
    m = ForkMaterializer(root=tmp_path / "fork1", fork_id="fork1")
    m.snapshot_parent_path("a.py", b"first")
    m.snapshot_parent_path("a.py", b"ignored_second_attempt")
    assert m.pre_flush_snapshot() == {"a.py": b"first"}


def test_snapshot_parent_path_is_read_only(tmp_path: Path) -> None:
    m = ForkMaterializer(root=tmp_path / "fork1", fork_id="fork1")
    m.snapshot_parent_path("a.py", b"content")
    target = tmp_path / "fork1" / "parent" / "a.py"
    assert not (target.stat().st_mode & 0o200), "parent snapshot must be read-only"


def test_snapshot_parent_path_records_missing_file_as_none(tmp_path: Path) -> None:
    m = ForkMaterializer(root=tmp_path / "fork1", fork_id="fork1")
    m.snapshot_parent_path("never_existed.py", None)
    assert m.pre_flush_snapshot() == {"never_existed.py": None}
    assert not (tmp_path / "fork1" / "parent" / "never_existed.py").exists()


def test_update_manifest_writes_status_list(tmp_path: Path) -> None:
    m = ForkMaterializer(root=tmp_path / "fork1", fork_id="fork1")
    status = BranchStatus(
        id="bid-1",
        label="alpha",
        state="done",
        current_turn=2,
        last_activity_at=datetime.now(timezone.utc),
        error=None,
    )
    m.update_manifest([status])
    data = json.loads(m.manifest_path().read_text())
    assert data == {
        "fork_id": "fork1",
        "branches": [
            {
                "id": "bid-1",
                "label": "alpha",
                "state": "done",
                "current_turn": 2,
                "error": None,
            }
        ],
    }


def test_mirror_to_disk_logs_oserror_but_does_not_propagate(tmp_path: Path, caplog: Any) -> None:
    """When materializer.flush_change raises OSError, BranchOverlay.write must
    still succeed and the overlay must hold the new content — the materializer
    is best-effort. The failure is logged so it does not vanish silently.
    """
    import logging

    parent = StateBackend()
    parent.write("a.py", "before")
    overlay = BranchOverlay(parent)
    materializer = ForkMaterializer(root=tmp_path / "fork1", fork_id="fork1")

    def _raise(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("disk full")

    materializer.flush_change = _raise  # type: ignore[method-assign]
    overlay.attach_materializer(materializer, "approach_a")

    with caplog.at_level(logging.WARNING, logger="pydantic_deep.features.forking.isolation"):
        result = overlay.write("a.py", "after")

    assert result.error is None
    assert overlay.read_bytes("a.py") == b"after"
    assert parent.read_bytes("a.py") == b"before"  # parent untouched
    assert any("flush_change failed" in record.message for record in caplog.records)


def test_safe_relative_strips_leading_slash(tmp_path: Path) -> None:
    m = ForkMaterializer(root=tmp_path / "fork1", fork_id="fork1")
    # Absolute-style paths should not escape the materializer root.
    target = m.branch_path("approach_a", "/etc/passwd")
    assert target.is_relative_to(tmp_path / "fork1" / "branches" / "approach_a")


def test_safe_relative_neutralizes_parent_traversal(tmp_path: Path) -> None:
    m = ForkMaterializer(root=tmp_path / "fork1", fork_id="fork1")
    branch_base = tmp_path / "fork1" / "branches" / "approach_a"
    parent_base = tmp_path / "fork1" / "parent"
    # `..` segments must not let a write escape the materializer root.
    for evil in ("../../etc/cron.d/x", "a/../../b", "/../../etc/passwd", "foo/../../../bar"):
        bt = m.branch_path("approach_a", evil)
        pt = m.parent_path(evil)
        assert bt.is_relative_to(branch_base), f"branch path escaped for {evil!r}: {bt}"
        assert pt.is_relative_to(parent_base), f"parent path escaped for {evil!r}: {pt}"


def test_cleanup_on_already_removed_dir_is_safe(tmp_path: Path) -> None:
    m = ForkMaterializer(root=tmp_path / "fork1", fork_id="fork1")
    import shutil

    shutil.rmtree(tmp_path / "fork1")
    m.cleanup()  # no-op, no exception
