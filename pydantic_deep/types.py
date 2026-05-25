"""Type definitions for pydantic-deep."""

from __future__ import annotations

from dataclasses import dataclass as _dataclass
from dataclasses import field as _field
from datetime import datetime
from typing import Any, Literal, TypedDict, TypeVar

from pydantic import BaseModel, Field
from pydantic_ai.output import OutputSpec
from pydantic_ai_backends import (
    EditResult as EditResult,
)
from pydantic_ai_backends import (
    ExecuteResponse as ExecuteResponse,
)
from pydantic_ai_backends import (
    FileData as FileData,
)
from pydantic_ai_backends import (
    FileInfo as FileInfo,
)
from pydantic_ai_backends import (
    GrepMatch as GrepMatch,
)
from pydantic_ai_backends import (
    RuntimeConfig as RuntimeConfig,
)
from pydantic_ai_backends import (
    WriteResult as WriteResult,
)
from pydantic_ai_todo import Todo as Todo
from subagents_pydantic_ai import CompiledSubAgent as CompiledSubAgent
from subagents_pydantic_ai import SubAgentConfig as SubAgentConfig

# Re-export new Skill dataclass from skills package
from pydantic_deep.toolsets.skills.types import Skill as Skill

# Re-export OutputSpec from pydantic-ai for structured output support
ResponseFormat = OutputSpec[object]

# Type variable for output types
OutputT = TypeVar("OutputT")


@_dataclass
class BrowseResult:
    """Result of a browser navigation or interaction.

    Returned by helper utilities that wrap ``BrowserToolset`` tool output
    into a structured form. The toolset tools themselves return plain strings
    for pydantic-ai compatibility; use this dataclass when you want typed
    access to individual fields in your own code.

    Attributes:
        url: The page URL after the action.
        title: The page title.
        content: Page content as Markdown, truncated to ``max_content_tokens``.
        screenshot: Base64-encoded PNG screenshot, or ``None`` if not captured.
        error: Error message if the action failed, or ``None`` on success.
    """

    url: str
    title: str
    content: str
    screenshot: str | None = None
    error: str | None = None


class UploadedFile(TypedDict):
    """Metadata for an uploaded file.

    Uploaded files are stored in the backend and can be accessed by the agent
    through file tools (read_file, grep, glob, execute).
    """

    name: str  # Original filename
    path: str  # Path in backend (e.g., /uploads/sales.csv)
    size: int  # Size in bytes
    line_count: int | None  # Number of lines (for text files)
    mime_type: str | None  # MIME type (e.g., text/plain)
    encoding: str  # Encoding (e.g., utf-8, binary)


@_dataclass(frozen=True)
class BranchSpec:
    """Specification for a single branch in a fork.

    Attributes:
        label: Human-readable branch label (e.g. ``"approach_a"``).
        steer: First user message delivered to the branch agent — the
            instruction that differentiates this branch from siblings.
        model: Optional model override for the branch. ``None`` inherits
            the parent's model.
        budget_usd: Optional per-branch budget. Enforced by
            :class:`_BudgetWatcher` (Stage 4): when the branch's
            ``CostTracking`` cumulative cost crosses this cap, the
            branch is cancelled and transitions to
            :data:`BranchState` ``"budget_exhausted"``.
        extra_instructions: Optional extra instructions appended to the
            branch's system prompt.
    """

    label: str
    steer: str
    model: str | None = None
    budget_usd: float | None = None
    extra_instructions: str | None = None


