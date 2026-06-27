"""Live Run Forking — budget and aggregate cap tests (issue #105).

The 7 cases from the issue's Test plan. Cost callbacks fire in two places
in production: `CostTracking.after_run` invokes `on_cost_update` once
per branch run, awaiting awaitables. These tests drive the watchers
directly with synthesised :class:`CostInfo` values to keep the test surface
deterministic — the integration test (#6) goes one level higher and
exercises the registry swap via :func:`create_deep_agent`.
"""

from __future__ import annotations

import asyncio
import warnings
from typing import Any, cast

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai.models.test import TestModel
from pydantic_ai_backends import StateBackend
from pydantic_ai_shields import CostInfo, CostTracking

from pydantic_deep import (
    BranchCost,
    BranchSpec,
    DeepAgentDeps,
    ForkCoordinator,
    ForkCostSummary,
    ForkDepthLimitError,
    InMemoryForkStateStore,
    create_deep_agent,
)
from pydantic_deep.features.checkpointing import InMemoryCheckpointStore
from pydantic_deep.features.forking import NOT_ENABLED_MESSAGE, create_fork_toolset
from pydantic_deep.features.forking.budget import BudgetWatcher
from pydantic_deep.features.forking.coordinator import (
    _agent_model_name,
    _build_branch_cost_tracking,
    _find_parent_cost_tracking,
    _PerBranchCostTracking,
)


def _make_test_agent() -> Agent[DeepAgentDeps, str]:
    return Agent(TestModel(), deps_type=DeepAgentDeps)


def _make_coordinator(
    agent: Agent[DeepAgentDeps, str],
    deps: DeepAgentDeps,
    *,
    max_branches: int = 10,
    max_depth: int = 2,
    aggregate_budget_usd: float | None = None,
) -> ForkCoordinator:
    return ForkCoordinator(
        agent=agent,
        parent_deps=deps,
        max_branches=max_branches,
        max_depth=max_depth,
        store=InMemoryForkStateStore(),
        checkpoint_store=InMemoryCheckpointStore(),
        aggregate_budget_usd=aggregate_budget_usd,
    )


def _seed_history(text: str) -> list[Any]:
    return [ModelRequest(parts=[UserPromptPart(content=text)])]


def _cost_info(total: float, run: float | None = None) -> CostInfo:
    """Synthesise a :class:`CostInfo` for driving watchers in tests."""
    return CostInfo(
        run_cost_usd=run if run is not None else total,
        total_cost_usd=total,
        run_request_tokens=0,
        run_response_tokens=0,
        total_request_tokens=0,
        total_response_tokens=0,
        run_count=1,
    )


async def _drain_branch_tasks(coord: ForkCoordinator) -> None:
    """Wait for all branch tasks to settle (cancelled / done / errored)."""
    await asyncio.gather(*(rt.task for rt in coord.branches.values()), return_exceptions=True)


async def test_five_branches_spawn_under_max_branches_ten():
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()
    coord = _make_coordinator(agent, deps)

    specs = [BranchSpec(label=f"b{i}", steer=f"steer {i}") for i in range(5)]
    handle = await coord.fork(specs, parent_history=_seed_history("parent"))

    assert len(handle.branches) == 5
    assert len(coord.branches) == 5
    for rt in coord.branches.values():
        assert rt.status.state == "running"

    await _drain_branch_tasks(coord)


