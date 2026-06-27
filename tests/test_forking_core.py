"""Live Run Forking — coordinator and branch kernel tests (issue #102)."""

from __future__ import annotations

import asyncio
import contextlib
import warnings
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
from pydantic_ai.models.test import TestModel
from pydantic_ai_backends import StateBackend

from pydantic_deep import (
    BranchIsolation,
    BranchOverlay,
    BranchSpec,
    DeepAgentDeps,
    FileChange,
    ForkBranchLimitError,
    ForkCoordinator,
    ForkDepthLimitError,
    ForkHandle,
    InMemoryForkStateStore,
    LiveForkCapability,
    MergeStrategy,
    PendingApprovalRequest,
    clone_for_branch,
    create_deep_agent,
)
from pydantic_deep.features.checkpointing import InMemoryCheckpointStore
from pydantic_deep.features.forking import NOT_ENABLED_MESSAGE, create_fork_toolset
from pydantic_deep.features.forking.coordinator import _APPROVAL_POLL_INTERVAL_S
from pydantic_deep.features.forking.isolation import _read_backend_bytes
from pydantic_deep.features.message_queue import MessageQueue


def _make_test_agent() -> Agent[DeepAgentDeps, str]:
    return Agent(TestModel(), deps_type=DeepAgentDeps)


def _make_coordinator(
    agent: Agent[DeepAgentDeps, str],
    deps: DeepAgentDeps,
    *,
    max_branches: int = 2,
    max_depth: int = 1,
    checkpoint_store: Any = None,
    materializer_root: Path | None = None,
) -> ForkCoordinator:
    return ForkCoordinator(
        agent=agent,
        parent_deps=deps,
        max_branches=max_branches,
        max_depth=max_depth,
        store=InMemoryForkStateStore(),
        checkpoint_store=checkpoint_store,
        materializer_root=materializer_root,
    )


def _seed_history(text: str) -> list[Any]:
    return [ModelRequest(parts=[UserPromptPart(content=text)])]


# ---------------------------------------------------------------------------
# Test 1 — fork spawns 2 tasks, both see parent history up to fork point.
# ---------------------------------------------------------------------------


async def test_fork_spawns_two_tasks_with_parent_history():
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()
    coord = _make_coordinator(agent, deps, checkpoint_store=InMemoryCheckpointStore())

    parent_history = _seed_history("parent turn 1")
    handle = await coord.fork(
        [BranchSpec(label="a", steer="explore A"), BranchSpec(label="b", steer="explore B")],
        parent_history=parent_history,
    )

    assert isinstance(handle, ForkHandle)
    assert len(handle.branches) == 2
    assert len(coord.branches) == 2

    # Wait for both branch tasks
    await asyncio.gather(*(rt.task for rt in coord.branches.values()))

    for rt in coord.branches.values():
        # The branch run sees the seeded parent message + its steer
        all_msgs = rt.task.result().all_messages()
        seeded_texts = [
            part.content
            for msg in all_msgs
            if isinstance(msg, ModelRequest)
            for part in msg.parts
            if isinstance(part, UserPromptPart)
        ]
        assert "parent turn 1" in seeded_texts


async def test_fork_enforces_unique_non_empty_labels():
    """fork() dedupes duplicate/blank labels so label_to_id can't collapse.

    The agent-facing fork_run tool passes labels through verbatim and has no
    picker to enforce distinctness, so the coordinator must.
    """
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()
    coord = _make_coordinator(
        agent, deps, max_branches=4, checkpoint_store=InMemoryCheckpointStore()
    )

    handle = await coord.fork(
        [
            BranchSpec(label="dup", steer="A"),
            BranchSpec(label="dup", steer="B"),
            BranchSpec(label="", steer="C"),
            BranchSpec(label="   ", steer="D"),
        ],
        parent_history=_seed_history("p"),
    )
    await asyncio.gather(*(rt.task for rt in coord.branches.values()))

    labels = [coord.branches[bid].spec.label for bid in handle.branches]
    # All labels are non-empty and unique.
    assert all(label.strip() for label in labels)
    assert len(set(labels)) == len(labels)
    # The first 'dup' keeps its label; the second is suffixed.
    assert "dup" in labels
    assert "dup-2" in labels


# ---------------------------------------------------------------------------
# Test 2 — each branch gets its `steer` as first new UserPromptPart.
# ---------------------------------------------------------------------------


async def test_each_branch_steer_is_first_new_user_prompt():
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()
    coord = _make_coordinator(agent, deps, checkpoint_store=InMemoryCheckpointStore())

    parent_history = _seed_history("parent")
    await coord.fork(
        [BranchSpec(label="a", steer="A steer"), BranchSpec(label="b", steer="B steer")],
        parent_history=parent_history,
    )

    await asyncio.gather(*(rt.task for rt in coord.branches.values()))

    for rt in coord.branches.values():
        msgs = rt.task.result().all_messages()
        user_texts = [
            part.content
            for msg in msgs
            if isinstance(msg, ModelRequest)
            for part in msg.parts
            if isinstance(part, UserPromptPart)
        ]
        # First entry should be the parent's prior turn, second is the steer
        assert user_texts[0] == "parent"
        assert user_texts[1] == rt.spec.steer


# ---------------------------------------------------------------------------
# Test 3 — BranchOverlay isolates writes.
# ---------------------------------------------------------------------------


def test_branch_overlay_isolates_writes():
    parent = StateBackend()
    parent.write("/foo.py", "v0")

    overlay_a = BranchOverlay(parent)
    overlay_b = BranchOverlay(parent)

    overlay_a.write("/foo.py", "vA")

    assert "vA" in overlay_a.read("/foo.py")
    assert "v0" in overlay_b.read("/foo.py")
    assert "v0" in parent.read("/foo.py")  # Parent untouched


def test_branch_overlay_records_changes():
    parent = StateBackend()
    parent.write("/foo.py", "v0")
    overlay = BranchOverlay(parent)

    overlay.write("/foo.py", "vA")
    overlay.edit("/foo.py", "vA", "vB")

    changes = overlay.changes()
    assert len(changes) == 2
    assert all(isinstance(c, FileChange) for c in changes)
    assert changes[0].op == "write"
    assert changes[1].op == "edit"
    # Mutating the returned list does not affect the overlay's history
    changes.clear()
    assert len(overlay.changes()) == 2


def test_branch_overlay_edit_materializes_from_parent():
    parent = StateBackend()
    parent.write("/foo.py", "hello world")
    overlay = BranchOverlay(parent)

    result = overlay.edit("/foo.py", "hello", "hi")
    assert result.error is None
    assert "hi world" in overlay.read("/foo.py")
    # Parent unchanged
    assert "hello world" in parent.read("/foo.py")


def test_branch_overlay_ls_and_glob_merge():
    parent = StateBackend()
    parent.write("/a.py", "x")
    overlay = BranchOverlay(parent)
    overlay.write("/b.py", "y")

    paths_ls = {e["path"] for e in overlay.ls_info("/")}
    assert "/a.py" in paths_ls
    assert "/b.py" in paths_ls

    paths_glob = {e["path"] for e in overlay.glob_info("**/*.py")}
    assert "/a.py" in paths_glob
    assert "/b.py" in paths_glob


def test_branch_overlay_grep_forwards():
    parent = StateBackend()
    parent.write("/a.py", "hello world")
    overlay = BranchOverlay(parent)

    result = overlay.grep_raw("hello", path="/")
    assert result is not None


def test_branch_overlay_read_bytes_overlay_and_parent():
    parent = StateBackend()
    parent.write("/a.py", "from-parent")
    overlay = BranchOverlay(parent)

    # Falls through to parent
    assert overlay.read_bytes("/a.py") == b"from-parent"

    overlay.write("/a.py", "from-overlay")
    assert overlay.read_bytes("/a.py") == b"from-overlay"


def test_read_backend_bytes_falls_back_to_private_reader():
    class LegacyBackend:
        def _read_bytes(self, path: str) -> bytes:
            assert path == "/legacy.txt"
            return b"legacy"

    assert _read_backend_bytes(LegacyBackend(), "/legacy.txt") == b"legacy"


def test_branch_overlay_parent_property():
    parent = StateBackend()
    overlay = BranchOverlay(parent)
    assert overlay.parent is parent


def test_branch_overlay_exists_falls_through_to_parent():
    """`exists()` returns True for files in either layer, False otherwise."""
    parent = StateBackend()
    parent.write("/parent_only.py", "v0")
    overlay = BranchOverlay(parent)

    # In parent only — fall-through hit.
    assert overlay.exists("/parent_only.py") is True
    # Branch writes — present in overlay.
    overlay.write("/branch_only.py", "vA")
    assert overlay.exists("/branch_only.py") is True
    # Nowhere — False.
    assert overlay.exists("/nothing.py") is False


# ---------------------------------------------------------------------------
# BranchOverlay.delete — tombstone semantics, exists/read masking, mirror to disk
# ---------------------------------------------------------------------------


def test_branch_overlay_delete_records_change():
    parent = StateBackend()
    parent.write("/x.py", "v0")
    overlay = BranchOverlay(parent)

    overlay.delete("/x.py")

    changes = overlay.changes()
    assert len(changes) == 1
    assert changes[0].op == "delete"
    assert changes[0].path == "/x.py"


def test_branch_overlay_delete_hides_path_from_exists():
    parent = StateBackend()
    parent.write("/x.py", "v0")
    overlay = BranchOverlay(parent)

    assert overlay.exists("/x.py") is True
    overlay.delete("/x.py")
    assert overlay.exists("/x.py") is False
    # Parent untouched.
    assert parent.exists("/x.py") is True


def test_branch_overlay_delete_hides_from_reads():
    import pytest as _pytest

    parent = StateBackend()
    parent.write("/x.py", "v0")
    overlay = BranchOverlay(parent)
    overlay.delete("/x.py")

    with _pytest.raises(FileNotFoundError):
        overlay.read("/x.py")
    with _pytest.raises(FileNotFoundError):
        overlay.read_bytes("/x.py")


def test_rmdir_hides_directory_from_ls_info():
    """record_rmdir hides the directory and its children from ls_info."""
    parent = StateBackend()
    parent.write("/proj/jajo/file.txt", "content")
    parent.write("/proj/keep/other.txt", "keep")
    overlay = BranchOverlay(parent)

    entries_before = {e["path"] for e in overlay.ls_info("/proj")}
    assert any(p == "/proj/jajo" or p.startswith("/proj/jajo/") for p in entries_before)

    overlay.record_rmdir("/proj/jajo")

    entries_after = {e["path"] for e in overlay.ls_info("/proj")}
    assert not any(p == "/proj/jajo" or p.startswith("/proj/jajo/") for p in entries_after)
    assert any(p.startswith("/proj/keep") for p in entries_after)


def test_write_inside_rmdir_directory_resurrects_file():
    """Writing a file inside a record_rmdir-ed directory un-deletes it."""
    parent = StateBackend()
    parent.write("/proj/jajo/old.txt", "old")
    overlay = BranchOverlay(parent)

    overlay.record_rmdir("/proj/jajo")
    assert overlay.exists("/proj/jajo/old.txt") is False

    overlay.write("/proj/jajo/new.txt", "new content")
    assert overlay.exists("/proj/jajo/new.txt") is True
    assert overlay.read_bytes("/proj/jajo/new.txt") == b"new content"
    # The old file is also visible again because the directory deletion was lifted.
    assert overlay.exists("/proj/jajo/old.txt") is True


def test_rmdir_hides_children_from_exists():
    """record_rmdir makes children of the deleted directory invisible via exists."""
    parent = StateBackend()
    parent.write("/proj/jajo/file.txt", "content")
    overlay = BranchOverlay(parent)

    assert overlay.exists("/proj/jajo/file.txt") is True

    overlay.record_rmdir("/proj/jajo")

    assert overlay.exists("/proj/jajo/file.txt") is False


def test_rmdir_hides_children_from_read():
    """record_rmdir makes children unreadable."""
    parent = StateBackend()
    parent.write("/proj/jajo/file.txt", "content")
    overlay = BranchOverlay(parent)

    overlay.record_rmdir("/proj/jajo")

    with pytest.raises(FileNotFoundError):
        overlay.read("/proj/jajo/file.txt")
    with pytest.raises(FileNotFoundError):
        overlay.read_bytes("/proj/jajo/file.txt")


def test_rmdir_hides_from_glob_info():
    """record_rmdir hides directory entries from glob_info."""
    parent = StateBackend()
    parent.write("/proj/jajo/file.txt", "content")
    parent.write("/proj/keep/other.txt", "keep")
    overlay = BranchOverlay(parent)

    overlay.record_rmdir("/proj/jajo")

    entries = [e["path"] for e in overlay.glob_info("**/*", "/proj")]
    assert not any("jajo" in p for p in entries)
    assert any("keep" in p for p in entries)


def test_branch_overlay_write_undeletes_path():
    parent = StateBackend()
    parent.write("/x.py", "v0")
    overlay = BranchOverlay(parent)
    overlay.delete("/x.py")
    overlay.write("/x.py", "v1")

    assert overlay.exists("/x.py") is True
    assert "v1" in overlay.read("/x.py")
    assert "/x.py" not in overlay.deleted()


def test_branch_overlay_edit_undeletes_path():
    parent = StateBackend()
    parent.write("/x.py", "abcdef")
    overlay = BranchOverlay(parent)
    overlay.delete("/x.py")
    # Edit re-materialises from parent then applies the edit; the tombstone
    # must be cleared first so the edit pathway re-reads parent bytes.
    res = overlay.edit("/x.py", "abc", "ZZZ")
    assert res.error is None
    assert "/x.py" not in overlay.deleted()
    assert "ZZZ" in overlay.read("/x.py")


def test_branch_overlay_deleted_returns_copy():
    parent = StateBackend()
    parent.write("/x.py", "v0")
    overlay = BranchOverlay(parent)
    overlay.delete("/x.py")

    snapshot = overlay.deleted()
    snapshot.clear()
    assert overlay.deleted() == {"/x.py"}


def test_branch_overlay_mirror_delete_swallows_oserror(tmp_path):
    """OSError from materializer.flush_delete is logged, not propagated."""
    from unittest.mock import patch as _patch

    from pydantic_deep.features.forking.materializer import ForkMaterializer

    parent = StateBackend()
    parent.write("/x.py", "v0")
    materializer = ForkMaterializer(root=tmp_path / "fork1", fork_id="fork1")
    overlay = BranchOverlay(parent)
    overlay.attach_materializer(materializer, "approach_a")

    with _patch.object(materializer, "flush_delete", side_effect=OSError("disk fault")):
        # Must not raise.
        overlay.delete("/x.py")

    assert "/x.py" in overlay.deleted()


def test_flush_to_dedupes_repeat_delete_for_same_path():
    """A path appearing in two consecutive delete ops surfaces once."""

    class _Counting(StateBackend):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__()
            self.deleted_calls: list[str] = []

        def delete(self, path: str) -> None:
            self.deleted_calls.append(path)

    parent = _Counting()
    parent.write("/x.py", "v0")
    overlay = BranchOverlay(parent)
    # Two consecutive deletes — the second exercises the dedup branch
    # in `_flush_delete` (path already in `deleted_set`).
    overlay.delete("/x.py")
    overlay.delete("/x.py")

    report = overlay.flush_to(parent)
    assert report.deleted_paths == ["/x.py"]
    # Both deletes still propagate to the parent — the dedup is bookkeeping.
    assert parent.deleted_calls == ["/x.py", "/x.py"]