@_dataclass(frozen=True)
class BranchIsolation:
    """Isolation flags controlling what state branches share with the parent.

    Defaults match the project's per-branch isolation policy:
    ``history`` always copies; ``backend``, ``memory``, ``todos`` copy by
    default; ``message_queue`` is isolated; ``team_bus`` is shared (peer-to-peer
    bus, branches CAN talk by default).

    Stage 1 fully exercises ``backend="copy"`` and ``message_queue="isolated"``;
    other values are accepted for forward-compat.
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

``budget_exhausted`` means the per-branch cap was crossed: the watcher
cancels the branch mid-run and the partial-history snapshot becomes the
durable record. ``aggregate_budget_exhausted`` means the fork-wide cap
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
    """Per-branch cost snapshot — element of :class:`ForkCostSummary`.

    ``cumulative_usd`` is the externally-facing name for the upstream
    ``CostTracking.total_cost`` value; the rename happens at the
    :meth:`ForkCoordinator.fork_cost` boundary. ``None`` indicates pricing
    was unavailable for the branch's model (e.g. an unrecognised model in
    the genai-prices catalogue) — the branch still runs, but its budget
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
    """Output of the ``fork_cost(fork_id)`` tool.

    Sums :attr:`BranchCost.cumulative_usd` across branches with a non-``None``
    cost; branches with ``None`` are omitted from the aggregate to avoid
    misleading partial sums.
    """

    fork_id: str
    per_branch: dict[str, BranchCost]
    aggregate_usd: float | None
    aggregate_budget_usd: float | None
    aggregate_remaining_usd: float | None


@_dataclass(frozen=True)
class MergeStrategy:
    """Merge strategy for resolving a fork.

    Stage 6 extends :attr:`kind` to four values:

    - ``"manual"`` — caller picks via ``merge_or_select(action="pick:<id>")``.
    - ``"auto"`` — :class:`JudgeAgent` picks; coordinator commits immediately.
    - ``"auto_with_fallback"`` — judge picks; if effective confidence is at or
      above :attr:`confidence_threshold` the commit is deferred to the caller
      (so the acceptance widget can offer an override), otherwise the caller
      opens the manual picker with the judge's pick preselected. **Default.**
    - ``"vote"`` — multiple judges (default: Haiku + GPT-mini + Gemini Flash)
      evaluate independently; majority wins, tie broken by highest confidence;
      coordinator commits immediately.

    Default flips from ``"manual"`` (Stages 1–5) to ``"auto_with_fallback"`` in
    Stage 6.
    """

    kind: Literal["manual", "auto", "auto_with_fallback", "vote"] = "auto_with_fallback"
    judge_model: str = "anthropic:claude-haiku-4-5-20251001"
    judge_models: list[str] | None = None
    confidence_threshold: float = 0.80
    show_reasoning: bool = True


@_dataclass
class ForkHandle:
    """Handle returned by ``ForkCoordinator.fork()`` identifying a live fork."""

    fork_id: str
    parent_checkpoint_id: str | None
    branches: list[str]
    merge_strategy: MergeStrategy
    created_at: datetime


@_dataclass(frozen=True)
class FlushError:
    """One per-write failure observed by :meth:`BranchOverlay.flush_to`.

    ``flush_to`` never aborts on the first failure — it accumulates errors
    for the caller to surface alongside the changes that did land. Surfaced
    on :attr:`MergeResult.errors` so the CLI / agent can report partial
    success without losing track of what didn't apply.
    """

    path: str
    op: Literal["write", "edit"]
    message: str


@_dataclass(frozen=True)
class FlushReport:
    """Outcome of replaying a :class:`BranchOverlay` onto the parent backend.

    Produced by :meth:`BranchOverlay.flush_to` during ``merge_or_select``
    when the user picks a winner with default-flush semantics. The fields
    flow through to :class:`MergeResult` so the CLI / agent can render
    "Merged: kept branch X · N files applied · conflicts: … · errors: N"
    style notifications.

    - ``applied_paths`` lists paths whose final overlay content was
      written; a path's last write/edit wins, multiple in-overlay edits
      to the same path collapse to one entry.
    - ``applied_changes`` counts every replayed op (≥ ``len(applied_paths)``).
    - ``conflicts`` lists paths where the parent's pre-flush content
      diverged from the pre-fork snapshot — both modified-by-third-actor
      and deleted-by-third-actor cases land here. Surfacing only; flush
      still proceeds (last-write-wins).
    - ``errors`` is one :class:`FlushError` per per-write failure (e.g.
      parent ``WriteResult.error`` non-empty or parent raised). The
      failing path is excluded from ``applied_paths``; remaining writes
      still flush.
    """

    applied_paths: list[str]
    applied_changes: int
    conflicts: list[str]
    errors: list[FlushError]