async def test_per_branch_budget_exhausts_only_target_branch():
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()
    coord = _make_coordinator(agent, deps)

    specs = [
        BranchSpec(label="a", steer="a", budget_usd=0.05),
        BranchSpec(label="b", steer="b", budget_usd=0.05),
    ]
    handle = await coord.fork(specs, parent_history=_seed_history("p"))
    a_id, b_id = handle.branches[0], handle.branches[1]

    a_watcher = coord.branches[a_id].cost_tracker
    assert isinstance(a_watcher, _PerBranchCostTracking)
    assert isinstance(a_watcher.on_cost_update, BudgetWatcher)

    await a_watcher.on_cost_update(_cost_info(total=0.10))

    assert coord.branches[a_id].status.state == "budget_exhausted"
    assert coord.branches[b_id].status.state == "running"
    assert "budget exhausted" in (coord.branches[a_id].status.error or "")

    b_tracker = coord.branches[b_id].cost_tracker
    assert isinstance(b_tracker, _PerBranchCostTracking)
    assert b_tracker.total_cost == 0.0

    await _drain_branch_tasks(coord)


async def test_aggregate_budget_terminates_all_running_branches():
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()
    coord = _make_coordinator(agent, deps, aggregate_budget_usd=0.10)

    specs = [BranchSpec(label=label, steer=label) for label in ("a", "b", "c")]
    handle = await coord.fork(specs, parent_history=_seed_history("p"))
    a_id, b_id, c_id = handle.branches

    for bid, total in [(a_id, 0.04), (b_id, 0.04), (c_id, 0.05)]:
        tracker = coord.branches[bid].cost_tracker
        assert tracker is not None
        await tracker.on_cost_update(_cost_info(total=total))

    for bid in handle.branches:
        assert coord.branches[bid].status.state == "aggregate_budget_exhausted"
        assert "aggregate budget exhausted" in (coord.branches[bid].status.error or "")

    await _drain_branch_tasks(coord)


async def test_fork_cost_returns_correct_breakdown_and_aggregate():
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()
    coord = _make_coordinator(agent, deps, aggregate_budget_usd=0.50)

    specs = [
        BranchSpec(label="a", steer="a", budget_usd=0.10),
        BranchSpec(label="b", steer="b", budget_usd=0.20),
    ]
    handle = await coord.fork(specs, parent_history=_seed_history("p"))
    a_id, b_id = handle.branches

    a_tracker = coord.branches[a_id].cost_tracker
    b_tracker = coord.branches[b_id].cost_tracker
    assert isinstance(a_tracker, CostTracking)
    assert isinstance(b_tracker, CostTracking)
    # fork_cost reads CostTracking.total_cost (_total_cost_usd), which only real
    # priced runs accrue (TestModel has no pricing), so inject known cumulatives
    # directly — this case tests fork_cost's per-branch/aggregate arithmetic. The
    # self-cancel watcher path is covered by
    # test_budget_watcher_cancels_running_branch_task below.
    a_tracker._total_cost_usd = 0.03
    b_tracker._total_cost_usd = 0.07

    summary = coord.fork_cost()
    assert isinstance(summary, ForkCostSummary)
    assert summary.fork_id == handle.fork_id
    assert summary.per_branch[a_id].cumulative_usd == pytest.approx(0.03)
    assert summary.per_branch[a_id].remaining_usd == pytest.approx(0.07)
    assert summary.per_branch[b_id].cumulative_usd == pytest.approx(0.07)
    assert summary.per_branch[b_id].remaining_usd == pytest.approx(0.13)
    assert summary.aggregate_usd == pytest.approx(0.10)
    assert summary.aggregate_budget_usd == pytest.approx(0.50)
    assert summary.aggregate_remaining_usd == pytest.approx(0.40)

    await _drain_branch_tasks(coord)


