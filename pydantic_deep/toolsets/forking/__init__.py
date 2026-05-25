"""Agent-facing tools for Live Run Forking.

Exposes ``create_fork_toolset()`` returning a :class:`FunctionToolset` with
four tools:

- ``fork_run`` — spawn N branch tasks.
- ``inspect_branches`` — read current branch statuses.
- ``merge_or_select`` — resolve the fork by picking a winner.
- ``terminate_branch`` — cancel one branch task.

All tools read the per-run :class:`ForkCoordinator` from
``ctx.deps.fork_coordinator``. The coordinator is allocated by
:class:`LiveForkCapability.for_run` on each ``agent.run()``.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.toolsets.forking.coordinator import (
    BranchRuntime,
    ForkBranchLimitError,
    ForkCoordinator,
    ForkDepthLimitError,
)
from pydantic_deep.toolsets.forking.diff import build_diff_report
from pydantic_deep.toolsets.forking.editor import EditorDetector, EditorKind
from pydantic_deep.toolsets.forking.isolation import BranchOverlay, clone_for_branch
from pydantic_deep.toolsets.forking.judge import (
    JUDGE_SYSTEM_PROMPT,
    JudgeAgent,
    compute_confidence,
    count_retry_parts,
    count_stuck_loop_hits,
)
from pydantic_deep.toolsets.forking.materializer import ForkMaterializer
from pydantic_deep.toolsets.forking.store import ForkStateStore, InMemoryForkStateStore
from pydantic_deep.types import (
    BranchCost,
    BranchDiffReport,
    BranchIsolation,
    BranchOutcome,
    BranchSpec,
    ConfidenceSignals,
    FlushError,
    FlushReport,
    ForkCostSummary,
    JudgeVerdict,
    MergeStrategy,
    ResolveOutcome,
)

NOT_ENABLED_MESSAGE = (
    "Forking is not enabled on this agent. Pass `forking=True` to `create_deep_agent()` to enable."
)


def _coordinator_from_ctx(ctx: RunContext[DeepAgentDeps]) -> ForkCoordinator | None:
    return getattr(ctx.deps, "fork_coordinator", None)


def _coerce_specs(raw: list[dict[str, Any]]) -> list[BranchSpec]:
    return [
        BranchSpec(
            label=item["label"],
            steer=item["steer"],
            model=item.get("model"),
            budget_usd=item.get("budget_usd"),
            extra_instructions=item.get("extra_instructions"),
        )
        for item in raw
    ]


def _coerce_isolation(raw: dict[str, Any] | None) -> BranchIsolation:
    if raw is None:
        return BranchIsolation()
    return BranchIsolation(**raw)


def _coerce_strategy(raw: dict[str, Any] | None) -> MergeStrategy:
    if raw is None:
        return MergeStrategy()
    return MergeStrategy(**raw)


def create_fork_toolset(  # noqa: C901
    id: str = "deep-forking",
) -> FunctionToolset[DeepAgentDeps]:
    """Build the four-tool forking toolset wired to the per-run coordinator."""

    toolset: FunctionToolset[DeepAgentDeps] = FunctionToolset(id=id)

    @toolset.tool
    async def fork_run(
        ctx: RunContext[DeepAgentDeps],
        specs: list[dict[str, Any]],
        isolation: dict[str, Any] | None = None,
        strategy: dict[str, Any] | None = None,
        aggregate_budget_usd: float | None = None,
    ) -> str:
        """Spawn branch tasks sharing the parent's history up to this point.

        Args:
            specs: List of branch specs; each item needs at least ``label``
                and ``steer`` keys. Optional: ``model``, ``budget_usd``,
                ``extra_instructions``.
            isolation: Optional per-branch isolation overrides
                (see :class:`BranchIsolation`).
            strategy: Optional merge strategy (defaults to ``{"kind": "auto_with_fallback"}``).
            aggregate_budget_usd: Optional fork-wide cap; when set, hitting
                the sum across branches terminates every still-running
                branch with state ``"aggregate_budget_exhausted"``.
        """
        coordinator = _coordinator_from_ctx(ctx)
        if coordinator is None:
            return NOT_ENABLED_MESSAGE
        if coordinator.capability is None:  # pragma: no cover - defensive
            return "Fork coordinator missing capability back-reference."
        parent_history = coordinator.capability.latest_messages
        try:
            handle = await coordinator.fork(
                _coerce_specs(specs),
                parent_history=parent_history,
                isolation=_coerce_isolation(isolation),
                strategy=_coerce_strategy(strategy),
                aggregate_budget_usd=aggregate_budget_usd,
            )
        except (ForkBranchLimitError, ForkDepthLimitError, ValueError) as e:
            return f"fork_run failed: {e}"
        lines = [f"Forked: fork_id={handle.fork_id}"]
        for bid in handle.branches:
            rt = coordinator.branches.get(bid)
            label = rt.spec.label if rt else "?"
            lines.append(f"- {bid} ({label})")
        return "\n".join(lines)

    @toolset.tool
    async def inspect_branches(ctx: RunContext[DeepAgentDeps]) -> str:
        """Return the current status of every branch in this fork."""
        coordinator = _coordinator_from_ctx(ctx)
        if coordinator is None:
            return NOT_ENABLED_MESSAGE
        statuses = coordinator.inspect_branches()
        if not statuses:
            return "No active branches."
        lines = []
        for s in statuses:
            error = f", error: {s.error}" if s.error else ""
            lines.append(f"- {s.id} ({s.label}): {s.state}{error}")
        return "\n".join(lines)

    @toolset.tool
    async def merge_or_select(
        ctx: RunContext[DeepAgentDeps],
        action: str,
    ) -> str:
        """Resolve the fork via ``action='pick:<branch_id>'``."""
        coordinator = _coordinator_from_ctx(ctx)
        if coordinator is None:
            return NOT_ENABLED_MESSAGE
        try:
            result = await coordinator.merge_or_select(action)
        except ValueError as e:
            return f"merge_or_select failed: {e}"
        return (
            f"Merged fork {result.fork_id}: winner={result.winner_branch_id}, "
            f"discarded={len(result.discarded_branches)}, "
            f"history={len(result.history_after_merge)} messages"
        )

    @toolset.tool
    async def terminate_branch(
        ctx: RunContext[DeepAgentDeps],
        branch_id: str,
    ) -> str:
        """Cancel a single branch task; the branch's status becomes ``terminated``."""
        coordinator = _coordinator_from_ctx(ctx)
        if coordinator is None:
            return NOT_ENABLED_MESSAGE
        try:
            await coordinator.terminate_branch(branch_id)
        except ValueError as e:
            return f"terminate_branch failed: {e}"
        return f"Branch {branch_id} terminated."

    @toolset.tool
    async def diff_branches(
        ctx: RunContext[DeepAgentDeps],
        fork_id: str,
        paths: list[str] | None = None,
    ) -> BranchDiffReport | str:
        """Build a typed diff over the current fork's branches.

        Args:
            fork_id: Must match the active fork's id; mismatches return a
                structured error rather than a partial report.
            paths: Optional path filter — when given, only these paths
                appear in the report (untouched filtered paths surface as
                ``agreement="unanimous_no_change"`` for transparency).

        Returns a :class:`BranchDiffReport` on success, or a string error
        message (forking disabled, no active fork, mismatched fork id).

        The mixed return type mirrors the forking tools'
        error-as-string convention so the LLM sees errors consistently.
        Programmatic Python consumers should call
        :func:`build_diff_report` directly instead — the builder takes
        only what it needs (a ``fork_id`` and a list of branch runtimes)
        and leaves coordinator-state validation to the caller, which is
        cleaner than parsing a string return value.

        **Best-effort read.** Built without acquiring the coordinator's
        lock; see :mod:`pydantic_deep.toolsets.forking.diff` for the
        read-consistency note.
        """
        coordinator = _coordinator_from_ctx(ctx)
        if coordinator is None:
            return NOT_ENABLED_MESSAGE
        active_fork_id = coordinator.fork_id
        if active_fork_id is None:
            return "diff_branches failed: no active fork — call fork_run first."
        if fork_id != active_fork_id:
            return (
                f"diff_branches failed: fork_id {fork_id!r} does not match the "
                f"active fork {active_fork_id!r}."
            )
        return build_diff_report(
            active_fork_id,
            list(coordinator.branches.values()),
            paths_filter=paths,
        )

    @toolset.tool
    async def fork_cost(
        ctx: RunContext[DeepAgentDeps],
        fork_id: str,
    ) -> ForkCostSummary | str:
        """Return per-branch and aggregate cost for the active fork.

        Args:
            fork_id: Must match the active fork's id; mismatches return a
                structured string error rather than a partial summary.

        Returns a :class:`ForkCostSummary` on success, or a string error
        message (forking disabled, no active fork, mismatched fork id) —
        the mixed return type mirrors :func:`diff_branches`' convention so
        the LLM sees errors consistently.
        """
        coordinator = _coordinator_from_ctx(ctx)
        if coordinator is None:
            return NOT_ENABLED_MESSAGE
        active_fork_id = coordinator.fork_id
        if active_fork_id is None:
            return "fork_cost failed: no active fork — call fork_run first."
        if fork_id != active_fork_id:
            return (
                f"fork_cost failed: fork_id {fork_id!r} does not match the "
                f"active fork {active_fork_id!r}."
            )
        return coordinator.fork_cost()

    return toolset


__all__ = [
    "BranchCost",
    "BranchDiffReport",
    "BranchOutcome",
    "BranchOverlay",
    "BranchRuntime",
    "ConfidenceSignals",
    "EditorDetector",
    "EditorKind",
    "FlushError",
    "FlushReport",
    "ForkBranchLimitError",
    "ForkCoordinator",
    "ForkCostSummary",
    "ForkDepthLimitError",
    "ForkMaterializer",
    "ForkStateStore",
    "InMemoryForkStateStore",
    "JUDGE_SYSTEM_PROMPT",
    "JudgeAgent",
    "JudgeVerdict",
    "NOT_ENABLED_MESSAGE",
    "ResolveOutcome",
    "build_diff_report",
    "clone_for_branch",
    "compute_confidence",
    "count_retry_parts",
    "count_stuck_loop_hits",
    "create_fork_toolset",
]