# ---------------------------------------------------------------------------
# Test 4 — clone_for_branch honours message_queue isolation flag.
# ---------------------------------------------------------------------------


def test_clone_for_branch_isolated_message_queue():
    parent_queue = MessageQueue()
    deps = DeepAgentDeps(backend=StateBackend(), message_queue=parent_queue)
    cloned = clone_for_branch(deps, BranchIsolation(message_queue="isolated"))
    assert cloned.message_queue is not None
    assert cloned.message_queue is not parent_queue


def test_clone_for_branch_shared_message_queue():
    parent_queue = MessageQueue()
    deps = DeepAgentDeps(backend=StateBackend(), message_queue=parent_queue)
    cloned = clone_for_branch(deps, BranchIsolation(message_queue="shared"))
    assert cloned.message_queue is parent_queue


def test_clone_for_branch_copy_todos():
    deps = DeepAgentDeps(backend=StateBackend())
    deps.todos.append({"id": "1", "content": "x", "status": "pending"})
    cloned = clone_for_branch(deps, BranchIsolation(todos="copy"))
    # "copy" inherits an independent copy of the parent's in-progress plan ...
    assert cloned.todos == deps.todos
    assert cloned.todos is not deps.todos
    # ... and mutating the branch's todos must not affect the parent's.
    cloned.todos.append({"id": "2", "content": "y", "status": "pending"})
    assert len(deps.todos) == 1


def test_clone_for_branch_share_todos():
    deps = DeepAgentDeps(backend=StateBackend())
    deps.todos.append({"id": "1", "content": "x", "status": "pending"})
    cloned = clone_for_branch(deps, BranchIsolation(todos="share"))
    assert cloned.todos is deps.todos


def test_clone_for_branch_share_readonly_backend_no_overlay():
    parent_backend = StateBackend()
    deps = DeepAgentDeps(backend=parent_backend)
    cloned = clone_for_branch(deps, BranchIsolation(backend="share_readonly"))
    assert cloned.backend.unwrap() is parent_backend
    cloned2 = clone_for_branch(deps, BranchIsolation(backend="share"))
    assert cloned2.backend.unwrap() is parent_backend


def test_clone_for_branch_increments_depth():
    deps = DeepAgentDeps(backend=StateBackend())
    assert deps._fork_depth == 0
    cloned = clone_for_branch(deps, BranchIsolation())
    assert cloned._fork_depth == 1


def test_clone_for_branch_drops_subagents_and_coordinator():
    deps = DeepAgentDeps(backend=StateBackend(), subagents={"foo": object()})
    deps.fork_coordinator = cast(Any, "sentinel")
    cloned = clone_for_branch(deps, BranchIsolation())
    assert cloned.subagents == {}
    assert cloned.fork_coordinator is None


# ---------------------------------------------------------------------------
# Test 5 — terminate_branch cancels the task; status becomes terminated.
# ---------------------------------------------------------------------------


async def test_terminate_branch_cancels_task_and_marks_terminated():
    deps = DeepAgentDeps(backend=StateBackend())

    sleep_event = asyncio.Event()

    class _SlowAgent:
        async def run(self, *args: Any, **kwargs: Any) -> Any:
            await sleep_event.wait()
            return None  # pragma: no cover - never reached, task is cancelled

    coord = _make_coordinator(_SlowAgent(), deps, checkpoint_store=InMemoryCheckpointStore())
    await coord.fork(
        [BranchSpec(label="slow", steer="go")],
        parent_history=_seed_history("p"),
    )
    branch_id = next(iter(coord.branches))

    await coord.terminate_branch(branch_id)
    # Give the loop a tick to process the cancellation
    await asyncio.sleep(0)
    assert coord.branches[branch_id].task.cancelled()
    assert coord.branches[branch_id].status.state == "terminated"


async def test_terminate_branch_unknown_id_raises():
    deps = DeepAgentDeps(backend=StateBackend())
    coord = _make_coordinator(_make_test_agent(), deps)
    with pytest.raises(ValueError):
        await coord.terminate_branch("does-not-exist")


async def test_terminate_branch_idempotent_for_finished_task():
    deps = DeepAgentDeps(backend=StateBackend())
    coord = _make_coordinator(_make_test_agent(), deps, checkpoint_store=InMemoryCheckpointStore())
    await coord.fork(
        [BranchSpec(label="quick", steer="go")],
        parent_history=_seed_history("p"),
    )
    branch_id = next(iter(coord.branches))
    await coord.branches[branch_id].task  # let it finish
    await coord.terminate_branch(branch_id)  # should not raise
    # Terminal state from _on_done must NOT be overwritten by a late terminate call.
    assert coord.branches[branch_id].status.state == "done"


# ---------------------------------------------------------------------------
# Test 6 — merge_or_select(pick:<id>) returns MergeResult; overlays released.
# ---------------------------------------------------------------------------


async def test_merge_or_select_picks_winner_and_releases_overlays():
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()
    cp_store = InMemoryCheckpointStore()
    coord = _make_coordinator(agent, deps, checkpoint_store=cp_store)

    parent_history = _seed_history("parent")
    handle = await coord.fork(
        [BranchSpec(label="a", steer="A"), BranchSpec(label="b", steer="B")],
        parent_history=parent_history,
    )

    branch_ids = list(coord.branches.keys())
    winner = branch_ids[0]
    loser = branch_ids[1]

    result = await coord.merge_or_select(f"pick:{winner}")
    assert result.fork_id == handle.fork_id
    assert result.winner_branch_id == winner
    assert result.discarded_branches == [loser]
    assert len(result.history_after_merge) >= 1
    assert coord.branches[loser].overlay is None

    # Post-fork checkpoint saved
    cps = await cp_store.list_all()
    labels = {cp.label for cp in cps}
    assert f"fork:{handle.fork_id}" in labels
    assert f"post-fork:{handle.fork_id}" in labels


async def test_merge_or_select_quiesces_losers_before_winner_flush():
    """Losing branches must be cancelled + awaited BEFORE the winner is flushed.

    Otherwise a not-yet-cancelled loser whose overlay reads fall through to the
    shared parent could observe the winner's just-flushed bytes — cross-branch
    state leaking into its tool results / partial_history.
    """
    deps = DeepAgentDeps(backend=StateBackend())

    class _Result:
        def all_messages(self) -> list[Any]:
            return _seed_history("winner-done")

    class _SteerAgent:
        async def run(self, steer: Any, *args: Any, **kwargs: Any) -> Any:
            if steer == "B":
                await asyncio.Event().wait()  # loser blocks until cancelled
                return None  # pragma: no cover
            return _Result()  # winner completes immediately

    coord = _make_coordinator(_SteerAgent(), deps, checkpoint_store=InMemoryCheckpointStore())
    await coord.fork(
        [BranchSpec(label="a", steer="A"), BranchSpec(label="b", steer="B")],
        parent_history=_seed_history("p"),
    )
    winner_id = next(bid for bid, rt in coord.branches.items() if rt.spec.steer == "A")
    loser_id = next(bid for bid, rt in coord.branches.items() if rt.spec.steer == "B")

    # Winner finishes; loser is still blocked when we start the merge.
    await coord.branches[winner_id].task
    assert not coord.branches[loser_id].task.done()

    captured: dict[str, Any] = {}
    winner_overlay = coord.branches[winner_id].overlay
    assert winner_overlay is not None
    real_flush = winner_overlay.flush_to

    def _spy_flush(*a: Any, **k: Any) -> Any:
        captured["loser_done_at_flush"] = coord.branches[loser_id].task.done()
        return real_flush(*a, **k)

    winner_overlay.flush_to = _spy_flush  # type: ignore[method-assign]

    result = await coord.merge_or_select(f"pick:{winner_id}")
    assert result.winner_branch_id == winner_id
    # The loser was quiesced (cancelled + awaited to done) before the winner flushed.
    assert captured["loser_done_at_flush"] is True


async def test_merge_or_select_invalid_action_raises():
    deps = DeepAgentDeps(backend=StateBackend())
    coord = _make_coordinator(_make_test_agent(), deps, checkpoint_store=InMemoryCheckpointStore())
    await coord.fork(
        [BranchSpec(label="a", steer="A")],
        parent_history=_seed_history("p"),
    )
    with pytest.raises(ValueError):
        await coord.merge_or_select("reject")
    with pytest.raises(ValueError):
        await coord.merge_or_select("pick:")
    with pytest.raises(ValueError):
        await coord.merge_or_select("pick:does-not-exist")


# ---------------------------------------------------------------------------
# Test 7 — max_branches=2 rejects a 3rd branch with ForkBranchLimitError.
# ---------------------------------------------------------------------------


async def test_max_branches_rejects_third():
    deps = DeepAgentDeps(backend=StateBackend())
    coord = _make_coordinator(_make_test_agent(), deps, checkpoint_store=InMemoryCheckpointStore())
    with pytest.raises(ForkBranchLimitError):
        await coord.fork(
            [
                BranchSpec(label="a", steer="A"),
                BranchSpec(label="b", steer="B"),
                BranchSpec(label="c", steer="C"),
            ],
            parent_history=_seed_history("p"),
        )


async def test_empty_specs_rejected():
    deps = DeepAgentDeps(backend=StateBackend())
    coord = _make_coordinator(_make_test_agent(), deps, checkpoint_store=InMemoryCheckpointStore())
    with pytest.raises(ValueError):
        await coord.fork([], parent_history=_seed_history("p"))


# ---------------------------------------------------------------------------
# Test 8 — max_depth=1 rejects nested fork_run calls with ForkDepthLimitError.
# ---------------------------------------------------------------------------


async def test_max_depth_rejects_nested():
    # Parent already at depth 1 (e.g. running inside a branch)
    deps = DeepAgentDeps(backend=StateBackend(), _fork_depth=1)
    coord = _make_coordinator(_make_test_agent(), deps, checkpoint_store=InMemoryCheckpointStore())
    with pytest.raises(ForkDepthLimitError):
        await coord.fork(
            [BranchSpec(label="a", steer="A")],
            parent_history=_seed_history("p"),
        )


# ---------------------------------------------------------------------------
# Test 9 — for_run() isolation — concurrent runs get independent coordinators.
# ---------------------------------------------------------------------------


async def test_for_run_produces_independent_coordinators():
    cap = LiveForkCapability()
    cap._agent_ref = _make_test_agent()

    deps1 = DeepAgentDeps(backend=StateBackend())
    deps2 = DeepAgentDeps(backend=StateBackend())

    class _Ctx:
        def __init__(self, deps: DeepAgentDeps) -> None:
            self.deps = deps

    clone1 = await cap.for_run(_Ctx(deps1))
    clone2 = await cap.for_run(_Ctx(deps2))

    assert clone1 is not clone2
    assert deps1.fork_coordinator is not None
    assert deps2.fork_coordinator is not None
    assert deps1.fork_coordinator is not deps2.fork_coordinator
    assert deps1.fork_coordinator.branches == {}
    assert deps2.fork_coordinator.branches == {}


# ---------------------------------------------------------------------------
# Capability-level coverage
# ---------------------------------------------------------------------------


def test_live_fork_capability_default_store():
    cap = LiveForkCapability()
    assert isinstance(cap.store, InMemoryForkStateStore)


def test_live_fork_capability_user_store():
    store = InMemoryForkStateStore()
    cap = LiveForkCapability(store=store)
    assert cap.store is store


async def test_capability_before_model_request_tracks_messages():
    cap = LiveForkCapability()

    class _Req:
        def __init__(self, msgs: list[Any]) -> None:
            self.messages = msgs

    seeded = [object(), object()]

    class _Ctx:
        deps = DeepAgentDeps(backend=StateBackend())

    result = await cap.before_model_request(_Ctx(), _Req(seeded))
    assert cap._latest_messages == seeded
    assert result.messages == seeded


# ---------------------------------------------------------------------------
# Checkpoint integration — warning when no store available
# ---------------------------------------------------------------------------


async def test_fork_warns_when_no_checkpoint_store():
    deps = DeepAgentDeps(backend=StateBackend())
    coord = _make_coordinator(_make_test_agent(), deps, checkpoint_store=None)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        handle = await coord.fork(
            [BranchSpec(label="a", steer="A")],
            parent_history=_seed_history("p"),
        )
    assert any("checkpoint" in str(w.message).lower() for w in caught)
    assert handle.parent_checkpoint_id is None


async def test_fork_no_warning_with_checkpoint_store():
    deps = DeepAgentDeps(backend=StateBackend())
    cp_store = InMemoryCheckpointStore()
    coord = _make_coordinator(_make_test_agent(), deps, checkpoint_store=cp_store)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        handle = await coord.fork(
            [BranchSpec(label="a", steer="A")],
            parent_history=_seed_history("p"),
        )
    assert handle.parent_checkpoint_id is not None
    assert not any("checkpoint" in str(w.message).lower() for w in caught)


async def test_fork_uses_deps_checkpoint_store_when_explicit_none():
    cp_store = InMemoryCheckpointStore()
    deps = DeepAgentDeps(backend=StateBackend())
    deps.checkpoint_store = cp_store
    coord = _make_coordinator(_make_test_agent(), deps, checkpoint_store=None)
    handle = await coord.fork(
        [BranchSpec(label="a", steer="A")],
        parent_history=_seed_history("p"),
    )
    assert handle.parent_checkpoint_id is not None


# ---------------------------------------------------------------------------
# Branch status transitions: done / failed
# ---------------------------------------------------------------------------


async def test_branch_status_transitions_to_done_on_success():
    deps = DeepAgentDeps(backend=StateBackend())
    coord = _make_coordinator(_make_test_agent(), deps, checkpoint_store=InMemoryCheckpointStore())
    await coord.fork(
        [BranchSpec(label="a", steer="A")],
        parent_history=_seed_history("p"),
    )
    rt = next(iter(coord.branches.values()))
    await rt.task
    await asyncio.sleep(0)
    assert rt.status.state == "done"


