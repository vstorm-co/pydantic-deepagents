"""Types for the live-forking subsystem: branch specs, costs, diffs, judging."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass as _dataclass
from dataclasses import field as _field
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from pydantic_deep.models import DEFAULT_JUDGE_MODEL


@_dataclass(frozen=True)
class BranchSpec:
    """Specification for a single branch in a fork.

    Attributes:
        label: Human-readable branch label (e.g. `"approach_a"`).
        steer: First user message delivered to the branch agent - the
            instruction that differentiates this branch from siblings.
        model: Optional model override for the branch. `None` inherits
            the parent's model.
        budget_usd: Optional per-branch USD budget. Enforced by
            :class:`BudgetWatcher`: when the branch's `CostTracking`
            cumulative cost crosses this cap the branch is cancelled and
            transitions to :data:`BranchState` `"budget_exhausted"`.
    """

    label: str
    steer: str
    model: str | None = None
    budget_usd: float | None = None


@_dataclass(frozen=True)
class BranchIsolation:
    """Isolation flags controlling what state branches share with the parent.

    Defaults match the project's per-branch isolation policy:
    `history` always copies; `backend`, `memory`, `todos` copy by
    default; `message_queue` is isolated; `team_bus` is shared
    (peer-to-peer bus - branches can talk to each other by default).

    Only `backend="copy"` and `message_queue="isolated"` are exercised
    by the current fork pipeline; the other `share` / `share_readonly`
    values are accepted for forward compatibility.
    """

    history: Literal["copy"] = "copy"
    backend: Literal["copy", "share_readonly", "share"] = "copy"
    memory: Literal["copy", "share"] = "copy"
    todos: Literal["copy", "share"] = "copy"
    message_queue: Literal["isolated", "shared"] = "isolated"
    team_bus: Literal["shared", "isolated"] = "shared"


BranchState = Literal[
    "running",
    "done",
    "failed",
    "terminated",
    "budget_exhausted",
    "aggregate_budget_exhausted",
]
"""Lifecycle states of a single branch.

