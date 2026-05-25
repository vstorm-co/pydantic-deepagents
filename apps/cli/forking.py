"""CLI bridge for Live Run Forking — Stage 3.

The TUI talks to the Stage 1 :class:`ForkCoordinator` through this thin
wrapper rather than going through the agent-facing ``fork_run`` tool: the
user types ``/fork`` directly, so we construct a coordinator ourselves
(mirroring what :meth:`LiveForkCapability.for_run` does inside an
``agent.run()``) and call :meth:`ForkCoordinator.fork` with the parent's
message history.

The Stage 1 coordinator handles the pre-fork / post-fork checkpoint
anchors internally; the CLI bridge must not re-create them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic_deep.capabilities.forking import LiveForkCapability
from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.toolsets.forking.coordinator import ForkCoordinator
from pydantic_deep.toolsets.forking.diff import build_diff_report
from pydantic_deep.types import (
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
        specs: Branch definitions; ``len(specs)`` matches
            ``app.fork_branch_count`` at modal-mount time.
        aggregate_budget_usd: Optional sum-cap across all branches; ``None``
            disables aggregate enforcement.
    """

    specs: list[BranchSpec]
    aggregate_budget_usd: float | None = None


class ForkingNotEnabledError(RuntimeError):
    """Raised when ``/fork`` is invoked on an agent without forking enabled."""


def resolve_capability(agent: Any) -> LiveForkCapability | None:
    """Locate the :class:`LiveForkCapability` registered on ``agent``.

    Returns ``None`` if forking is not enabled on this agent. Walks
    ``agent.root_capability.capabilities`` (pydantic-ai's ``CombinedCapability``
    surface) and falls back to ``getattr(agent, "_capabilities", [])`` for
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
        coordinator: The Stage 1 coordinator owning per-branch tasks.
        handle: The :class:`ForkHandle` returned by :meth:`ForkCoordinator.fork`.
        label_to_id: Resolves user-supplied branch labels (e.g. ``"a"``,
            ``"approach_a"``) to the coordinator's internal UUID branch ids.
            Populated once after ``fork()`` returns.
    """

    coordinator: ForkCoordinator
    handle: Any
    label_to_id: dict[str, str] = field(default_factory=dict)

    def _resolve_id(self, label_or_id: str) -> str | None:
        """Return the canonical branch id for ``label_or_id``, or ``None`` if unknown."""
        if label_or_id in self.coordinator.branches:
            return label_or_id
        return self.label_to_id.get(label_or_id)

    def branch_state(self, label_or_id: str) -> str | None:
        """Return the lifecycle state of a branch (``running``/``done``/...) or ``None``.

        Used by the CLI input router to decide whether ``>>{label} <msg>`` should
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
        """Route ``msg`` into one branch's :class:`MessageQueue`.

        Returns ``True`` if the message landed on a live branch's queue,
        ``False`` if ``label_or_id`` doesn't match an active branch. The CLI
        routes ``>>{label} <msg>`` here — same prefix as #100's queue-steer,
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

    async def terminate_branch(self, branch_id: str) -> None:
        """Cancel one branch's task; the branch's status becomes ``terminated``."""
        await self.coordinator.terminate_branch(branch_id)

    async def abort(self) -> None:
        """Cancel every running branch task — used by the overview's Esc-abort flow."""
        await self.coordinator.aclose()

    async def merge(self, branch_id: str) -> MergeResult:
        """Resolve the fork by picking ``branch_id`` as the winner.

        Flushes the winner's overlay onto the parent backend.
        """
        return await self.coordinator.merge_or_select(f"pick:{branch_id}")

    def inspect(self) -> list[BranchStatus]:
        """Return a snapshot of every branch's current status."""
        return self.coordinator.inspect_branches()

    def build_diff(self) -> BranchDiffReport | None:
        """Build a :class:`BranchDiffReport` over the active fork, or ``None`` if not yet forked."""
        fork_id = self.coordinator.fork_id
        if fork_id is None:  # pragma: no cover - defensive: a CLIForkSession only exists post-fork
            return None
        return build_diff_report(fork_id, list(self.coordinator.branches.values()))


async def start_fork_from_cli(
    app: DeepApp,
    result: ForkPickerResult,
    *,
    isolation: BranchIsolation | None = None,
) -> CLIForkSession:
    """Construct a :class:`ForkCoordinator` for ``app`` and fork it.

    The Stage 1 :meth:`LiveForkCapability.for_run` only allocates a
    coordinator at the start of an ``agent.run()``; since the CLI fires
    ``/fork`` outside of any run, we mirror that allocation here. The
    fresh coordinator is assigned to ``app.deps.fork_coordinator`` so the
    agent-facing ``fork_run`` / ``inspect_branches`` / ``merge_or_select``
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
    )
    coordinator.capability = cap
    app.deps.fork_coordinator = coordinator

    from pydantic_deep.processors.patch import patch_tool_calls_processor

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


__all__ = [
    "CLIForkSession",
    "ForkPickerResult",
    "ForkingNotEnabledError",
    "resolve_capability",
    "start_fork_from_cli",
]