async def test_branch_status_transitions_to_failed_on_exception():
    deps = DeepAgentDeps(backend=StateBackend())

    class _FailingAgent:
        async def run(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("boom")

    coord = _make_coordinator(_FailingAgent(), deps, checkpoint_store=InMemoryCheckpointStore())
    await coord.fork(
        [BranchSpec(label="a", steer="A")],
        parent_history=_seed_history("p"),
    )
    rt = next(iter(coord.branches.values()))
    with pytest.raises(RuntimeError):
        await rt.task
    await asyncio.sleep(0)
    assert rt.status.state == "failed"
    assert rt.status.error and "boom" in rt.status.error


# ---------------------------------------------------------------------------
# Coordinator aclose cancels outstanding tasks
# ---------------------------------------------------------------------------


async def test_coordinator_aclose_cancels_outstanding_tasks():
    deps = DeepAgentDeps(backend=StateBackend())
    sleep_event = asyncio.Event()

    class _SlowAgent:
        async def run(self, *args: Any, **kwargs: Any) -> Any:
            await sleep_event.wait()
            return None  # pragma: no cover

    coord = _make_coordinator(_SlowAgent(), deps, checkpoint_store=InMemoryCheckpointStore())
    await coord.fork(
        [BranchSpec(label="a", steer="A")],
        parent_history=_seed_history("p"),
    )
    await coord.aclose()
    await asyncio.sleep(0)
    rt = next(iter(coord.branches.values()))
    assert rt.task.cancelled()


async def test_coordinator_aclose_awaits_tasks_before_cleanup(tmp_path: Path) -> None:
    """aclose must await cancelled branch tasks to quiescence *before* rmtree.

    Otherwise a branch still unwinding mid-write can recreate part of the fork
    directory after cleanup, leaking an orphaned dir. The slow agent here keeps
    running until cancelled and only finishes its unwind after an extra await.
    """
    deps = DeepAgentDeps(backend=StateBackend())
    started = asyncio.Event()

    class _SlowUnwindAgent:
        async def run(self, *args: Any, **kwargs: Any) -> Any:
            started.set()
            try:
                await asyncio.Event().wait()  # block forever until cancelled
            except asyncio.CancelledError:
                # Simulate cleanup work during unwind that yields control.
                await asyncio.sleep(0)
                raise

    materializer_root = tmp_path / "forks"
    coord = _make_coordinator(
        _SlowUnwindAgent(),
        deps,
        checkpoint_store=InMemoryCheckpointStore(),
        materializer_root=materializer_root,
    )
    await coord.fork(
        [BranchSpec(label="a", steer="A")],
        parent_history=_seed_history("p"),
    )
    await started.wait()
    assert coord.materializer is not None
    fork_dir = coord.materializer.root
    assert fork_dir.exists()

    await coord.aclose()

    rt = next(iter(coord.branches.values()))
    # The fix awaits the task: it is fully done (not merely scheduled for cancel)
    # by the time aclose returns — no extra event-loop tick needed.
    assert rt.task.done()
    # And the fork directory is removed with nothing left behind.
    assert not fork_dir.exists()


# ---------------------------------------------------------------------------
# merge_or_select fails fast when winner task was already cancelled
# ---------------------------------------------------------------------------


async def test_merge_or_select_falls_back_to_pre_fork_history_when_winner_terminated_empty():
    """A winner terminated before recording any partial history falls back.

    Bug 82: a branch cancelled before its first `before_model_request` hook
    fired has an empty `partial_history` even though its state is a valid
    exhausted state (`"terminated"`). Rather than spuriously raising, the
    merge falls back to the pre-fork parent history so the resolution still
    completes.
    """
    deps = DeepAgentDeps(backend=StateBackend())
    sleep_event = asyncio.Event()

    class _SlowAgent:
        async def run(self, *args: Any, **kwargs: Any) -> Any:
            await sleep_event.wait()
            return None  # pragma: no cover

    coord = _make_coordinator(_SlowAgent(), deps, checkpoint_store=InMemoryCheckpointStore())
    parent_history = _seed_history("p")
    await coord.fork(
        [BranchSpec(label="a", steer="A")],
        parent_history=parent_history,
    )
    branch_id = next(iter(coord.branches))
    await coord.terminate_branch(branch_id)
    await asyncio.sleep(0)
    assert coord.branches[branch_id].status.state == "terminated"
    assert not coord.branches[branch_id].partial_history

    result = await coord.merge_or_select(f"pick:{branch_id}")
    assert result.winner_branch_id == branch_id
    # Fallback uses the pre-fork parent history, not an empty list.
    assert result.history_after_merge == parent_history


async def test_merge_or_select_raises_if_winner_cancelled_in_non_exhausted_state():
    """A winner cancelled while NOT in an exhausted state still raises.

    The pre-fork fallback only applies to valid exhausted states; an
    out-of-band cancellation that leaves the status non-terminal must surface
    the original RuntimeError so callers can handle the unexpected case.
    """
    deps = DeepAgentDeps(backend=StateBackend())
    sleep_event = asyncio.Event()

    class _SlowAgent:
        async def run(self, *args: Any, **kwargs: Any) -> Any:
            await sleep_event.wait()
            return None  # pragma: no cover

    coord = _make_coordinator(_SlowAgent(), deps, checkpoint_store=InMemoryCheckpointStore())
    await coord.fork(
        [BranchSpec(label="a", steer="A")],
        parent_history=_seed_history("p"),
    )
    branch_id = next(iter(coord.branches))
    rt = coord.branches[branch_id]
    # Force a non-exhausted terminal state ("failed") BEFORE cancelling so the
    # done-callback (which only rewrites "running" -> "terminated") leaves it
    # alone. The winner await still raises CancelledError, but the guard's
    # exhausted-state check is False, so the original RuntimeError surfaces.
    rt.status.state = "failed"
    rt.task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await rt.task
    assert rt.status.state == "failed"
    with pytest.raises(RuntimeError, match="was cancelled before merge"):
        await coord.merge_or_select(f"pick:{branch_id}")


async def test_merge_or_select_wraps_failed_winner_exception():
    """A *failed* winner (branch raised) yields a typed RuntimeError, not the raw exc.

    This is the path the merge_or_select tool catches via `except (ValueError,
    RuntimeError)` — proving picking a failed branch resolves gracefully instead
    of aborting agent.run().
    """
    deps = DeepAgentDeps(backend=StateBackend())

    class _FailingAgent:
        async def run(self, *args: Any, **kwargs: Any) -> Any:
            raise ValueError("branch blew up")

    coord = _make_coordinator(_FailingAgent(), deps, checkpoint_store=InMemoryCheckpointStore())
    await coord.fork(
        [BranchSpec(label="a", steer="A")],
        parent_history=_seed_history("p"),
    )
    branch_id = next(iter(coord.branches))
    # Let the branch task run and fail.
    rt = coord.branches[branch_id]
    with contextlib.suppress(Exception):
        await rt.task
    await asyncio.sleep(0)
    assert rt.status.state == "failed"

    with pytest.raises(RuntimeError) as excinfo:
        await coord.merge_or_select(f"pick:{branch_id}")
    # The raw ValueError is wrapped, not propagated, so the tool's RuntimeError
    # handler catches it and returns a graceful string.
    assert "failed before merge" in str(excinfo.value)
    assert "branch blew up" in str(excinfo.value)


async def test_merge_or_select_does_not_hold_lock_while_awaiting_winner():
    """The winner await must happen outside self._lock.

    A winner parked on a pending human tool-approval (or just a long run) would
    otherwise hold the coordinator lock for that unbounded duration, freezing
    every other lock user (fork, run_on_branch, abort, the budget watcher).
    """
    deps = DeepAgentDeps(backend=StateBackend())
    release = asyncio.Event()

    class _Result:
        def all_messages(self) -> list[Any]:
            return _seed_history("winner-done")

    class _BlockingAgent:
        async def run(self, *args: Any, **kwargs: Any) -> Any:
            await release.wait()
            return _Result()

    coord = _make_coordinator(_BlockingAgent(), deps, checkpoint_store=InMemoryCheckpointStore())
    await coord.fork(
        [BranchSpec(label="a", steer="A")],
        parent_history=_seed_history("p"),
    )
    branch_id = next(iter(coord.branches))

    merge_task = asyncio.create_task(coord.merge_or_select(f"pick:{branch_id}"))
    # Let merge_or_select reach the (blocked) winner await.
    await asyncio.sleep(0)
    assert not merge_task.done()

    # While the winner is parked, the coordinator lock must remain free and acquirable.
    assert not coord._lock.locked()
    await asyncio.wait_for(coord._lock.acquire(), timeout=1.0)
    coord._lock.release()

    # Unblock the winner; the merge then completes normally.
    release.set()
    result = await asyncio.wait_for(merge_task, timeout=2.0)
    assert result.winner_branch_id == branch_id


# ---------------------------------------------------------------------------
# inspect_branches snapshot
# ---------------------------------------------------------------------------


async def test_inspect_branches_returns_snapshot():
    deps = DeepAgentDeps(backend=StateBackend())
    coord = _make_coordinator(_make_test_agent(), deps, checkpoint_store=InMemoryCheckpointStore())
    snap = coord.inspect_branches()
    assert snap == []
    await coord.fork(
        [BranchSpec(label="a", steer="A")],
        parent_history=_seed_history("p"),
    )
    snap = coord.inspect_branches()
    assert len(snap) == 1
    assert snap[0].label == "a"


# ---------------------------------------------------------------------------
# Toolset tool wrappers — tested directly via FunctionToolset
# ---------------------------------------------------------------------------


def _build_capability_with_coordinator(deps: DeepAgentDeps) -> LiveForkCapability:
    cap = LiveForkCapability()
    cap._agent_ref = _make_test_agent()
    cap._latest_messages = _seed_history("parent")
    coord = ForkCoordinator(
        agent=cap._agent_ref,
        parent_deps=deps,
        max_branches=cap.max_branches,
        max_depth=cap.max_depth,
        store=cap.store,
        checkpoint_store=InMemoryCheckpointStore(),
    )
    coord.capability = cap
    deps.fork_coordinator = coord
    return cap


class _StubCtx:
    def __init__(self, deps: DeepAgentDeps) -> None:
        self.deps = deps


async def test_fork_tool_returns_disabled_when_no_coordinator():
    deps = DeepAgentDeps(backend=StateBackend())
    toolset = create_fork_toolset()
    fork_fn = toolset.tools["fork_run"].function
    out = await fork_fn(_StubCtx(deps), [{"label": "a", "steer": "go"}], None, None)
    assert out == NOT_ENABLED_MESSAGE


async def test_inspect_tool_returns_disabled_when_no_coordinator():
    deps = DeepAgentDeps(backend=StateBackend())
    toolset = create_fork_toolset()
    inspect_fn = toolset.tools["inspect_branches"].function
    out = await inspect_fn(_StubCtx(deps))
    assert out == NOT_ENABLED_MESSAGE


async def test_merge_tool_returns_disabled_when_no_coordinator():
    deps = DeepAgentDeps(backend=StateBackend())
    toolset = create_fork_toolset()
    merge_fn = toolset.tools["merge_or_select"].function
    out = await merge_fn(_StubCtx(deps), "pick:x")
    assert out == NOT_ENABLED_MESSAGE


async def test_terminate_tool_returns_disabled_when_no_coordinator():
    deps = DeepAgentDeps(backend=StateBackend())
    toolset = create_fork_toolset()
    terminate_fn = toolset.tools["terminate_branch"].function
    out = await terminate_fn(_StubCtx(deps), "x")
    assert out == NOT_ENABLED_MESSAGE


async def test_fork_tool_happy_path():
    deps = DeepAgentDeps(backend=StateBackend())
    _build_capability_with_coordinator(deps)
    toolset = create_fork_toolset()
    fork_fn = toolset.tools["fork_run"].function
    out = await fork_fn(
        _StubCtx(deps),
        [{"label": "a", "steer": "A"}, {"label": "b", "steer": "B"}],
        None,
        {"kind": "manual"},
    )
    assert "Forked: fork_id=" in out
    # wait for branches to complete
    coord = deps.fork_coordinator
    assert coord is not None
    await asyncio.gather(*(rt.task for rt in coord.branches.values()))


async def test_fork_tool_strips_trailing_model_request_from_parent_history():
    """fork_run strips a trailing ModelRequest from latest_messages.

    `before_model_request` captures the in-progress request, so the snapshot
    always ends with a ModelRequest.  Passing that verbatim to branches would
    create two consecutive ModelRequests, which pydantic-ai rejects.  The tool
    must strip it so branches receive a history ending with a ModelResponse.
    """
    deps = DeepAgentDeps(backend=StateBackend())
    cap = LiveForkCapability()
    cap._agent_ref = _make_test_agent()
    # Simulate a snapshot that includes the current in-progress ModelRequest
    # at the end (exactly what before_model_request captures).
    cap._latest_messages = [
        ModelRequest(parts=[UserPromptPart(content="user turn 1")]),
        ModelResponse(parts=[TextPart(content="assistant reply")]),
        ModelRequest(parts=[UserPromptPart(content="in-progress request")]),
    ]
    assert cap.store is not None
    coord = ForkCoordinator(
        agent=cap._agent_ref,
        parent_deps=deps,
        max_branches=cap.max_branches,
        max_depth=cap.max_depth,
        store=cap.store,
        checkpoint_store=InMemoryCheckpointStore(),
    )
    coord.capability = cap
    deps.fork_coordinator = coord

    toolset = create_fork_toolset()
    fork_fn = toolset.tools["fork_run"].function
    out = await fork_fn(
        _StubCtx(deps),
        [{"label": "a", "steer": "A"}],
        None,
        {"kind": "manual"},
    )
    assert "Forked: fork_id=" in out
    # Branches should have received only the first two messages (the trailing
    # ModelRequest was stripped), so the history passed to agent.run() is valid.
    await asyncio.gather(*(rt.task for rt in coord.branches.values()))
    for rt in coord.branches.values():
        all_msgs = rt.task.result().all_messages()
        user_texts = [
            part.content
            for msg in all_msgs
            if isinstance(msg, ModelRequest)
            for part in msg.parts
            if isinstance(part, UserPromptPart)
        ]
        # "in-progress request" was stripped — should NOT appear in branch history
        assert "in-progress request" not in user_texts
        # The steer ("A") should be present as the new first request
        assert "A" in user_texts


async def test_fork_tool_no_strip_when_history_ends_with_response():
    """When latest_messages ends with a ModelResponse, nothing is stripped."""
    deps = DeepAgentDeps(backend=StateBackend())
    cap = LiveForkCapability()
    cap._agent_ref = _make_test_agent()
    cap._latest_messages = [
        ModelRequest(parts=[UserPromptPart(content="user turn 1")]),
        ModelResponse(parts=[TextPart(content="assistant reply")]),
    ]
    assert cap.store is not None
    coord = ForkCoordinator(
        agent=cap._agent_ref,
        parent_deps=deps,
        max_branches=cap.max_branches,
        max_depth=cap.max_depth,
        store=cap.store,
        checkpoint_store=InMemoryCheckpointStore(),
    )
    coord.capability = cap
    deps.fork_coordinator = coord

    toolset = create_fork_toolset()
    fork_fn = toolset.tools["fork_run"].function
    out = await fork_fn(
        _StubCtx(deps),
        [{"label": "b", "steer": "B"}],
        None,
        {"kind": "manual"},
    )
    assert "Forked: fork_id=" in out
    await asyncio.gather(*(rt.task for rt in coord.branches.values()))


async def test_fork_tool_returns_error_string_on_limit():
    deps = DeepAgentDeps(backend=StateBackend())
    cap = LiveForkCapability(max_branches=2)
    cap._agent_ref = _make_test_agent()
    cap._latest_messages = _seed_history("parent")
    assert cap.store is not None
    coord = ForkCoordinator(
        agent=cap._agent_ref,
        parent_deps=deps,
        max_branches=cap.max_branches,
        max_depth=cap.max_depth,
        store=cap.store,
        checkpoint_store=InMemoryCheckpointStore(),
    )
    coord.capability = cap
    deps.fork_coordinator = coord

    toolset = create_fork_toolset()
    fork_fn = toolset.tools["fork_run"].function
    out = await fork_fn(
        _StubCtx(deps),
        [
            {"label": "a", "steer": "A"},
            {"label": "b", "steer": "B"},
            {"label": "c", "steer": "C"},
        ],
        None,
        None,
    )
    assert "fork_run failed" in out


async def test_inspect_tool_renders_status():
    deps = DeepAgentDeps(backend=StateBackend())
    cap = _build_capability_with_coordinator(deps)
    toolset = create_fork_toolset()
    fork_fn = toolset.tools["fork_run"].function
    await fork_fn(_StubCtx(deps), [{"label": "a", "steer": "A"}], None, None)
    inspect_fn = toolset.tools["inspect_branches"].function
    out = await inspect_fn(_StubCtx(deps))
    assert "(a):" in out
    # Wait for branch task to complete; also keep cap referenced so coverage path runs
    assert cap is not None
    assert deps.fork_coordinator is not None
    await asyncio.gather(*(rt.task for rt in deps.fork_coordinator.branches.values()))


async def test_inspect_tool_no_active_branches():
    deps = DeepAgentDeps(backend=StateBackend())
    _build_capability_with_coordinator(deps)
    toolset = create_fork_toolset()
    inspect_fn = toolset.tools["inspect_branches"].function
    out = await inspect_fn(_StubCtx(deps))
    assert out == "No active branches."


async def test_merge_tool_returns_error_on_bad_action():
    deps = DeepAgentDeps(backend=StateBackend())
    _build_capability_with_coordinator(deps)
    toolset = create_fork_toolset()
    fork_fn = toolset.tools["fork_run"].function
    await fork_fn(_StubCtx(deps), [{"label": "a", "steer": "A"}], None, None)
    merge_fn = toolset.tools["merge_or_select"].function
    out = await merge_fn(_StubCtx(deps), "bogus-action")
    assert "merge_or_select failed" in out
    # cleanup: pick the only branch to merge
    assert deps.fork_coordinator is not None
    branch_id = next(iter(deps.fork_coordinator.branches))
    await merge_fn(_StubCtx(deps), f"pick:{branch_id}")


async def test_merge_tool_happy_path():
    deps = DeepAgentDeps(backend=StateBackend())
    _build_capability_with_coordinator(deps)
    toolset = create_fork_toolset()
    fork_fn = toolset.tools["fork_run"].function
    await fork_fn(_StubCtx(deps), [{"label": "a", "steer": "A"}], None, None)
    assert deps.fork_coordinator is not None
    branch_id = next(iter(deps.fork_coordinator.branches))
    merge_fn = toolset.tools["merge_or_select"].function
    out = await merge_fn(_StubCtx(deps), f"pick:{branch_id}")
    # Output renders winner as "label (short-id)" so the agent (and the user
    # reading the tool log) sees the human-friendly branch name, not just the UUID.
    assert "winner=a (" in out
    assert branch_id[:8] in out


async def test_merge_tool_action_auto_uses_judge_and_commits():
    """action='auto' calls coordinator.resolve() and commits via judge verdict."""
    from unittest.mock import patch

    from pydantic_deep import JudgeVerdict

    deps = DeepAgentDeps(backend=StateBackend())
    _build_capability_with_coordinator(deps)
    toolset = create_fork_toolset()
    fork_fn = toolset.tools["fork_run"].function
    # Fork with an auto strategy so resolve() commits immediately.
    await fork_fn(
        _StubCtx(deps),
        [{"label": "a", "steer": "A"}, {"label": "b", "steer": "B"}],
        None,
        {"kind": "auto"},
    )
    assert deps.fork_coordinator is not None
    coord = deps.fork_coordinator
    # Wait for branches so the coordinator has outcomes to judge.
    await asyncio.gather(*(rt.task for rt in coord.branches.values()))
    winner_id = next(iter(coord.branches))

    # Stub the judge so we don't need a real API key.
    class _FakeJudge:
        def __init__(self, model: Any) -> None:
            pass

        async def evaluate(self, goal: str, diff_report: Any, outcomes: list[Any]) -> Any:
            return JudgeVerdict(winner_branch_id=winner_id, reasoning="fake", confidence=0.9), None

    merge_fn = toolset.tools["merge_or_select"].function
    with patch("pydantic_deep.features.forking.coordinator.JudgeAgent", _FakeJudge):
        out = await merge_fn(_StubCtx(deps), "auto")
    # Should have committed the merge automatically.
    assert "winner=" in out
    assert coord.is_resolved


async def test_merge_tool_action_auto_on_manual_strategy_returns_advisory():
    """action='auto' on a manual-strategy fork falls back to a human-readable error."""
    deps = DeepAgentDeps(backend=StateBackend())
    _build_capability_with_coordinator(deps)
    toolset = create_fork_toolset()
    fork_fn = toolset.tools["fork_run"].function
    # Fork with manual strategy — resolve() is a no-op (returns manual outcome).
    await fork_fn(
        _StubCtx(deps),
        [{"label": "a", "steer": "A"}],
        None,
        {"kind": "manual"},
    )
    assert deps.fork_coordinator is not None
    coord = deps.fork_coordinator
    await asyncio.gather(*(rt.task for rt in coord.branches.values()))

    merge_fn = toolset.tools["merge_or_select"].function
    out = await merge_fn(_StubCtx(deps), "auto")
    # Should surface a message telling the agent to pick explicitly.
    assert "manual" in out.lower()
    # Fork should still be unresolved (we didn't commit).
    assert not coord.is_resolved
    # Cleanup: commit the winner so tests don't leak open branches.
    branch_id = next(iter(coord.branches))
    await merge_fn(_StubCtx(deps), f"pick:{branch_id}")


async def test_merge_tool_action_abort_discards_all_branches():
    """action='abort' releases overlays and cancels every branch without merging."""
    deps = DeepAgentDeps(backend=StateBackend())
    _build_capability_with_coordinator(deps)
    toolset = create_fork_toolset()
    fork_fn = toolset.tools["fork_run"].function
    await fork_fn(
        _StubCtx(deps),
        [{"label": "a", "steer": "A"}, {"label": "b", "steer": "B"}],
        None,
        {"kind": "manual"},
    )
    assert deps.fork_coordinator is not None
    coord = deps.fork_coordinator
    # Don't even wait for branches — abort should cancel any still-running task.
    merge_fn = toolset.tools["merge_or_select"].function
    out = await merge_fn(_StubCtx(deps), "abort")
    assert "aborted" in out.lower()
    # Every branch should have its overlay released.
    assert all(rt.overlay is None for rt in coord.branches.values())
    # Coordinator should report itself resolved (no overlays left).
    assert coord.is_resolved


async def test_merge_tool_action_auto_autoaborts_when_all_branches_failed():
    """action='auto' auto-aborts when every branch is in a failed state."""
    deps = DeepAgentDeps(backend=StateBackend())
    _build_capability_with_coordinator(deps)
    toolset = create_fork_toolset()
    fork_fn = toolset.tools["fork_run"].function
    await fork_fn(
        _StubCtx(deps),
        [{"label": "a", "steer": "A"}, {"label": "b", "steer": "B"}],
        None,
        {"kind": "auto"},
    )
    assert deps.fork_coordinator is not None
    coord = deps.fork_coordinator
    # Wait for branches to reach terminal state, then force them to "failed".
    await asyncio.gather(*(rt.task for rt in coord.branches.values()))
    for rt in coord.branches.values():
        rt.status.state = "failed"
        rt.status.error = "synthetic test failure"

    merge_fn = toolset.tools["merge_or_select"].function
    # The judge must NOT be called when we already know everything failed.
    out = await merge_fn(_StubCtx(deps), "auto")
    assert "every branch failed" in out.lower() or "fork aborted" in out.lower()
    assert "synthetic test failure" in out
    # All overlays released; nothing further to merge.
    assert all(rt.overlay is None for rt in coord.branches.values())


async def test_coordinator_abort_fork_releases_overlays():
    """ForkCoordinator.abort_fork cancels tasks and releases overlays."""
    deps = DeepAgentDeps(backend=StateBackend())
    _build_capability_with_coordinator(deps)
    toolset = create_fork_toolset()
    fork_fn = toolset.tools["fork_run"].function
    await fork_fn(
        _StubCtx(deps),
        [{"label": "a", "steer": "A"}, {"label": "b", "steer": "B"}],
        None,
        {"kind": "manual"},
    )
    assert deps.fork_coordinator is not None
    coord = deps.fork_coordinator
    aborted = await coord.abort_fork()
    assert len(aborted) == 2
    assert all(rt.overlay is None for rt in coord.branches.values())


async def test_coordinator_abort_fork_raises_when_not_forked():
    """abort_fork on a coordinator without an active fork raises RuntimeError."""
    deps = DeepAgentDeps(backend=StateBackend())
    cap = _build_capability_with_coordinator(deps)
    assert deps.fork_coordinator is not None
    # Don't call fork(); abort_fork should error.
    with pytest.raises(RuntimeError, match="abort_fork called before fork"):
        await deps.fork_coordinator.abort_fork()
    del cap  # silence unused-variable


async def test_merge_tool_abort_fails_gracefully_when_no_fork():
    """action='abort' on a coordinator without an active fork returns a clean error."""
    deps = DeepAgentDeps(backend=StateBackend())
    _build_capability_with_coordinator(deps)
    toolset = create_fork_toolset()
    merge_fn = toolset.tools["merge_or_select"].function
    out = await merge_fn(_StubCtx(deps), "abort")
    assert "abort failed" in out.lower()


async def test_terminate_tool_happy_path():
    deps = DeepAgentDeps(backend=StateBackend())
    _build_capability_with_coordinator(deps)
    toolset = create_fork_toolset()
    fork_fn = toolset.tools["fork_run"].function
    await fork_fn(_StubCtx(deps), [{"label": "a", "steer": "A"}], None, None)
    assert deps.fork_coordinator is not None
    branch_id = next(iter(deps.fork_coordinator.branches))
    terminate_fn = toolset.tools["terminate_branch"].function
    out = await terminate_fn(_StubCtx(deps), branch_id)
    assert "terminated" in out


async def test_terminate_tool_unknown_id():
    deps = DeepAgentDeps(backend=StateBackend())
    _build_capability_with_coordinator(deps)
    toolset = create_fork_toolset()
    terminate_fn = toolset.tools["terminate_branch"].function
    out = await terminate_fn(_StubCtx(deps), "bogus")
    assert "terminate_branch failed" in out


# ---------------------------------------------------------------------------
# Store coverage
# ---------------------------------------------------------------------------


async def test_in_memory_fork_state_store_crud():
    store = InMemoryForkStateStore()
    handle = ForkHandle(
        fork_id="f1",
        parent_checkpoint_id=None,
        branches=["b1"],
        merge_strategy=MergeStrategy(),
        created_at=__import__("datetime").datetime.now(),
    )
    await store.save(handle)
    assert (await store.get("f1")) is handle
    assert (await store.get("missing")) is None
    assert (await store.list_all()) == [handle]
    assert await store.remove("f1") is True
    assert await store.remove("f1") is False


# ---------------------------------------------------------------------------
# Factory integration — forking=True wires the capability + toolset
# ---------------------------------------------------------------------------


async def test_merge_or_select_cancels_still_running_discarded_branches():
    """Covers merge_or_select branch that cancels a still-running loser."""
    deps = DeepAgentDeps(backend=StateBackend())
    quick_finished = asyncio.Event()
    slow_release = asyncio.Event()

    class _MixedAgent:
        async def run(self, prompt: Any, **kwargs: Any) -> Any:
            if prompt == "fast":
                quick_finished.set()
                return _MixedResult([])
            await slow_release.wait()
            return _MixedResult([])  # pragma: no cover - never reached

    class _MixedResult:
        def __init__(self, msgs: list[Any]) -> None:
            self._msgs = msgs

        def all_messages(self) -> list[Any]:
            return list(self._msgs)

    coord = _make_coordinator(_MixedAgent(), deps, checkpoint_store=InMemoryCheckpointStore())
    await coord.fork(
        [BranchSpec(label="fast", steer="fast"), BranchSpec(label="slow", steer="slow")],
        parent_history=_seed_history("p"),
    )
    await quick_finished.wait()
    # Pick the winner via label = "fast"
    winner_id = next(bid for bid, rt in coord.branches.items() if rt.spec.label == "fast")
    result = await coord.merge_or_select(f"pick:{winner_id}")
    assert result.winner_branch_id == winner_id


async def test_merge_or_select_no_checkpoint_store_skips_post_fork():
    """Covers merge_or_select branch where checkpoint store is missing."""
    deps = DeepAgentDeps(backend=StateBackend())
    coord = _make_coordinator(_make_test_agent(), deps, checkpoint_store=None)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        await coord.fork(
            [BranchSpec(label="a", steer="A")],
            parent_history=_seed_history("p"),
        )
    branch_id = next(iter(coord.branches))
    result = await coord.merge_or_select(f"pick:{branch_id}")
    assert result.winner_branch_id == branch_id


async def test_aclose_skips_done_tasks():
    """Covers aclose branch where a task is already done."""
    deps = DeepAgentDeps(backend=StateBackend())
    coord = _make_coordinator(_make_test_agent(), deps, checkpoint_store=InMemoryCheckpointStore())
    await coord.fork(
        [BranchSpec(label="a", steer="A")],
        parent_history=_seed_history("p"),
    )
    # Let task complete normally
    rt = next(iter(coord.branches.values()))
    await rt.task
    # aclose should iterate but skip the done task
    await coord.aclose()
    assert rt.task.done()


async def test_fork_tool_passes_isolation_dict():
    """Covers `_coerce_isolation` non-None branch."""
    deps = DeepAgentDeps(backend=StateBackend())
    _build_capability_with_coordinator(deps)
    toolset = create_fork_toolset()
    fork_fn = toolset.tools["fork_run"].function
    out = await fork_fn(
        _StubCtx(deps),
        [{"label": "a", "steer": "A"}],
        {"message_queue": "shared"},
        None,
    )
    assert "Forked: fork_id=" in out
    assert deps.fork_coordinator is not None
    await asyncio.gather(*(rt.task for rt in deps.fork_coordinator.branches.values()))


async def test_branch_overlay_records_no_change_on_edit_failure():
    """Covers the `if not result.error` False branch in edit()."""
    parent = StateBackend()
    parent.write("/foo.py", "hello world")
    overlay = BranchOverlay(parent)
    res = overlay.edit("/foo.py", "NOT-PRESENT", "X")
    assert res.error is not None
    # No FileChange recorded for a failed edit
    assert all(c.op == "write" for c in overlay.changes())
    # _overlay.write() bypasses the _changes log; no edit op recorded.
    edit_ops = [c for c in overlay.changes() if c.op == "edit"]
    assert edit_ops == []


def test_branch_overlay_records_no_change_on_write_failure():
    """Covers the `if not result.error` False branch in write() via a stub backend."""
    from pydantic_ai_backends import WriteResult

    class _FailingBackend(StateBackend):  # type: ignore[misc]
        def write(self, path: str, content: str | bytes) -> WriteResult:
            return WriteResult(path=None, error="forced failure")

    overlay = BranchOverlay(StateBackend())
    # Swap the internal overlay backend with the failing one
    overlay._overlay = _FailingBackend()
    res = overlay.write("/x.py", "y")
    assert res.error == "forced failure"
    assert overlay.changes() == []


def test_factory_wires_forking_true():
    agent = create_deep_agent(model=TestModel(), forking=True)
    # The capability is registered with the agent's Capabilities API; assert
    # the toolset re-exports work and the agent was constructed.
    assert agent is not None


def test_factory_accepts_capability_instance():
    cap = LiveForkCapability(max_branches=2, max_depth=1)
    agent = create_deep_agent(model=TestModel(), forking=cap)
    assert cap._agent_ref is agent


def test_factory_forking_false_no_op():
    agent = create_deep_agent(model=TestModel(), forking=False)
    assert agent is not None


def test_factory_rejects_invalid_forking_value():
    with pytest.raises(TypeError, match="forking must be bool or LiveForkCapability"):
        create_deep_agent(model=TestModel(), forking=cast(Any, "yes"))


# ---------------------------------------------------------------------------
# BranchOverlay.execute / async_execute — snapshot isolation
# ---------------------------------------------------------------------------


def test_branch_overlay_execute_rm_isolated(tmp_path: Path) -> None:
    """`rm` inside a branch snapshot removes the file only from the snapshot."""
    from pydantic_ai_backends import LocalBackend

    # Create a real file in a temp parent root.
    real_file = tmp_path / "target.py"
    real_file.write_text("# real")

    parent = LocalBackend(root_dir=tmp_path)
    overlay = BranchOverlay(parent)

    result = overlay.execute(f"rm {real_file}")

    # Command succeeds.
    assert result.exit_code == 0
    # Real file is untouched.
    assert real_file.exists(), "rm inside branch must not delete the real file"


def test_branch_overlay_execute_mkdir_isolated(tmp_path: Path) -> None:
    """`mkdir` inside a branch snapshot does not create the dir on the real FS."""
    from pydantic_ai_backends import LocalBackend

    parent = LocalBackend(root_dir=tmp_path)
    overlay = BranchOverlay(parent)

    new_dir = tmp_path / "newdir"
    result = overlay.execute(f"mkdir {new_dir}")

    assert result.exit_code == 0
    assert not new_dir.exists(), "mkdir inside branch must not create dir on real FS"


def test_branch_overlay_execute_sees_overlay_writes(tmp_path: Path) -> None:
    """Files written via the overlay are visible to execute in the snapshot."""
    from pydantic_ai_backends import LocalBackend

    parent = LocalBackend(root_dir=tmp_path)
    overlay = BranchOverlay(parent)
    overlay.write(str(tmp_path / "hello.py"), "print('branch')")

    result = overlay.execute(f"cat {tmp_path / 'hello.py'}")

    assert result.exit_code == 0
    assert "branch" in result.output


def test_branch_overlay_execute_sees_deleted_as_absent(tmp_path: Path) -> None:
    """A file deleted via the overlay is absent in the execute snapshot."""
    from pydantic_ai_backends import LocalBackend

    real_file = tmp_path / "gone.py"
    real_file.write_text("# gone")

    parent = LocalBackend(root_dir=tmp_path)
    overlay = BranchOverlay(parent)
    overlay.delete(str(real_file))

    result = overlay.execute(f"ls {tmp_path}")

    assert "gone.py" not in result.output
    assert real_file.exists(), "overlay delete must not touch the real file"


def test_branch_overlay_execute_mv_isolated(tmp_path: Path) -> None:
    """`mv` inside a branch snapshot does not rename on the real FS."""
    from pydantic_ai_backends import LocalBackend

    src = tmp_path / "old.py"
    src.write_text("# old")

    parent = LocalBackend(root_dir=tmp_path)
    overlay = BranchOverlay(parent)

    result = overlay.execute(f"mv {src} {tmp_path / 'new.py'}")

    assert result.exit_code == 0
    assert src.exists(), "mv inside branch must not rename the real file"
    assert not (tmp_path / "new.py").exists()


def test_branch_overlay_execute_forwards_when_no_root_dir() -> None:
    """With a StateBackend parent (no root_dir) the call is forwarded as-is."""
    parent = StateBackend()
    overlay = BranchOverlay(parent)
    # StateBackend.execute doesn't exist in the protocol; the forward
    # will raise AttributeError, confirming the forwarding path was taken.
    import pytest

    with pytest.raises((AttributeError, RuntimeError)):
        overlay.execute("ls")


async def test_branch_overlay_async_execute_rm_isolated(tmp_path: Path) -> None:
    """async_execute also isolates rm via asyncio.to_thread."""
    from pydantic_ai_backends import LocalBackend

    real_file = tmp_path / "async_target.py"
    real_file.write_text("# real")

    parent = LocalBackend(root_dir=tmp_path)
    overlay = BranchOverlay(parent)

    result = await overlay.async_execute(f"rm {real_file}")

    assert result.exit_code == 0
    assert real_file.exists(), "async rm inside branch must not delete the real file"


# ---------------------------------------------------------------------------
# BranchOverlay.execute — mutation propagation back to overlay
# ---------------------------------------------------------------------------


def test_execute_rm_propagates_delete_to_overlay(tmp_path: Path) -> None:
    """After execute(rm …), the path appears in overlay.deleted() for merge."""
    from pydantic_ai_backends import LocalBackend

    real_file = tmp_path / "todelete.py"
    real_file.write_text("# will be removed by branch")

    parent = LocalBackend(root_dir=tmp_path)
    overlay = BranchOverlay(parent)

    result = overlay.execute(f"rm {real_file}")

    assert result.exit_code == 0
    # Real file must be untouched.
    assert real_file.exists()
    # But the overlay must record the deletion so flush_to propagates it.
    assert str(real_file) in overlay.deleted()


def test_execute_create_file_propagates_write_to_overlay(tmp_path: Path) -> None:
    """A file created by execute is captured in the overlay as a write."""
    from pydantic_ai_backends import LocalBackend

    parent = LocalBackend(root_dir=tmp_path)
    overlay = BranchOverlay(parent)
    new_file = tmp_path / "created.py"

    result = overlay.execute(f'echo "# new" > {new_file}')

    assert result.exit_code == 0
    # Not on real FS.
    assert not new_file.exists()
    # Captured in overlay.
    assert overlay.exists(str(new_file))
    content = overlay.read(str(new_file))
    assert "new" in content


def test_execute_modify_existing_propagates_write_to_overlay(tmp_path: Path) -> None:
    """Modifying an existing file via execute captures the change in the overlay
    WITHOUT touching the real parent file (copy-on-write isolation).

    Regression for the symlink-escape bug: the snapshot copies parent files, so an
    in-place `>` redirection lands on the copy, never the real parent. The
    overlay still records the update for a later merge/flush.
    """
    from pydantic_ai_backends import LocalBackend

    real_file = tmp_path / "existing.py"
    real_file.write_text("original content")

    parent = LocalBackend(root_dir=tmp_path)
    overlay = BranchOverlay(parent)

    result = overlay.execute(f'echo "modified" > {real_file}')

    assert result.exit_code == 0
    # Overlay must have captured the modified version.
    assert overlay.exists(str(real_file))
    assert "modified" in overlay.read(str(real_file))
    # CRITICAL: the real parent file must be untouched — the branch write did not
    # escape onto the parent.
    assert real_file.read_text() == "original content"


def test_execute_mv_propagates_delete_and_create_to_overlay(tmp_path: Path) -> None:
    """mv via execute records the old path as deleted and new path as written."""
    from pydantic_ai_backends import LocalBackend

    src = tmp_path / "src.py"
    src.write_text("# src content")

    parent = LocalBackend(root_dir=tmp_path)
    overlay = BranchOverlay(parent)
    dst = tmp_path / "dst.py"

    result = overlay.execute(f"mv {src} {dst}")

    assert result.exit_code == 0
    # Real FS untouched.
    assert src.exists()
    assert not dst.exists()
    # src deleted in overlay.
    assert str(src) in overlay.deleted()
    # dst created in overlay.
    assert overlay.exists(str(dst))


def test_execute_timeout_still_propagates_partial_mutations(tmp_path: Path) -> None:
    """A command that writes a file then hangs until timeout still records the write.

    Regression: mutations made before a TimeoutExpired must be mirrored into the
    overlay, not silently discarded from changes()/merge.
    """
    from pydantic_ai_backends import LocalBackend

    from pydantic_deep.features.forking.isolation import _EXIT_TIMEOUT

    parent = LocalBackend(root_dir=str(tmp_path))
    overlay = BranchOverlay(parent)
    partial = tmp_path / "partial.py"

    # Create the file, then sleep past the timeout so the command is killed.
    result = overlay.execute(f'echo "# partial work" > {partial}; sleep 30', timeout=1)

    assert result.exit_code == _EXIT_TIMEOUT
    # Real FS untouched (copy-on-write isolation).
    assert not partial.exists()
    # The partial mutation must survive into the overlay despite the timeout.
    assert overlay.exists(str(partial))
    assert "partial work" in overlay.read(str(partial))


def test_execute_crash_still_propagates_partial_mutations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-timeout subprocess failure after a mutation still records the write.

    Simulates `subprocess.run` raising a generic exception after the file was
    created in the snapshot; the finally-block propagation must still run.
    """
    import subprocess

    from pydantic_ai_backends import LocalBackend

    from pydantic_deep.features.forking import isolation

    parent = LocalBackend(root_dir=str(tmp_path))
    overlay = BranchOverlay(parent)
    created = tmp_path / "crashed.py"

    real_run = subprocess.run

    def fake_run(args: Any, **kwargs: Any) -> Any:
        # Let the command create the file, then crash before returning.
        real_run(args, **kwargs)
        raise RuntimeError("boom")

    monkeypatch.setattr(f"{isolation.__name__}.subprocess.run", fake_run)

    result = overlay.execute(f'echo "# crash work" > {created}')

    assert result.exit_code == 1
    assert "boom" in result.output
    # Real FS untouched.
    assert not created.exists()
    # The mutation made before the crash must survive into the overlay.
    assert overlay.exists(str(created))
    assert "crash work" in overlay.read(str(created))


# ---------------------------------------------------------------------------
# Directory create/delete propagation via execute
# ---------------------------------------------------------------------------


def test_execute_mkdir_propagates_to_overlay(tmp_path: Path) -> None:
    """mkdir via execute records a 'mkdir' FileChange in the overlay."""
    from pydantic_ai_backends import LocalBackend

    from pydantic_deep.features.forking.isolation import BranchOverlay

    parent = LocalBackend(root_dir=str(tmp_path))
    overlay = BranchOverlay(parent)

    new_dir = tmp_path / "subdir"
    result = overlay.execute(f"mkdir -p {new_dir}")
    assert result.exit_code == 0

    mkdir_changes = [c for c in overlay.changes() if c.op == "mkdir"]
    assert len(mkdir_changes) == 1
    assert mkdir_changes[0].path == str(new_dir)


def test_execute_rmdir_propagates_to_overlay(tmp_path: Path) -> None:
    """rmdir via execute records a 'rmdir' FileChange in the overlay."""
    from pydantic_ai_backends import LocalBackend

    from pydantic_deep.features.forking.isolation import BranchOverlay

    target_dir = tmp_path / "existing"
    target_dir.mkdir()
    parent = LocalBackend(root_dir=str(tmp_path))
    overlay = BranchOverlay(parent)

    result = overlay.execute(f"rm -rf {target_dir}")
    assert result.exit_code == 0

    rmdir_changes = [c for c in overlay.changes() if c.op == "rmdir"]
    assert len(rmdir_changes) == 1
    assert rmdir_changes[0].path == str(target_dir)


def test_flush_mkdir_creates_directory_on_parent(tmp_path: Path) -> None:
    """flush_to with a mkdir change creates the directory on the parent backend."""
    from pydantic_ai_backends import LocalBackend

    from pydantic_deep.features.forking.isolation import BranchOverlay

    parent = LocalBackend(root_dir=str(tmp_path))
    overlay = BranchOverlay(parent)

    new_dir = tmp_path / "created_by_flush"
    overlay.record_mkdir(str(new_dir))

    report = overlay.flush_to(parent)
    assert new_dir.is_dir()
    assert str(new_dir) in report.applied_paths


def test_flush_rmdir_removes_directory_on_parent(tmp_path: Path) -> None:
    """flush_to with an rmdir change removes the directory on the parent backend."""
    from pydantic_ai_backends import LocalBackend

    from pydantic_deep.features.forking.isolation import BranchOverlay

    target_dir = tmp_path / "to_remove"
    target_dir.mkdir()
    assert target_dir.exists()

    parent = LocalBackend(root_dir=str(tmp_path))
    overlay = BranchOverlay(parent)

    overlay.record_rmdir(str(target_dir))

    report = overlay.flush_to(parent)
    assert not target_dir.exists()
    assert str(target_dir) in report.deleted_paths


def test_flush_mkdir_no_execute_reports_error() -> None:
    """flush_to mkdir on a backend without execute reports a FlushError."""
    from pydantic_ai_backends import StateBackend

    from pydantic_deep.features.forking.isolation import BranchOverlay

    parent = StateBackend()
    overlay = BranchOverlay(parent)
    overlay.record_mkdir("/fake/dir")

    report = overlay.flush_to(parent)
    assert len(report.errors) == 1
    assert report.errors[0].op == "mkdir"


def test_flush_rmdir_no_execute_reports_error() -> None:
    """flush_to rmdir on a backend without execute reports a FlushError."""
    from pydantic_ai_backends import StateBackend

    from pydantic_deep.features.forking.isolation import BranchOverlay

    parent = StateBackend()
    overlay = BranchOverlay(parent)
    overlay.record_rmdir("/fake/dir")

    report = overlay.flush_to(parent)
    assert len(report.errors) == 1
    assert report.errors[0].op == "rmdir"


def test_collect_state_records_empty_directories(tmp_path: Path) -> None:
    """_collect_state records empty directories as entries ending with '/'."""
    from pydantic_deep.features.forking.isolation import _collect_state

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    state: dict[str, tuple[bool, float]] = {}
    _collect_state(tmp_path, tmp_path, state)
    assert "empty/" in state


def test_flush_mkdir_nonzero_exit_reports_error(tmp_path: Path) -> None:
    """flush_to mkdir that returns non-zero exit code reports FlushError."""
    from datetime import datetime, timezone
    from unittest.mock import MagicMock

    from pydantic_deep.features.forking.isolation import BranchOverlay
    from pydantic_deep.features.forking.types import FileChange

    parent = MagicMock()
    parent.execute_enabled = True
    response = MagicMock()
    response.exit_code = 1
    response.output = "permission denied"
    parent.execute.return_value = response

    change = FileChange(path="/fake/dir", op="mkdir", timestamp=datetime.now(timezone.utc))
    errors: list[Any] = []
    result = BranchOverlay._flush_mkdir(parent, change, errors)
    assert result is False
    assert len(errors) == 1
    assert errors[0].op == "mkdir"


def test_flush_rmdir_nonzero_exit_reports_error(tmp_path: Path) -> None:
    """flush_to rmdir that returns non-zero exit code reports FlushError."""
    from datetime import datetime, timezone
    from unittest.mock import MagicMock

    from pydantic_deep.features.forking.isolation import BranchOverlay
    from pydantic_deep.features.forking.types import FileChange

    parent = MagicMock()
    parent.execute_enabled = True
    response = MagicMock()
    response.exit_code = 1
    response.output = "permission denied"
    parent.execute.return_value = response

    change = FileChange(path="/fake/dir", op="rmdir", timestamp=datetime.now(timezone.utc))
    errors: list[Any] = []
    deleted_paths: list[str] = []
    deleted_set: set[str] = set()
    result = BranchOverlay._flush_rmdir(parent, change, errors, deleted_paths, deleted_set)
    assert result is False
    assert len(errors) == 1
    assert errors[0].op == "rmdir"


def test_propagate_mutations_handles_directory_create(tmp_path: Path) -> None:
    """_propagate_mutations detects a new empty directory and calls record_mkdir."""
    from unittest.mock import MagicMock

    from pydantic_deep.features.forking.isolation import _propagate_mutations

    parent_root = tmp_path / "root"
    parent_root.mkdir()
    snap = tmp_path / "snap"
    snap.mkdir()

    pre: dict[str, tuple[bool, float]] = {}
    post: dict[str, tuple[bool, float]] = {"newdir/": (False, 0.0)}

    overlay = MagicMock()
    _propagate_mutations(snap, parent_root, pre, post, overlay)
    overlay.record_mkdir.assert_called_once_with(str(parent_root / "newdir"))


def test_propagate_mutations_handles_directory_delete(tmp_path: Path) -> None:
    """_propagate_mutations detects a removed directory and calls record_rmdir."""
    from unittest.mock import MagicMock

    from pydantic_deep.features.forking.isolation import _propagate_mutations

    parent_root = tmp_path / "root"
    parent_root.mkdir()
    snap = tmp_path / "snap"
    snap.mkdir()

    pre: dict[str, tuple[bool, float]] = {"olddir/": (False, 0.0)}
    post: dict[str, tuple[bool, float]] = {}

    overlay = MagicMock()
    _propagate_mutations(snap, parent_root, pre, post, overlay)
    overlay.record_rmdir.assert_called_once_with(str(parent_root / "olddir"))


def test_propagate_mutations_unchanged_directory_is_noop(tmp_path: Path) -> None:
    """_propagate_mutations skips directories present in both pre and post."""
    from unittest.mock import MagicMock

    from pydantic_deep.features.forking.isolation import _propagate_mutations

    parent_root = tmp_path / "root"
    parent_root.mkdir()
    snap = tmp_path / "snap"
    snap.mkdir()

    pre: dict[str, tuple[bool, float]] = {"stable/": (False, 0.0)}
    post: dict[str, tuple[bool, float]] = {"stable/": (False, 0.0)}

    overlay = MagicMock()
    _propagate_mutations(snap, parent_root, pre, post, overlay)
    overlay.record_mkdir.assert_not_called()
    overlay.record_rmdir.assert_not_called()


def test_collect_state_does_not_record_nonempty_directories(tmp_path: Path) -> None:
    """_collect_state does NOT record directories that contain files."""
    from pydantic_deep.features.forking.isolation import _collect_state

    nonempty = tmp_path / "has_file"
    nonempty.mkdir()
    (nonempty / "f.txt").write_text("content")

    state: dict[str, tuple[bool, float]] = {}
    _collect_state(tmp_path, tmp_path, state)
    assert "has_file/" not in state
    assert "has_file/f.txt" in state


# ---------------------------------------------------------------------------
# _rewrite_parent_root — path-boundary rewriting (no naive substring replace)
# ---------------------------------------------------------------------------


def test_rewrite_parent_root_only_on_path_boundaries() -> None:
    from pydantic_deep.features.forking.isolation import _rewrite_parent_root

    root = "/home/u/proj"
    snap = "/tmp/snap"

    # Boundary matches ARE rewritten: separator, end-of-string, whitespace, quote.
    assert _rewrite_parent_root(f"cat {root}/a.py", root, snap) == f"cat {snap}/a.py"
    assert _rewrite_parent_root(f"cd {root}", root, snap) == f"cd {snap}"
    assert _rewrite_parent_root(f"ls {root} -la", root, snap) == f"ls {snap} -la"
    assert _rewrite_parent_root(f"cat '{root}/a.py'", root, snap) == f"cat '{snap}/a.py'"

    # A sibling sharing the prefix must NOT be mangled.
    assert _rewrite_parent_root(f"cat {root}_backup/x", root, snap) == f"cat {root}_backup/x"
    # The root inside an unrelated literal token must NOT be rewritten.
    assert _rewrite_parent_root(f"echo {root}xyz", root, snap) == f"echo {root}xyz"

    # Empty root is a no-op.
    assert _rewrite_parent_root("ls -la", "", snap) == "ls -la"


# ---------------------------------------------------------------------------
# _copy_tree — subdirectory recursion and _SNAP_SKIP_DIRS skip
# ---------------------------------------------------------------------------


def test_copy_tree_recurses_into_subdirectory(tmp_path: Path) -> None:
    """_copy_tree mirrors subdirectory structure as real copies and skips _SNAP_SKIP_DIRS."""
    from pydantic_deep.features.forking.isolation import _SNAP_SKIP_DIRS, _copy_tree

    src = tmp_path / "src"
    src.mkdir()
    (src / "root_file.py").write_text("root")
    subdir = src / "subdir"
    subdir.mkdir()
    (subdir / "nested.py").write_text("nested")
    # Add a _SNAP_SKIP_DIRS entry — should be skipped.
    skip_name = next(iter(_SNAP_SKIP_DIRS))
    (src / skip_name).mkdir()
    (src / skip_name / "ignored.py").write_text("ignored")

    dst = tmp_path / "dst"
    dst.mkdir()
    _copy_tree(src, dst)

    # Files are detached real copies, NOT symlinks (copy-on-write isolation).
    assert (dst / "root_file.py").is_file()
    assert not (dst / "root_file.py").is_symlink()
    assert (dst / "root_file.py").read_text() == "root"
    assert (dst / "subdir").is_dir()
    assert (dst / "subdir" / "nested.py").is_file()
    assert not (dst / "subdir" / "nested.py").is_symlink()
    assert (dst / "subdir" / "nested.py").read_text() == "nested"
    assert not (dst / skip_name).exists()

    # Writing into the copy must not touch the source (the isolation guarantee).
    (dst / "root_file.py").write_text("branch-modified")
    assert (src / "root_file.py").read_text() == "root"


def test_copy_tree_skips_unreadable_entry(tmp_path: Path) -> None:
    """_copy_tree logs and skips an entry it can't copy (e.g. a dangling symlink)."""
    from pydantic_deep.features.forking.isolation import _copy_tree

    src = tmp_path / "src"
    src.mkdir()
    (src / "good.py").write_text("ok")
    # Dangling symlink: copy2(follow_symlinks=True) raises FileNotFoundError (OSError).
    (src / "dangling.py").symlink_to(tmp_path / "missing-target.py")

    dst = tmp_path / "dst"
    dst.mkdir()
    _copy_tree(src, dst)

    # The good file is copied; the unreadable entry is skipped (absent), no raise.
    assert (dst / "good.py").read_text() == "ok"
    assert not (dst / "dangling.py").exists()


# ---------------------------------------------------------------------------
# _collect_state — error paths, skip dirs, subdirectory, OSError mtime
# ---------------------------------------------------------------------------


def test_collect_state_skips_snap_skip_dirs(tmp_path: Path) -> None:
    """_collect_state does not recurse into _SNAP_SKIP_DIRS entries."""
    from pydantic_deep.features.forking.isolation import _SNAP_SKIP_DIRS, _collect_state

    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / "real.py").write_text("real")
    skip_name = next(iter(_SNAP_SKIP_DIRS))
    skip_dir = snap / skip_name
    skip_dir.mkdir()
    (skip_dir / "deep.py").write_text("deep")

    out: dict[str, tuple[bool, float]] = {}
    _collect_state(snap, snap, out)

    assert "real.py" in out
    assert f"{skip_name}/deep.py" not in out
    assert not any(k.startswith(skip_name) for k in out)


