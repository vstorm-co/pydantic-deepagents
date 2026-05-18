"""Per-parent-run fork coordinator owning branch tasks and merge resolution.

The coordinator is the workhorse of Live Run Forking Stage 1. It owns the
``asyncio.Task`` for each branch, snapshots parent history at fork-call time,
serialises mutating operations via a per-coordinator lock, and resolves
merges by awaiting the picked winner's task.

Stage 1 limits: ``max_branches=2`` and ``max_depth=1`` are passed in from
:class:`LiveForkCapability`; Stage 4 lifts both.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Literal

from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.toolsets.checkpointing import Checkpoint, CheckpointStore
from pydantic_deep.toolsets.forking.isolation import BranchOverlay, clone_for_branch
from pydantic_deep.toolsets.forking.store import ForkStateStore
from pydantic_deep.types import (
    BranchIsolation,
    BranchSpec,
    BranchStatus,
    ForkHandle,
    MergeResult,
    MergeStrategy,
)

if TYPE_CHECKING:
    from pydantic_deep.capabilities.forking import LiveForkCapability


logger = logging.getLogger(__name__)

#: How long to wait for a cancelled discarded branch to finish its ``finally``
#: cleanup during ``merge_or_select`` before giving up and moving on.
_CANCEL_CLEANUP_TIMEOUT_S: float = 1.0


class ForkBranchLimitError(Exception):
    """Raised when a ``fork_run`` call exceeds ``max_branches``."""


class ForkDepthLimitError(Exception):
    """Raised when a ``fork_run`` call from within a branch exceeds ``max_depth``."""


@dataclass
class BranchRuntime:
    """Runtime state of a single branch task."""

    spec: BranchSpec
    task: asyncio.Task[Any]
    deps: DeepAgentDeps
    overlay: BranchOverlay | None
    status: BranchStatus


class ForkCoordinator:
    """Owns per-branch state for one parent run.

    A fresh coordinator is allocated by :meth:`LiveForkCapability.for_run`,
    so concurrent parent runs of the same agent never share state.

    Args:
        agent: The owning agent — used to spawn branch ``agent.run()`` tasks.
        parent_deps: The parent run's deps; cloned per branch via
            :func:`clone_for_branch`.
        max_branches: Maximum number of branches per fork (hard-coded ``2``
            in Stage 1).
        max_depth: Maximum fork nesting depth (hard-coded ``1`` in Stage 1).
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
    ) -> None:
        self.agent = agent
        self.parent_deps = parent_deps
        self.max_branches = max_branches
        self.max_depth = max_depth
        self.store = store
        self.checkpoint_store = checkpoint_store
        self.branches: dict[str, BranchRuntime] = {}
        self._handle: ForkHandle | None = None
        self._lock = asyncio.Lock()
        self.capability: LiveForkCapability | None = None

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
    ) -> ForkHandle:
        """Spawn ``len(specs)`` branch tasks and return a handle.

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

            for spec in specs:
                branch_id = str(uuid.uuid4())
                cloned_deps = clone_for_branch(self.parent_deps, effective_isolation)
                overlay = (
                    cloned_deps.backend if isinstance(cloned_deps.backend, BranchOverlay) else None
                )
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

    async def terminate_branch(self, branch_id: str) -> None:
        """Cancel a branch task and mark its status ``terminated``.

        Only sets ``state="terminated"`` when the task is still running; if it
        already completed (success / failure / earlier cancellation),
        ``_on_done`` has already written the correct terminal state and we
        must not overwrite it.
        """
        if branch_id not in self.branches:
            raise ValueError(f"Unknown branch id: {branch_id!r}")
        runtime = self.branches[branch_id]
        if not runtime.task.done():
            runtime.task.cancel()
            runtime.status.state = "terminated"

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
            except asyncio.CancelledError:
                raise RuntimeError(
                    f"Winning branch {target_id!r} was cancelled before merge."
                ) from None

            history_after_merge = list(result.all_messages())

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

    async def aclose(self) -> None:
        """Cancel every outstanding branch task — used on parent cancellation."""
        for rt in self.branches.values():
            if not rt.task.done():
                rt.task.cancel()


# Aliases the toolset module re-exports — keeps the public surface stable.
__all__ = [
    "BranchRuntime",
    "ForkBranchLimitError",
    "ForkCoordinator",
    "ForkDepthLimitError",
]