`budget_exhausted` means the per-branch cap was crossed: the watcher
cancels the branch mid-run and the partial-history snapshot becomes the
durable record. `aggregate_budget_exhausted` means the fork-wide cap
was hit and may interrupt any still-running branch mid-stream.
"""


@_dataclass
class BranchStatus:
    """Runtime status snapshot of a single branch."""

    id: str
    label: str
    state: BranchState
    current_turn: int
    last_activity_at: datetime
    last_message_preview: str | None = None
    error: str | None = None


@_dataclass(frozen=True)
class BranchCost:
    """Per-branch cost snapshot - element of :class:`ForkCostSummary`.

    `cumulative_usd` is the externally-facing name for the upstream
    `CostTracking.total_cost` value; the rename happens at the
    :meth:`ForkCoordinator.fork_cost` boundary. `None` indicates pricing
    was unavailable for the branch's model (e.g. an unrecognised model in
    the genai-prices catalogue) - the branch still runs, but its budget
    cap is effectively disabled.
    """

    branch_id: str
    branch_label: str
    cumulative_usd: float | None
    budget_usd: float | None
    remaining_usd: float | None
    state: BranchState


@_dataclass(frozen=True)
class ForkCostSummary:
    """Output of the `fork_cost(fork_id)` tool.

    Sums :attr:`BranchCost.cumulative_usd` across branches with a non-`None`
    cost; branches with `None` are omitted from the aggregate to avoid
    misleading partial sums.
    """

    fork_id: str
    per_branch: dict[str, BranchCost]
    aggregate_usd: float | None
    aggregate_budget_usd: float | None
    aggregate_remaining_usd: float | None


@_dataclass(frozen=True)
class MergeStrategy:
    """How a fork is resolved into a single winning branch.

    :attr:`kind` selects the resolution mode:

    - `"manual"` - caller picks via `merge_or_select(action="pick:<id>")`.
    - `"auto"` - :class:`JudgeAgent` picks; coordinator commits immediately.
    - `"auto_with_fallback"` - judge picks; if effective confidence is at
      or above :attr:`confidence_threshold` the commit is deferred to the
      caller (so the acceptance widget can offer an override), otherwise
      the caller opens the manual picker with the judge's pick
      preselected. This is the default.
    - `"vote"` - multiple judges (default: Haiku + GPT-mini + Gemini
      Flash) evaluate independently; majority wins, tie broken by highest
      confidence; coordinator commits immediately.
    """

    kind: Literal["manual", "auto", "auto_with_fallback", "vote"] = "auto_with_fallback"
    judge_model: str = DEFAULT_JUDGE_MODEL
    judge_models: list[str] | None = None
    confidence_threshold: float = 0.80
    show_reasoning: bool = True


@_dataclass
class ForkHandle:
    """Handle returned by `ForkCoordinator.fork()` identifying a live fork."""

    fork_id: str
    parent_checkpoint_id: str | None
    branches: list[str]
    merge_strategy: MergeStrategy
    created_at: datetime


@_dataclass
class PendingApprovalRequest:
    """A tool call from a branch task that is awaiting user approval.

    Branch tasks run as plain :class:`asyncio.Task` coroutines and cannot
    reach the TUI's interactive permission modal directly.  When a branch
    agent triggers a deferred-approval tool call (e.g. `execute`), the
    branch sets :attr:`~BranchRuntime.pending_approval` on its own
    :class:`BranchRuntime` and suspends until the user responds via
    :attr:`response`.

    The TUI poll loop detects a non-`None` `pending_approval`, surfaces
    a :class:`~apps.cli.modals.branch_approval.BranchApprovalModal`, and
    puts `True` (approve) or `False` (deny) into :attr:`response`.
    The branch then resumes and forwards the answer to pydantic-ai's
    :class:`~pydantic_ai.tools.DeferredToolResults`.

    Attributes:
        branch_id: Branch that is waiting (matches :attr:`BranchRuntime.spec.branch_id`).
        description: Human-readable "tool_name: arg" string, shown in the modal.
        response: Single-slot :class:`asyncio.Queue`; put `True` to approve,
            `False` to deny.  The branch `await`s :meth:`asyncio.Queue.get`
            and unblocks as soon as the TUI responds.
    """

    branch_id: str
    description: str
    response: asyncio.Queue[bool] = _field(default_factory=lambda: asyncio.Queue(maxsize=1))


@_dataclass(frozen=True)
class FlushError:
    """One per-write failure observed by :meth:`BranchOverlay.flush_to`.

    `flush_to` never aborts on the first failure - it accumulates errors
    for the caller to surface alongside the changes that did land. Surfaced
    on :attr:`MergeResult.errors` so the CLI / agent can report partial
    success without losing track of what didn't apply.
    """

    path: str
    op: Literal["write", "edit", "delete", "mkdir", "rmdir"]
    message: str


@_dataclass(frozen=True)
class FlushReport:
    """Outcome of replaying a :class:`BranchOverlay` onto the parent backend.

    Produced by :meth:`BranchOverlay.flush_to` during `merge_or_select`
    when the user picks a winner with default-flush semantics. The fields
    flow through to :class:`MergeResult` so the CLI / agent can render
    "Merged: kept branch X · N files applied · conflicts: … · errors: N"
    style notifications.

    - `applied_paths` lists paths whose final overlay content was
      written; a path's last write/edit wins, multiple in-overlay edits
      to the same path collapse to one entry.
    - `applied_changes` counts every replayed op (≥ `len(applied_paths)`).
    - `conflicts` lists paths where the parent's pre-flush content
      diverged from the pre-fork snapshot - both modified-by-third-actor
      and deleted-by-third-actor cases land here. Conflicting paths are
      NOT replayed onto the parent (non-destructive): the newer parent
      content is preserved and the path is excluded from `applied_paths`
      so the caller can resolve the conflict manually.
    - `errors` is one :class:`FlushError` per per-write failure (e.g.
      parent `WriteResult.error` non-empty or parent raised). The
      failing path is excluded from `applied_paths`; remaining writes
      still flush.
    - `deleted_paths` lists paths the branch removed via the `delete`
      agent tool that were successfully propagated to the parent backend
      on merge. Paths whose deletion failed (parent raised, or the
      parent backend cannot delete) land in `errors` instead.
    """

    applied_paths: list[str]
    applied_changes: int
    conflicts: list[str]
    errors: list[FlushError]
    deleted_paths: list[str] = _field(default_factory=list)


@_dataclass
class MergeResult:
    """Result returned by `ForkCoordinator.merge_or_select()`."""

    fork_id: str
    winner_branch_id: str
    discarded_branches: list[str]
    history_after_merge: list[Any]
    applied_paths: list[str] = _field(default_factory=list)
    applied_changes: int = 0
    conflicts: list[str] = _field(default_factory=list)
    errors: list[FlushError] = _field(default_factory=list)
    deleted_paths: list[str] = _field(default_factory=list)
    blocked_commands: list[str] = _field(default_factory=list)


@_dataclass(frozen=True)
class FileChange:
    """Single overlay mutation event recorded by :class:`BranchOverlay`.

    Event-level log entry: one record per successful `write`, `edit`,
    or `delete` on the branch overlay. The temporal-ordered list
    returned by :meth:`BranchOverlay.changes` is the data spine consumed
    by every downstream consumer of the fork pipeline:

    - :func:`build_diff_report` - uses `path` to know which files a
      branch touched.
    - :class:`ForkMaterializer` - uses `op` to replay `write` /
      `edit` / `delete` semantics on the on-disk mirror.
    - :class:`JudgeAgent` - uses `timestamp` for temporal heuristics
      when scoring branch outcomes.

    Not to be confused with :class:`BranchChange`, which is a state-level
    aggregate describing a branch's per-path outcome relative to the
    parent backend (`"created"` / `"modified"` / `"deleted"` /
    `"untouched"`). `FileChange` logs individual operations;
    `BranchChange` summarises their cumulative effect.
    """

    path: str
    op: Literal["write", "edit", "delete", "mkdir", "rmdir"]
    timestamp: datetime


BranchDiffOperation = Literal["created", "modified", "deleted", "untouched"]
"""What a single branch did to a given path, relative to the parent backend.