def test_collect_state_recurses_into_subdirectory(tmp_path: Path) -> None:
    """_collect_state recurses into normal subdirectories."""
    from pydantic_deep.features.forking.isolation import _collect_state

    snap = tmp_path / "snap"
    snap.mkdir()
    sub = snap / "pkg"
    sub.mkdir()
    (sub / "module.py").write_text("x")

    out: dict[str, tuple[bool, float]] = {}
    _collect_state(snap, snap, out)

    assert "pkg/module.py" in out


def test_collect_state_skips_non_file_non_dir_entries(tmp_path: Path) -> None:
    """_collect_state ignores entries that are not symlinks, files, or directories."""
    import os

    from pydantic_deep.features.forking.isolation import _collect_state

    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / "real.py").write_text("real")
    # Named pipe is not a symlink, not a regular file, not a directory.
    fifo = snap / "mypipe"
    os.mkfifo(fifo)

    out: dict[str, tuple[bool, float]] = {}
    _collect_state(snap, snap, out)

    assert "real.py" in out
    assert "mypipe" not in out


def test_collect_state_permission_error_returns_silently(tmp_path: Path) -> None:
    """_collect_state silently returns when os.scandir raises PermissionError."""
    from unittest.mock import patch

    from pydantic_deep.features.forking.isolation import _collect_state

    with patch("os.scandir", side_effect=PermissionError("no access")):
        out: dict[str, tuple[bool, float]] = {}
        _collect_state(tmp_path, tmp_path, out)  # must not raise
    assert out == {}


