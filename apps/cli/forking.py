"""CLI bridge for Live Run Forking.

The TUI talks to the :class:`ForkCoordinator` through this thin
wrapper rather than going through the agent-facing `fork_run` tool: the
user types `/fork` directly, so we construct a coordinator ourselves
(mirroring what :meth:`LiveForkCapability.for_run` does inside an
`agent.run()`) and call :meth:`ForkCoordinator.fork` with the parent's
message history.

The coordinator handles the pre-fork / post-fork checkpoint anchors
internally; the CLI bridge must not re-create them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.features.forking.capability import LiveForkCapability
from pydantic_deep.features.forking.coordinator import ForkCoordinator
from pydantic_deep.features.forking.diff import build_diff_report
from pydantic_deep.features.forking.types import (
    BranchDiffReport,
    BranchIsolation,
    BranchSpec,
    BranchStatus,
    MergeResult,
    MergeStrategy,
)

if TYPE_CHECKING:
    from apps.cli.app import DeepApp


@dataclass(frozen=True)
class ForkPickerResult:
    """Return value of :class:`ForkPickerModal`.

    Bundles the per-branch specs with the optional fork-wide aggregate budget
    cap so :func:`start_fork_from_cli` can forward everything to
    :meth:`ForkCoordinator.fork` in a single call.

    Attributes:
        specs: Branch definitions; `len(specs)` matches
            `app.fork_branch_count` at modal-mount time.
        aggregate_budget_usd: Optional sum-cap across all branches; `None`
            disables aggregate enforcement.
    """

    specs: list[BranchSpec]
    aggregate_budget_usd: float | None = None


class ForkingNotEnabledError(RuntimeError):
    """Raised when `/fork` is invoked on an agent without forking enabled."""


def resolve_capability(agent: Any) -> LiveForkCapability | None:
    """Locate the :class:`LiveForkCapability` registered on `agent`.

    Returns `None` if forking is not enabled on this agent. Walks
    `agent.root_capability.capabilities` (pydantic-ai's `CombinedCapability`
    surface) and falls back to `getattr(agent, "_capabilities", [])` for
    test stubs / older agents that expose capabilities directly.
    """
    root = getattr(agent, "root_capability", None)
    candidates = []
    if root is not None:
        candidates = list(getattr(root, "capabilities", []) or [])
    if not candidates:
        candidates = list(getattr(agent, "_capabilities", []) or [])
    for cap in candidates:
        if isinstance(cap, LiveForkCapability):
            return cap
    return None


@dataclass
class CLIForkSession:
    """App-level wrapper around a single active :class:`ForkCoordinator`.

    Attributes:
        coordinator: The :class:`ForkCoordinator` owning per-branch tasks.
        handle: The :class:`ForkHandle` returned by :meth:`ForkCoordinator.fork`.
        label_to_id: Resolves user-supplied branch labels (e.g. `"a"`,
            `"approach_a"`) to the coordinator's internal UUID branch ids.
            Populated once after `fork()` returns.
        adopted: `True` when the session wraps a coordinator the agent
            allocated mid-run (via the `fork_run` tool); `False` for
            user-initiated forks via the `/fork` command. The `/fork`
            command guard branches on this so the user gets a different
            notification when the active fork was started by the agent.
    """

    coordinator: ForkCoordinator
    handle: Any
    label_to_id: dict[str, str] = field(default_factory=dict)
    adopted: bool = False

    def _resolve_id(self, label_or_id: str) -> str | None:
        """Return the canonical branch id for `label_or_id`, or `None` if unknown."""
        if label_or_id in self.coordinator.branches:
            return label_or_id
        return self.label_to_id.get(label_or_id)

    def branch_state(self, label_or_id: str) -> str | None:
        """Return the lifecycle state of a branch (`running`/`done`/...) or `None`.

        Used by the CLI input router to decide whether `>>{label} <msg>` should
        actually be delivered: steering a branch whose task already finished
        would silently drop the message into a queue nobody consumes.
        """
        branch_id = self._resolve_id(label_or_id)
        if branch_id is None:
            return None
        runtime = self.coordinator.branches.get(branch_id)
        if runtime is None:  # pragma: no cover - defensive: _resolve_id said it exists
            return None
        return runtime.status.state

    async def steer_branch(self, label_or_id: str, msg: str) -> bool:
        """Route `msg` into one branch's :class:`MessageQueue`.

        Returns `True` if the message landed on a live branch's queue,
        `False` if `label_or_id` doesn't match an active branch. The CLI
        routes `>>{label} <msg>` here — same prefix as #100's queue-steer,
        scoped to a branch when the label matches a live one.
        """
        branch_id = self._resolve_id(label_or_id)
        if branch_id is None:
            return False
        runtime = self.coordinator.branches[branch_id]
        queue = runtime.deps.message_queue
        if queue is None:
            return False
        await queue.steer(msg)
        return True

    async def run_on_branch(self, branch_id: str, user_message: str) -> Any:
        """Start a new interactive turn on a finished branch.

        Delegates to :meth:`ForkCoordinator.run_on_branch` and returns
        the spawned `asyncio.Task`.
        """
        return await self.coordinator.run_on_branch(branch_id, user_message)

    async def terminate_branch(self, branch_id: str) -> None:
        """Cancel one branch's task; the branch's status becomes `terminated`."""
        await self.coordinator.terminate_branch(branch_id)

    async def abort(self) -> None:
        """Cancel every running branch task and release overlays.

        Uses :meth:`ForkCoordinator.abort_fork` (not `aclose`) so that
        overlays are released and :attr:`is_resolved` becomes `True`.
        Also detaches the coordinator from parent deps so
        :func:`reconcile_active_fork` does not re-adopt it on the next turn.
        """
        await self.coordinator.abort_fork()
        self.coordinator.parent_deps.fork_coordinator = None

    async def merge(self, branch_id: str) -> MergeResult:
        """Resolve the fork by picking `branch_id` as the winner.

        Flushes the winner's overlay onto the parent backend.
        """
        return await self.coordinator.merge_or_select(f"pick:{branch_id}")

    def inspect(self) -> list[BranchStatus]:
        """Return a snapshot of every branch's current status."""
        return self.coordinator.inspect_branches()

    async def build_diff(self) -> BranchDiffReport | None:
        """Build a :class:`BranchDiffReport` over the active fork, or `None` if not yet forked."""
        fork_id = self.coordinator.fork_id
        if fork_id is None:  # pragma: no cover - defensive: a CLIForkSession only exists post-fork
            return None
        return await build_diff_report(fork_id, list(self.coordinator.branches.values()))