@_dataclass
class MergeResult:
    """Result returned by ``ForkCoordinator.merge_or_select()``."""

    fork_id: str
    winner_branch_id: str
    discarded_branches: list[str]
    history_after_merge: list[Any]
    applied_paths: list[str] = _field(default_factory=list)
    applied_changes: int = 0
    conflicts: list[str] = _field(default_factory=list)
    errors: list[FlushError] = _field(default_factory=list)


@_dataclass(frozen=True)
class FileChange:
    """Single overlay write event recorded by ``BranchOverlay``.

    Event-level log entry: one record per successful ``write`` or ``edit``
    on the branch overlay. The temporal-ordered ``list[FileChange]`` exposed
    by ``BranchOverlay.changes()`` is the data spine consumed across stages:

    - Stage 2 ``diff_branches`` — uses ``path`` to know which files were touched
    - Stage 5 materializer — uses ``op`` to replay ``write`` vs ``edit`` semantics
    - Stage 6 judge — uses ``timestamp`` for temporal heuristics

    Not to be confused with :class:`BranchChange` (Stage 2), which is a
    state-level aggregate describing a branch's per-path outcome relative
    to the parent backend (``"created"`` / ``"modified"`` / ``"deleted"`` /
    ``"untouched"``). ``FileChange`` logs individual operations;
    ``BranchChange`` summarizes their effect.
    """

    path: str
    op: Literal["write", "edit"]
    timestamp: datetime


BranchDiffOperation = Literal["created", "modified", "deleted", "untouched"]
"""What a single branch did to a given path, relative to the parent backend.

NOTE: ``"deleted"`` is reserved for future use. Stage 1 ``BranchOverlay``
records only writes and edits — no delete operation exists in the runtime
pipeline today, so :func:`~pydantic_deep.toolsets.forking.diff.build_diff_report`
cannot produce ``operation="deleted"``. The classifier
``_classify_agreement`` handles it correctly for forward compat
(unit-tested via ``test_diff_classifies_deletion_as_split``), but the
literal won't surface in real reports until ``BranchOverlay`` gains
delete support.
"""


BranchDiffAgreement = Literal["unanimous_change", "unanimous_no_change", "split", "unique"]
"""Cross-branch classification of a single path's outcomes.

- ``unanimous_change``: ≥2 branches touched and all touchers produced identical content.
- ``unanimous_no_change``: no branch touched the path (only surfaces when an
  explicit ``paths`` filter pulls it into the report for transparency).
- ``split``: ≥2 branches touched and their outcomes differ.
- ``unique``: exactly one branch touched (others left the path alone).
"""


@_dataclass(frozen=True)
class BranchChange:
    """One branch's outcome for a single path within a ``BranchDiffReport``.

    State-level aggregate: describes the END STATE of a path on a single
    branch relative to the parent backend, classified into one
    :data:`BranchDiffOperation` (``"created"`` / ``"modified"`` /
    ``"deleted"`` / ``"untouched"``). The classification is derived from
    parent existence + overlay content, NOT from :class:`FileChange.op` —
    a branch that issues an ``op="write"`` on a path absent from the
    parent yields ``operation="created"``; the same ``op="write"`` on a
    path present in the parent yields ``operation="modified"``.

    Not to be confused with :class:`FileChange` (Stage 1), which is the
    event-level log of individual writes/edits that produced this state.
    """

    branch_id: str
    branch_label: str
    operation: BranchDiffOperation
    new_content: str | None
    unified_diff_vs_parent: str
    size_bytes: int
    is_binary: bool


@_dataclass(frozen=True)
class PathDiff:
    """Per-path slice of a ``BranchDiffReport``: parent state + every branch's outcome."""

    path: str
    parent_content: str | None
    branches: dict[str, BranchChange]
    agreement: BranchDiffAgreement


@_dataclass(frozen=True)
class DiffSummary:
    """Aggregate metrics for a ``BranchDiffReport``."""

    total_paths_touched: int
    unanimous_paths: int
    split_paths: int
    per_branch_unique: dict[str, int]
    agreement_score: float