def test_collect_state_symlink_signature_oserror_fallback(tmp_path: Path) -> None:
    """A dangling symlink → content signature falls back to '' (unreadable)."""
    from pydantic_deep.features.forking.isolation import _collect_state

    snap = tmp_path / "snap"
    snap.mkdir()
    link = snap / "dangling.py"
    link.symlink_to(tmp_path / "does_not_exist.py")

    out: dict[str, tuple[bool, str]] = {}
    _collect_state(snap, snap, out)

    assert "dangling.py" in out
    is_sym, sig = out["dangling.py"]
    assert is_sym
    assert sig == ""


def test_collect_state_file_signature_oserror_fallback(tmp_path: Path) -> None:
    """_collect_state uses signature='' when a file's content can't be read."""
    from unittest.mock import MagicMock, patch

    from pydantic_deep.features.forking.isolation import _collect_state

    snap = tmp_path / "snap"
    snap.mkdir()

    # Mock entry pointing at a path open() can't read → _file_signature returns ''.
    mock_entry = MagicMock()
    mock_entry.name = "file.py"
    mock_entry.path = str(snap / "nonexistent.py")
    mock_entry.is_symlink.return_value = False
    mock_entry.is_file.return_value = True
    mock_entry.is_dir.return_value = False

    with patch("os.scandir", return_value=iter([mock_entry])):
        out: dict[str, tuple[bool, str]] = {}
        _collect_state(snap, snap, out)

    assert "nonexistent.py" in out
    _, sig = out["nonexistent.py"]
    assert sig == ""