async def start_fork_from_cli(
    app: DeepApp,
    result: ForkPickerResult,
    *,
    isolation: BranchIsolation | None = None,
) -> CLIForkSession:
    """Construct a :class:`ForkCoordinator` for `app` and fork it.

    :meth:`LiveForkCapability.for_run` only allocates a coordinator at the
    start of an `agent.run()`; since the CLI fires `/fork` outside of
    any run, we mirror that allocation here. The
    fresh coordinator is assigned to `app.deps.fork_coordinator` so the
    agent-facing `fork_run` / `inspect_branches` / `merge_or_select`
    tools also resolve to the same coordinator if the agent driving any
    follow-up run wants to inspect or interact with it.

    Args:
        app: The TUI app — supplies the agent, deps, and message history.
        result: Picker output bundling per-branch specs and the optional
            fork-wide aggregate cap. The aggregate is forwarded to
            :meth:`ForkCoordinator.fork`.
        isolation: Optional per-branch isolation override (default policy
            applies otherwise).

    Raises:
        ForkingNotEnabledError: When the agent has no :class:`LiveForkCapability`
            registered. The caller should surface this as a user-facing
            notification ("forking is not enabled — restart with forking on").
    """
    cap = resolve_capability(app.agent)
    if cap is None:
        raise ForkingNotEnabledError(
            "Forking is not enabled on this agent. Pass `forking=True` to "
            "`create_deep_agent()` (or `create_cli_agent()`) to enable."
        )
    if app.deps is None:  # pragma: no cover - defensive: app always has deps when /fork dispatches
        raise ForkingNotEnabledError("Cannot fork — agent dependencies are not configured.")
    parent_deps: DeepAgentDeps = app.deps
    coordinator = ForkCoordinator(
        agent=app.agent,
        parent_deps=parent_deps,
        max_branches=cap.max_branches,
        max_depth=cap.max_depth,
        store=cap.store,  # type: ignore[arg-type]
        keep_artifacts=cap.keep_artifacts,
        test_command=cap.test_command,
        test_timeout_s=cap.test_timeout_s,
    )
    coordinator.capability = cap
    app.deps.fork_coordinator = coordinator

    from pydantic_deep.features.patch import patch_tool_calls_processor

    safe_history = patch_tool_calls_processor(list(app.message_history))
    merge_strategy = MergeStrategy(
        kind=app.fork_merge_strategy,  # type: ignore[arg-type]
        judge_model=app.fork_judge_model,
        confidence_threshold=app.fork_confidence_threshold,
    )
    handle = await coordinator.fork(
        result.specs,
        parent_history=safe_history,
        isolation=isolation,
        aggregate_budget_usd=result.aggregate_budget_usd,
        strategy=merge_strategy,
    )
    label_to_id: dict[str, str] = {}
    for branch_id in handle.branches:
        runtime = coordinator.branches[branch_id]
        label_to_id[runtime.spec.label] = branch_id
    return CLIForkSession(coordinator=coordinator, handle=handle, label_to_id=label_to_id)