async def test_budget_watcher_cancels_running_branch_task():
    """An over-budget on_cost_update while the branch is still running cancels it.

    Drives the public on_cost_update path from outside the test coroutine's
    completion and asserts the branch task actually stopped (cancelled, state
    budget_exhausted) and the agent did NOT run to completion.
    """
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()

    started = asyncio.Event()
    completed = {"done": False}

    async def _blocking_run(*_args: Any, **_kwargs: Any) -> Any:
        started.set()
        await asyncio.Event().wait()  # block until cancelled
        completed["done"] = True  # pragma: no cover - never reached
        return None

    agent.run = _blocking_run  # type: ignore[method-assign]

    coord = _make_coordinator(agent, deps)
    handle = await coord.fork(
        [BranchSpec(label="a", steer="a", budget_usd=0.10)],
        parent_history=_seed_history("p"),
    )
    bid = handle.branches[0]
    await started.wait()

    rt = coord.branches[bid]
    tracker = rt.cost_tracker
    assert isinstance(tracker, CostTracking)

    # Over-budget cost arrives mid-run → watcher terminates the running branch.
    await tracker.on_cost_update(_cost_info(total=0.50))
    await asyncio.sleep(0)

    assert rt.task.cancelled()
    assert rt.status.state == "budget_exhausted"
    assert completed["done"] is False


async def test_budget_exhausted_branch_can_be_picked_as_winner():
    """See "Capturing partial history" in docs/capabilities/live-fork.md —
    the awaited task raises CancelledError but the coordinator returns the
    snapshot captured on the last `before_model_request` instead."""
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()
    coord = _make_coordinator(agent, deps)

    specs = [
        BranchSpec(label="a", steer="a", budget_usd=0.05),
        BranchSpec(label="b", steer="b"),
    ]
    handle = await coord.fork(specs, parent_history=_seed_history("p"))
    a_id, _b_id = handle.branches

    snapshot = _seed_history("partial work")
    coord.capture_partial_history(a_id, snapshot)

    a_tracker = coord.branches[a_id].cost_tracker
    assert a_tracker is not None
    await a_tracker.on_cost_update(_cost_info(total=0.10))

    result = await coord.merge_or_select(f"pick:{a_id}")
    assert result.winner_branch_id == a_id
    assert len(result.history_after_merge) == len(snapshot)


async def test_cost_callbacks_isolated_per_branch_via_registry():
    """Goes through the agent.py swap: with forking=True + cost_tracking=True,
    cost_cap is a _PerBranchCostTracking whose for_run returns the per-branch
    instance set on cloned_deps._branch_cost_tracking. A's costs do not flow
    into B's tracker."""
    agent = create_deep_agent(
        model=TestModel(),
        forking=True,
        cost_tracking=True,
        cost_budget_usd=None,
    )

    root_cap = agent._root_capability
    cost_caps = [c for c in root_cap.capabilities if isinstance(c, CostTracking)]
    assert len(cost_caps) == 1
    assert isinstance(cost_caps[0], _PerBranchCostTracking)

    deps = DeepAgentDeps(backend=StateBackend())
    coord = ForkCoordinator(
        agent=agent,
        parent_deps=deps,
        max_branches=10,
        max_depth=2,
        store=InMemoryForkStateStore(),
        checkpoint_store=InMemoryCheckpointStore(),
    )
    deps.fork_coordinator = coord
    handle = await coord.fork(
        [
            BranchSpec(label="a", steer="a", budget_usd=0.05),
            BranchSpec(label="b", steer="b", budget_usd=0.05),
        ],
        parent_history=_seed_history("p"),
    )
    a_id, b_id = handle.branches

    a_tracker = coord.branches[a_id].cost_tracker
    b_tracker = coord.branches[b_id].cost_tracker
    assert isinstance(a_tracker, _PerBranchCostTracking)
    assert isinstance(b_tracker, _PerBranchCostTracking)
    assert a_tracker is not b_tracker

    await a_tracker.on_cost_update(_cost_info(total=0.10))

    assert coord.branches[a_id].status.state == "budget_exhausted"
    assert coord.branches[b_id].status.state == "running"
    assert b_tracker.total_cost == 0.0

    await _drain_branch_tasks(coord)


