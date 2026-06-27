"""Per-parent-run fork coordinator owning branch tasks and merge resolution.

The coordinator is the workhorse of Live Run Forking. It owns the
`asyncio.Task` for each branch, snapshots parent history at fork-call time,
serialises mutating operations via a per-coordinator lock, and resolves
merges by awaiting the picked winner's task.

Supports up to `max_branches=10` parallel branches and `max_depth=2`
nested forks. Per-branch :class:`CostTracking`-driven budget caps are
managed by :class:`BudgetWatcher`; a fork-wide aggregate cap by
:class:`AggregateBudgetWatcher`. Partial-history capture ensures
budget-exhausted branches can still be picked as merge winners.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import functools
import logging
import os
import shlex
import uuid
import warnings
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic_ai.messages import ModelRequest, ModelResponse, UserPromptPart
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults
from pydantic_ai_shields import CostInfo, CostTracking

from pydantic_deep.deps import DeepAgentDeps, unwrap_backend
from pydantic_deep.features.checkpointing import Checkpoint, CheckpointStore
from pydantic_deep.features.forking.budget import AggregateBudgetWatcher, BudgetWatcher
from pydantic_deep.features.forking.diff import build_diff_report
from pydantic_deep.features.forking.isolation import BranchOverlay, clone_for_branch
from pydantic_deep.features.forking.judge import (
    JudgeAgent,
    _majority_pick,
    compute_confidence,
    count_retry_parts,
    count_stuck_loop_hits,
)
from pydantic_deep.features.forking.materializer import ForkMaterializer
from pydantic_deep.features.forking.store import ForkStateStore
from pydantic_deep.features.forking.types import (
    BranchCost,
    BranchIsolation,
    BranchOutcome,
    BranchSpec,
    BranchState,
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
from pydantic_deep.models import (
    GOOGLE_CHEAP_MODEL,
    GOOGLE_ENV_VARS,
    NATIVE_CHEAP_MODELS,
    OPENROUTER_CHEAP_MODELS,
)

if TYPE_CHECKING:
    from pydantic_ai import RunContext
    from pydantic_ai.models import Model

    from pydantic_deep.features.forking.capability import LiveForkCapability


logger = logging.getLogger(__name__)

_CANCEL_CLEANUP_TIMEOUT_S: float = 1.0

#: Poll interval while driving an auto/vote winner past deferred approvals it
#: parks on — no human can answer them, so they're denied until the task ends.
_APPROVAL_POLL_INTERVAL_S: float = 0.05

#: Branch states where a cancelled winner may legitimately have no partial
#: history yet, so the merge falls back to the pre-fork parent history.
_EXHAUSTED_BRANCH_STATES: frozenset[str] = frozenset(
    {"terminated", "budget_exhausted", "aggregate_budget_exhausted"}
)

#: Every terminal branch state. Once a branch reaches one of these its status
#: is frozen — `_set_branch_state` never overwrites it (A3).
_TERMINAL_BRANCH_STATES: frozenset[str] = _EXHAUSTED_BRANCH_STATES | {"done", "failed"}


async def _reap_process(proc: asyncio.subprocess.Process) -> None:
    """Terminate (then kill) `proc` if it is still running, reaping it.

    Shielded against cancellation so a parent abort mid-`proc.wait()` cannot
    leave an orphaned/zombie test subprocess behind.
    """
    if proc.returncode is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        proc.terminate()
    try:
        await asyncio.shield(asyncio.wait_for(proc.wait(), timeout=_CANCEL_CLEANUP_TIMEOUT_S))
    except (asyncio.TimeoutError, asyncio.CancelledError):
        # SIGTERM ignored or we were cancelled mid-wait - escalate to SIGKILL.
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        with contextlib.suppress(Exception):
            await asyncio.shield(asyncio.wait_for(proc.wait(), timeout=_CANCEL_CLEANUP_TIMEOUT_S))


def _detect_vote_models(fallback: str) -> list[str]:
    """Build a diverse 3-judge panel from whichever API keys are present.

    Detection order:

    1. Native providers (Anthropic, OpenAI, Mistral, Groq, Cohere) - each
       contributes one cheap model when its env var is set.
    2. Google - checked via several possible env var names.
    3. OpenRouter - contributes three different model-family representatives
       (haiku, gpt-mini, gemini-flash) through a single key, maximising
       diversity when only one API key is configured.

    The collected models are deduplicated (OpenRouter + Anthropic key would
    otherwise produce two haiku variants), then cycled to fill exactly 3
    slots. If no keys are detected the `fallback` model is used three
    times - same behaviour as before, but at least won't crash on a missing
    key.
    """
    pool: list[str] = []

    for env_var, model in NATIVE_CHEAP_MODELS:
        if os.environ.get(env_var):
            pool.append(model)

    if any(os.environ.get(v) for v in GOOGLE_ENV_VARS):
        pool.append(GOOGLE_CHEAP_MODEL)

    if os.environ.get("OPENROUTER_API_KEY"):
        pool.extend(OPENROUTER_CHEAP_MODELS)

    seen: set[str] = set()
    unique: list[str] = []
    for m in pool:  # pragma: no branch
        if m not in seen:
            unique.append(m)
            seen.add(m)

    if not unique:
        return [fallback] * 3

    return [unique[i % len(unique)] for i in range(3)]


def _ensure_unique_labels(specs: list[BranchSpec]) -> list[BranchSpec]:
    """Return `specs` with guaranteed non-empty, unique branch labels.

    Empty/blank labels become `branch-{n}`; duplicates are auto-suffixed
    (`-2`, `-3`, …). Without this, a blank or duplicate label collapses
    the CLI `label_to_id` map (and the inverse in diff_picker), making one
    branch unreachable and `>>label` steering ambiguous - `BranchSpec` and
    the agent-facing `fork_run` tool otherwise pass labels through verbatim.
    """
    used: set[str] = set()
    out: list[BranchSpec] = []
    for i, spec in enumerate(specs):
        base = (spec.label or "").strip() or f"branch-{i + 1}"
        label = base
        suffix = 2
        while label in used:
            label = f"{base}-{suffix}"
            suffix += 1
        used.add(label)
        out.append(spec if label == spec.label else replace(spec, label=label))
    return out


def _strategy_cache_key(strategy: MergeStrategy) -> tuple[Any, ...]:
    """Hashable identity of a :class:`MergeStrategy` for the resolve cache.

    Includes every field that affects the resolved outcome - kind,
    confidence_threshold, and the judge model(s) - so a re-resolve with any
    differing field misses the cache and re-runs the judge.
    """
    judge_models = tuple(strategy.judge_models) if strategy.judge_models is not None else None
    return (strategy.kind, strategy.confidence_threshold, strategy.judge_model, judge_models)


def _describe_blocked_call(call: Any) -> str:
    """Render an auto-denied tool call as `"tool: arg"` for surfacing.

    Handles the common :class:`pydantic_ai.messages.ToolCallPart` shape
    (`tool_name` + `args`) where `args` is typically a dict but may
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
    """Join the text parts of the final :class:`ModelResponse` in `messages`.

    Returns `""` when no model response is present (e.g. a branch that was
    cancelled before any assistant turn fired). Used by
    :meth:`ForkCoordinator._build_branch_outcomes` to seed the per-branch
    `final_assistant_message` shown to the judge.
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
    """Raised when a `fork_run` call exceeds `max_branches`."""


class ForkDepthLimitError(Exception):
    """Raised when a `fork_run` call from within a branch exceeds `max_depth`."""


class _PerBranchCostTracking(CostTracking):  # type: ignore[misc]
    """:class:`CostTracking` subclass that isolates per-run state.

    Stock :class:`CostTracking` inherits :meth:`AbstractCapability.for_run`,
    which returns `self` - so every concurrent branch run would mutate
    the same accumulator and a single `budget_usd` would apply across
    all branches. This subclass overrides `for_run` to return the
    instance stored on :attr:`DeepAgentDeps._branch_cost_tracking` when
    set, giving each branch its own zero-initialised accumulators.
    """

    async def for_run(self, ctx: RunContext[Any]) -> CostTracking:
        per_branch: CostTracking | None = getattr(ctx.deps, "_branch_cost_tracking", None)
        if per_branch is None:
            return self
        return per_branch


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


class BranchRunnerFunc(Protocol):
    """Runs one branch turn, letting the host (e.g. the TUI) stream output.

    When set on `ForkCoordinator.branch_runner`, it replaces the plain
    `agent.run(...)` call so the host can observe tokens and tool events.
    """

    async def __call__(
        self,
        agent: Any,
        steer: str | None,
        message_history: list[Any],
        deps: DeepAgentDeps,
        deferred_results: DeferredToolResults | None,
        runtime: BranchRuntime,
    ) -> Any: ...


class ForkCoordinator:
    """Owns per-branch state for one parent run.

    A fresh coordinator is allocated by :meth:`LiveForkCapability.for_run`,
    so concurrent parent runs of the same agent never share state.

    Args:
        agent: The owning agent - used to spawn branch `agent.run()` tasks.
        parent_deps: The parent run's deps; cloned per branch via
            :func:`clone_for_branch`.
        max_branches: Maximum number of branches per fork.
        max_depth: Maximum fork nesting depth.
        store: The :class:`ForkStateStore` used to persist :class:`ForkHandle`.
        checkpoint_store: Optional explicit checkpoint store. When `None`,
            the coordinator falls back to `parent_deps.checkpoint_store`.
        test_command: Optional shell command run against each branch's
            materialised tree during :meth:`resolve` to feed the
            `test_pass_ratio` confidence signal. `None` disables the
            runner - the cap-at-0.65 safety rail then keeps
            `auto_with_fallback` falling through to the manual picker.
            Restricted to :class:`~pydantic_ai_backends.LocalBackend`
            parents; non-local parents always produce `None`.
            SECURITY: this is operator-configured and runs with the parent
            process's full `os.environ` inherited (only `UV_NO_SYNC=1` is
            added). The environment is deliberately NOT filtered, since most
            test commands need `PATH` / `HOME` / language runtime vars to
            function. Operators must therefore avoid configuring a
            `test_command` that could exfiltrate secrets held in the
            environment (e.g. API keys), as those vars are visible to it.
        test_timeout_s: Wall-clock cap (seconds) per branch test run. On
            timeout the branch's `test_pass_ratio` is `None` (treated as
            "no signal"), not `0.0`.
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
        test_command: str | None = None,
        test_timeout_s: float = 60.0,
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
        self.test_command = test_command
        self.test_timeout_s = test_timeout_s
        self.branches: dict[str, BranchRuntime] = {}
        #: Parent message snapshot captured at fork() time. Used as the
        #: merge fallback when a winner is cancelled before recording any
        #: partial history (see merge_or_select).
        self._pre_fork_history: list[Any] = []
        self._handle: ForkHandle | None = None
        self._lock = asyncio.Lock()
        self.capability: LiveForkCapability | None = None
        self._aggregate_watcher: AggregateBudgetWatcher | None = None
        self.materializer: ForkMaterializer | None = None
        self._cached_outcome: ResolveOutcome | None = None
        self._cached_outcome_key: tuple[Any, ...] | None = None
        self.branch_runner: BranchRunnerFunc | None = None
        self._closed = False
        #: JudgeAgent reuse across vote/auto resolves, keyed by model (A8).
        self._judge_cache: dict[Any, JudgeAgent] = {}

    @property
    def fork_id(self) -> str | None:
        """The active fork's id, or `None` if `fork()` has not been called yet.

        Exposed so consumers (e.g. the `diff_branches` tool) can
        validate caller-supplied `fork_id` without reaching into the
        coordinator's private `_handle` attribute.
        """
        return self._handle.fork_id if self._handle is not None else None

    @property
    def handle(self) -> ForkHandle | None:
        """The :class:`ForkHandle` returned by :meth:`fork`, or `None` before fork.

        Read-only public accessor for the same value :meth:`fork` returns.
        Cross-package consumers (the CLI adopter, debug inspectors) read this
        instead of reaching into `_handle`.
        """
        return self._handle

    @property
    def is_resolved(self) -> bool:
        """True when the coordinator no longer owns live branch state.

        Resolved iff either the coordinator has not yet forked
        (`_handle is None`) or every branch's overlay has been released
        (`rt.overlay is None`) - which only happens inside
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
        """Save a fork anchor checkpoint; return its id, or `None` if no store.

        Writes directly to `CheckpointStore` rather than calling
        `CheckpointMiddleware._save_now`: the coordinator owns its own
        anchor lifecycle and must remain functional even when checkpoint
        middleware is not registered on the agent. Consequence - anchor
        checkpoints are subject to the store's pruning policy
        (`max_checkpoints`) just like any other checkpoint; see the
        "Pre-fork anchor pruning" callout in `docs/capabilities/live-fork.md`.
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
        """Spawn `len(specs)` branch tasks and return a handle.

        Args:
            specs: Branch definitions; `len(specs)` must not exceed
                :attr:`max_branches`.
            parent_history: Parent run's message snapshot at fork time.
            isolation: Per-branch isolation overrides (defaults to
                :class:`BranchIsolation`).
            strategy: Merge strategy (currently `kind="manual"` only).
            aggregate_budget_usd: Optional fork-wide budget cap; when set,
                hitting it terminates every still-running branch with
                `state="aggregate_budget_exhausted"`. Overrides the
                value passed to :meth:`__init__`. Enforcement is
                best-effort under concurrent callbacks - see the
                "Aggregate budget enforcement" note in the live-fork doc.

        Raises:
            ValueError: If `specs` is empty.
            ForkBranchLimitError: If `len(specs) > max_branches`.
            ForkDepthLimitError: If parent's `_fork_depth >= max_depth`.
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

        # Guarantee non-empty, unique labels so label_to_id / steering never collapse.
        specs = _ensure_unique_labels(specs)

        fork_id = str(uuid.uuid4())
        # Save the pre-fork anchor before taking the lock: it touches only the
        # checkpoint store, not coordinator state, so a file/SQLite store's IO
        # must not block every other coordinator op for its duration (A9).
        parent_checkpoint_id = await self._save_anchor_checkpoint(
            anchor="pre-fork", fork_id=fork_id, messages=parent_history
        )
        if parent_checkpoint_id is None:
            warnings.warn(
                "Forking enabled without a checkpoint store - rewind safety net unavailable.",
                stacklevel=2,
            )

        async with self._lock:
            self._pre_fork_history = list(parent_history)

            self.materializer = ForkMaterializer(
                root=self.materializer_root / fork_id,
                fork_id=fork_id,
                keep_artifacts=self.keep_artifacts,
            )

            effective_isolation = isolation or BranchIsolation()
            effective_strategy = strategy or MergeStrategy()

            effective_aggregate = (
                aggregate_budget_usd
                if aggregate_budget_usd is not None
                else self.aggregate_budget_usd
            )
            self._aggregate_watcher = AggregateBudgetWatcher(
                coordinator=self, aggregate_budget_usd=effective_aggregate
            )

            parent_cost_cap = _find_parent_cost_tracking(self.parent_deps)

            for spec in specs:
                branch_id = str(uuid.uuid4())
                cloned_deps = clone_for_branch(self.parent_deps, effective_isolation)
                # Unwrap async adapter — BranchOverlay is a sync backend that
                # gets auto-wrapped by DeepAgentDeps.__post_init__.
                raw_cloned = unwrap_backend(cloned_deps.backend)
                overlay = raw_cloned if isinstance(raw_cloned, BranchOverlay) else None
                if overlay is not None and self.materializer is not None:
                    overlay.attach_materializer(self.materializer, spec.label)

                watcher = BudgetWatcher(
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
                task.add_done_callback(functools.partial(self._on_branch_task_done, runtime))

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
            self._cached_outcome_key = None
            self._refresh_manifest()
            return handle

    async def _run_branch_with_approval(
        self,
        branch_id: str,
        spec: BranchSpec,
        parent_history: list[Any],
        cloned_deps: DeepAgentDeps,
    ) -> Any:
        """Run a branch's `agent.run()` and route each deferred approval to the user.

        Branch tasks are plain :class:`asyncio.Task` coroutines that share
        the same asyncio event loop as the TUI.  When a branch agent
        triggers a deferred-approval call (e.g. `execute`), this method:

        1. Sets :attr:`BranchRuntime.pending_approval` to a
           :class:`~pydantic_deep.types.PendingApprovalRequest` that holds
           an :class:`asyncio.Queue`.
        2. `await`s :meth:`asyncio.Queue.get` - the branch suspends.
        3. The TUI poll loop (:meth:`~apps.cli.screens.chat.ChatScreen._poll_fork_state`)
           detects `pending_approval`, surfaces a
           :class:`~apps.cli.modals.branch_approval.BranchApprovalModal`, and
           puts `True` (approve) or `False` (deny) into the queue.
        4. The branch resumes, forwards the answer to pydantic-ai's
           :class:`~pydantic_ai.tools.DeferredToolResults`, and continues.

        Denied calls are appended to :attr:`BranchRuntime.blocked_commands`
        for post-merge reporting.  The loop repeats until the agent stops
        producing :class:`~pydantic_ai.output.DeferredToolRequests` output.
        """

        runtime = self.branches.get(branch_id)
        result = await self._invoke(spec.steer, parent_history, cloned_deps, runtime, None)
        while isinstance(getattr(result, "output", None), DeferredToolRequests):
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
                    logger.warning(
                        "branch %s has no runtime registered; denying deferred call %s",
                        branch_id,
                        description,
                    )
                    approvals[call.tool_call_id] = False
            result = await self._invoke(
                None,
                result.all_messages(),
                cloned_deps,
                runtime,
                DeferredToolResults(approvals=approvals),
            )
        return result

    async def _invoke(
        self,
        steer: str | None,
        history: list[Any],
        deps: DeepAgentDeps,
        runtime: BranchRuntime | None,
        deferred: DeferredToolResults | None,
    ) -> Any:
        """Run one branch turn via the host runner if set, else `agent.run`."""
        runner = self.branch_runner
        if runner is not None and runtime is not None:
            return await runner(self.agent, steer, list(history), deps, deferred, runtime)
        kwargs: dict[str, Any] = {} if deferred is None else {"deferred_tool_results": deferred}
        return await self.agent.run(steer, message_history=list(history), deps=deps, **kwargs)

    async def run_on_branch(self, branch_id: str, user_message: str) -> asyncio.Task[Any]:
        """Start a new turn on a finished branch with `user_message`.

        The branch must be in `done` state. Seeds the new turn's message
        history from the previous run's `all_messages()` (which already holds
        the full conversation), spawns a new `asyncio.Task`, replaces
        `runtime.task`, and re-attaches the done-callback so the status
        transitions back through `running` → `done`.

        Returns the spawned task so the caller can `await` it if needed.

        Raises:
            ValueError: If `branch_id` is unknown.
            RuntimeError: If the branch is still running.
        """
        if branch_id not in self.branches:
            raise ValueError(f"Unknown branch id: {branch_id!r}")

        async with self._lock:
            runtime = self.branches[branch_id]
            if not runtime.task.done():
                raise RuntimeError(
                    f"Branch {branch_id!r} is still running - cannot start a new turn."
                )
            if runtime.status.state != "done":
                raise RuntimeError(
                    f"Branch {branch_id!r} is in state {runtime.status.state!r} - "
                    "only 'done' branches accept new turns."
                )
            prev_result = runtime.task.result()
            # all_messages() already holds the full conversation; a separate tail duplicates it.
            effective_history = list(prev_result.all_messages())

            runtime.status.state = "running"
            runtime.status.current_turn += 1
            self._cached_outcome = None
            self._cached_outcome_key = None
            self._refresh_manifest()

            new_spec = BranchSpec(
                label=runtime.spec.label,
                steer=user_message,
                model=runtime.spec.model,
                budget_usd=runtime.spec.budget_usd,
            )

            task = asyncio.create_task(
                self._run_branch_with_approval(branch_id, new_spec, effective_history, runtime.deps)
            )
            runtime.task = task
            task.add_done_callback(functools.partial(self._on_branch_task_done, runtime))
            return task

    def _set_branch_state(
        self,
        runtime: BranchRuntime,
        new_state: BranchState,
        *,
        error: str | None = None,
    ) -> bool:
        """Funnel for every `BranchStatus.state` write (A3).

        Returns `True` if the transition was applied. A branch already in a
        terminal state is frozen: the write is dropped and `False` returned, so
        a racing watcher / done-callback can't clobber the first terminal state
        that landed.

        This is the single place the "don't overwrite a terminal state /
        idempotent" guarantee lives. No lock is taken: asyncio is
        single-threaded and every caller (sync done-callbacks included) reaches
        this without an intervening `await`, so the read-then-write is already
        atomic — and an async lock can't be acquired from a sync done-callback
        anyway.
        """
        status = runtime.status
        if status.state in _TERMINAL_BRANCH_STATES:
            return False
        status.state = new_state
        if error is not None:
            status.error = error
        self._refresh_manifest()
        return True

    def _on_branch_task_done(self, runtime: BranchRuntime, task: asyncio.Task[Any]) -> None:
        """Done-callback shared by `fork` and `run_on_branch` (A3).

        Routes the task's final state through `_set_branch_state`, so a task
        that ends cancelled *after* a watcher already recorded a terminal state
        (`budget_exhausted` / `aggregate_budget_exhausted`) keeps that state
        rather than overwriting it with the generic `"terminated"`.
        """
        try:
            if task.cancelled():
                self._set_branch_state(runtime, "terminated")
            elif task.exception() is not None:
                self._set_branch_state(runtime, "failed", error=str(task.exception()))
            else:
                self._set_branch_state(runtime, "done")
        except Exception:  # pragma: no cover - defensive
            logger.warning("branch %s done-callback failed", runtime.status.id, exc_info=True)

    async def terminate_branch(self, branch_id: str, *, reason: str | None = None) -> None:
        """Cancel a branch task and mark its terminal status.

        Args:
            branch_id: Branch to cancel.
            reason: When `"budget_exhausted"` or
                `"aggregate_budget_exhausted"`, the branch's status is
                set to the matching state and its `error` field is
                populated with a debug-friendly message. Otherwise the
                terminal state is `"terminated"`.

        Only sets a new terminal state when the task is still running; if
        it already completed (success / failure / earlier cancellation),
        `_on_done` has already written the correct terminal state and we
        must not overwrite it. Idempotent: a second call for the same
        `branch_id` (e.g. when the aggregate watcher races with the
        per-branch watcher) is a no-op.
        """
        if branch_id not in self.branches:
            raise ValueError(f"Unknown branch id: {branch_id!r}")
        runtime = self.branches[branch_id]
        if runtime.task.done() or runtime.status.state != "running":
            return
        runtime.task.cancel()
        if reason == "budget_exhausted":
            cap = runtime.cost_tracker
            total = cap.total_cost if cap is not None else 0.0
            self._set_branch_state(
                runtime,
                "budget_exhausted",
                error=f"budget exhausted: ${total:.4f} >= ${runtime.budget_usd}",
            )
        elif reason == "aggregate_budget_exhausted":
            agg_watcher = self._aggregate_watcher
            agg = agg_watcher.aggregate() if agg_watcher is not None else None
            cap = agg_watcher.aggregate_budget_usd if agg_watcher is not None else None
            self._set_branch_state(
                runtime,
                "aggregate_budget_exhausted",
                error=(
                    f"aggregate budget exhausted: ${agg:.4f} >= ${cap}"
                    if agg is not None
                    else "aggregate budget exhausted"
                ),
            )
        else:
            self._set_branch_state(runtime, "terminated")

    def _refresh_manifest(self) -> None:
        """Write a fresh `manifest.json` reflecting current branch statuses."""
        materializer = self.materializer
        if materializer is None:  # pragma: no cover - only callers run after fork()
            return
        try:
            materializer.update_manifest([rt.status for rt in self.branches.values()])
        except Exception:  # pragma: no cover - defensive: manifest is non-load-bearing
            logger.warning("manifest refresh failed", exc_info=True)

    async def _on_branch_cost_update(self, branch_id: str, info: CostInfo) -> None:
        """Relay a per-branch cost update to the aggregate watcher.

        Called by :class:`BudgetWatcher` before it checks the per-branch
        cap; lets the coordinator track the fork-wide sum without giving
        the per-branch watcher a reference to its sibling watchers.
        """
        if self._aggregate_watcher is None:  # pragma: no cover - defensive
            return
        await self._aggregate_watcher.update(branch_id, info)

    def iter_pending_approvals(self) -> list[tuple[str, PendingApprovalRequest]]:
        """Return `(branch_id, request)` for every branch currently suspended on approval.

        The TUI poll loop uses this instead of reading
        :attr:`BranchRuntime.pending_approval` directly, so the coordinator
        owns the contract about who may inspect that field.
        """
        return [
            (bid, rt.pending_approval)
            for bid, rt in self.branches.items()
            if rt.pending_approval is not None
        ]

    async def _cancel_branch_task(self, rt: BranchRuntime, log_label: str) -> None:
        """Cancel a branch task and await its cleanup, swallowing cleanup errors.

        No-op when the task is already done. Shared by the merge, abort, and
        close paths so the cancel-await-with-timeout dance lives in one place.
        """
        if rt.task.done():
            return
        rt.task.cancel()
        try:
            await asyncio.wait_for(rt.task, timeout=_CANCEL_CLEANUP_TIMEOUT_S)
        except asyncio.CancelledError:
            pass  # the task acknowledged cancellation — expected
        except asyncio.TimeoutError:
            # The task ignored cancel for too long. We can't force-stop a coroutine,
            # so surface it: a still-running loser's overlay reads fall through to the
            # parent and could observe the winner's flushed bytes.
            logger.warning(
                "%s did not stop within %.1fs of cancel; it may still run during flush",
                log_label,
                _CANCEL_CLEANUP_TIMEOUT_S,
            )
        except Exception:  # pragma: no cover - defensive
            logger.warning("%s cleanup raised", log_label, exc_info=True)

    async def _await_winner(self, winner: BranchRuntime, *, auto_deny_approvals: bool) -> Any:
        """Await the winning branch's task to completion.

        In `manual` mode an interactive approver answers any deferred-tool
        approval the branch parks on, so a plain `await` suffices. In
        `auto`/`vote` mode there is no human — the branch would block on
        `pending_approval` forever — so each approval is denied as it appears
        until the task finishes. Denied calls are recorded by the branch loop
        in `blocked_commands`, surfacing in the merge notification.
        """
        if not auto_deny_approvals:
            return await winner.task
        while not winner.task.done():
            pending = winner.pending_approval
            if pending is not None:
                with contextlib.suppress(Exception):  # queue full / already answered
                    pending.response.put_nowait(False)
            await asyncio.wait({winner.task}, timeout=_APPROVAL_POLL_INTERVAL_S)
        return winner.task.result()

    async def merge_or_select(
        self, action: str, *, _auto_deny_approvals: bool = False
    ) -> MergeResult:
        """Resolve the fork by picking a winner.

        `action="pick:<branch_id>"` awaits the winning branch's task,
        cancels and discards the others, replays the winner's overlay
        onto the parent backend, releases every overlay, and saves a
        `post-fork:<fork_id>` checkpoint when checkpointing is available.

        `_auto_deny_approvals` is set by the non-interactive auto/vote commit
        path so a winner parked on a deferred approval can't deadlock the merge.
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
        handle = self._handle

        winner = self.branches[target_id]
        # Await the winner outside the lock - it may park on human approval indefinitely,
        # which would freeze every other lock user. Take the lock only for the merge below.
        try:
            result = await self._await_winner(winner, auto_deny_approvals=_auto_deny_approvals)
            history_after_merge = list(result.all_messages())
        except asyncio.CancelledError:
            if winner.status.state in _EXHAUSTED_BRANCH_STATES:
                # A winner cancelled in a valid exhausted state may have no
                # partial history yet (e.g. cancelled before its first
                # before_model_request hook fired). Fall back to the pre-fork
                # parent history so the merge still completes rather than
                # spuriously raising. partial_history wins when present.
                if winner.partial_history:
                    history_after_merge = list(winner.partial_history)
                else:
                    history_after_merge = list(self._pre_fork_history)
            else:
                raise RuntimeError(
                    f"Winning branch {target_id!r} was cancelled before merge."
                ) from None
        except Exception as exc:
            # Wrap a failed branch's own exception so callers can handle it gracefully.
            raise RuntimeError(f"Winning branch {target_id!r} failed before merge: {exc}") from exc

        async with self._lock:
            # Quiesce losers before flushing the winner: their overlay reads fall through
            # to the parent, so an un-cancelled loser could observe the winner's flushed bytes.
            discarded: list[str] = []
            for bid, rt in list(self.branches.items()):
                if bid == target_id:
                    continue
                await self._cancel_branch_task(rt, f"discarded branch {bid}")
                rt.overlay = None
                discarded.append(bid)

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
                # Unwrap adapter — flush_to is sync and expects a raw BackendProtocol.
                raw_parent: Any = unwrap_backend(self.parent_deps.backend)
                report = winner_overlay.flush_to(raw_parent, snapshot)
                applied_paths = list(report.applied_paths)
                applied_changes = report.applied_changes
                conflicts = list(report.conflicts)
                flush_errors = list(report.errors)
                deleted_paths = list(report.deleted_paths)

            winner.overlay = None

            merge_result = MergeResult(
                fork_id=handle.fork_id,
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
            self._cached_outcome_key = None

        # Save the post-fork anchor outside the lock (A9) — store IO only, no
        # coordinator state, so it mustn't hold the lock against other ops.
        await self._save_anchor_checkpoint(
            anchor="post-fork",
            fork_id=handle.fork_id,
            messages=history_after_merge,
        )
        return merge_result

    async def abort_fork(self) -> list[str]:
        """Discard the entire fork without merging - releases overlays, cancels tasks.

        Use when every branch has failed (or otherwise become unmergeable)
        so the fork can be resolved without picking a winner.  Mirrors the
        cleanup half of :meth:`merge_or_select` but without flushing any
        overlay onto the parent backend.

        Returns the list of branch ids that were aborted.  After this
        call, :attr:`is_resolved` becomes `True` and a new fork can be
        started on the same coordinator.
        """
        if self._handle is None:
            raise RuntimeError("abort_fork called before fork()")

        async with self._lock:
            aborted: list[str] = []
            for bid, rt in list(self.branches.items()):
                await self._cancel_branch_task(rt, f"aborted branch {bid}")
                rt.overlay = None
                aborted.append(bid)

            if self.materializer is not None:  # pragma: no branch
                self.materializer.cleanup()

            self._cached_outcome = None
            self._cached_outcome_key = None
            return aborted

    async def _run_tests_for_branch(self, rt: BranchRuntime) -> float | None:
        """Run :attr:`test_command` against a snapshot of the branch and return a ratio.

        Materialises the branch (parent `LocalBackend.root_dir` + overlay
        writes / deletions) into a fresh tempdir via
        :meth:`BranchOverlay.snapshot`, runs the command via
        :func:`asyncio.create_subprocess_exec` (no shell - argv via
        :func:`shlex.split`) with a `test_timeout_s` cap,
        and returns:

        - `1.0` on exit code `0`
        - `0.0` on any non-zero exit
        - `None` when the runner is disabled, the parent backend has no
          `root_dir` (e.g. :class:`StateBackend` in tests), the branch
          overlay is gone, the command failed to spawn, or the run timed out

        `None` is the "no signal" return - :func:`compute_confidence`
        keeps the cap-at-0.65 safety rail active in that case, identical to
        the no-test behaviour. `0.0` only fires for an explicit non-zero
        exit, distinguishing "tests ran and some failed" from "we never
        learned anything".

        All exceptions raised by the materialiser or the subprocess setup
        are caught and logged at `WARNING` - a broken test runner must
        never cause :meth:`resolve` to fail. The accompanying `asyncio.gather`
        in :meth:`_build_branch_outcomes` therefore runs WITHOUT
        `return_exceptions=True`: a leaked exception is a real bug.

        SECURITY: the snapshot is built with `include_venv=True` (so the
        runner sees the parent's virtualenv) and the command inherits the
        full parent `os.environ` (only `UV_NO_SYNC=1` is added). The
        environment is intentionally not scrubbed - filtering it would break
        commands needing `PATH` / `HOME` / runtime vars - so a
        `test_command` runs with whatever secrets the parent process holds.
        See the `test_command` constructor arg for the operator caveat.
        """
        if self.test_command is None:
            return None
        # Unwrap adapter — root_dir is an attribute on the raw backend (e.g. LocalBackend).
        raw_parent = unwrap_backend(self.parent_deps.backend)
        parent_root_obj: Any = getattr(raw_parent, "root_dir", None)
        if not isinstance(parent_root_obj, (str, Path)):
            return None
        overlay = rt.overlay
        if overlay is None:
            return None
        parent_root = Path(parent_root_obj)
        # UV_NO_SYNC=1: editable deps with relative paths break in the temp snapshot.
        env = {**os.environ, "UV_NO_SYNC": "1"}
        # Off the event loop: the snapshot file-copy walk is synchronous and would freeze the TUI.
        loop = asyncio.get_running_loop()

        def _enter() -> tuple[Any, Any]:
            ctx = overlay.snapshot(parent_root, include_venv=True)
            return ctx, ctx.__enter__()

        try:
            snap_ctx, snap = await loop.run_in_executor(None, _enter)
        except Exception:
            logger.warning(
                "branch %s snapshot creation failed; reporting None",
                rt.status.id,
                exc_info=True,
            )
            return None
        try:
            try:
                _argv = shlex.split(self.test_command)
                proc = await asyncio.create_subprocess_exec(
                    *_argv,
                    cwd=snap,
                    env=env,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
            except (OSError, FileNotFoundError) as exc:
                logger.warning(
                    "branch %s test command failed to spawn: %s",
                    rt.status.id,
                    exc,
                )
                return None
            try:
                returncode = await asyncio.wait_for(proc.wait(), timeout=self.test_timeout_s)
            except asyncio.TimeoutError:
                logger.warning("branch %s test runner timed out", rt.status.id)
                return None
            else:
                return 1.0 if returncode == 0 else 0.0
            finally:
                # Reap on any exit (timeout/return/cancellation) so the child can't be orphaned.
                await _reap_process(proc)
        finally:
            # Shield the tempdir cleanup so it completes even under cancellation.
            await asyncio.shield(loop.run_in_executor(None, snap_ctx.__exit__, None, None, None))

    async def _build_branch_outcomes(self) -> tuple[list[BranchOutcome], str]:
        """Materialise per-branch summaries + the parent's first user message.

        `goal` is the first :class:`UserPromptPart` content found in any
        branch's history - every branch shares the parent's pre-fork history,
        so the first one we encounter is canonical. Returns `""` if no
        `UserPromptPart` is present (defensive; the prompt builder handles
        an empty goal gracefully).

        Test runs are dispatched concurrently across branches via
        :func:`asyncio.gather`; the per-branch ratio (or `None`) is
        threaded into each :class:`BranchOutcome` so the judge sees it AND
        :meth:`_compute_signals` can lift the cap-at-0.65 safety rail for
        the winner.
        """
        runtimes = list(self.branches.items())
        test_ratios = await asyncio.gather(*(self._run_tests_for_branch(rt) for _, rt in runtimes))

        outcomes: list[BranchOutcome] = []
        goal = ""
        goal_found = False
        terminal_error_states = {
            "failed",
            "terminated",
            "budget_exhausted",
            "aggregate_budget_exhausted",
        }
        for (branch_id, rt), test_pass_ratio in zip(runtimes, test_ratios, strict=True):
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
                    test_pass_ratio=test_pass_ratio,
                )
            )
        return outcomes, goal

    @staticmethod
    def _messages_for(rt: BranchRuntime) -> list[Any]:
        """Return the best-available message list for one branch runtime.

        Prefers the completed task's `result.all_messages()` when the task
        finished cleanly; otherwise falls back to the live
        `partial_history` snapshot captured by
        :class:`LiveForkCapability.before_model_request`. Always returns a
        `list` so downstream consumers can iterate without a None-check.
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

        `test_pass_ratio` is read off the winner's :class:`BranchOutcome`
        (populated by :meth:`_run_tests_for_branch`). When the runner is
        disabled, the parent backend is not a :class:`LocalBackend`, or the
        run timed out, the value is `None` - :func:`compute_confidence`
        then applies its cap-at-0.65 safety rail, identical to the
        no-test-signal behaviour.
        """
        quality_spread = 1.0 - report.summary.agreement_score
        winner = next((o for o in outcomes if o.branch_id == winner_id), None)
        if winner is None:
            internal_consistency = 0.0
            test_pass_ratio: float | None = None
        else:
            denom = max(winner.turns, 1)
            raw = 1.0 - (winner.retry_count + winner.stuck_loop_hits) / denom
            internal_consistency = max(0.0, min(1.0, raw))
            test_pass_ratio = winner.test_pass_ratio
        return ConfidenceSignals(
            quality_spread=quality_spread,
            test_pass_ratio=test_pass_ratio,
            internal_consistency=internal_consistency,
        )

    async def resolve(
        self,
        strategy: MergeStrategy | None = None,
    ) -> ResolveOutcome:
        """Dispatch on :attr:`MergeStrategy.kind` - judge runs for non-manual modes.

        - `"manual"` → early-return `ResolveOutcome(committed=False,
          auto_eligible=False, verdict=None, ...)`; the caller picks via
          :meth:`merge_or_select`.
        - `"auto"` → judge picks, `merge_or_select` fires immediately.
        - `"auto_with_fallback"` → judge picks. If the combined confidence is
          at or above :attr:`MergeStrategy.confidence_threshold` the commit is
          **deferred** to the caller (`committed=False,
          auto_eligible=True`) so the CLI's acceptance widget can offer an
          override; otherwise `auto_eligible=False` and the caller opens
          the manual picker preselected.
        - `"vote"` → multiple judges evaluate concurrently; majority wins,
          ties broken by highest individual confidence; `merge_or_select`
          fires immediately on the synthetic majority verdict.

        The judge's `result.usage()` rides on
        :attr:`ResolveOutcome.judge_usage` (summed across judges for
        `"vote"`) so the caller can attribute cost without faking a
        `cost_category` field on pydantic-ai-shields' `CostTracking`.
        """
        if self._handle is None:
            raise RuntimeError("resolve() called before fork() - no active fork.")
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

        # Reuse the cached outcome only for an identical strategy - the key spans
        # threshold + judge model(s), not just kind, so a changed threshold/panel re-runs.
        strategy_key = _strategy_cache_key(effective_strategy)
        if self._cached_outcome is not None and self._cached_outcome_key == strategy_key:
            logger.debug("resolve: returning cached outcome (key=%r)", strategy_key)
            return self._cached_outcome

        outcomes, goal = await self._build_branch_outcomes()
        diff_report = await build_diff_report(self._handle.fork_id, list(self.branches.values()))

        verdict, judge_usage = await self._run_judges(
            effective_strategy, goal, diff_report, outcomes
        )

        signals = self._compute_signals(diff_report, outcomes, verdict.winner_branch_id)
        effective_confidence = compute_confidence(signals, verdict.confidence)

        if effective_strategy.kind in ("auto", "vote"):
            # auto/vote commit immediately - no point caching a committed outcome.
            return await self._commit_and_wrap(
                verdict=verdict,
                signals=signals,
                effective_confidence=effective_confidence,
                judge_usage=judge_usage,
            )
        # kind == "auto_with_fallback" - commit is deferred; cache so the user
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
        self._cached_outcome_key = strategy_key
        return outcome

    async def _commit_and_wrap(
        self,
        *,
        verdict: JudgeVerdict,
        signals: ConfidenceSignals,
        effective_confidence: float,
        judge_usage: Any,
    ) -> ResolveOutcome:
        """Commit the merge for `auto` / `vote` modes and wrap the result.

        Extracted from :meth:`resolve` so both modes share one code path -
        keeps the two paths from drifting if the commit semantics ever grow
        (e.g. an additional checkpoint, a notification hook).
        """
        merge_result = await self.merge_or_select(
            f"pick:{verdict.winner_branch_id}", _auto_deny_approvals=True
        )
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
        """Run one or multiple judges depending on `strategy.kind`.

        For `"vote"` mode the judges are evaluated concurrently via
        :func:`asyncio.gather`; the synthetic majority verdict is built by
        :func:`_majority_pick` and the per-judge usages are **summed** into a
        single `RunUsage` - matching the single-judge path and the
        `ResolveOutcome.judge_usage` contract ("summed across judges"), so
        cost attribution sees one consistent usage object regardless of mode.

        `strategy.judge_models` distinguishes `None` (use the project
        default triple) from `[]` (an explicit empty list - raised as a
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
            if len(set(models)) < 2:
                warnings.warn(
                    f"vote panel resolved to < 2 distinct judge models ({models}); "
                    "the majority vote degenerates to a single deterministic judge. "
                    "Configure more provider keys or pass explicit `judge_models`.",
                    stacklevel=2,
                )
            judges = [self._judge_for(m) for m in models]
            results = await asyncio.gather(
                *(j.evaluate(goal, diff_report, outcomes) for j in judges)
            )
            verdicts = [v for v, _ in results]
            # Sum per-judge usages into one RunUsage (RunUsage.__add__ returns a
            # new object, leaving the judges' own usage untouched). None entries
            # are skipped; an all-None panel yields None.
            summed_usage: Any = None
            for _, u in results:
                if u is None:
                    continue
                summed_usage = u if summed_usage is None else summed_usage + u
            return _majority_pick(verdicts), summed_usage
        judge = self._judge_for(strategy.judge_model)
        return await judge.evaluate(goal, diff_report, outcomes)

    def _judge_for(self, model: str | Model) -> JudgeAgent:
        """Return a cached `JudgeAgent` for `model`, building one on first use (A8).

        `JudgeAgent` holds no per-evaluate state, so reuse across resolves (and
        concurrent vote judges) is safe. Unhashable `Model` instances can't be
        cached and get a fresh agent each time.
        """
        try:
            cached = self._judge_cache.get(model)
        except TypeError:  # pragma: no cover - unhashable Model instance
            return JudgeAgent(model)
        if cached is None:
            cached = JudgeAgent(model)
            self._judge_cache[model] = cached
        return cached

    def inspect_branches(self) -> list[BranchStatus]:
        """Return a snapshot of every branch's current status."""
        return [rt.status for rt in self.branches.values()]

    def fork_cost(self) -> ForkCostSummary:
        """Return per-branch and aggregate cost for the active fork.

        Returns:
            :class:`ForkCostSummary` with one :class:`BranchCost` entry per
            branch. `aggregate_usd` sums the `cumulative_usd` values of
            branches whose cost is known (skips branches whose model has no
            pricing or has not produced a tracked run yet); when no branch
            has a known cost, `aggregate_usd` is `None`.

        Raises:
            RuntimeError: If called before :meth:`fork` has been invoked.
        """
        if self._handle is None:
            raise RuntimeError("fork_cost() called before fork() - no active fork.")
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
        the branch is unknown - defensive against late callbacks after
        `aclose()`.
        """
        runtime = self.branches.get(branch_id)
        if runtime is None:  # pragma: no cover - defensive
            return
        # Deep-copy, not list(): later capabilities (message queue, periodic
        # reminder) reassign and edit message parts in place. A shallow snapshot
        # would leak those post-snapshot edits into the history the merge
        # replays for a budget-exhausted winner (A5).
        runtime.partial_history = copy.deepcopy(messages)

    async def aclose(self) -> None:
        """Cancel every outstanding branch task - used on parent cancellation.

        Also runs `materializer.cleanup()` so the on-disk fork directory
        is removed on abort (unless `keep_artifacts` is set), mirroring
        the merge-resolution cleanup. Safe to call multiple times.
        """
        # Lock so close serialises with an in-flight merge/abort over the same
        # branches + materializer; `_closed` makes repeat calls a no-op.
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            # Await before cleanup so a mid-write branch can't recreate the fork dir.
            for rt in self.branches.values():
                await self._cancel_branch_task(rt, f"aclose: branch {rt.status.id}")
            if self.materializer is not None:  # pragma: no branch - fork() always allocates one
                self.materializer.cleanup()


def _find_parent_cost_tracking(deps: DeepAgentDeps) -> CostTracking | None:
    """Locate the parent agent's :class:`CostTracking` capability.

    Resolution order:
    1. `deps._branch_cost_tracking` - set when the parent is itself a
       nested branch (fork-of-fork).
    2. Walk `agent._root_capability.capabilities` via the fork
       coordinator's agent reference and return the first
       :class:`CostTracking` instance found.

    Returns `None` when no capability is registered - callers should
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
    watcher: BudgetWatcher,
) -> _PerBranchCostTracking | None:
    """Build the per-branch :class:`_PerBranchCostTracking` clone.

    Returns `None` when neither the parent's registered capability nor
    the agent's model can supply a pricing-capable instance - the branch
    still runs, but budget enforcement is silently disabled and
    `BranchCost.cumulative_usd` will be `None`.
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
            "model name on the agent - per-branch budget enforcement is disabled.",
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

    Pydantic-AI's `Agent.model` can be either a string ("anthropic:...")
    or a model object with a `model_id` attribute; we accept both. Returns
    `None` when neither shape applies (e.g. a `TestModel` instance).
    """
    model = getattr(agent, "model", None)
    if isinstance(model, str):
        return model
    model_id = getattr(model, "model_id", None)
    if isinstance(model_id, str):
        return model_id
    return None


# Aliases the toolset module re-exports - keeps the public surface stable.
__all__ = [
    "BranchRuntime",
    "ForkBranchLimitError",
    "ForkCoordinator",
    "ForkDepthLimitError",
    "ResolveOutcome",
]
