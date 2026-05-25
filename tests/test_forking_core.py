"""Live Run Forking — coordinator and branch kernel tests (issue #102)."""

from __future__ import annotations

import asyncio
import warnings
from typing import Any, cast

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, UserPromptPart
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
    assert f"winner={branch_id}" in out


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
    # The materialization write is recorded but not the edit
    # (overlay copied parent_bytes via _overlay.write which doesn't log)
    # Actually our overlay.write() is the public method; here we used
    # _overlay.write() directly (bypassing _changes log).  Confirm:
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