async def test_max_depth_two_walks_three_transitions():
    """Walk all three depth transitions explicitly:
    depth 0 → 1 OK, depth 1 → 2 OK, depth 2 → 3 rejected."""
    agent = _make_test_agent()

    deps0 = DeepAgentDeps(backend=StateBackend(), _fork_depth=0)
    coord0 = _make_coordinator(agent, deps0)
    await coord0.fork(
        [BranchSpec(label="a", steer="a")],
        parent_history=_seed_history("p"),
    )

    deps1 = DeepAgentDeps(backend=StateBackend(), _fork_depth=1)
    coord1 = _make_coordinator(agent, deps1)
    await coord1.fork(
        [BranchSpec(label="a1", steer="a1")],
        parent_history=_seed_history("p1"),
    )

    deps2 = DeepAgentDeps(backend=StateBackend(), _fork_depth=2)
    coord2 = _make_coordinator(agent, deps2)
    with pytest.raises(ForkDepthLimitError):
        await coord2.fork(
            [BranchSpec(label="a2", steer="a2")],
            parent_history=_seed_history("p2"),
        )

    for c in (coord0, coord1):
        await _drain_branch_tasks(c)


def test_branch_cost_dataclass_defaults():
    cost = BranchCost(
        branch_id="b1",
        branch_label="a",
        cumulative_usd=None,
        budget_usd=None,
        remaining_usd=None,
        state="running",
    )
    assert cost.branch_id == "b1"
    assert cost.cumulative_usd is None


async def test_fork_cost_raises_when_no_active_fork():
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()
    coord = _make_coordinator(agent, deps)
    with pytest.raises(RuntimeError, match="no active fork"):
        coord.fork_cost()


async def test_fork_cost_aggregate_none_when_no_tracked_costs():
    """When pricing fails for every branch, aggregate_usd surfaces as None."""
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()
    coord = _make_coordinator(agent, deps)
    handle = await coord.fork(
        [BranchSpec(label="a", steer="a")],
        parent_history=_seed_history("p"),
    )
    coord.branches[handle.branches[0]].cost_tracker = None
    summary = coord.fork_cost()
    assert summary.aggregate_usd is None
    assert summary.aggregate_remaining_usd is None
    await _drain_branch_tasks(coord)


async def test_terminate_branch_idempotent():
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()
    coord = _make_coordinator(agent, deps)
    handle = await coord.fork(
        [BranchSpec(label="a", steer="a")],
        parent_history=_seed_history("p"),
    )
    bid = handle.branches[0]
    await coord.terminate_branch(bid, reason="budget_exhausted")
    first_state = coord.branches[bid].status.state
    await coord.terminate_branch(bid, reason="aggregate_budget_exhausted")
    assert coord.branches[bid].status.state == first_state
    await _drain_branch_tasks(coord)


async def test_terminate_branch_default_reason_uses_terminated():
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()
    coord = _make_coordinator(agent, deps)
    handle = await coord.fork(
        [BranchSpec(label="a", steer="a")],
        parent_history=_seed_history("p"),
    )
    bid = handle.branches[0]
    await coord.terminate_branch(bid)
    assert coord.branches[bid].status.state == "terminated"
    await _drain_branch_tasks(coord)


async def test_terminate_branch_unknown_id_raises():
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()
    coord = _make_coordinator(agent, deps)
    await coord.fork(
        [BranchSpec(label="a", steer="a")],
        parent_history=_seed_history("p"),
    )
    with pytest.raises(ValueError, match="Unknown branch id"):
        await coord.terminate_branch("not-a-real-id")
    await _drain_branch_tasks(coord)


async def test_aggregate_watcher_no_op_below_cap():
    """When the running sum is below the cap, no termination fires."""
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()
    coord = _make_coordinator(agent, deps, aggregate_budget_usd=10.0)

    handle = await coord.fork(
        [BranchSpec(label="a", steer="a"), BranchSpec(label="b", steer="b")],
        parent_history=_seed_history("p"),
    )
    for bid in handle.branches:
        tracker = coord.branches[bid].cost_tracker
        assert tracker is not None
        await tracker.on_cost_update(_cost_info(total=0.01))
        assert coord.branches[bid].status.state == "running"
    await _drain_branch_tasks(coord)