`"deleted"` surfaces when a branch removed the path — either via the
`delete_file` agent tool, or via a shell `rm` invoked through
`execute` against a :class:`~pydantic_ai_backends.LocalBackend` parent
(the snapshot mutation tracker propagates the deletion back into the
overlay). The classifier `_classify_agreement` treats deletions like
any other operation: all-deleters → `unanimous_change`, mixed →
`split`, single deleter → `unique`.
"""


BranchDiffAgreement = Literal["unanimous_change", "unanimous_no_change", "split", "unique"]
"""Cross-branch classification of a single path's outcomes.

- `unanimous_change`: ≥2 branches touched and all touchers produced identical content.
- `unanimous_no_change`: no branch touched the path (only surfaces when an
  explicit `paths` filter pulls it into the report for transparency).
- `split`: ≥2 branches touched and their outcomes differ.
- `unique`: exactly one branch touched (others left the path alone).
"""


@_dataclass(frozen=True)
class BranchChange:
    """One branch's outcome for a single path within a `BranchDiffReport`.

    State-level aggregate: describes the END STATE of a path on a single
    branch relative to the parent backend, classified into one
    :data:`BranchDiffOperation` (`"created"` / `"modified"` /
    `"deleted"` / `"untouched"`). The classification is derived from
    parent existence + overlay content, NOT from :class:`FileChange.op` -
    a branch that issues an `op="write"` on a path absent from the
    parent yields `operation="created"`; the same `op="write"` on a
    path present in the parent yields `operation="modified"`.

    Not to be confused with :class:`FileChange`, which is the event-level
    log of individual writes/edits/deletes that produced this state.
    """

    branch_id: str
    branch_label: str
    operation: BranchDiffOperation
    new_content: str | None
    unified_diff_vs_parent: str
    size_bytes: int
    is_binary: bool
    #: Full hex sha256 of the raw bytes for binary changes; `None` otherwise.
    #: Used as the content-identity key for agreement classification so two
    #: distinct binaries are never collapsed into agreement. The
    #: human-readable `unified_diff_vs_parent` placeholder keeps only a
    #: truncated prefix, which is not collision-safe for comparison.
    binary_sha256: str | None = None


@_dataclass(frozen=True)
class PathDiff:
    """Per-path slice of a `BranchDiffReport`: parent state + every branch's outcome."""

    path: str
    parent_content: str | None
    branches: dict[str, BranchChange]
    agreement: BranchDiffAgreement


@_dataclass(frozen=True)
class DiffSummary:
    """Aggregate metrics for a `BranchDiffReport`.

    `agreement_score` is `1.0 - split_paths / max(total_paths_touched, 1)`.
    Only *contested* paths - those touched by more than one branch with
    diverging end states (`agreement == "split"`) - count against the
    score. Paths touched by exactly one branch (`agreement == "unique"`)
    count toward neither agreement nor disagreement, so maximal
    non-overlapping divergence (every branch editing different files) yields
    `agreement_score == 1.0`. This is intentional: the metric measures
    same-path conflict, not breadth of divergence. `per_branch_unique`
    captures the orthogonal "how much did each branch touch alone" signal.
    The judge consumes `1 - agreement_score` as `quality_spread`.
    """

    total_paths_touched: int
    unanimous_paths: int
    split_paths: int
    per_branch_unique: dict[str, int]
    agreement_score: float