def test_snapshot_state_detects_content_change_with_preserved_mtime(tmp_path: Path) -> None:
    """A same-size content rewrite with mtime restored is still detected.

    Regression for mtime-only detection: the signature is content-based, so a
    write that preserves mtime (or lands within the mtime tick) still changes
    the signature.
    """
    import os

    from pydantic_deep.features.forking.isolation import _snapshot_state

    snap = tmp_path / "snap"
    snap.mkdir()
    f = snap / "a.py"
    f.write_text("aaaa")
    st = os.stat(f)
    pre = _snapshot_state(snap)

    # Same byte length, different content, mtime restored to the original.
    f.write_text("bbbb")
    os.utime(f, (st.st_atime, st.st_mtime))
    post = _snapshot_state(snap)

    assert pre["a.py"][1] != post["a.py"][1]


# ---------------------------------------------------------------------------
# _branch_snapshot — error / edge-case paths
# ---------------------------------------------------------------------------


def test_branch_snapshot_overlay_read_failure_is_skipped(tmp_path: Path) -> None:
    """An exception from overlay.read_bytes skips that path without crashing."""
    from unittest.mock import patch

    from pydantic_deep.features.forking.isolation import _branch_snapshot

    overlay = StateBackend()
    from datetime import datetime, timezone

    changes = [FileChange(path="/parent/file.py", op="write", timestamp=datetime.now(timezone.utc))]
    deleted: set[str] = set()

    # Patch StateBackend.read_bytes to raise.
    with (
        patch.object(overlay, "read_bytes", side_effect=OSError("bad read")),
        _branch_snapshot(tmp_path, overlay, changes, deleted) as snap_dir,
    ):
        snap = Path(snap_dir)
        # The file should NOT appear (exception was swallowed).
        assert not (snap / "file.py").exists()


def test_branch_snapshot_path_not_relative_to_root(tmp_path: Path) -> None:
    """A path that isn't under parent_root uses lstrip('/') as fallback."""
    from pydantic_deep.features.forking.isolation import _branch_snapshot

    overlay = StateBackend()
    # Write a file with a path NOT under tmp_path (different absolute root).
    from datetime import datetime, timezone

    overlay.write("/tmp/orphan.py", b"content")
    changes = [FileChange(path="/tmp/orphan.py", op="write", timestamp=datetime.now(timezone.utc))]
    deleted: set[str] = set()

    # parent_root is tmp_path, but the path is under /tmp — triggers ValueError.
    with _branch_snapshot(tmp_path, overlay, changes, deleted) as snap_dir:
        snap = Path(snap_dir)
        # The fallback `path.lstrip("/")` → "tmp/orphan.py" inside snap.
        assert (snap / "tmp" / "orphan.py").exists()


def test_branch_snapshot_unlinks_existing_symlink_before_overlay_write(
    tmp_path: Path,
) -> None:
    """When overlay writes to a path already symlinked from parent, symlink is removed."""
    from pydantic_deep.features.forking.isolation import _branch_snapshot

    # Parent has file.py.
    parent_file = tmp_path / "file.py"
    parent_file.write_text("original")

    overlay = StateBackend()
    overlay.write(str(parent_file), b"overlay content")
    from datetime import datetime, timezone

    changes = [FileChange(path=str(parent_file), op="write", timestamp=datetime.now(timezone.utc))]
    deleted: set[str] = set()

    with _branch_snapshot(tmp_path, overlay, changes, deleted) as snap_dir:
        snap = Path(snap_dir)
        rel = parent_file.relative_to(tmp_path)
        dst = snap / rel
        # dst must be a real file (not symlink) with overlay content.
        assert not dst.is_symlink()
        assert dst.read_text() == "overlay content"


def test_branch_snapshot_deleted_path_not_relative_to_root(tmp_path: Path) -> None:
    """Deleted paths not under parent_root fall back to lstrip('/') placement."""
    from pydantic_deep.features.forking.isolation import _branch_snapshot

    overlay = StateBackend()
    # Create a file in the snapshot that we'll then mark deleted.
    other_path = "/tmp/_snap_delete_test_orphan.py"
    changes: list[FileChange] = []
    deleted: set[str] = {other_path}

    # Just confirm the context manager doesn't raise when the path
    # isn't under parent_root and the target doesn't exist.
    with _branch_snapshot(tmp_path, overlay, changes, deleted) as snap_dir:
        snap = Path(snap_dir)
        # "tmp/_snap_delete_test_orphan.py" after lstrip — may or may not exist.
        # The critical check is no exception was raised.
        assert snap.exists()


def test_branch_snapshot_deleted_path_unlinks_existing_entry(tmp_path: Path) -> None:
    """Deleted path whose symlink exists in snap is removed."""
    from pydantic_deep.features.forking.isolation import _branch_snapshot

    parent_file = tmp_path / "todel.py"
    parent_file.write_text("original")

    overlay = StateBackend()
    changes: list[FileChange] = []
    deleted = {str(parent_file)}

    with _branch_snapshot(tmp_path, overlay, changes, deleted) as snap_dir:
        snap = Path(snap_dir)
        rel = parent_file.relative_to(tmp_path)
        # Symlink from step 1 must have been removed.
        assert not (snap / rel).exists()


# ---------------------------------------------------------------------------
# _propagate_mutations — modified-file branches
# ---------------------------------------------------------------------------


def test_propagate_mutations_created_path_snap_file_missing(tmp_path: Path) -> None:
    """Created path whose snap_file doesn't exist at propagation time is skipped."""
    from pydantic_deep.features.forking.isolation import _propagate_mutations

    snap = tmp_path / "snap"
    snap.mkdir()

    pre: dict[str, tuple[bool, float]] = {}
    post: dict[str, tuple[bool, float]] = {"ghost.py": (False, 1.0)}

    overlay = BranchOverlay(StateBackend())
    _propagate_mutations(snap, tmp_path, pre, post, overlay)  # must not raise
    # Nothing should be written since snap/ghost.py doesn't exist.
    assert not overlay.exists(str(tmp_path / "ghost.py"))