async def test_aggregate_watcher_ignores_none_total_cost():
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()
    coord = _make_coordinator(agent, deps, aggregate_budget_usd=0.10)
    assert coord._aggregate_watcher is None
    handle = await coord.fork(
        [BranchSpec(label="a", steer="a")],
        parent_history=_seed_history("p"),
    )
    bid = handle.branches[0]
    tracker = coord.branches[bid].cost_tracker
    assert tracker is not None
    await tracker.on_cost_update(
        CostInfo(
            run_cost_usd=None,
            total_cost_usd=None,
            run_request_tokens=0,
            run_response_tokens=0,
            total_request_tokens=0,
            total_response_tokens=0,
            run_count=1,
        )
    )
    assert coord.branches[bid].status.state == "running"
    agg = coord._aggregate_watcher
    assert agg is not None and agg.aggregate() is None
    await _drain_branch_tasks(coord)


async def test_aggregate_per_call_budget_overrides_constructor_default():
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()
    coord = _make_coordinator(agent, deps, aggregate_budget_usd=999.0)
    handle = await coord.fork(
        [BranchSpec(label="a", steer="a")],
        parent_history=_seed_history("p"),
        aggregate_budget_usd=0.05,
    )
    assert coord._aggregate_watcher is not None
    assert coord._aggregate_watcher.aggregate_budget_usd == 0.05
    bid = handle.branches[0]
    tracker = coord.branches[bid].cost_tracker
    assert tracker is not None
    await tracker.on_cost_update(_cost_info(total=0.10))
    assert coord.branches[bid].status.state == "aggregate_budget_exhausted"
    await _drain_branch_tasks(coord)


async def test_per_branch_cost_tracking_for_run_returns_self_without_branch_field():
    """Parent runs (no _branch_cost_tracking on deps) keep the parent's clone."""
    parent = _PerBranchCostTracking(model_name="anthropic:claude-sonnet-4-6")
    deps = DeepAgentDeps(backend=StateBackend())
    ctx = type("Ctx", (), {"deps": deps})()
    out = await parent.for_run(cast(Any, ctx))
    assert out is parent


async def test_per_branch_cost_tracking_for_run_returns_per_branch_when_set():
    parent = _PerBranchCostTracking(model_name="anthropic:claude-sonnet-4-6")
    branch_cap = _PerBranchCostTracking(model_name="anthropic:claude-sonnet-4-6", budget_usd=0.05)
    deps = DeepAgentDeps(backend=StateBackend())
    deps._branch_cost_tracking = branch_cap
    ctx = type("Ctx", (), {"deps": deps})()
    out = await parent.for_run(cast(Any, ctx))
    assert out is branch_cap


def test_agent_model_name_handles_string_and_object_and_unknown():
    class FakeAgentWithStr:
        model = "anthropic:claude-sonnet-4-6"

    class _ModelObj:
        model_id = "openai:gpt-4o-mini"

    class FakeAgentWithObj:
        model = _ModelObj()

    class FakeAgentUnknown:
        model = object()

    assert _agent_model_name(FakeAgentWithStr()) == "anthropic:claude-sonnet-4-6"
    assert _agent_model_name(FakeAgentWithObj()) == "openai:gpt-4o-mini"
    assert _agent_model_name(FakeAgentUnknown()) is None


def test_find_parent_cost_tracking_via_deps_direct():
    """When deps._branch_cost_tracking is set (nested fork), return it."""
    deps = DeepAgentDeps(backend=StateBackend())
    direct = CostTracking(model_name="anthropic:claude-sonnet-4-6")
    deps._branch_cost_tracking = direct
    assert _find_parent_cost_tracking(deps) is direct


def test_find_parent_cost_tracking_returns_none_when_unwired():
    deps = DeepAgentDeps(backend=StateBackend())
    assert _find_parent_cost_tracking(deps) is None