def reconcile_active_fork(app: DeepApp) -> bool:
    """Reconcile `app.active_fork` with `deps.fork_coordinator` after a turn.

    Called at the end of every parent `agent.run()` to handle the two
    agent-initiated fork transitions the user-driven `/fork` path cannot
    observe:

    - **Agent merged its own fork** — `app.active_fork` wraps a
      coordinator that is now resolved (e.g. `MergeStrategy.kind="auto"`
      drove `merge_or_select` itself). Clear `app.active_fork` so the
      panels go away, mirroring :meth:`ChatScreen.action_merge_focused_branch`.
    - **Agent forked but did not merge** — no `app.active_fork` yet, but
      `deps.fork_coordinator` has live branches. Adopt via
      :func:`adopt_agent_coordinator` so the panels light up.

    The combination of both transitions in one call lets the timing edge
    case (agent forks AND merges within a single turn) cleanly land on
    `app.active_fork is None` without a brief UI flash.

    Returns `True` when the function mutated `app.active_fork` —
    useful for tests that need to assert the transition happened (the
    final value is also readable from `app.active_fork` directly).
    """
    active = app.active_fork
    if active is not None and active.coordinator.is_resolved:
        app.active_fork = None
        return True
    if active is None:
        adopted = adopt_agent_coordinator(app)
        if adopted is not None:
            app.active_fork = adopted
            return True
    return False


def adopt_agent_coordinator(app: DeepApp) -> CLIForkSession | None:
    """Wrap a coordinator the agent allocated mid-run in a :class:`CLIForkSession`.

    `LiveForkCapability.for_run` allocates a :class:`ForkCoordinator` at
    the start of every `agent.run()` and stores it on
    `deps.fork_coordinator`. When the agent itself calls `fork_run`
    during that run, the coordinator gains a :class:`ForkHandle` and live
    branches — but `app.active_fork` (the TUI's reactive entry point)
    stays `None` because the CLI `/fork` path never executed.

    This helper closes the gap: it inspects the running deps, builds the
    same wrapper :func:`start_fork_from_cli` produces, and tags it as
    `adopted=True` so the `/fork` command guard can distinguish
    user-initiated vs agent-initiated forks.

    Returns `None` when there is nothing to adopt:

    - `app.deps` is unset (app not fully booted);
    - no coordinator on deps;
    - coordinator has no branches (agent did not call `fork_run`);
    - coordinator is already resolved (`is_resolved` is True) — covers
      the timing case where the agent forks and merges in a single turn,
      so the UI does not flash a panel for a fork that's already done.

    Idempotent: if `app.active_fork` already wraps the same coordinator,
    the existing session is returned unchanged.
    """
    deps = app.deps
    if deps is None:
        return None
    coordinator = getattr(deps, "fork_coordinator", None)
    if coordinator is None or not coordinator.branches or coordinator.is_resolved:
        return None
    existing = app.active_fork
    if existing is not None and existing.coordinator is coordinator:
        return existing
    handle = coordinator.handle
    if handle is None:  # pragma: no cover - defensive: branches non-empty implies handle set
        return None
    label_to_id: dict[str, str] = {}
    for branch_id in handle.branches:
        runtime = coordinator.branches[branch_id]
        label_to_id[runtime.spec.label] = branch_id
    return CLIForkSession(
        coordinator=coordinator,
        handle=handle,
        label_to_id=label_to_id,
        adopted=True,
    )


__all__ = [
    "CLIForkSession",
    "ForkPickerResult",
    "ForkingNotEnabledError",
    "adopt_agent_coordinator",
    "reconcile_active_fork",
    "resolve_capability",
    "start_fork_from_cli",
]