def test_propagate_mutations_symlink_replaced_by_real_file(tmp_path: Path) -> None:
    """Symlink → real file transition is captured as an overlay write."""
    from pydantic_deep.features.forking.isolation import _propagate_mutations

    snap = tmp_path / "snap"
    snap.mkdir()
    snap_file = snap / "replaced.py"
    snap_file.write_text("new content")

    pre: dict[str, tuple[bool, float]] = {"replaced.py": (True, 1.0)}  # symlink
    post: dict[str, tuple[bool, float]] = {"replaced.py": (False, 2.0)}  # real file

    overlay = BranchOverlay(StateBackend())
    _propagate_mutations(snap, tmp_path, pre, post, overlay)

    abs_path = str(tmp_path / "replaced.py")
    assert overlay.exists(abs_path)
    assert overlay.read_bytes(abs_path) == b"new content"


def test_propagate_mutations_real_file_mtime_changed(tmp_path: Path) -> None:
    """An existing real file whose mtime changed is captured as an overlay write."""
    from pydantic_deep.features.forking.isolation import _propagate_mutations

    snap = tmp_path / "snap"
    snap.mkdir()
    snap_file = snap / "changed.py"
    snap_file.write_text("updated content")

    pre: dict[str, tuple[bool, float]] = {"changed.py": (False, 1.0)}
    post: dict[str, tuple[bool, float]] = {"changed.py": (False, 2.0)}  # mtime changed

    overlay = BranchOverlay(StateBackend())
    _propagate_mutations(snap, tmp_path, pre, post, overlay)

    abs_path = str(tmp_path / "changed.py")
    assert overlay.exists(abs_path)
    assert overlay.read_bytes(abs_path) == b"updated content"


def test_propagate_mutations_write_through_symlink_snap_missing(tmp_path: Path) -> None:
    """Write-through-symlink case where snap_file doesn't exist is skipped."""
    from pydantic_deep.features.forking.isolation import _propagate_mutations

    snap = tmp_path / "snap"
    snap.mkdir()
    # snap/write_through.py does NOT exist.

    pre: dict[str, tuple[bool, float]] = {"write_through.py": (True, 1.0)}
    post: dict[str, tuple[bool, float]] = {"write_through.py": (True, 2.0)}  # mtime changed

    overlay = BranchOverlay(StateBackend())
    _propagate_mutations(snap, tmp_path, pre, post, overlay)  # must not raise
    abs_path = str(tmp_path / "write_through.py")
    assert not overlay.exists(abs_path)


def test_propagate_mutations_symlink_replaced_snap_file_missing(tmp_path: Path) -> None:
    """Symlink→real-file case where snap_file vanished is skipped silently."""
    from pydantic_deep.features.forking.isolation import _propagate_mutations

    snap = tmp_path / "snap"
    snap.mkdir()
    # snap/gone.py does NOT exist — snap_file.exists() will be False.

    pre: dict[str, tuple[bool, float]] = {"gone.py": (True, 1.0)}  # symlink
    post: dict[str, tuple[bool, float]] = {"gone.py": (False, 2.0)}  # real file

    overlay = BranchOverlay(StateBackend())
    _propagate_mutations(snap, tmp_path, pre, post, overlay)  # must not raise
    assert not overlay.exists(str(tmp_path / "gone.py"))


def test_propagate_mutations_real_file_modified_snap_file_missing(tmp_path: Path) -> None:
    """Real-file mtime change where snap_file vanished is skipped silently."""
    from pydantic_deep.features.forking.isolation import _propagate_mutations

    snap = tmp_path / "snap"
    snap.mkdir()
    # snap/gone2.py does NOT exist.

    pre: dict[str, tuple[bool, float]] = {"gone2.py": (False, 1.0)}
    post: dict[str, tuple[bool, float]] = {"gone2.py": (False, 2.0)}  # mtime changed

    overlay = BranchOverlay(StateBackend())
    _propagate_mutations(snap, tmp_path, pre, post, overlay)  # must not raise
    assert not overlay.exists(str(tmp_path / "gone2.py"))


def test_propagate_mutations_overlay_write_oserror_is_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """An `OSError` from `overlay.write` is logged, not silently swallowed."""
    import logging

    from pydantic_deep.features.forking.isolation import _propagate_mutations

    snap = tmp_path / "snap"
    snap.mkdir()
    snap_file = snap / "boom.py"
    snap_file.write_text("payload")

    pre: dict[str, tuple[bool, float]] = {}
    post: dict[str, tuple[bool, float]] = {"boom.py": (False, 1.0)}

    class _FailingOverlay(BranchOverlay):
        def write(self, path: str, content: str | bytes) -> Any:
            raise OSError("disk full")

    overlay = _FailingOverlay(StateBackend())
    with caplog.at_level(logging.WARNING, logger="pydantic_deep.features.forking.isolation"):
        _propagate_mutations(snap, tmp_path, pre, post, overlay)
    assert any("failed to capture" in rec.message for rec in caplog.records)


def test_propagate_mutations_overlay_delete_oserror_is_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """An `OSError` from `overlay.delete` is logged, not silently swallowed."""
    import logging

    from pydantic_deep.features.forking.isolation import _propagate_mutations

    snap = tmp_path / "snap"
    snap.mkdir()

    pre: dict[str, tuple[bool, float]] = {"gone.py": (True, 1.0)}
    post: dict[str, tuple[bool, float]] = {}

    class _FailingOverlay(BranchOverlay):
        def delete(self, path: str) -> None:
            raise OSError("readonly fs")

    overlay = _FailingOverlay(StateBackend())
    with caplog.at_level(logging.WARNING, logger="pydantic_deep.features.forking.isolation"):
        _propagate_mutations(snap, tmp_path, pre, post, overlay)
    assert any("failed to record delete" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# _run_in_snapshot — timeout, exception, and truncation paths
# ---------------------------------------------------------------------------


def test_run_in_snapshot_timeout_returns_exit_124(tmp_path: Path) -> None:
    """A timed-out command returns exit_code=124 without raising."""
    import subprocess
    from unittest.mock import patch

    from pydantic_ai_backends import LocalBackend

    parent = LocalBackend(root_dir=tmp_path)
    overlay = BranchOverlay(parent)

    with patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="sleep", timeout=1),
    ):
        result = overlay.execute("sleep 100", timeout=1)

    assert result.exit_code == 124
    assert "timed out" in result.output.lower()


def test_run_in_snapshot_generic_exception_returns_exit_1(tmp_path: Path) -> None:
    """An unexpected exception from subprocess.run returns exit_code=1."""
    from unittest.mock import patch

    from pydantic_ai_backends import LocalBackend

    parent = LocalBackend(root_dir=tmp_path)
    overlay = BranchOverlay(parent)

    with patch("subprocess.run", side_effect=RuntimeError("bang")):
        result = overlay.execute("bang")

    assert result.exit_code == 1
    assert "bang" in result.output


def test_run_in_snapshot_output_truncated(tmp_path: Path) -> None:
    """Output longer than _EXEC_MAX_CHARS is truncated and truncated=True."""
    from pydantic_ai_backends import LocalBackend

    from pydantic_deep.features.forking.isolation import _EXEC_MAX_CHARS

    parent = LocalBackend(root_dir=tmp_path)
    overlay = BranchOverlay(parent)

    # Generate output exceeding the limit via python -c.
    result = overlay.execute(f"python3 -c \"print('x' * {_EXEC_MAX_CHARS + 100})\"")

    assert result.truncated is True
    assert len(result.output) <= _EXEC_MAX_CHARS


# ---------------------------------------------------------------------------
# delete_file tool — error guards and success path
# ---------------------------------------------------------------------------


async def test_delete_file_tool_outside_branch_returns_error() -> None:
    """delete_file returns an error message when backend is not a BranchOverlay."""
    deps = DeepAgentDeps(backend=StateBackend())
    toolset = create_fork_toolset()
    delete_fn = toolset.tools["delete_file"].function
    result = await delete_fn(_StubCtx(deps), "/any/path.py")
    assert "only available inside a fork branch" in result


async def test_delete_file_tool_nonexistent_path_returns_error() -> None:
    """delete_file returns an error when the path doesn't exist in the overlay."""
    parent = StateBackend()
    overlay = BranchOverlay(parent)
    deps = DeepAgentDeps(backend=overlay)
    toolset = create_fork_toolset()
    delete_fn = toolset.tools["delete_file"].function
    result = await delete_fn(_StubCtx(deps), "/missing.py")
    assert "does not exist" in result


async def test_delete_file_tool_success() -> None:
    """delete_file marks the path deleted in the overlay and returns confirmation."""
    parent = StateBackend()
    parent.write("/src/util.py", b"# util")
    overlay = BranchOverlay(parent)
    deps = DeepAgentDeps(backend=overlay)
    toolset = create_fork_toolset()
    delete_fn = toolset.tools["delete_file"].function
    result = await delete_fn(_StubCtx(deps), "/src/util.py")
    assert result == "deleted: /src/util.py"
    assert "/src/util.py" in overlay.deleted()
    assert not overlay.exists("/src/util.py")


# ---------------------------------------------------------------------------
# Step 0 — Coordinator public surfaces (handle + is_resolved)
# ---------------------------------------------------------------------------


def test_coordinator_handle_returns_none_before_fork():
    """`coord.handle` is `None` until `fork()` runs."""
    deps = DeepAgentDeps(backend=StateBackend())
    coord = _make_coordinator(_make_test_agent(), deps)
    assert coord.handle is None


async def test_coordinator_handle_returns_fork_handle_after_fork():
    """`coord.handle` returns the same :class:`ForkHandle` `fork()` returned."""
    deps = DeepAgentDeps(backend=StateBackend())
    coord = _make_coordinator(_make_test_agent(), deps, checkpoint_store=InMemoryCheckpointStore())
    returned = await coord.fork(
        [BranchSpec(label="a", steer="A")],
        parent_history=_seed_history("p"),
    )
    assert coord.handle is returned


def test_is_resolved_true_when_no_handle():
    """A coordinator that has not forked is resolved (no live state to discard)."""
    deps = DeepAgentDeps(backend=StateBackend())
    coord = _make_coordinator(_make_test_agent(), deps)
    assert coord.is_resolved is True


async def test_is_resolved_false_when_branches_have_overlays():
    """After `fork()` but before merge, `is_resolved` is False."""
    deps = DeepAgentDeps(backend=StateBackend())
    coord = _make_coordinator(_make_test_agent(), deps, checkpoint_store=InMemoryCheckpointStore())
    await coord.fork(
        [BranchSpec(label="a", steer="A")],
        parent_history=_seed_history("p"),
    )
    assert coord.is_resolved is False
    await asyncio.gather(*(rt.task for rt in coord.branches.values()))


async def test_is_resolved_true_after_merge():
    """`merge_or_select` releases every overlay → `is_resolved` becomes True."""
    deps = DeepAgentDeps(backend=StateBackend())
    coord = _make_coordinator(_make_test_agent(), deps, checkpoint_store=InMemoryCheckpointStore())
    handle = await coord.fork(
        [BranchSpec(label="a", steer="A"), BranchSpec(label="b", steer="B")],
        parent_history=_seed_history("p"),
    )
    await asyncio.gather(*(rt.task for rt in coord.branches.values()))
    winner_id = handle.branches[0]
    await coord.merge_or_select(f"pick:{winner_id}")
    assert coord.is_resolved is True


# ---------------------------------------------------------------------------
# B1 — Prompt content assertions
# ---------------------------------------------------------------------------


def test_fork_run_docstring_warns_against_wait_tasks():
    """`fork_run` docstring must steer the agent away from `wait_tasks`."""
    toolset = create_fork_toolset()
    doc = toolset.tools["fork_run"].function.__doc__ or ""
    assert "wait_tasks" in doc
    assert "NOT" in doc or "Do not" in doc.lower() or "do not" in doc.lower()


def test_inspect_branches_docstring_is_polling_primitive():
    """`inspect_branches` docstring must frame it as the polling primitive."""
    toolset = create_fork_toolset()
    doc = toolset.tools["inspect_branches"].function.__doc__ or ""
    assert "poll" in doc.lower()


def test_merge_or_select_docstring_marks_required():
    """`merge_or_select` docstring must flag it as required."""
    toolset = create_fork_toolset()
    doc = toolset.tools["merge_or_select"].function.__doc__ or ""
    assert "required" in doc.lower() or "REQUIRED" in doc


def test_base_prompt_has_forking_section():
    """`BASE_PROMPT` must include a `## Forking` section."""
    from pydantic_deep.prompts import BASE_PROMPT

    assert "## Forking" in BASE_PROMPT


# ---------------------------------------------------------------------------
# B3 — Stash invariant on LiveForkCapability.for_run / after_run
# ---------------------------------------------------------------------------


async def test_for_run_preserves_unresolved_coordinator():
    """An unresolved coordinator survives across `for_run` calls."""
    cap = LiveForkCapability()
    cap._agent_ref = _make_test_agent()

    deps = DeepAgentDeps(backend=StateBackend())

    class _Ctx:
        def __init__(self, d: DeepAgentDeps) -> None:
            self.deps = d

    # First call allocates a coordinator
    await cap.for_run(_Ctx(deps))
    coord = deps.fork_coordinator
    assert coord is not None
    # Simulate an unresolved fork: install a fake handle + leave overlays attached
    from datetime import datetime, timezone

    coord._handle = ForkHandle(
        fork_id="fk-test",
        branches=[],
        parent_checkpoint_id=None,
        merge_strategy=MergeStrategy(),
        created_at=datetime.now(timezone.utc),
    )

    class _RuntimeStub:
        def __init__(self) -> None:
            self.overlay = object()  # non-None ⇒ unresolved

    coord.branches["bid-1"] = cast(Any, _RuntimeStub())
    assert coord.is_resolved is False

    # Second for_run must not allocate a new coordinator
    await cap.for_run(_Ctx(deps))
    assert deps.fork_coordinator is coord


async def test_for_run_allocates_new_coordinator_when_previous_resolved():
    """When the previous coordinator is resolved, `for_run` allocates a fresh one."""
    cap = LiveForkCapability()
    cap._agent_ref = _make_test_agent()
    deps = DeepAgentDeps(backend=StateBackend())

    class _Ctx:
        def __init__(self, d: DeepAgentDeps) -> None:
            self.deps = d

    await cap.for_run(_Ctx(deps))
    first = deps.fork_coordinator
    assert first is not None
    # No handle ⇒ is_resolved True ⇒ overwrite allowed
    assert first.is_resolved is True

    await cap.for_run(_Ctx(deps))
    assert deps.fork_coordinator is not first


async def test_for_run_allocates_when_no_existing_coordinator():
    """Happy path: no existing coordinator → a fresh one is allocated."""
    cap = LiveForkCapability()
    cap._agent_ref = _make_test_agent()
    deps = DeepAgentDeps(backend=StateBackend())
    assert deps.fork_coordinator is None

    class _Ctx:
        def __init__(self, d: DeepAgentDeps) -> None:
            self.deps = d

    await cap.for_run(_Ctx(deps))
    assert deps.fork_coordinator is not None


async def test_after_run_is_passthrough():
    """`after_run` is a documented no-op anchor — returns `result` unchanged."""
    cap = LiveForkCapability()
    cap._agent_ref = _make_test_agent()
    deps = DeepAgentDeps(backend=StateBackend())

    class _Ctx:
        def __init__(self, d: DeepAgentDeps) -> None:
            self.deps = d

    sentinel = object()
    before = deps.fork_coordinator
    returned = await cap.after_run(_Ctx(deps), result=sentinel)
    assert returned is sentinel
    assert deps.fork_coordinator is before


