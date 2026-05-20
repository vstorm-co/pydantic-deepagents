"""Per-parent-run fork coordinator owning branch tasks and merge resolution.

The coordinator is the workhorse of Live Run Forking. It owns the
``asyncio.Task`` for each branch, snapshots parent history at fork-call time,
serialises mutating operations via a per-coordinator lock, and resolves
merges by awaiting the picked winner's task.

Stage 1 limits (``max_branches=2``, ``max_depth=1``) are lifted to ``10`` /
``2`` in Stage 4, which also adds per-branch :class:`CostTracking`-driven
budget caps (:class:`_BudgetWatcher`), a fork-wide aggregate cap
(:class:`_AggregateBudgetWatcher`), the :meth:`ForkCoordinator.fork_cost`
method, and partial-history capture so a budget-exhausted branch can still
be picked as merge winner.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

from pydantic_ai_shields import CostInfo, CostTracking

from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.toolsets.checkpointing import Checkpoint, CheckpointStore
from pydantic_deep.toolsets.forking.isolation import BranchOverlay, clone_for_branch
from pydantic_deep.toolsets.forking.store import ForkStateStore
from pydantic_deep.types import (
    BranchCost,
    BranchIsolation,
    BranchSpec,
    BranchStatus,
    ForkCostSummary,
    ForkHandle,
    MergeResult,
    MergeStrategy,
)

if TYPE_CHECKING:
    from pydantic_ai import RunContext

    from pydantic_deep.capabilities.forking import LiveForkCapability


logger = logging.getLogger(__name__)

#: How long to wait for a cancelled discarded branch to finish its ``finally``
#: cleanup during ``merge_or_select`` before giving up and moving on.
_CANCEL_CLEANUP_TIMEOUT_S: float = 1.0


class ForkBranchLimitError(Exception):
    """Raised when a ``fork_run`` call exceeds ``max_branches``."""


class ForkDepthLimitError(Exception):
    """Raised when a ``fork_run`` call from within a branch exceeds ``max_depth``."""


class _PerBranchCostTracking(CostTracking):  # type: ignore[misc]
    """:class:`CostTracking` subclass that isolates per-run state.

    Stock :class:`CostTracking` inherits :meth:`AbstractCapability.for_run`,
    which returns ``self`` — so every concurrent branch run would mutate
    the same accumulator and a single ``budget_usd`` would apply across
    all branches. This subclass overrides ``for_run`` to return the
    instance stored on :attr:`DeepAgentDeps._branch_cost_tracking` when
    set, giving each branch its own zero-initialised accumulators.
    """

    async def for_run(self, ctx: RunContext[Any]) -> CostTracking:
        per_branch: CostTracking | None = getattr(ctx.deps, "_branch_cost_tracking", None)
        if per_branch is None:
            return self
        return per_branch


@dataclass
class _BudgetWatcher:
    """Per-branch ``on_cost_update`` callback that enforces ``budget_usd``.

    The cost callback is awaited by ``CostTracking.after_run`` when it
    returns a coroutine, so this watcher uses direct ``await`` rather than
    spawning a background task.
    """

    coordinator: ForkCoordinator
    branch_id: str
    budget_usd: float | None

    async def __call__(self, info: CostInfo) -> None:
        await self.coordinator._on_branch_cost_update(self.branch_id, info)
        if (
            self.budget_usd is not None
            and info.total_cost_usd is not None
            and info.total_cost_usd >= self.budget_usd
        ):
            await self.coordinator.terminate_branch(self.branch_id, reason="budget_exhausted")


@dataclass
class _AggregateBudgetWatcher:
    """Coordinator-level aggregate cap.

    Tracks the latest ``total_cost_usd`` per branch. When the sum exceeds
    :attr:`aggregate_budget_usd`, terminates every still-running branch
    with reason ``"aggregate_budget_exhausted"``.

    Best-effort — concurrent callbacks may briefly overrun before
    terminations propagate. See the "Aggregate budget enforcement is
    best-effort" callout in ``docs/capabilities/live-fork.md``.
    """

    coordinator: ForkCoordinator
    aggregate_budget_usd: float | None
    _per_branch: dict[str, float] = field(default_factory=dict, init=False, repr=False)

    async def update(self, branch_id: str, info: CostInfo) -> None:
        if info.total_cost_usd is None:
            return
        self._per_branch[branch_id] = info.total_cost_usd
        if self.aggregate_budget_usd is None:
            return
        total = sum(self._per_branch.values())
        if total < self.aggregate_budget_usd:
            return
        for bid, rt in list(self.coordinator.branches.items()):
            if rt.status.state == "running":
                await self.coordinator.terminate_branch(bid, reason="aggregate_budget_exhausted")

    def aggregate(self) -> float | None:
        if not self._per_branch:
            return None
        return sum(self._per_branch.values())


@dataclass
class BranchRuntime:
    """Runtime state of a single branch task."""

    spec: BranchSpec
    task: asyncio.Task[Any]
    deps: DeepAgentDeps
    overlay: BranchOverlay | None
    status: BranchStatus
    cost_tracker: CostTracking | None = None
    budget_usd: float | None = None
    #: Snapshot of the branch's history captured on every
    #: ``before_model_request``. When a budget watcher cancels the task
    #: mid-run, ``merge_or_select`` falls back to this list because the
    #: awaited task raises ``CancelledError`` and produces no result.
    partial_history: list[Any] = field(default_factory=list)


class ForkCoordinator:
    """Owns per-branch state for one parent run.

    A fresh coordinator is allocated by :meth:`LiveForkCapability.for_run`,
    so concurrent parent runs of the same agent never share state.

    Args:
        agent: The owning agent — used to spawn branch ``agent.run()`` tasks.
        parent_deps: The parent run's deps; cloned per branch via
            :func:`clone_for_branch`.
        max_branches: Maximum number of branches per fork.
        max_depth: Maximum fork nesting depth.
        store: The :class:`ForkStateStore` used to persist :class:`ForkHandle`.
        checkpoint_store: Optional explicit checkpoint store. When ``None``,
            the coordinator falls back to ``parent_deps.checkpoint_store``.
    """

    def __init__(
        self,
        agent: Any,
        parent_deps: DeepAgentDeps,
        *,
        max_branches: int,
        max_depth: int,
        store: ForkStateStore,
        checkpoint_store: CheckpointStore | None = None,
        aggregate_budget_usd: float | None = None,
    ) -> None:
        self.agent = agent
        self.parent_deps = parent_deps
        self.max_branches = max_branches
        self.max_depth = max_depth
        self.store = store
        self.checkpoint_store = checkpoint_store
        self.aggregate_budget_usd = aggregate_budget_usd
        self.branches: dict[str, BranchRuntime] = {}
        self._handle: ForkHandle | None = None
        self._lock = asyncio.Lock()
        self.capability: LiveForkCapability | None = None
        self._aggregate_watcher: _AggregateBudgetWatcher | None = None

    @property
    def fork_id(self) -> str | None:
        """The active fork's id, or ``None`` if ``fork()`` has not been called yet.

        Exposed so consumers (e.g. Stage 2's ``diff_branches`` tool) can
        validate caller-supplied ``fork_id`` without reaching into the
        coordinator's private ``_handle`` attribute.
        """
        return self._handle.fork_id if self._handle is not None else None

    def _resolve_checkpoint_store(self) -> CheckpointStore | None:
        explicit = self.checkpoint_store
        if explicit is not None:
            return explicit
        return getattr(self.parent_deps, "checkpoint_store", None)

    async def _save_anchor_checkpoint(
        self,
        *,
        anchor: Literal["pre-fork", "post-fork"],
        fork_id: str,
        messages: list[Any],
    ) -> str | None:
        """Save a fork anchor checkpoint; return its id, or ``None`` if no store.

        Writes directly to ``CheckpointStore`` rather than calling
        ``CheckpointMiddleware._save_now``: the coordinator owns its own
        anchor lifecycle and must remain functional even when checkpoint
        middleware is not registered on the agent. Consequence — anchor
        checkpoints are subject to the store's pruning policy
        (``max_checkpoints``) just like any other checkpoint; see the
        "Pre-fork anchor pruning" callout in ``docs/capabilities/live-fork.md``.
        """
        cp_store = self._resolve_checkpoint_store()
        if cp_store is None:
            return None
        label = f"fork:{fork_id}" if anchor == "pre-fork" else f"post-fork:{fork_id}"
        cp = Checkpoint(
            id=str(uuid.uuid4()),
            label=label,
            turn=0,
            messages=list(messages),
            message_count=len(messages),
            created_at=datetime.now(timezone.utc),
            metadata={"fork_id": fork_id, "anchor": anchor},
        )
        await cp_store.save(cp)
        return cp.id

    async def fork(
        self,
        specs: list[BranchSpec],
        *,
        parent_history: list[Any],
        isolation: BranchIsolation | None = None,
        strategy: MergeStrategy | None = None,
        aggregate_budget_usd: float | None = None,
    ) -> ForkHandle:
        """Spawn ``len(specs)`` branch tasks and return a handle.

        Args:
            specs: Branch definitions; ``len(specs)`` must not exceed
                :attr:`max_branches`.
            parent_history: Parent run's message snapshot at fork time.
            isolation: Per-branch isolation overrides (defaults to
                :class:`BranchIsolation`).
            strategy: Merge strategy (currently ``kind="manual"`` only).
            aggregate_budget_usd: Optional fork-wide budget cap; when set,
                hitting it terminates every still-running branch with
                ``state="aggregate_budget_exhausted"``. Overrides the
                value passed to :meth:`__init__`. Enforcement is
                best-effort under concurrent callbacks — see the
                "Aggregate budget enforcement" note in the live-fork doc.

        Raises:
            ValueError: If ``specs`` is empty.
            ForkBranchLimitError: If ``len(specs) > max_branches``.
            ForkDepthLimitError: If parent's ``_fork_depth >= max_depth``.
        """
        if not specs:
            raise ValueError("fork() requires at least one BranchSpec.")
        if len(specs) > self.max_branches:
            raise ForkBranchLimitError(
                f"{len(specs)} branches requested, max_branches={self.max_branches}."
            )
        if self.parent_deps._fork_depth >= self.max_depth:
            raise ForkDepthLimitError(
                f"Parent run is already at fork depth {self.parent_deps._fork_depth}; "
                f"max_depth={self.max_depth}."
            )

        async with self._lock:
            fork_id = str(uuid.uuid4())

            parent_checkpoint_id = await self._save_anchor_checkpoint(
                anchor="pre-fork", fork_id=fork_id, messages=parent_history
            )
            if parent_checkpoint_id is None:
                warnings.warn(
                    "Forking enabled without a checkpoint store — rewind safety net unavailable.",
                    stacklevel=2,
                )

            effective_isolation = isolation or BranchIsolation()
            effective_strategy = strategy or MergeStrategy()

            effective_aggregate = (
                aggregate_budget_usd
                if aggregate_budget_usd is not None
                else self.aggregate_budget_usd
            )
            self._aggregate_watcher = _AggregateBudgetWatcher(
                coordinator=self, aggregate_budget_usd=effective_aggregate
            )

            parent_cost_cap = _find_parent_cost_tracking(self.parent_deps)

            for spec in specs:
                branch_id = str(uuid.uuid4())
                cloned_deps = clone_for_branch(self.parent_deps, effective_isolation)
                overlay = (
                    cloned_deps.backend if isinstance(cloned_deps.backend, BranchOverlay) else None
                )

                watcher = _BudgetWatcher(
                    coordinator=self, branch_id=branch_id, budget_usd=spec.budget_usd
                )
                branch_cost_cap = _build_branch_cost_tracking(
                    parent_cost_cap=parent_cost_cap,
                    agent=self.agent,
                    branch_label=spec.label,
                    budget_usd=spec.budget_usd,
                    watcher=watcher,
                )
                cloned_deps._branch_cost_tracking = branch_cost_cap
                cloned_deps._branch_id = branch_id
                cloned_deps._parent_fork_coordinator = self

                task = asyncio.create_task(
                    self.agent.run(
                        spec.steer,
                        message_history=list(parent_history),
                        deps=cloned_deps,
                    )
                )
                status = BranchStatus(
                    id=branch_id,
                    label=spec.label,
                    state="running",
                    current_turn=0,
                    last_activity_at=datetime.now(timezone.utc),
                )
                runtime = BranchRuntime(
                    spec=spec,
                    task=task,
                    deps=cloned_deps,
                    overlay=overlay,
                    status=status,
                    cost_tracker=branch_cost_cap,
                    budget_usd=spec.budget_usd,
                )
                self.branches[branch_id] = runtime

                def _make_done_cb(rt: BranchRuntime) -> Any:
                    def _on_done(t: asyncio.Task[Any]) -> None:
                        try:
                            if t.cancelled():
                                if rt.status.state == "running":
                                    rt.status.state = "terminated"
                            elif t.exception() is not None:
                                rt.status.state = "failed"
                                rt.status.error = str(t.exception())
                            else:
                                rt.status.state = "done"
                        except Exception:  # pragma: no cover - defensive
                            logger.warning(
                                "branch %s done-callback failed", rt.status.id, exc_info=True
                            )

                    return _on_done

                task.add_done_callback(_make_done_cb(runtime))

            handle = ForkHandle(
                fork_id=fork_id,
                parent_checkpoint_id=parent_checkpoint_id,
                branches=list(self.branches.keys()),
                merge_strategy=effective_strategy,
                created_at=datetime.now(timezone.utc),
            )
            await self.store.save(handle)
            self._handle = handle
            return handle

    async def terminate_branch(self, branch_id: str, *, reason: str | None = None) -> None:
        """Cancel a branch task and mark its terminal status.

        Args:
            branch_id: Branch to cancel.
            reason: When ``"budget_exhausted"`` or
                ``"aggregate_budget_exhausted"``, the branch's status is
                set to the matching state and its ``error`` field is
                populated with a debug-friendly message. Otherwise the
                terminal state is ``"terminated"``.

        Only sets a new terminal state when the task is still running; if
        it already completed (success / failure / earlier cancellation),
        ``_on_done`` has already written the correct terminal state and we
        must not overwrite it. Idempotent: a second call for the same
        ``branch_id`` (e.g. when the aggregate watcher races with the
        per-branch watcher) is a no-op.
        """
        if branch_id not in self.branches:
            raise ValueError(f"Unknown branch id: {branch_id!r}")
        runtime = self.branches[branch_id]
        if runtime.task.done() or runtime.status.state != "running":
            return
        runtime.task.cancel()
        if reason == "budget_exhausted":
            runtime.status.state = "budget_exhausted"
            cap = runtime.cost_tracker
            total = cap.total_cost if cap is not None else 0.0
            runtime.status.error = f"budget exhausted: ${total:.4f} >= ${runtime.budget_usd}"
        elif reason == "aggregate_budget_exhausted":
            runtime.status.state = "aggregate_budget_exhausted"
            agg_watcher = self._aggregate_watcher
            agg = agg_watcher.aggregate() if agg_watcher is not None else None
            cap = agg_watcher.aggregate_budget_usd if agg_watcher is not None else None
            runtime.status.error = (
                f"aggregate budget exhausted: ${agg:.4f} >= ${cap}"
                if agg is not None
                else "aggregate budget exhausted"
            )
        else:
            runtime.status.state = "terminated"

    async def _on_branch_cost_update(self, branch_id: str, info: CostInfo) -> None:
        """Relay a per-branch cost update to the aggregate watcher.

        Called by :class:`_BudgetWatcher` before it checks the per-branch
        cap; lets the coordinator track the fork-wide sum without giving
        the per-branch watcher a reference to its sibling watchers.
        """
        if self._aggregate_watcher is None:  # pragma: no cover - defensive
            return
        await self._aggregate_watcher.update(branch_id, info)

    async def merge_or_select(self, action: str) -> MergeResult:
        """Resolve the fork by picking a winner.

        Supported actions:

        - ``"pick:<branch_id>"`` — await that branch's task; cancel and
          discard all others; release discarded overlays; save a
          ``post-fork:<fork_id>`` checkpoint if checkpointing is available.
        """
        if not action.startswith("pick:"):
            raise ValueError(f"Unsupported merge action: {action!r}. Expected 'pick:<branch_id>'.")
        target_id = action.split(":", 1)[1]
        if not target_id:
            raise ValueError("pick action missing branch id.")
        if target_id not in self.branches:
            raise ValueError(f"Unknown branch id: {target_id!r}")
        if self._handle is None:  # pragma: no cover - defensive
            raise RuntimeError("merge_or_select called before fork()")

        async with self._lock:
            winner = self.branches[target_id]
            try:
                result = await winner.task
                history_after_merge = list(result.all_messages())
            except asyncio.CancelledError:
                _exhausted_states = {
                    "terminated",
                    "budget_exhausted",
                    "aggregate_budget_exhausted",
                }
                if winner.status.state in _exhausted_states and winner.partial_history:
                    history_after_merge = list(winner.partial_history)
                else:
                    raise RuntimeError(
                        f"Winning branch {target_id!r} was cancelled before merge."
                    ) from None

            discarded: list[str] = []
            for bid, rt in list(self.branches.items()):
                if bid == target_id:
                    continue
                if not rt.task.done():
                    rt.task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
                        try:
                            await asyncio.wait_for(rt.task, timeout=_CANCEL_CLEANUP_TIMEOUT_S)
                        except Exception:  # pragma: no cover - defensive
                            logger.warning("discarded branch %s cleanup raised", bid, exc_info=True)
                rt.overlay = None
                discarded.append(bid)

            await self._save_anchor_checkpoint(
                anchor="post-fork",
                fork_id=self._handle.fork_id,
                messages=history_after_merge,
            )

            return MergeResult(
                fork_id=self._handle.fork_id,
                winner_branch_id=target_id,
                discarded_branches=discarded,
                history_after_merge=history_after_merge,
            )

    def inspect_branches(self) -> list[BranchStatus]:
        """Return a snapshot of every branch's current status."""
        return [rt.status for rt in self.branches.values()]

    def fork_cost(self) -> ForkCostSummary:
        """Return per-branch and aggregate cost for the active fork.

        Returns:
            :class:`ForkCostSummary` with one :class:`BranchCost` entry per
            branch. ``aggregate_usd`` sums the ``cumulative_usd`` values of
            branches whose cost is known (skips branches whose model has no
            pricing or has not produced a tracked run yet); when no branch
            has a known cost, ``aggregate_usd`` is ``None``.

        Raises:
            RuntimeError: If called before :meth:`fork` has been invoked.
        """
        if self._handle is None:
            raise RuntimeError("fork_cost() called before fork() — no active fork.")
        per_branch: dict[str, BranchCost] = {}
        agg_total: float = 0.0
        agg_has_value = False
        for bid, rt in self.branches.items():
            cumulative = rt.cost_tracker.total_cost if rt.cost_tracker is not None else None
            if cumulative is not None:
                agg_total += cumulative
                agg_has_value = True
            remaining: float | None = (
                rt.budget_usd - cumulative
                if rt.budget_usd is not None and cumulative is not None
                else None
            )
            per_branch[bid] = BranchCost(
                branch_id=bid,
                branch_label=rt.spec.label,
                cumulative_usd=cumulative,
                budget_usd=rt.budget_usd,
                remaining_usd=remaining,
                state=rt.status.state,
            )
        aggregate_usd: float | None = agg_total if agg_has_value else None
        aggregate_budget_usd: float | None = (
            self._aggregate_watcher.aggregate_budget_usd
            if self._aggregate_watcher is not None
            else self.aggregate_budget_usd
        )
        aggregate_remaining_usd: float | None = (
            aggregate_budget_usd - aggregate_usd
            if aggregate_budget_usd is not None and aggregate_usd is not None
            else None
        )
        return ForkCostSummary(
            fork_id=self._handle.fork_id,
            per_branch=per_branch,
            aggregate_usd=aggregate_usd,
            aggregate_budget_usd=aggregate_budget_usd,
            aggregate_remaining_usd=aggregate_remaining_usd,
        )

    def capture_partial_history(self, branch_id: str, messages: list[Any]) -> None:
        """Record a branch's latest message snapshot for merge fallback.

        Called by :class:`LiveForkCapability.before_model_request` on every
        branch run so that, if the branch is later cancelled by a budget
        watcher, :meth:`merge_or_select` has a snapshot to return when the
        user picks the exhausted branch as winner. Silently ignored when
        the branch is unknown — defensive against late callbacks after
        ``aclose()``.
        """
        runtime = self.branches.get(branch_id)
        if runtime is None:  # pragma: no cover - defensive
            return
        runtime.partial_history = list(messages)

    async def aclose(self) -> None:
        """Cancel every outstanding branch task — used on parent cancellation."""
        for rt in self.branches.values():
            if not rt.task.done():
                rt.task.cancel()


def _find_parent_cost_tracking(deps: DeepAgentDeps) -> CostTracking | None:
    """Locate the parent agent's :class:`CostTracking` capability.

    Resolution order:
    1. ``deps._branch_cost_tracking`` — set when the parent is itself a
       nested branch (fork-of-fork).
    2. Walk ``agent._root_capability.capabilities`` via the fork
       coordinator's agent reference and return the first
       :class:`CostTracking` instance found.

    Returns ``None`` when no capability is registered — callers should
    fall back to constructing a fresh :class:`_PerBranchCostTracking`
    from the agent's model name.
    """
    direct: CostTracking | None = getattr(deps, "_branch_cost_tracking", None)
    if direct is not None:
        return direct
    coord = getattr(deps, "fork_coordinator", None)
    if coord is None:  # pragma: no cover - fork() is only called via the coordinator
        return None
    root_cap = getattr(coord.agent, "_root_capability", None)
    if root_cap is None:  # pragma: no cover - all real agents have _root_capability
        return None
    for cap in getattr(root_cap, "capabilities", ()):
        if isinstance(cap, CostTracking):
            return cap
    return None


def _build_branch_cost_tracking(
    *,
    parent_cost_cap: CostTracking | None,
    agent: Any,
    branch_label: str,
    budget_usd: float | None,
    watcher: _BudgetWatcher,
) -> _PerBranchCostTracking | None:
    """Build the per-branch :class:`_PerBranchCostTracking` clone.

    Returns ``None`` when neither the parent's registered capability nor
    the agent's model can supply a pricing-capable instance — the branch
    still runs, but budget enforcement is silently disabled and
    ``BranchCost.cumulative_usd`` will be ``None``.
    """
    if parent_cost_cap is not None:
        return _PerBranchCostTracking(
            model_name=parent_cost_cap.model_name,
            budget_usd=budget_usd if budget_usd is not None else parent_cost_cap.budget_usd,
            strict=parent_cost_cap.strict,
            on_cost_update=watcher,
        )
    model_name = _agent_model_name(agent)
    if model_name is None:
        warnings.warn(
            f"Branch {branch_label!r}: no CostTracking on parent and no resolvable "
            "model name on the agent — per-branch budget enforcement is disabled.",
            stacklevel=2,
        )
        return None
    return _PerBranchCostTracking(
        model_name=model_name,
        budget_usd=budget_usd,
        on_cost_update=watcher,
    )


def _agent_model_name(agent: Any) -> str | None:
    """Best-effort extraction of the agent's model name string.

    Pydantic-AI's ``Agent.model`` can be either a string ("anthropic:...")
    or a model object with a ``model_id`` attribute; we accept both. Returns
    ``None`` when neither shape applies (e.g. a ``TestModel`` instance).
    """
    model = getattr(agent, "model", None)
    if isinstance(model, str):
        return model
    model_id = getattr(model, "model_id", None)
    if isinstance(model_id, str):
        return model_id
    return None


# Aliases the toolset module re-exports — keeps the public surface stable.
__all__ = [
    "BranchRuntime",
    "ForkBranchLimitError",
    "ForkCoordinator",
    "ForkDepthLimitError",
]
