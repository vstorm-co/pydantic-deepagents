"""Live Run Forking capability - agent-level entry point.

Adds :class:`LiveForkCapability` to an agent. The capability tracks the
parent run's latest message snapshot (mirroring
:class:`CheckpointMiddleware`) and, on each `for_run` call, allocates
a fresh :class:`ForkCoordinator` that the agent-facing tools
(`fork_run`, `inspect_branches`, `merge_or_select`, etc.) use to
spawn and resolve branch tasks.

Concurrent parent runs of the same agent get independent coordinators,
so per-branch isolation holds at the `agent.run(...)` level.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.messages import ModelMessage

from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.features.forking.coordinator import ForkCoordinator
from pydantic_deep.features.forking.store import ForkStateStore, InMemoryForkStateStore


@dataclass
class LiveForkCapability(AbstractCapability[DeepAgentDeps]):
    """Capability that wires Live Run Forking into an agent.

    Args:
        max_branches: Maximum branches per fork.
        max_depth: Maximum fork nesting depth - `2` allows one level of
            fork-of-fork.
        store: Optional :class:`ForkStateStore`. Defaults to
            :class:`InMemoryForkStateStore`.
        test_command: Optional shell command run against each branch's
            materialised tree during :meth:`ForkCoordinator.resolve` to feed
            the `test_pass_ratio` confidence signal. `None` leaves the
            ratio at `None` for every branch - :func:`compute_confidence`
            then keeps its cap-at-0.65 safety rail active, identical to
            "no test signal". Only honoured when the parent backend is a
            :class:`~pydantic_ai_backends.LocalBackend`.
        test_timeout_s: Wall-clock cap (seconds) per branch test run. On
            timeout the branch's `test_pass_ratio` is `None` (treated
            as "no signal"), not `0.0`. Independent of
            `branch_budget_usd` - runner time is not LLM cost.

    The owning agent reference is set by `create_deep_agent()` after the
    Agent is constructed (mirrors how `agent._task_manager` is set today).
    """

    max_branches: int = 10
    max_depth: int = 2
    store: ForkStateStore | None = None
    #: Independent of apply-to-parent semantics - disk artefacts stay even on abandon.
    keep_artifacts: bool = False
    test_command: str | None = None
    test_timeout_s: float = 60.0

    _agent_ref: Any = field(default=None, init=False, repr=False)
    _latest_messages: list[ModelMessage] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.store is None:
            self.store = InMemoryForkStateStore()

    @property
    def latest_messages(self) -> list[ModelMessage]:
        """Snapshot of the parent run's most recent message list.

        Returns a copy so callers can't mutate the capability's internal state.
        Updated on every `before_model_request`; used by `fork_run` to
        seed each branch's history at the moment of the fork call.
        """
        return list(self._latest_messages)

    async def for_run(self, ctx: RunContext[DeepAgentDeps]) -> LiveForkCapability:
        """Return a fresh per-run capability with an independent coordinator.

        Preserves an unresolved coordinator from a previous turn rather
        than overwriting it. If the previous parent run forked but did
        not call `merge_or_select` before yielding back to the user,
        the coordinator stays on `deps.fork_coordinator` so the next
        turn (or the CLI adopter) can still resolve or abort it; the
        new capability clone takes ownership via the `capability`
        back-reference so per-run state (e.g. `latest_messages`)
        flows through the right instance.
        """
        clone = replace(
            self,
            max_branches=self.max_branches,
            max_depth=self.max_depth,
            store=self.store,
            keep_artifacts=self.keep_artifacts,
            test_command=self.test_command,
            test_timeout_s=self.test_timeout_s,
        )
        # init=False fields are reset by replace(); restore the agent ref.
        clone._agent_ref = self._agent_ref

        assert clone.store is not None  # __post_init__ guarantees this

        existing = getattr(ctx.deps, "fork_coordinator", None)
        if existing is not None and not existing.is_resolved:
            existing.capability = clone
            return clone

        coordinator = ForkCoordinator(
            agent=clone._agent_ref,
            parent_deps=ctx.deps,
            max_branches=clone.max_branches,
            max_depth=clone.max_depth,
            store=clone.store,
            keep_artifacts=clone.keep_artifacts,
            test_command=clone.test_command,
            test_timeout_s=clone.test_timeout_s,
        )
        coordinator.capability = clone
        ctx.deps.fork_coordinator = coordinator
        return clone

    async def after_run(self, ctx: RunContext[DeepAgentDeps], *, result: Any) -> Any:
        """Anchor for the post-turn stash protocol - currently a no-op.

        The coordinator survives a parent turn ending because
        :meth:`for_run` refuses to overwrite an unresolved one on the
        next turn (see above). This hook exists as a documented
        anchor so future strategy changes (eager artefact cleanup on
        abort, post-turn telemetry, partial-history persistence) plug
        in here without restructuring the lifecycle. `result` is
        returned unchanged.
        """
        return result

    async def before_model_request(
        self,
        ctx: RunContext[DeepAgentDeps],
        request_context: Any,
    ) -> Any:
        """Snapshot the latest message list.

        For parent runs the snapshot lands on
        :attr:`_latest_messages` so :meth:`ForkCoordinator.fork` can seed
        each branch's history.

        For branch runs (identified by `ctx.deps._branch_id` being
        non-`None` - set by :meth:`ForkCoordinator.fork`) the snapshot
        is forwarded to the parent coordinator via
        :meth:`ForkCoordinator.capture_partial_history`, so that if a
        budget watcher cancels the branch the merge resolver still has
        a history to return when the branch is picked as winner.
        """
        branch_id = getattr(ctx.deps, "_branch_id", None)
        parent_coord = getattr(ctx.deps, "_parent_fork_coordinator", None)
        if branch_id is not None and parent_coord is not None:
            parent_coord.capture_partial_history(branch_id, request_context.messages)
        else:
            self._latest_messages = list(request_context.messages)
        return request_context


__all__ = ["LiveForkCapability"]