# ---------------------------------------------------------------------------
# B3 — Orphan stash lifecycle hardening
# ---------------------------------------------------------------------------


async def test_b3a_stash_preserves_coordinator_identity_and_handle():
    """B3.a — unresolved coordinator survives `for_run`; same id, handle non-None."""
    cap = LiveForkCapability()
    agent = _make_test_agent()
    cap._agent_ref = agent
    deps = DeepAgentDeps(backend=StateBackend())

    class _Ctx:
        def __init__(self, d: DeepAgentDeps) -> None:
            self.deps = d

    await cap.for_run(_Ctx(deps))
    coord = deps.fork_coordinator
    assert coord is not None

    handle = await coord.fork(
        [BranchSpec(label="a", steer="explore A")],
        parent_history=_seed_history("parent turn"),
    )
    assert handle is not None
    assert coord._handle is not None
    assert coord.is_resolved is False
    coord_id = id(coord)

    await cap.for_run(_Ctx(deps))
    assert deps.fork_coordinator is coord
    assert id(deps.fork_coordinator) == coord_id
    assert deps.fork_coordinator._handle is not None
    await asyncio.gather(*(rt.task for rt in coord.branches.values()))


async def test_b3b_non_fork_turn_preserves_stashed_coordinator():
    """B3.b — a follow-up non-forking turn does not clear the stashed coordinator."""
    cap = LiveForkCapability()
    agent = _make_test_agent()
    cap._agent_ref = agent
    deps = DeepAgentDeps(backend=StateBackend())

    class _Ctx:
        def __init__(self, d: DeepAgentDeps) -> None:
            self.deps = d

    await cap.for_run(_Ctx(deps))
    coord = deps.fork_coordinator
    assert coord is not None

    await coord.fork(
        [BranchSpec(label="a", steer="A"), BranchSpec(label="b", steer="B")],
        parent_history=_seed_history("initial"),
    )
    assert not coord.is_resolved
    branch_ids = list(coord.branches.keys())
    assert len(branch_ids) == 2

    # Simulate a second parent turn — for_run should keep the same coordinator
    await cap.for_run(_Ctx(deps))
    assert deps.fork_coordinator is coord
    assert list(deps.fork_coordinator.branches.keys()) == branch_ids
    for bid in branch_ids:
        assert deps.fork_coordinator.branches[bid].overlay is not None
    assert deps.fork_coordinator.materializer is not None

    # Third turn — still the same
    await cap.for_run(_Ctx(deps))
    assert deps.fork_coordinator is coord

    await asyncio.gather(*(rt.task for rt in coord.branches.values()))


# ---------------------------------------------------------------------------
# E2 — Interactive multi-branch chat
# ---------------------------------------------------------------------------


async def test_e2_run_on_branch_starts_new_turn():
    """E2.a — run_on_branch on a finished branch starts a new turn."""
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()
    coord = _make_coordinator(agent, deps)
    parent_history = _seed_history("parent prompt")
    await coord.fork(
        [BranchSpec(label="a", steer="first turn")],
        parent_history=parent_history,
    )
    await asyncio.gather(*(rt.task for rt in coord.branches.values()))

    branch_id = list(coord.branches.keys())[0]
    rt = coord.branches[branch_id]
    assert rt.status.state == "done"

    task = await coord.run_on_branch(branch_id, "second turn")
    await task
    assert rt.status.state == "done"
    assert rt.status.current_turn == 1


async def test_e2_run_on_branch_rejects_running_branch():
    """E2.d — run_on_branch on a still-running branch raises RuntimeError."""
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()

    barrier = asyncio.Event()

    async def _slow_run(*args: Any, **kwargs: Any) -> Any:
        await barrier.wait()
        return await agent.__class__.run(agent, *args, **kwargs)

    agent.run = _slow_run  # type: ignore[method-assign]

    coord = _make_coordinator(agent, deps)
    await coord.fork(
        [BranchSpec(label="a", steer="go")],
        parent_history=_seed_history("parent"),
    )
    branch_id = list(coord.branches.keys())[0]

    with pytest.raises(RuntimeError, match="still running"):
        await coord.run_on_branch(branch_id, "should fail")

    barrier.set()
    await asyncio.gather(*(rt.task for rt in coord.branches.values()))


async def test_e2_run_on_branch_rejects_failed_branch():
    """run_on_branch on a failed (but task-done) branch raises RuntimeError."""
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()
    coord = _make_coordinator(agent, deps)
    await coord.fork(
        [BranchSpec(label="a", steer="go")],
        parent_history=_seed_history("parent"),
    )
    await asyncio.gather(*(rt.task for rt in coord.branches.values()))

    branch_id = list(coord.branches.keys())[0]
    rt = coord.branches[branch_id]
    rt.status.state = "failed"

    with pytest.raises(RuntimeError, match="only 'done' branches"):
        await coord.run_on_branch(branch_id, "should fail")


async def test_e2_run_on_branch_unknown_id_raises():
    """run_on_branch with unknown branch_id raises ValueError."""
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()
    coord = _make_coordinator(agent, deps)
    await coord.fork(
        [BranchSpec(label="a", steer="go")],
        parent_history=_seed_history("parent"),
    )
    await asyncio.gather(*(rt.task for rt in coord.branches.values()))

    with pytest.raises(ValueError, match="Unknown branch"):
        await coord.run_on_branch("bogus-id", "hello")


def _count_user_prompts(messages: list[Any], text: str) -> int:
    """Count ModelRequest UserPromptParts whose content equals `text`."""
    count = 0
    for msg in messages:
        for part in getattr(msg, "parts", []):
            if isinstance(part, UserPromptPart) and part.content == text:
                count += 1
    return count


async def test_e2_merge_includes_continued_turn_history():
    """E2.b — merging a branch that ran extra turns includes the continued history."""
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()
    coord = _make_coordinator(agent, deps)
    parent_history = _seed_history("parent seed")
    await coord.fork(
        [BranchSpec(label="a", steer="first"), BranchSpec(label="b", steer="other")],
        parent_history=parent_history,
    )
    await asyncio.gather(*(rt.task for rt in coord.branches.values()))

    branch_a = list(coord.branches.keys())[0]
    task = await coord.run_on_branch(branch_a, "second turn on A")
    await task

    merge_result = await coord.merge_or_select(f"pick:{branch_a}")
    assert len(merge_result.history_after_merge) >= 3  # parent + first + continued


async def test_run_on_branch_does_not_duplicate_history_across_turns():
    """Continued turns must not re-append the prior turn's request/response pairs.

    Regression: seeding the next turn from all_messages() + a separately
    accumulated tail duplicated the previous turn after the second continued turn.
    """
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()
    coord = _make_coordinator(agent, deps)
    parent_history = _seed_history("parent seed")
    await coord.fork(
        [BranchSpec(label="a", steer="first")],
        parent_history=parent_history,
    )
    await asyncio.gather(*(rt.task for rt in coord.branches.values()))
    branch_a = next(iter(coord.branches))

    await (await coord.run_on_branch(branch_a, "turn one"))
    await (await coord.run_on_branch(branch_a, "turn two"))

    final_history = list(coord.branches[branch_a].task.result().all_messages())

    # Each continued-turn user prompt appears exactly once — no duplication.
    assert _count_user_prompts(final_history, "turn one") == 1
    assert _count_user_prompts(final_history, "turn two") == 1

    # The merged history is exactly the final task history — merge adds nothing extra.
    merge_result = await coord.merge_or_select(f"pick:{branch_a}")
    assert merge_result.history_after_merge == final_history
    assert _count_user_prompts(merge_result.history_after_merge, "turn one") == 1


# ---------------------------------------------------------------------------
# Coverage — merge_or_select tool: auto mode exception / verdict paths
# ---------------------------------------------------------------------------


async def test_merge_tool_action_auto_resolve_exception_returns_error_string():
    """action='auto' where coordinator.resolve() raises → clean error string, no crash."""
    from unittest.mock import AsyncMock, patch

    deps = DeepAgentDeps(backend=StateBackend())
    _build_capability_with_coordinator(deps)
    toolset = create_fork_toolset()
    fork_fn = toolset.tools["fork_run"].function
    await fork_fn(
        _StubCtx(deps),
        [{"label": "a", "steer": "A"}],
        None,
        {"kind": "auto"},
    )
    assert deps.fork_coordinator is not None
    coord = deps.fork_coordinator
    await asyncio.gather(*(rt.task for rt in coord.branches.values()))

    merge_fn = toolset.tools["merge_or_select"].function
    with patch.object(coord, "resolve", new=AsyncMock(side_effect=RuntimeError("boom"))):
        out = await merge_fn(_StubCtx(deps), "auto")
    assert "merge_or_select auto failed" in out
    assert "boom" in out


async def test_merge_tool_action_auto_committed_without_verdict():
    """action='auto' committed=True but verdict=None → success string without judge_pick."""
    from unittest.mock import AsyncMock, patch

    from pydantic_deep import MergeResult
    from pydantic_deep.features.forking.types import ResolveOutcome

    deps = DeepAgentDeps(backend=StateBackend())
    _build_capability_with_coordinator(deps)
    toolset = create_fork_toolset()
    fork_fn = toolset.tools["fork_run"].function
    await fork_fn(
        _StubCtx(deps),
        [{"label": "a", "steer": "A"}, {"label": "b", "steer": "B"}],
        None,
        {"kind": "auto"},
    )
    assert deps.fork_coordinator is not None
    coord = deps.fork_coordinator
    await asyncio.gather(*(rt.task for rt in coord.branches.values()))
    winner_id = next(iter(coord.branches))

    fake_merge_result = MergeResult(
        fork_id=coord.fork_id or "fk-test",
        winner_branch_id=winner_id,
        discarded_branches=[],
        history_after_merge=[],
    )
    # verdict=None — exercises the 290->295 branch (committed=True, no judge pick)
    fake_outcome = ResolveOutcome(
        committed=True,
        auto_eligible=True,
        verdict=None,
        signals=None,
        effective_confidence=0.0,
        merge_result=fake_merge_result,
    )
    merge_fn = toolset.tools["merge_or_select"].function
    with patch.object(coord, "resolve", new=AsyncMock(return_value=fake_outcome)):
        out = await merge_fn(_StubCtx(deps), "auto")
    # Should include the merge summary but NOT the judge_pick fragment.
    assert "winner=" in out
    assert "judge_pick=" not in out


async def test_merge_tool_action_auto_not_committed_with_verdict_picks_winner():
    """action='auto' where resolve() returns committed=False + verdict set → auto-picks winner."""
    from unittest.mock import AsyncMock, patch

    from pydantic_deep import JudgeVerdict
    from pydantic_deep.features.forking.types import ResolveOutcome

    deps = DeepAgentDeps(backend=StateBackend())
    _build_capability_with_coordinator(deps)
    toolset = create_fork_toolset()
    fork_fn = toolset.tools["fork_run"].function
    await fork_fn(
        _StubCtx(deps),
        [{"label": "a", "steer": "A"}, {"label": "b", "steer": "B"}],
        None,
        {"kind": "auto"},
    )
    assert deps.fork_coordinator is not None
    coord = deps.fork_coordinator
    await asyncio.gather(*(rt.task for rt in coord.branches.values()))
    winner_id = next(iter(coord.branches))

    # verdict is not None but committed=False → line 304: action = f"pick:{winner_id}"
    fake_verdict = JudgeVerdict(winner_branch_id=winner_id, reasoning="ok", confidence=0.7)
    fake_outcome = ResolveOutcome(
        committed=False,
        auto_eligible=True,
        verdict=fake_verdict,
        signals=None,
        effective_confidence=0.7,
        merge_result=None,
    )
    merge_fn = toolset.tools["merge_or_select"].function
    with patch.object(coord, "resolve", new=AsyncMock(return_value=fake_outcome)):
        out = await merge_fn(_StubCtx(deps), "auto")
    # The tool should have fallen through to merge_or_select(pick:<winner_id>)
    assert "winner=" in out
    assert coord.is_resolved


# ---------------------------------------------------------------------------
# A1 — auto/vote merge must not deadlock on a winner parked on approval.
# ---------------------------------------------------------------------------


async def test_await_winner_auto_denies_parked_approval():
    """Non-interactive (auto/vote) commit denies a parked approval instead of hanging."""
    from types import SimpleNamespace

    deps = DeepAgentDeps(backend=StateBackend())
    coord = _make_coordinator(_make_test_agent(), deps)
    approval = PendingApprovalRequest(branch_id="w", description="execute: rm -rf /")
    winner = SimpleNamespace(task=None, pending_approval=approval)

    async def _parked() -> str:
        answered = await approval.response.get()
        assert answered is False  # auto-denied
        winner.pending_approval = None  # branch resets it after answering
        await asyncio.sleep(_APPROVAL_POLL_INTERVAL_S * 3)  # an iter sees not-done + no pending
        return "done"

    winner.task = asyncio.create_task(_parked())
    await asyncio.sleep(0)  # let the task reach its await

    result = await coord._await_winner(cast(Any, winner), auto_deny_approvals=True)
    assert result == "done"


async def test_await_winner_manual_plain_await():
    """Manual mode awaits the task directly (a human answers approvals via the TUI)."""
    from types import SimpleNamespace

    deps = DeepAgentDeps(backend=StateBackend())
    coord = _make_coordinator(_make_test_agent(), deps)

    async def _quick() -> str:
        return "ok"

    winner = SimpleNamespace(task=asyncio.create_task(_quick()), pending_approval=None)
    assert await coord._await_winner(cast(Any, winner), auto_deny_approvals=False) == "ok"


# ---------------------------------------------------------------------------
# A2 — aclose is locked + idempotent.
# ---------------------------------------------------------------------------


async def test_aclose_is_idempotent(tmp_path: Path) -> None:
    deps = DeepAgentDeps(backend=StateBackend())
    coord = _make_coordinator(_make_test_agent(), deps, materializer_root=tmp_path)
    await coord.fork(
        [BranchSpec(label="a", steer="A"), BranchSpec(label="b", steer="B")],
        parent_history=_seed_history("p"),
    )
    await asyncio.gather(*(rt.task for rt in coord.branches.values()))

    await coord.aclose()
    assert coord._closed is True
    await coord.aclose()  # second call is a no-op via the _closed guard
    assert coord._closed is True


async def test_cancel_branch_task_warns_when_loser_ignores_cancel(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A4: a loser that doesn't quiesce in time is logged, not silently ignored."""
    from types import SimpleNamespace

    from pydantic_deep.features.forking import coordinator as _coord_mod

    monkeypatch.setattr(_coord_mod, "_CANCEL_CLEANUP_TIMEOUT_S", 0.01)
    coord = _make_coordinator(_make_test_agent(), DeepAgentDeps(backend=StateBackend()))
    started = asyncio.Event()

    async def _stubborn() -> None:
        started.set()
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            await asyncio.sleep(0.05)  # exceed the 0.01s quiesce window before honoring cancel
            raise

    task = asyncio.create_task(_stubborn())
    await started.wait()
    rt = SimpleNamespace(task=task)
    with caplog.at_level("WARNING"):
        await coord._cancel_branch_task(cast(Any, rt), "loser z")
    assert any("did not stop" in r.getMessage() for r in caplog.records)
    with contextlib.suppress(asyncio.CancelledError):
        await task