async def test_find_parent_cost_tracking_walks_root_capability():
    """When no direct deps tracker, walk the agent's root capability list."""
    agent = create_deep_agent(
        model=TestModel(),
        forking=True,
        cost_tracking=True,
        cost_budget_usd=None,
    )
    deps = DeepAgentDeps(backend=StateBackend())
    coord = ForkCoordinator(
        agent=agent,
        parent_deps=deps,
        max_branches=10,
        max_depth=2,
        store=InMemoryForkStateStore(),
    )
    deps.fork_coordinator = coord
    found = _find_parent_cost_tracking(deps)
    assert isinstance(found, CostTracking)


def test_build_branch_cost_tracking_warns_when_no_parent_and_no_model():
    """No registered CostTracking, no resolvable model name — warns and returns None."""

    class FakeAgent:
        model = object()  # unrecognised shape

    watcher = BudgetWatcher(
        coordinator=cast(Any, None),
        branch_id="bx",
        budget_usd=0.05,
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = _build_branch_cost_tracking(
            parent_cost_cap=None,
            agent=FakeAgent(),
            branch_label="x",
            budget_usd=0.05,
            watcher=watcher,
        )
    assert result is None
    assert any("budget enforcement is disabled" in str(w.message) for w in caught)


async def test_aggregate_watcher_second_call_skips_non_running_branches():
    """After branches transition to aggregate_budget_exhausted, a follow-up
    cost update must not re-terminate them (covers the non-`running`
    branch of the watcher's iteration)."""
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()
    coord = _make_coordinator(agent, deps, aggregate_budget_usd=0.05)

    handle = await coord.fork(
        [BranchSpec(label="a", steer="a")],
        parent_history=_seed_history("p"),
    )
    bid = handle.branches[0]
    tracker = coord.branches[bid].cost_tracker
    assert tracker is not None
    await tracker.on_cost_update(_cost_info(total=0.10))
    assert coord.branches[bid].status.state == "aggregate_budget_exhausted"
    await tracker.on_cost_update(_cost_info(total=0.20))
    assert coord.branches[bid].status.state == "aggregate_budget_exhausted"
    await _drain_branch_tasks(coord)


async def test_aggregate_watcher_skips_already_terminated_sibling():
    """When the aggregate cap trips, the termination loop skips a sibling that
    is already in a terminal state (covers the non-`running` loop branch)."""
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()
    coord = _make_coordinator(agent, deps, aggregate_budget_usd=0.05)

    handle = await coord.fork(
        [BranchSpec(label="a", steer="a"), BranchSpec(label="b", steer="b")],
        parent_history=_seed_history("p"),
    )
    aid, bid = handle.branches
    await coord.terminate_branch(aid)
    assert coord.branches[aid].status.state == "terminated"

    tracker_b = coord.branches[bid].cost_tracker
    assert tracker_b is not None
    await tracker_b.on_cost_update(_cost_info(total=0.10))

    assert coord.branches[bid].status.state == "aggregate_budget_exhausted"
    assert coord.branches[aid].status.state == "terminated"
    await _drain_branch_tasks(coord)


class _StubCtx:
    def __init__(self, deps: DeepAgentDeps) -> None:
        self.deps = deps


async def test_fork_cost_tool_returns_disabled_when_no_coordinator():
    deps = DeepAgentDeps(backend=StateBackend())
    toolset = create_fork_toolset()
    fork_cost_fn = toolset.tools["fork_cost"].function
    out = await fork_cost_fn(cast(Any, _StubCtx(deps)), "any-id")
    assert out == NOT_ENABLED_MESSAGE


async def test_fork_cost_tool_no_active_fork():
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()
    coord = _make_coordinator(agent, deps)
    deps.fork_coordinator = coord
    toolset = create_fork_toolset()
    fork_cost_fn = toolset.tools["fork_cost"].function
    out = await fork_cost_fn(cast(Any, _StubCtx(deps)), "any-id")
    assert isinstance(out, str)
    assert "no active fork" in out


async def test_fork_cost_tool_mismatched_fork_id():
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()
    coord = _make_coordinator(agent, deps)
    deps.fork_coordinator = coord
    await coord.fork(
        [BranchSpec(label="a", steer="a")],
        parent_history=_seed_history("p"),
    )
    toolset = create_fork_toolset()
    fork_cost_fn = toolset.tools["fork_cost"].function
    out = await fork_cost_fn(cast(Any, _StubCtx(deps)), "wrong-id")
    assert isinstance(out, str)
    assert "does not match" in out
    await _drain_branch_tasks(coord)


async def test_fork_cost_tool_success_returns_summary():
    deps = DeepAgentDeps(backend=StateBackend())
    agent = _make_test_agent()
    coord = _make_coordinator(agent, deps)
    deps.fork_coordinator = coord
    handle = await coord.fork(
        [BranchSpec(label="a", steer="a")],
        parent_history=_seed_history("p"),
    )
    toolset = create_fork_toolset()
    fork_cost_fn = toolset.tools["fork_cost"].function
    out = await fork_cost_fn(cast(Any, _StubCtx(deps)), handle.fork_id)
    assert isinstance(out, ForkCostSummary)
    assert out.fork_id == handle.fork_id
    await _drain_branch_tasks(coord)


def test_build_branch_cost_tracking_from_model_name_when_no_parent():
    """No parent CostTracking but a resolvable model name — fresh tracker built."""

    class FakeAgent:
        model = "anthropic:claude-sonnet-4-6"

    watcher = BudgetWatcher(
        coordinator=cast(Any, None),
        branch_id="bx",
        budget_usd=0.05,
    )
    result = _build_branch_cost_tracking(
        parent_cost_cap=None,
        agent=FakeAgent(),
        branch_label="x",
        budget_usd=0.05,
        watcher=watcher,
    )
    assert isinstance(result, _PerBranchCostTracking)
    assert result.budget_usd == 0.05
    assert result.on_cost_update is watcher


async def test_start_fork_from_cli_forwards_aggregate_budget():
    """`apps.cli.forking.start_fork_from_cli` must thread the picker's
    `aggregate_budget_usd` through to `coordinator.fork` so the
    aggregate watcher gets the right cap. Mirrors the constructor-vs-call
    test `test_aggregate_per_call_budget_overrides_constructor_default`
    but at the CLI bridge level."""
    from pydantic_ai.messages import ModelRequest, UserPromptPart

    from apps.cli.app import DeepApp
    from apps.cli.forking import ForkPickerResult, start_fork_from_cli
    from pydantic_deep import create_deep_agent

    agent = create_deep_agent(
        model=TestModel(call_tools=[]),
        forking=True,
        include_skills=False,
        include_plan=False,
        include_memory=False,
        include_subagents=False,
        include_teams=False,
        include_todo=False,
        web_search=False,
        web_fetch=False,
        cost_tracking=False,
        context_manager=False,
        stuck_loop_detection=False,
        context_discovery=False,
    )
    deps = DeepAgentDeps(backend=StateBackend())
    app = DeepApp(agent=agent, deps=deps, model="test", version="0.0.0")
    app.message_history = [ModelRequest(parts=[UserPromptPart(content="seed")])]

    result = ForkPickerResult(
        specs=[BranchSpec(label="a", steer="approach A")],
        aggregate_budget_usd=0.50,
    )
    session = await start_fork_from_cli(app, result)
    assert session.coordinator._aggregate_watcher is not None
    assert session.coordinator._aggregate_watcher.aggregate_budget_usd == 0.50

    await asyncio.gather(
        *(rt.task for rt in session.coordinator.branches.values()),
        return_exceptions=True,
    )
