"""Per-branch and fork-wide budget enforcement for live forking."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic_ai_shields import CostInfo

    from pydantic_deep.features.forking.coordinator import ForkCoordinator


@dataclass
class BudgetWatcher:
    """Per-branch `on_cost_update` callback that enforces `budget_usd`.

    The cost callback is awaited by `CostTracking.after_run` when it returns a
    coroutine, so this watcher uses direct `await` rather than spawning a task.
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
class AggregateBudgetWatcher:
    """Coordinator-level aggregate cap.

    Tracks the latest `total_cost_usd` per branch. When the sum exceeds
    `aggregate_budget_usd`, terminates every still-running branch with reason
    `"aggregate_budget_exhausted"`.

    Best-effort - concurrent callbacks may briefly overrun before terminations
    propagate. See the "Aggregate budget enforcement is best-effort" callout in
    `docs/capabilities/live-fork.md`.
    """

    coordinator: ForkCoordinator
    aggregate_budget_usd: float | None
    _per_branch: dict[str, float] = field(default_factory=dict, init=False, repr=False)

    async def update(self, branch_id: str, info: CostInfo) -> None:
        if info.total_cost_usd is None:
            return
        # Ignore a late callback from a branch that has already terminated: its
        # cost was captured at termination, and recording a higher straggler
        # value would inflate aggregate() past true live spend (A6).
        rt = self.coordinator.branches.get(branch_id)
        if rt is not None and rt.status.state != "running":
            return
        self._per_branch[branch_id] = info.total_cost_usd
        if self.aggregate_budget_usd is None:
            return
        total = sum(list(self._per_branch.values()))
        if total < self.aggregate_budget_usd:
            return
        for bid, rt in list(self.coordinator.branches.items()):
            if rt.status.state == "running":
                await self.coordinator.terminate_branch(bid, reason="aggregate_budget_exhausted")

    def aggregate(self) -> float | None:
        values = list(self._per_branch.values())
        if not values:
            return None
        return sum(values)