@_dataclass(frozen=True)
class BranchDiffReport:
    """Typed diff over fork branches — Stage 2 output of ``diff_branches``."""

    fork_id: str
    paths: list[PathDiff]
    summary: DiffSummary


class JudgeVerdict(BaseModel):
    """Structured output of :meth:`JudgeAgent.evaluate`.

    Pydantic ``BaseModel`` (not dataclass) because pydantic-ai's ``output_type``
    contract requires a ``BaseModel``-shaped schema for structured output.
    """

    winner_branch_id: str
    confidence: float
    reasoning: str
    rejected_with_reasons: dict[str, str] = Field(default_factory=dict)
    caveats: list[str] = Field(default_factory=list)
    recommended_followup: str | None = None


@_dataclass(frozen=True)
class ConfidenceSignals:
    """Three weighted signals combined by ``compute_confidence``.

    - ``quality_spread`` — ``1 - agreement_score`` from :class:`BranchDiffReport`.
      High = branches diverged meaningfully; weight 0.4.
    - ``test_pass_ratio`` — passed / total tests in the winner branch. ``None``
      when no per-branch test signal is available; the cap-at-0.65 safety rail
      kicks in. Weight 0.4.
    - ``internal_consistency`` — ``1 - (retries + stuck_loop_hits) / turns`` for
      the winner; clamped to ``[0.0, 1.0]``. Weight 0.2.

    Stage 6 ships without per-branch test integration so ``test_pass_ratio`` is
    always ``None`` in practice; the safety rail keeps the heuristic ≤ 0.65 in
    that case and ``auto_with_fallback`` always falls through to manual until a
    test-signal hook lands (see follow-ups in the live-fork doc).
    """

    quality_spread: float
    test_pass_ratio: float | None
    internal_consistency: float


@_dataclass(frozen=True)
class BranchOutcome:
    """Per-branch summary the judge sees in its prompt.

    Intentionally narrow — no full message history. The judge gets the original
    goal, the structured diff report, and one of these per branch. Keeps the
    prompt bounded and the cost predictable.

    ``error_count`` is ``0`` or ``1`` for a single branch — the issue's type
    sketch uses generic ``int`` but Stage 6 narrows it to a per-branch boolean
    derived from terminal branch state; richer tool-error counting is left for
    a follow-up.
    """

    branch_id: str
    branch_label: str
    #: The steer message that was sent to this branch when the fork was created
    #: (``BranchSpec.steer``). Included in the judge prompt so the judge can
    #: evaluate each branch against its own instruction, not just the parent goal.
    steer: str
    final_assistant_message: str
    cost_usd: float | None
    turns: int
    error_count: int
    retry_count: int
    stuck_loop_hits: int


@_dataclass(frozen=True)
class ResolveOutcome:
    """Outcome envelope returned by :meth:`ForkCoordinator.resolve`.

    Three commit semantics live behind the same envelope so the caller (CLI)
    can branch cleanly:

    - ``committed=True``: the coordinator already ran ``merge_or_select``; see
      :attr:`merge_result`. Modes that hit this path: ``"auto"`` and ``"vote"``.
    - ``committed=False, auto_eligible=True``: above-threshold
      ``"auto_with_fallback"``. Commit is deferred to the caller so the
      acceptance widget can offer an ``[o]`` override before the merge fires.
    - ``committed=False, auto_eligible=False``: below-threshold
      ``"auto_with_fallback"`` (caller opens picker preselected) OR
      ``"manual"`` (no judge ran, caller picks).

    :attr:`judge_usage` carries the judge's ``result.usage`` (summed across
    judges in vote mode) so the caller can attribute the cost — Stage 6 does
    not introduce a faked ``cost_category`` field into pydantic-ai-shields'
    ``CostTracking`` API.
    """

    committed: bool
    auto_eligible: bool
    verdict: JudgeVerdict | None
    signals: ConfidenceSignals | None
    effective_confidence: float
    merge_result: MergeResult | None
    judge_usage: Any | None = None
