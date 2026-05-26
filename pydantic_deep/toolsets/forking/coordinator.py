"""Per-parent-run fork coordinator owning branch tasks and merge resolution.

The coordinator is the workhorse of Live Run Forking. It owns the
``asyncio.Task`` for each branch, snapshots parent history at fork-call time,
serialises mutating operations via a per-coordinator lock, and resolves
merges by awaiting the picked winner's task.

Supports up to ``max_branches=10`` parallel branches and ``max_depth=2``
nested forks. Per-branch :class:`CostTracking`-driven budget caps are
managed by :class:`_BudgetWatcher`; a fork-wide aggregate cap by
:class:`_AggregateBudgetWatcher`. Partial-history capture ensures
budget-exhausted branches can still be picked as merge winners.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import uuid
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart
from pydantic_ai_shields import CostInfo, CostTracking

from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.toolsets.checkpointing import Checkpoint, CheckpointStore
from pydantic_deep.toolsets.forking.diff import build_diff_report
from pydantic_deep.toolsets.forking.isolation import BranchOverlay, clone_for_branch
from pydantic_deep.toolsets.forking.judge import (
    JudgeAgent,
    _majority_pick,
    compute_confidence,
    count_retry_parts,
    count_stuck_loop_hits,
)
from pydantic_deep.toolsets.forking.materializer import ForkMaterializer
from pydantic_deep.toolsets.forking.store import ForkStateStore
from pydantic_deep.types import (
    BranchCost,
    BranchIsolation,
    BranchOutcome,
    BranchSpec,
    BranchStatus,
    ConfidenceSignals,
    ForkCostSummary,
    ForkHandle,
    JudgeVerdict,
    MergeResult,
    MergeStrategy,
    PendingApprovalRequest,
    ResolveOutcome,
)

if TYPE_CHECKING:
    from pydantic_ai import RunContext

    from pydantic_deep.capabilities.forking import LiveForkCapability


logger = logging.getLogger(__name__)

_CANCEL_CLEANUP_TIMEOUT_S: float = 1.0

#: Checked in order; first available env var wins the slot in the vote panel.
_NATIVE_CHEAP_MODELS: tuple[tuple[str, str], ...] = (
    ("ANTHROPIC_API_KEY", "anthropic:claude-haiku-4-5"),
    ("OPENAI_API_KEY", "openai:gpt-4o-mini"),
    ("MISTRAL_API_KEY", "mistral:mistral-small-latest"),
    ("GROQ_API_KEY", "groq:llama-3.1-8b-instant"),
    ("COHERE_API_KEY", "cohere:command-r"),
)

#: Google uses several different env var names depending on the SDK version.
_GOOGLE_ENV_VARS: tuple[str, ...] = (
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_GENERATIVE_AI_API_KEY",
)
_GOOGLE_CHEAP_MODEL = "google-gla:gemini-3.1-flash-lite-preview"

#: OpenRouter: one API key, three cheap model-family representatives.
_OPENROUTER_CHEAP_MODELS: tuple[str, ...] = (
    "openrouter:anthropic/claude-haiku-4-5",
    "openrouter:openai/gpt-5.4",
    "openrouter:google/gemini-3.1-flash-lite-preview",
)


def _detect_vote_models(fallback: str) -> list[str]:
    """Build a diverse 3-judge panel from whichever API keys are present.

    Detection order:

    1. Native providers (Anthropic, OpenAI, Mistral, Groq, Cohere) — each
       contributes one cheap model when its env var is set.
    2. Google — checked via several possible env var names.
    3. OpenRouter — contributes three different model-family representatives
       (haiku, gpt-mini, gemini-flash) through a single key, maximising
       diversity when only one API key is configured.

    The collected models are deduplicated (OpenRouter + Anthropic key would
    otherwise produce two haiku variants), then cycled to fill exactly 3
    slots. If no keys are detected the ``fallback`` model is used three
    times — same behaviour as before, but at least won't crash on a missing
    key.
    """
    pool: list[str] = []

    for env_var, model in _NATIVE_CHEAP_MODELS:
        if os.environ.get(env_var):
            pool.append(model)

    if any(os.environ.get(v) for v in _GOOGLE_ENV_VARS):
        pool.append(_GOOGLE_CHEAP_MODEL)

    if os.environ.get("OPENROUTER_API_KEY"):
        pool.extend(_OPENROUTER_CHEAP_MODELS)

    seen: set[str] = set()
    unique: list[str] = []
    for m in pool:  # pragma: no branch
        if m not in seen:
            unique.append(m)
            seen.add(m)

    if not unique:
        return [fallback] * 3

    return [unique[i % len(unique)] for i in range(3)]


def _describe_blocked_call(call: Any) -> str:
    """Render an auto-denied tool call as ``"tool: arg"`` for surfacing.

    Handles the common :class:`pydantic_ai.messages.ToolCallPart` shape
    (``tool_name`` + ``args``) where ``args`` is typically a dict but may
    occasionally be a plain string or absent. The renderer falls back to
    the tool name only when no meaningful argument is available.
    """
    tool_name = getattr(call, "tool_name", "<unknown>")
    raw_args = getattr(call, "args", None)
    args_dict: dict[str, Any] | None = None
    if isinstance(raw_args, dict):
        args_dict = raw_args
    else:
        as_dict = getattr(call, "args_as_dict", None)
        if callable(as_dict):
            try:
                produced = as_dict()
            except (TypeError, ValueError) as exc:
                # Narrow so a real bug propagates; log so denials aren't invisible.
                logger.warning("args_as_dict() failed for %s: %s", tool_name, exc)
                produced = None
            if isinstance(produced, dict):
                args_dict = produced
    if args_dict:
        command = args_dict.get("command")
        if isinstance(command, str) and command:
            return f"{tool_name}: {command}"
    return tool_name


def _last_assistant_text(messages: list[Any]) -> str:
    """Join the text parts of the final :class:`ModelResponse` in ``messages``.

    Returns ``""`` when no model response is present (e.g. a branch that was
    cancelled before any assistant turn fired). Used by
    :meth:`ForkCoordinator._build_branch_outcomes` to seed the per-branch
    ``final_assistant_message`` shown to the judge.
    """
    for msg in reversed(messages):
        if not isinstance(msg, ModelResponse):
            continue
        chunks: list[str] = []
        for part in msg.parts:
            text = getattr(part, "content", None)
            if isinstance(text, str):
                chunks.append(text)
        return "".join(chunks)
    return ""


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
    partial_history: list[Any] = field(default_factory=list)
    pending_approval: PendingApprovalRequest | None = None
    blocked_commands: list[str] = field(default_factory=list)


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
        keep_artifacts: bool = False,
        materializer_root: Path | None = None,
    ) -> None:
        self.agent = agent
        self.parent_deps = parent_deps
        self.max_branches = max_branches
        self.max_depth = max_depth
        self.store = store
        self.checkpoint_store = checkpoint_store
        self.aggregate_budget_usd = aggregate_budget_usd
        self.keep_artifacts = keep_artifacts
        self.materializer_root: Path = (
            materializer_root if materializer_root is not None else Path(".pydantic-deep") / "forks"
        )
        self.branches: dict[str, BranchRuntime] = {}
        self._handle: ForkHandle | None = None
        self._lock = asyncio.Lock()
        self.capability: LiveForkCapability | None = None
        self._aggregate_watcher: _AggregateBudgetWatcher | None = None
        self.materializer: ForkMaterializer | None = None
        self._cached_outcome: ResolveOutcome | None = None
        self._cached_outcome_strategy_kind: str | None = None

    @property
    def fork_id(self) -> str | None:
        """The active fork's id, or ``None`` if ``fork()`` has not been called yet.

        Exposed so consumers (e.g. the ``diff_branches`` tool) can
        validate caller-supplied ``fork_id`` without reaching into the
        coordinator's private ``_handle`` attribute.
        """
        return self._handle.fork_id if self._handle is not None else None

    @property
    def handle(self) -> ForkHandle | None:
        """The :class:`ForkHandle` returned by :meth:`fork`, or ``None`` before fork.

        Read-only public accessor for the same value :meth:`fork` returns.
        Cross-package consumers (the CLI adopter, debug inspectors) read this
        instead of reaching into ``_handle``.
        """
        return self._handle

    @property
    def is_resolved(self) -> bool:
        """True when the coordinator no longer owns live branch state.

        Resolved iff either the coordinator has not yet forked
        (``_handle is None``) or every branch's overlay has been released
        (``rt.overlay is None``) — which only happens inside
        :meth:`merge_or_select` (winner flushed, losers cancelled) and
        :meth:`aclose` (abort). This is the canonical "safe to discard"
        signal used by the CLI adopter and :meth:`LiveForkCapability.for_run`
        to distinguish a fork that needs preserving from one that does not.
        """
        if self._handle is None:
            return True
        return all(rt.overlay is None for rt in self.branches.values())

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

            self.materializer = ForkMaterializer(
                root=self.materializer_root / fork_id,
                fork_id=fork_id,
                keep_artifacts=self.keep_artifacts,
            )

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
                if overlay is not None and self.materializer is not None:
                    overlay.attach_materializer(self.materializer, spec.label)

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
                    self._run_branch_with_approval(
                        branch_id, spec, list(parent_history), cloned_deps
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
                            self._refresh_manifest()
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
            self._cached_outcome = None
            self._cached_outcome_strategy_kind = None
            self._refresh_manifest()
            return handle

    async def _run_branch_with_approval(
        self,
        branch_id: str,
        spec: BranchSpec,
        parent_history: list[Any],
        cloned_deps: DeepAgentDeps,
    ) -> Any:
        """Run a branch's ``agent.run()`` and route each deferred approval to the user.

        Branch tasks are plain :class:`asyncio.Task` coroutines that share
        the same asyncio event loop as the TUI.  When a branch agent
        triggers a deferred-approval call (e.g. ``execute``), this method:

        1. Sets :attr:`BranchRuntime.pending_approval` to a
           :class:`~pydantic_deep.types.PendingApprovalRequest` that holds
           an :class:`asyncio.Queue`.
        2. ``await``s :meth:`asyncio.Queue.get` — the branch suspends.
        3. The TUI poll loop (:meth:`~apps.cli.screens.chat.ChatScreen._poll_fork_state`)
           detects ``pending_approval``, surfaces a
           :class:`~apps.cli.modals.branch_approval.BranchApprovalModal`, and
           puts ``True`` (approve) or ``False`` (deny) into the queue.
        4. The branch resumes, forwards the answer to pydantic-ai's
           :class:`~pydantic_ai.tools.DeferredToolResults`, and continues.

        Denied calls are appended to :attr:`BranchRuntime.blocked_commands`
        for post-merge reporting.  The loop repeats until the agent stops
        producing :class:`~pydantic_ai.output.DeferredToolRequests` output.
        """
        from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults

        result = await self.agent.run(
            spec.steer,
            message_history=list(parent_history),
            deps=cloned_deps,
        )
        while isinstance(getattr(result, "output", None), DeferredToolRequests):
            # Type widened to Any-value dict so Pyright accepts it as
            # ``dict[str, DeferredToolApprovalResult | bool]`` (dict is invariant).
            approvals: dict[str, Any] = {}
            runtime = self.branches.get(branch_id)
            for call in result.output.approvals:
                description = _describe_blocked_call(call)
                if runtime is not None:
                    request = PendingApprovalRequest(
                        branch_id=branch_id,
                        description=description,
                    )
                    runtime.pending_approval = request
                    try:
                        approved = await request.response.get()
                    finally:
                        runtime.pending_approval = None
                    if not approved:
                        runtime.blocked_commands.append(description)
                    approvals[call.tool_call_id] = approved
                else:
                    # No runtime → no path to user consent → deny (auto-approving
                    # a gated tool would be a permissions hole).
                    logger.warning(
                        "branch %s has no runtime registered; denying deferred call %s",
                        branch_id,
                        description,
                    )
                    approvals[call.tool_call_id] = False
            result = await self.agent.run(
                None,
                message_history=result.all_messages(),
                deps=cloned_deps,
                deferred_tool_results=DeferredToolResults(approvals=approvals),
            )
        return result

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
        self._refresh_manifest()

    def _refresh_manifest(self) -> None:
        """Write a fresh ``manifest.json`` reflecting current branch statuses."""
        materializer = self.materializer
        if materializer is None:  # pragma: no cover - only callers run after fork()
            return
        try:
            materializer.update_manifest([rt.status for rt in self.branches.values()])
        except Exception:  # pragma: no cover - defensive: manifest is non-load-bearing
            logger.warning("manifest refresh failed", exc_info=True)

    async def _on_branch_cost_update(self, branch_id: str, info: CostInfo) -> None:
        """Relay a per-branch cost update to the aggregate watcher.

        Called by :class:`_BudgetWatcher` before it checks the per-branch
        cap; lets the coordinator track the fork-wide sum without giving
        the per-branch watcher a reference to its sibling watchers.
        """
        if self._aggregate_watcher is None:  # pragma: no cover - defensive
            return
        await self._aggregate_watcher.update(branch_id, info)

    def iter_pending_approvals(self) -> list[tuple[str, PendingApprovalRequest]]:
        """Return ``(branch_id, request)`` for every branch currently suspended on approval.

        The TUI poll loop uses this instead of reading
        :attr:`BranchRuntime.pending_approval` directly, so the coordinator
        owns the contract about who may inspect that field.
        """
        return [
            (bid, rt.pending_approval)
            for bid, rt in self.branches.items()
            if rt.pending_approval is not None
        ]

    async def merge_or_select(self, action: str) -> MergeResult:
        """Resolve the fork by picking a winner.

        ``action="pick:<branch_id>"`` awaits the winning branch's task,
        cancels and discards the others, replays the winner's overlay
        onto the parent backend, releases every overlay, and saves a
        ``post-fork:<fork_id>`` checkpoint when checkpointing is available.
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

            applied_paths: list[str] = []
            applied_changes = 0
            conflicts: list[str] = []
            flush_errors: list[Any] = []
            deleted_paths: list[str] = []
            winner_overlay = winner.overlay
            if winner_overlay is not None:
                snapshot = (
                    self.materializer.pre_flush_snapshot()
                    if self.materializer is not None
                    else None
                )
                report = winner_overlay.flush_to(self.parent_deps.backend, snapshot)
                applied_paths = list(report.applied_paths)
                applied_changes = report.applied_changes
                conflicts = list(report.conflicts)
                flush_errors = list(report.errors)
                deleted_paths = list(report.deleted_paths)

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

            winner.overlay = None

            await self._save_anchor_checkpoint(
                anchor="post-fork",
                fork_id=self._handle.fork_id,
                messages=history_after_merge,
            )

            merge_result = MergeResult(
                fork_id=self._handle.fork_id,
                winner_branch_id=target_id,
                discarded_branches=discarded,
                history_after_merge=history_after_merge,
                applied_paths=applied_paths,
                applied_changes=applied_changes,
                conflicts=conflicts,
                errors=flush_errors,
                deleted_paths=deleted_paths,
                blocked_commands=list(winner.blocked_commands),
            )

            if self.materializer is not None:  # pragma: no branch - fork() always allocates one
                self.materializer.cleanup()

            self._cached_outcome = None
            self._cached_outcome_strategy_kind = None

            return merge_result

    async def abort_fork(self) -> list[str]:
        """Discard the entire fork without merging — releases overlays, cancels tasks.

        Use when every branch has failed (or otherwise become unmergeable)
        so the fork can be resolved without picking a winner.  Mirrors the
        cleanup half of :meth:`merge_or_select` but without flushing any
        overlay onto the parent backend.

        Returns the list of branch ids that were aborted.  After this
        call, :attr:`is_resolved` becomes ``True`` and a new fork can be
        started on the same coordinator.
        """
        if self._handle is None:
            raise RuntimeError("abort_fork called before fork()")

        async with self._lock:
            aborted: list[str] = []
            for bid, rt in list(self.branches.items()):
                if not rt.task.done():
                    rt.task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, asyncio.TimeoutError):
                        try:
                            await asyncio.wait_for(rt.task, timeout=_CANCEL_CLEANUP_TIMEOUT_S)
                        except Exception:  # pragma: no cover - defensive
                            logger.warning("aborted branch %s cleanup raised", bid, exc_info=True)
                rt.overlay = None
                aborted.append(bid)

            if self.materializer is not None:  # pragma: no branch
                self.materializer.cleanup()

            self._cached_outcome = None
            self._cached_outcome_strategy_kind = None
            return aborted

    def _build_branch_outcomes(self) -> tuple[list[BranchOutcome], str]:
        """Materialise per-branch summaries + the parent's first user message.

        ``goal`` is the first :class:`UserPromptPart` content found in any
        branch's history — every branch shares the parent's pre-fork history,
        so the first one we encounter is canonical. Returns ``""`` if no
        ``UserPromptPart`` is present (defensive; the prompt builder handles
        an empty goal gracefully).
        """
        outcomes: list[BranchOutcome] = []
        goal = ""
        goal_found = False
        terminal_error_states = {
            "failed",
            "terminated",
            "budget_exhausted",
            "aggregate_budget_exhausted",
        }
        for branch_id, rt in self.branches.items():
            messages = self._messages_for(rt)
            if not goal_found:
                for msg in messages:
                    if not isinstance(msg, ModelRequest):
                        continue
                    for part in msg.parts:
                        if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                            goal = part.content
                            goal_found = True
                            break
                    if goal_found:
                        break
            final_msg = _last_assistant_text(messages)
            turns = sum(1 for m in messages if isinstance(m, ModelResponse))
            cost = rt.cost_tracker.total_cost if rt.cost_tracker is not None else None
            outcomes.append(
                BranchOutcome(
                    branch_id=branch_id,
                    branch_label=rt.spec.label,
                    steer=rt.spec.steer,
                    final_assistant_message=final_msg,
                    cost_usd=cost,
                    turns=turns,
                    error_count=1 if rt.status.state in terminal_error_states else 0,
                    retry_count=count_retry_parts(messages),
                    stuck_loop_hits=count_stuck_loop_hits(messages),
                )
            )
        return outcomes, goal

    @staticmethod
    def _messages_for(rt: BranchRuntime) -> list[Any]:
        """Return the best-available message list for one branch runtime.

        Prefers the completed task's ``result.all_messages()`` when the task
        finished cleanly; otherwise falls back to the live
        ``partial_history`` snapshot captured by
        :class:`LiveForkCapability.before_model_request`. Always returns a
        ``list`` so downstream consumers can iterate without a None-check.
        """
        if rt.task.done() and not rt.task.cancelled():
            try:
                result = rt.task.result()
            except Exception:
                # Narrow on Exception so CancelledError / SystemExit propagate.
                logger.warning(
                    "branch %s result unreadable; falling back to partial_history",
                    rt.status.id,
                    exc_info=True,
                )
                return list(rt.partial_history)
            messages_fn = getattr(result, "all_messages", None)
            if callable(messages_fn):
                produced: Any = messages_fn()
                return list(produced)
        return list(rt.partial_history)

    def _compute_signals(
        self,
        report: Any,
        outcomes: list[BranchOutcome],
        winner_id: str,
    ) -> ConfidenceSignals:
        """Build :class:`ConfidenceSignals` for the winning branch.

        No per-branch test integration is available yet, so
        ``test_pass_ratio`` is always ``None``; the cap-at-0.65 safety rail in
        :func:`compute_confidence` keeps ``auto_with_fallback`` falling back to
        manual until a real test signal lands (see follow-ups).
        """
        quality_spread = 1.0 - report.summary.agreement_score
        winner = next((o for o in outcomes if o.branch_id == winner_id), None)
        if winner is None:
            internal_consistency = 0.0
        else:
            denom = max(winner.turns, 1)
            raw = 1.0 - (winner.retry_count + winner.stuck_loop_hits) / denom
            internal_consistency = max(0.0, min(1.0, raw))
        return ConfidenceSignals(
            quality_spread=quality_spread,
            test_pass_ratio=None,
            internal_consistency=internal_consistency,
        )

    async def resolve(
        self,
        strategy: MergeStrategy | None = None,
    ) -> ResolveOutcome:
        """Dispatch on :attr:`MergeStrategy.kind` — judge runs for non-manual modes.

        - ``"manual"`` → early-return ``ResolveOutcome(committed=False,
          auto_eligible=False, verdict=None, ...)``; the caller picks via
          :meth:`merge_or_select`.
        - ``"auto"`` → judge picks, ``merge_or_select`` fires immediately.
        - ``"auto_with_fallback"`` → judge picks. If the combined confidence is
          at or above :attr:`MergeStrategy.confidence_threshold` the commit is
          **deferred** to the caller (``committed=False,
          auto_eligible=True``) so the CLI's acceptance widget can offer an
          override; otherwise ``auto_eligible=False`` and the caller opens
          the manual picker preselected.
        - ``"vote"`` → multiple judges evaluate concurrently; majority wins,
          ties broken by highest individual confidence; ``merge_or_select``
          fires immediately on the synthetic majority verdict.

        The judge's ``result.usage()`` rides on
        :attr:`ResolveOutcome.judge_usage` (summed across judges for
        ``"vote"``) so the caller can attribute cost without faking a
        ``cost_category`` field on pydantic-ai-shields' ``CostTracking``.
        """
        if self._handle is None:
            raise RuntimeError("resolve() called before fork() — no active fork.")
        effective_strategy = strategy if strategy is not None else self._handle.merge_strategy

        if effective_strategy.kind == "manual":
            return ResolveOutcome(
                committed=False,
                auto_eligible=False,
                verdict=None,
                signals=None,
                effective_confidence=0.0,
                merge_result=None,
                judge_usage=None,
            )

        # Skip re-invoking the judge when the user re-opens /merge with the same strategy.
        if (
            self._cached_outcome is not None
            and self._cached_outcome_strategy_kind == effective_strategy.kind
        ):
            logger.debug("resolve: returning cached outcome (kind=%r)", effective_strategy.kind)
            return self._cached_outcome

        outcomes, goal = self._build_branch_outcomes()
        diff_report = build_diff_report(self._handle.fork_id, list(self.branches.values()))

        verdict, judge_usage = await self._run_judges(
            effective_strategy, goal, diff_report, outcomes
        )

        signals = self._compute_signals(diff_report, outcomes, verdict.winner_branch_id)
        effective_confidence = compute_confidence(signals, verdict.confidence)

        if effective_strategy.kind in ("auto", "vote"):
            # auto/vote commit immediately — no point caching a committed outcome.
            return await self._commit_and_wrap(
                verdict=verdict,
                signals=signals,
                effective_confidence=effective_confidence,
                judge_usage=judge_usage,
            )
        # kind == "auto_with_fallback" — commit is deferred; cache so the user
        # can re-open /merge without re-paying for the judge call.
        above_threshold = effective_confidence >= effective_strategy.confidence_threshold
        outcome = ResolveOutcome(
            committed=False,
            auto_eligible=above_threshold,
            verdict=verdict,
            signals=signals,
            effective_confidence=effective_confidence,
            merge_result=None,
            judge_usage=judge_usage,
        )
        self._cached_outcome = outcome
        self._cached_outcome_strategy_kind = effective_strategy.kind
        return outcome

    async def _commit_and_wrap(
        self,
        *,
        verdict: JudgeVerdict,
        signals: ConfidenceSignals,
        effective_confidence: float,
        judge_usage: Any,
    ) -> ResolveOutcome:
        """Commit the merge for ``auto`` / ``vote`` modes and wrap the result.

        Extracted from :meth:`resolve` so both modes share one code path —
        keeps the two paths from drifting if the commit semantics ever grow
        (e.g. an additional checkpoint, a notification hook).
        """
        merge_result = await self.merge_or_select(f"pick:{verdict.winner_branch_id}")
        return ResolveOutcome(
            committed=True,
            auto_eligible=False,
            verdict=verdict,
            signals=signals,
            effective_confidence=effective_confidence,
            merge_result=merge_result,
            judge_usage=judge_usage,
        )

    async def _run_judges(
        self,
        strategy: MergeStrategy,
        goal: str,
        diff_report: Any,
        outcomes: list[BranchOutcome],
    ) -> tuple[JudgeVerdict, Any]:
        """Run one or multiple judges depending on ``strategy.kind``.

        For ``"vote"`` mode the judges are evaluated concurrently via
        :func:`asyncio.gather`; the synthetic majority verdict is built by
        :func:`_majority_pick` and the ``usage`` field aggregates the list of
        per-judge usage objects so the caller has full visibility.

        ``strategy.judge_models`` distinguishes ``None`` (use the project
        default triple) from ``[]`` (an explicit empty list — raised as a
        :class:`ValueError`, never silently replaced with defaults).
        """
        if strategy.kind == "vote":
            if strategy.judge_models is None:
                models = _detect_vote_models(strategy.judge_model)
                logger.debug("vote: auto-detected judge panel %s", models)
            elif not strategy.judge_models:
                raise ValueError(
                    "MergeStrategy(kind='vote') requires at least one judge model; "
                    "pass `judge_models=None` for the default triple."
                )
            else:
                models = list(strategy.judge_models)
            judges = [JudgeAgent(m) for m in models]
            results = await asyncio.gather(
                *(j.evaluate(goal, diff_report, outcomes) for j in judges)
            )
            verdicts = [v for v, _ in results]
            usages = [u for _, u in results]
            return _majority_pick(verdicts), usages
        judge = JudgeAgent(strategy.judge_model)
        return await judge.evaluate(goal, diff_report, outcomes)

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
        """Cancel every outstanding branch task — used on parent cancellation.

        Also runs ``materializer.cleanup()`` so the on-disk fork directory
        is removed on abort (unless ``keep_artifacts`` is set), mirroring
        the merge-resolution cleanup. Safe to call multiple times.
        """
        for rt in self.branches.values():
            if not rt.task.done():
                rt.task.cancel()
        if self.materializer is not None:  # pragma: no branch - fork() always allocates one
            self.materializer.cleanup()


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
