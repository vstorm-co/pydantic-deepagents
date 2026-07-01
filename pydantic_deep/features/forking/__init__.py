"""Agent-facing tools for Live Run Forking.

Exposes `create_fork_toolset()` returning a :class:`FunctionToolset` with
four tools:

- `fork_run` - spawn N branch tasks.
- `inspect_branches` - read current branch statuses.
- `merge_or_select` - resolve the fork by picking a winner.
- `terminate_branch` - cancel one branch task.

All tools read the per-run :class:`ForkCoordinator` from
`ctx.deps.fork_coordinator`. The coordinator is allocated by
:class:`LiveForkCapability.for_run` on each `agent.run()`.
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.messages import ModelRequest as _ModelRequest
from pydantic_ai.toolsets import FunctionToolset

from pydantic_deep.deps import DeepAgentDeps, unwrap_backend
from pydantic_deep.features.forking.coordinator import (
    BranchRuntime,
    ForkBranchLimitError,
    ForkCoordinator,
    ForkDepthLimitError,
)
from pydantic_deep.features.forking.diff import build_diff_report
from pydantic_deep.features.forking.editor import EditorDetector, EditorKind
from pydantic_deep.features.forking.isolation import BranchOverlay, clone_for_branch
from pydantic_deep.features.forking.judge import (
    JUDGE_SYSTEM_PROMPT,
    JudgeAgent,
    compute_confidence,
    count_retry_parts,
    count_stuck_loop_hits,
)
from pydantic_deep.features.forking.materializer import ForkMaterializer
from pydantic_deep.features.forking.store import ForkStateStore, InMemoryForkStateStore
from pydantic_deep.features.forking.types import (
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
        """Spawn N branch tasks sharing the parent's history up to the call site.

        Branches run in the background. This call returns immediately with
        the branch ids - it does NOT wait for completion. To wait, poll
        with `inspect_branches` until every branch reaches a terminal
        state (`done`, `failed`, `terminated`, `budget_exhausted`,
        `aggregate_budget_exhausted`).

        Do NOT use `wait_tasks` for branches - that tool is for subagent
        task ids and will return "not found" for branch ids. Branch ids
        only resolve through the forking tools (`inspect_branches`,
        `merge_or_select`, `terminate_branch`, `diff_branches`,
        `fork_cost`).

        The fork is unresolved until `merge_or_select(action="pick:<id>")`
        returns. The parent run MUST call `merge_or_select` before
        yielding back to the user - an unresolved fork at the end of a
        turn leaves branch tasks running and the user looking at dark
        panels until the next turn re-adopts the coordinator.

        Args:
            specs: List of branch specs; each item needs at least `label`
                and `steer` keys. Optional: `model`, `budget_usd`.
            isolation: Optional per-branch isolation overrides
                (see :class:`BranchIsolation`).
            strategy: Optional merge strategy (defaults to `{"kind": "auto_with_fallback"}`).
            aggregate_budget_usd: Optional fork-wide cap; when set, hitting
                the sum across branches terminates every still-running
                branch with state `"aggregate_budget_exhausted"`.
        """
        coordinator = _coordinator_from_ctx(ctx)
        if coordinator is None:
            return NOT_ENABLED_MESSAGE
        if coordinator.capability is None:  # pragma: no cover - defensive
            return "Fork coordinator missing capability back-reference."
        parent_history = coordinator.capability.latest_messages
        # Strip trailing in-progress ModelRequest: pydantic-ai rejects two
        # consecutive ModelRequests in branch history.

        if parent_history and isinstance(parent_history[-1], _ModelRequest):
            parent_history = parent_history[:-1]
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
        """Return the current status of every branch in this fork.

        This is the correct polling primitive for fork status - NOT
        `wait_tasks` (which is for subagent task ids and will not see
        branch ids). Use it in a loop after `fork_run` until every
        branch reaches a terminal state, then call `merge_or_select`.

        Typical polling loop::

            fork_run(specs=[...])
            while True:
                statuses = inspect_branches()
                # branch states are emitted one per line - parse and check
                # every one of them; stop when none are "running".
                if no branch is still running:
                    break
            merge_or_select(action="pick:<winner_id>")

        Terminal states: `done`, `failed`, `terminated`,
        `budget_exhausted`, `aggregate_budget_exhausted`.
        Non-terminal: `running`.
        """
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
        """Resolve the fork by picking a winner. REQUIRED before turn ends.

        The fork is not considered resolved until this returns. Skipping
        it leaves branches running into the next parent turn, where the
        CLI re-adopts the coordinator and presents the user with stale
        fork panels they did not ask for.

        `action` syntax:
            `"pick:<branch_id>"` - flush this branch's overlay writes
            to the parent backend, cancel and discard the other branches,
            and replay the winner's full message history into the parent
            run.
            `"auto"` - let the judge evaluate all branches and pick the
            winner automatically according to the fork's configured
            :class:`MergeStrategy` (`"auto"`, `"auto_with_fallback"`,
            or `"vote"`).  Use this when the fork was created with a
            non-`"manual"` strategy so the judge's verdict drives the
            choice rather than your own assessment of the branches.

        When to use `"auto"` vs `"pick:<id>"` vs `"abort"`:
            Use `"auto"` when the fork's strategy is not `"manual"` -
            the judge runs, evaluates the diff and outcomes, and commits
            the best branch.  Use `"pick:<id>"` only for `"manual"`
            strategy forks or when you have a specific reason to override
            automatic evaluation.  Use `"abort"` to discard every branch
            without merging - required when every branch ended in a
            failed / terminated / budget-exhausted state so no winner is
            mergeable.  `"auto"` auto-detects the all-failed case and
            calls `"abort"` for you, so you only need `"abort"` when
            you want to bail out early on your own.
        """
        coordinator = _coordinator_from_ctx(ctx)
        if coordinator is None:
            return NOT_ENABLED_MESSAGE

        # Detect when every branch is in a non-mergeable terminal state.
        _failed_states = {
            "failed",
            "terminated",
            "budget_exhausted",
            "aggregate_budget_exhausted",
        }
        _branches = list(coordinator.branches.values())
        all_failed = bool(_branches) and all(rt.status.state in _failed_states for rt in _branches)

        if action == "abort" or (action == "auto" and all_failed):
            # Nothing mergeable - release overlays and discard everything.
            try:
                aborted = await coordinator.abort_fork()
            except RuntimeError as e:
                return f"merge_or_select abort failed: {e}"
            if all_failed and _branches:
                err_lines = [
                    f"- {rt.status.label} ({rt.status.state}): "
                    f"{rt.status.error or '(no error message)'}"
                    for rt in _branches
                ]
                return (
                    f"Fork aborted: every branch failed before merge "
                    f"({len(aborted)} branch(es)).\n"
                    + "\n".join(err_lines)
                    + "\nThe parent run can continue from the pre-fork checkpoint; "
                    "do NOT call merge_or_select again on this fork."
                )
            return f"Fork aborted: discarded {len(aborted)} branch(es) without merging."

        def _label(bid: str) -> str:
            """Resolve a branch id to its human-readable label, or fall back to the id."""
            rt = coordinator.branches.get(bid)
            return rt.spec.label if rt is not None else bid

        def _winner_str(bid: str) -> str:
            """Render the winner as `label (short-id)` for tool output."""
            return f"{_label(bid)} ({bid[:8]})"

        if action == "auto":
            try:
                outcome = await coordinator.resolve()
            except Exception as e:
                return f"merge_or_select auto failed: {e}"
            if outcome.committed and outcome.merge_result is not None:
                r = outcome.merge_result
                verdict_summary = ""
                if outcome.verdict is not None:
                    verdict_summary = (
                        f", judge_pick={_winner_str(outcome.verdict.winner_branch_id)}"
                        f" (confidence={outcome.effective_confidence:.2f})"
                    )
                return (
                    f"Merged fork {r.fork_id}: winner={_winner_str(r.winner_branch_id)}"
                    f"{verdict_summary}, "
                    f"discarded={len(r.discarded_branches)}, "
                    f"history={len(r.history_after_merge)} messages"
                )
            # Strategy was manual or auto_with_fallback below threshold -
            # fall through with the judge's recommended pick if available.
            if outcome.verdict is not None:
                action = f"pick:{outcome.verdict.winner_branch_id}"
            else:
                return (
                    "merge_or_select auto: strategy is 'manual' — "
                    "call merge_or_select(action='pick:<branch_id>') explicitly."
                )

        try:
            result = await coordinator.merge_or_select(action)
        except (ValueError, RuntimeError) as e:
            # Bad action, or winner cancelled/budget-exhausted/failed - report, don't crash the run.
            return f"merge_or_select failed: {e}"
        return (
            f"Merged fork {result.fork_id}: winner={_winner_str(result.winner_branch_id)}, "
            f"discarded={len(result.discarded_branches)}, "
            f"history={len(result.history_after_merge)} messages"
        )

    @toolset.tool
    async def delete_file(ctx: RunContext[DeepAgentDeps], path: str) -> str:
        """Delete a file inside the current branch.

        Records the deletion in the branch overlay so it is propagated to
        the parent backend on merge. Equivalent to `execute('rm <path>')`
        against a :class:`~pydantic_ai_backends.LocalBackend` parent - the
        snapshot mutation tracker mirrors shell deletions back into the
        overlay - but preferred because it works against any backend
        (`StateBackend` has no shell) and makes the intent explicit.

        Args:
            path: File path to delete (relative to backend root).

        Returns:
            Confirmation string `"deleted: <path>"`, or an error string
            when the path is absent or the tool is invoked outside a
            branch.
        """
        backend = ctx.deps.backend
        raw = unwrap_backend(backend)
        if not isinstance(raw, BranchOverlay):
            return "delete_file is only available inside a fork branch."
        if not raw.exists(path):
            return f"error: '{path}' does not exist in this branch"
        raw.delete(path)
        return f"deleted: {path}"

    @toolset.tool
    async def terminate_branch(
        ctx: RunContext[DeepAgentDeps],
        branch_id: str,
    ) -> str:
        """Cancel a single branch task; the branch's status becomes `terminated`."""
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
            paths: Optional path filter - when given, only these paths
                appear in the report (untouched filtered paths surface as
                `agreement="unanimous_no_change"` for transparency).

        Returns a :class:`BranchDiffReport` on success, or a string error
        message (forking disabled, no active fork, mismatched fork id).

        The mixed return type mirrors the forking tools'
        error-as-string convention so the LLM sees errors consistently.
        Programmatic Python consumers should call
        :func:`build_diff_report` directly instead - the builder takes
        only what it needs (a `fork_id` and a list of branch runtimes)
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
        return await build_diff_report(
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
        message (forking disabled, no active fork, mismatched fork id) -
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