@_dataclass(frozen=True)
class BranchDiffReport:
    """Typed cross-branch diff returned by :func:`diff_branches`.

    Bundles a per-path :class:`PathDiff` list with a :class:`DiffSummary`
    of aggregate metrics (agreement score, unanimous vs split path
    counts, per-branch unique-touch counts) so callers can render or
    score the fork's divergence without re-walking individual overlays.
    """

    fork_id: str
    paths: list[PathDiff]
    summary: DiffSummary


class JudgeVerdict(BaseModel):
    """Structured output of :meth:`JudgeAgent.evaluate`.

    Pydantic `BaseModel` (not dataclass) because pydantic-ai's `output_type`
    contract requires a `BaseModel`-shaped schema for structured output.
    """

    winner_branch_id: str
    # Bounded to [0, 1]: an out-of-range value (e.g. a model emitting 1.5) would
    # otherwise skew the tie-break (max by confidence), inflate mean_confidence,
    # and distort compute_confidence's heuristic × judge_confidence product.
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str
    rejected_with_reasons: dict[str, str] = Field(default_factory=dict)
    caveats: list[str] = Field(default_factory=list)
    recommended_followup: str | None = None


@_dataclass(frozen=True)
class ConfidenceSignals:
    """Three weighted signals combined by `compute_confidence`.

    - `quality_spread` - `1 - agreement_score` from :class:`BranchDiffReport`.
      High = branches diverged meaningfully; weight 0.4.
    - `test_pass_ratio` - passed / total tests in the winner branch. `None`
      when no per-branch test signal is available; the cap-at-0.65 safety rail
      kicks in. Weight 0.4.
    - `internal_consistency` - `1 - (retries + stuck_loop_hits) / turns` for
      the winner; clamped to `[0.0, 1.0]`. Weight 0.2.

    The pipeline currently ships without a per-branch test-runner hook,
    so `test_pass_ratio` is `None` in practice; the safety rail caps
    the combined heuristic at `0.65` in that case and
    `auto_with_fallback` falls through to manual resolution until a
    test-signal hook lands (see follow-ups in the live-fork doc).
    """

    quality_spread: float
    test_pass_ratio: float | None
    internal_consistency: float


@_dataclass(frozen=True)
class BranchOutcome:
    """Per-branch summary the judge sees in its prompt.

    Intentionally narrow - no full message history. The judge sees the
    original goal, the structured diff report, and one `BranchOutcome`
    per branch. Keeps the prompt bounded and the cost predictable.

    `error_count` is typed as `int` but in practice is `0` or `1`
    per branch (derived from the terminal branch state). Richer tool-level
    error counting is a forward-compatible extension.
    """

    branch_id: str
    branch_label: str
    #: Included in the judge prompt so it evaluates each branch against its own steer.
    steer: str
    final_assistant_message: str
    cost_usd: float | None
    turns: int
    error_count: int
    retry_count: int
    stuck_loop_hits: int
    test_pass_ratio: float | None = None


@_dataclass(frozen=True)
class ResolveOutcome:
    """Outcome envelope returned by :meth:`ForkCoordinator.resolve`.

    Three commit semantics live behind the same envelope so the caller (CLI)
    can branch cleanly:

    - `committed=True`: the coordinator already ran `merge_or_select`; see
      :attr:`merge_result`. Modes that hit this path: `"auto"` and `"vote"`.
    - `committed=False, auto_eligible=True`: above-threshold
      `"auto_with_fallback"`. Commit is deferred to the caller so the
      acceptance widget can offer an `[o]` override before the merge fires.
    - `committed=False, auto_eligible=False`: below-threshold
      `"auto_with_fallback"` (caller opens picker preselected) OR
      `"manual"` (no judge ran, caller picks).

    :attr:`judge_usage` carries the judge's `result.usage` (summed across
    judges in vote mode) so the caller can attribute the cost separately
    from branch-agent usage, without extending `pydantic-ai-shields`'
    :class:`CostTracking` API with a new cost category.
    """

    committed: bool
    auto_eligible: bool
    verdict: JudgeVerdict | None
    signals: ConfidenceSignals | None
    effective_confidence: float
    merge_result: MergeResult | None
    judge_usage: Any | None = None
