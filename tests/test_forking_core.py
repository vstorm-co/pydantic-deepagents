"""Live Run Forking — coordinator and branch kernel tests (issue #102)."""

from __future__ import annotations

import asyncio
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
    clone_for_branch,
    create_deep_agent,
)
from pydantic_deep.capabilities.message_queue import MessageQueue
from pydantic_deep.toolsets.checkpointing import InMemoryCheckpointStore
from pydantic_deep.toolsets.forking import NOT_ENABLED_MESSAGE, create_fork_toolset


def _make_test_agent() -> Agent[DeepAgentDeps, str]:
    return Agent(TestModel(), deps_type=DeepAgentDeps)


def _make_coordinator(
    agent: Agent[DeepAgentDeps, str],
    deps: DeepAgentDeps,
    *,
    max_branches: int = 2,
    max_depth: int = 1,
    checkpoint_store: Any = None,
) -> ForkCoordinator:
    return ForkCoordinator(
        agent=agent,
        parent_deps=deps,
        max_branches=max_branches,
        max_depth=max_depth,
        store=InMemoryForkStateStore(),
        checkpoint_store=checkpoint_store,
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


def test_branch_overlay_parent_property():
    parent = StateBackend()
    overlay = BranchOverlay(parent)
    assert overlay.parent is parent


def test_branch_overlay_exists_falls_through_to_parent():
    """``exists()`` returns True for files in either layer, False otherwise."""
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

    from pydantic_deep.toolsets.forking.materializer import ForkMaterializer

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
    # in ``_flush_delete`` (path already in ``deleted_set``).
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
    assert cloned.todos == []
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
    assert cloned.backend is parent_backend
    cloned2 = clone_for_branch(deps, BranchIsolation(backend="share"))
    assert cloned2.backend is parent_backend


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


# ---------------------------------------------------------------------------
# merge_or_select fails fast when winner task was already cancelled
# ---------------------------------------------------------------------------


async def test_merge_or_select_raises_if_winner_cancelled():
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
    await coord.terminate_branch(branch_id)
    await asyncio.sleep(0)
    with pytest.raises(RuntimeError):
        await coord.merge_or_select(f"pick:{branch_id}")


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

    ``before_model_request`` captures the in-progress request, so the snapshot
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
    with patch("pydantic_deep.toolsets.forking.coordinator.JudgeAgent", _FakeJudge):
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
    """``rm`` inside a branch snapshot removes the file only from the snapshot."""
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
    """``mkdir`` inside a branch snapshot does not create the dir on the real FS."""
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
    """``mv`` inside a branch snapshot does not rename on the real FS."""
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
    """Modifying an existing file via execute captures the change in the overlay.

    Note: shell ``>`` redirections follow symlinks, so the real file may also
    be modified.  The critical invariant is that the overlay records the update
    so that a subsequent merge or flush propagates the correct content.
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


# ---------------------------------------------------------------------------
# _symlink_tree — subdirectory recursion and _SNAP_SKIP_DIRS skip
# ---------------------------------------------------------------------------


def test_symlink_tree_recurses_into_subdirectory(tmp_path: Path) -> None:
    """_symlink_tree mirrors subdirectory structure and skips _SNAP_SKIP_DIRS."""
    from pydantic_deep.toolsets.forking.isolation import _SNAP_SKIP_DIRS, _symlink_tree

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
    _symlink_tree(src, dst)

    assert (dst / "root_file.py").is_symlink()
    assert (dst / "subdir").is_dir()
    assert (dst / "subdir" / "nested.py").is_symlink()
    assert not (dst / skip_name).exists()


# ---------------------------------------------------------------------------
# _collect_state — error paths, skip dirs, subdirectory, OSError mtime
# ---------------------------------------------------------------------------


def test_collect_state_skips_snap_skip_dirs(tmp_path: Path) -> None:
    """_collect_state does not recurse into _SNAP_SKIP_DIRS entries."""
    from pydantic_deep.toolsets.forking.isolation import _SNAP_SKIP_DIRS, _collect_state

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
    from pydantic_deep.toolsets.forking.isolation import _collect_state

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

    from pydantic_deep.toolsets.forking.isolation import _collect_state

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

    from pydantic_deep.toolsets.forking.isolation import _collect_state

    with patch("os.scandir", side_effect=PermissionError("no access")):
        out: dict[str, tuple[bool, float]] = {}
        _collect_state(tmp_path, tmp_path, out)  # must not raise
    assert out == {}


def test_collect_state_symlink_mtime_oserror_fallback(tmp_path: Path) -> None:
    """_collect_state uses mtime=0.0 when os.stat raises OSError for a symlink."""
    import os
    from unittest.mock import patch

    from pydantic_deep.toolsets.forking.isolation import _collect_state

    snap = tmp_path / "snap"
    snap.mkdir()
    target = tmp_path / "real.py"
    target.write_text("t")
    link = snap / "real.py"
    link.symlink_to(target)

    def _failing_stat(path: str, *, follow_symlinks: bool = True) -> os.stat_result:
        raise OSError("stat error")

    with patch("os.stat", side_effect=_failing_stat):
        out: dict[str, tuple[bool, float]] = {}
        _collect_state(snap, snap, out)

    assert "real.py" in out
    is_sym, mtime = out["real.py"]
    assert is_sym
    assert mtime == 0.0


def test_collect_state_file_mtime_oserror_fallback(tmp_path: Path) -> None:
    """_collect_state uses mtime=0.0 when entry.stat raises OSError for a real file."""
    from unittest.mock import MagicMock, patch

    from pydantic_deep.toolsets.forking.isolation import _collect_state

    snap = tmp_path / "snap"
    snap.mkdir()
    real_file = snap / "file.py"
    real_file.write_text("content")

    # Patch os.scandir to return a mock entry whose .stat() raises OSError.
    mock_entry = MagicMock()
    mock_entry.name = "file.py"
    mock_entry.path = str(real_file)
    mock_entry.is_symlink.return_value = False
    mock_entry.is_file.return_value = True
    mock_entry.is_dir.return_value = False
    mock_entry.stat.side_effect = OSError("stat fail")

    with patch("os.scandir", return_value=iter([mock_entry])):
        out: dict[str, tuple[bool, float]] = {}
        _collect_state(snap, snap, out)

    assert "file.py" in out
    _, mtime = out["file.py"]
    assert mtime == 0.0


# ---------------------------------------------------------------------------
# _branch_snapshot — error / edge-case paths
# ---------------------------------------------------------------------------


def test_branch_snapshot_overlay_read_failure_is_skipped(tmp_path: Path) -> None:
    """An exception from overlay.read_bytes skips that path without crashing."""
    from unittest.mock import patch

    from pydantic_deep.toolsets.forking.isolation import _branch_snapshot

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
    from pydantic_deep.toolsets.forking.isolation import _branch_snapshot

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
    from pydantic_deep.toolsets.forking.isolation import _branch_snapshot

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
    from pydantic_deep.toolsets.forking.isolation import _branch_snapshot

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
    from pydantic_deep.toolsets.forking.isolation import _branch_snapshot

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
    from pydantic_deep.toolsets.forking.isolation import _propagate_mutations

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
    from pydantic_deep.toolsets.forking.isolation import _propagate_mutations

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
    from pydantic_deep.toolsets.forking.isolation import _propagate_mutations

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
    from pydantic_deep.toolsets.forking.isolation import _propagate_mutations

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
    from pydantic_deep.toolsets.forking.isolation import _propagate_mutations

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
    from pydantic_deep.toolsets.forking.isolation import _propagate_mutations

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
    """An ``OSError`` from ``overlay.write`` is logged, not silently swallowed."""
    import logging

    from pydantic_deep.toolsets.forking.isolation import _propagate_mutations

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
    with caplog.at_level(logging.WARNING, logger="pydantic_deep.toolsets.forking.isolation"):
        _propagate_mutations(snap, tmp_path, pre, post, overlay)
    assert any("failed to capture" in rec.message for rec in caplog.records)


def test_propagate_mutations_overlay_delete_oserror_is_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """An ``OSError`` from ``overlay.delete`` is logged, not silently swallowed."""
    import logging

    from pydantic_deep.toolsets.forking.isolation import _propagate_mutations

    snap = tmp_path / "snap"
    snap.mkdir()

    pre: dict[str, tuple[bool, float]] = {"gone.py": (True, 1.0)}
    post: dict[str, tuple[bool, float]] = {}

    class _FailingOverlay(BranchOverlay):
        def delete(self, path: str) -> None:
            raise OSError("readonly fs")

    overlay = _FailingOverlay(StateBackend())
    with caplog.at_level(logging.WARNING, logger="pydantic_deep.toolsets.forking.isolation"):
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

    from pydantic_deep.toolsets.forking.isolation import _EXEC_MAX_CHARS

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
    """``coord.handle`` is ``None`` until ``fork()`` runs."""
    deps = DeepAgentDeps(backend=StateBackend())
    coord = _make_coordinator(_make_test_agent(), deps)
    assert coord.handle is None


async def test_coordinator_handle_returns_fork_handle_after_fork():
    """``coord.handle`` returns the same :class:`ForkHandle` ``fork()`` returned."""
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
    """After ``fork()`` but before merge, ``is_resolved`` is False."""
    deps = DeepAgentDeps(backend=StateBackend())
    coord = _make_coordinator(_make_test_agent(), deps, checkpoint_store=InMemoryCheckpointStore())
    await coord.fork(
        [BranchSpec(label="a", steer="A")],
        parent_history=_seed_history("p"),
    )
    assert coord.is_resolved is False
    await asyncio.gather(*(rt.task for rt in coord.branches.values()))


async def test_is_resolved_true_after_merge():
    """``merge_or_select`` releases every overlay → ``is_resolved`` becomes True."""
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
    """``fork_run`` docstring must steer the agent away from ``wait_tasks``."""
    toolset = create_fork_toolset()
    doc = toolset.tools["fork_run"].function.__doc__ or ""
    assert "wait_tasks" in doc
    assert "NOT" in doc or "Do not" in doc.lower() or "do not" in doc.lower()


def test_inspect_branches_docstring_is_polling_primitive():
    """``inspect_branches`` docstring must frame it as the polling primitive."""
    toolset = create_fork_toolset()
    doc = toolset.tools["inspect_branches"].function.__doc__ or ""
    assert "poll" in doc.lower()


def test_merge_or_select_docstring_marks_required():
    """``merge_or_select`` docstring must flag it as required."""
    toolset = create_fork_toolset()
    doc = toolset.tools["merge_or_select"].function.__doc__ or ""
    assert "required" in doc.lower() or "REQUIRED" in doc


def test_base_prompt_has_forking_section():
    """``BASE_PROMPT`` must include a ``## Forking`` section."""
    from pydantic_deep.prompts import BASE_PROMPT

    assert "## Forking" in BASE_PROMPT


# ---------------------------------------------------------------------------
# B3 — Stash invariant on LiveForkCapability.for_run / after_run
# ---------------------------------------------------------------------------


async def test_for_run_preserves_unresolved_coordinator():
    """An unresolved coordinator survives across ``for_run`` calls."""
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
    """When the previous coordinator is resolved, ``for_run`` allocates a fresh one."""
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
    """``after_run`` is a documented no-op anchor — returns ``result`` unchanged."""
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
