"""Autonomous judge for Live Run Forking.

This module wires a cheap model behind the :class:`MergeStrategy` `"auto"` /
`"auto_with_fallback"` / `"vote"` paths. The judge sees the original goal,
the structured :class:`BranchDiffReport`, and per-branch
:class:`BranchOutcome` summaries - never the full per-branch message history,
which keeps the prompt bounded and the cost predictable.

The combined confidence is `heuristic × judge.confidence`; the heuristic is
`0.4 * quality_spread + 0.4 * test_pass_ratio + 0.2 * internal_consistency`,
capped at `0.65` when no test signal is available (no per-branch test
integration yet; the cap forces fallback-to-manual in practice).

The agent-facing :meth:`ForkCoordinator.resolve` calls into this module; the
toolset's `__init__` re-exports :class:`JudgeAgent` and helpers for
external consumers.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from pydantic_ai import Agent
from pydantic_ai.messages import ModelRequest, RetryPromptPart

from pydantic_deep.features.forking.types import (
    BranchDiffReport,
    BranchOutcome,
    ConfidenceSignals,
    JudgeVerdict,
)

if TYPE_CHECKING:
    from pydantic_ai.models import Model


#: Hard cap on the rendered judge prompt - truncated tail with marker.
_MAX_JUDGE_PROMPT_CHARS: int = 32_000

#: Per-section caps composed into the prompt.
_MAX_GOAL_CHARS: int = 2_000
_MAX_OUTCOME_MESSAGE_CHARS: int = 400

#: Three confidence-signal weights - must sum to 1.0 (guarded below).
_QUALITY_SPREAD_WEIGHT: float = 0.4
_TEST_RATIO_WEIGHT: float = 0.4
_INTERNAL_CONSISTENCY_WEIGHT: float = 0.2
# raise > assert so the invariant guard survives python -O (see diff.py:225 for
# the same convention). math.isclose absorbs float-summation rounding.
if not math.isclose(
    _QUALITY_SPREAD_WEIGHT + _TEST_RATIO_WEIGHT + _INTERNAL_CONSISTENCY_WEIGHT, 1.0
):  # pragma: no cover - module-load invariant guard
    raise RuntimeError(
        "confidence-signal weights must sum to 1.0: "
        f"{_QUALITY_SPREAD_WEIGHT} + {_TEST_RATIO_WEIGHT} + {_INTERNAL_CONSISTENCY_WEIGHT}"
    )

#: Safety rail when no test signal: caps heuristic so `auto_with_fallback`
#: falls back to manual until a test-runner hook lands.
_NO_TEST_HEURISTIC_CAP: float = 0.65

#: Best-effort - see `pydantic_deep/capabilities/stuck_loop.py` for the source strings.
_STUCK_LOOP_MARKERS: tuple[str, ...] = (
    "identical arguments",
    "alternating between",
    "returned the same result",
)


JUDGE_SYSTEM_PROMPT = (
    "You are evaluating parallel branch attempts of an AI coding agent. "
    "Each branch was forked from a parent conversation and given its own instruction "
    "(shown as 'instruction:' under each branch in the Outcomes section). "
    "IMPORTANT: evaluate each branch against its OWN instruction, not the parent context. "
    "The '## Parent context' section shows what the parent agent was doing before the fork "
    "— it is background only and NOT the success criterion. "
    "Pick the single best branch that best fulfilled its own instruction "
    "and explain in 2-3 sentences. "
    "Be specific: cite diffs, cost, turns, structural issues. "
    "If all branches share the same instruction, evaluate them comparatively. "
    "Set rejected_with_reasons[branch_id] for every loser. "
    "Set caveats for anything you couldn't verify. "
    "Return a JudgeVerdict."
)


def _truncate(text: str, limit: int) -> str:
    """Trim `text` to `limit` chars, appending a marker when truncated."""
    if len(text) <= limit:
        return text
    return text[:limit] + "…[truncated]"


def _format_outcomes(outcomes: list[BranchOutcome]) -> str:
    """One bullet per branch - bounded final message + key counters."""
    lines: list[str] = []
    for o in outcomes:
        msg = _truncate(o.final_assistant_message, _MAX_OUTCOME_MESSAGE_CHARS)
        cost = f"${o.cost_usd:.4f}" if o.cost_usd is not None else "?"
        lines.append(
            f"- {o.branch_id} ({o.branch_label}):\n"
            f"  [SUCCESS CRITERION] instruction: {_truncate(o.steer, 300)}\n"
            f"  turns={o.turns} cost={cost} errors={o.error_count} "
            f"retries={o.retry_count} stuck_loop={o.stuck_loop_hits}\n"
            f"  final: {msg}"
        )
    return "\n".join(lines)


def _format_diff_report(report: BranchDiffReport) -> str:
    """Compact textual rendering of a :class:`BranchDiffReport`.

    :func:`build_diff_report` already truncates each path's unified diff
    at 500 lines via `create_content_preview`; we don't re-truncate here.
    """
    summary = report.summary
    lines = [
        f"fork_id: {report.fork_id}",
        f"summary: total_paths={summary.total_paths_touched} "
        f"unanimous={summary.unanimous_paths} split={summary.split_paths} "
        f"agreement_score={summary.agreement_score:.3f}",
    ]
    for pd in report.paths:
        lines.append(f"### {pd.path} (agreement={pd.agreement})")
        for change in pd.branches.values():
            if change.operation == "untouched":
                continue
            elif change.operation == "deleted":
                lines.append(f"  - {change.branch_id} ({change.branch_label}) DELETED")
            else:
                lines.append(
                    f"  - {change.branch_id} ({change.branch_label}) "
                    f"{change.operation} {change.size_bytes}B"
                )
            diff_text = change.unified_diff_vs_parent
            if diff_text:
                lines.append(diff_text)
    return "\n".join(lines)


def _build_judge_prompt(
    goal: str,
    diff_report: BranchDiffReport,
    outcomes: list[BranchOutcome],
) -> str:
    """Render the judge's prompt with per-section + overall caps.

    Returns a `str` whose length is at most :data:`_MAX_JUDGE_PROMPT_CHARS`;
    the test plan's bound assertion (case #7) checks against that constant.
    The composition is intentional: full per-branch message history is never
    included - the judge only sees the goal, the structured diff, and the
    outcome bullets.
    """
    parts = [
        "## Parent context (background only — NOT the success criterion)",
        _truncate(goal, _MAX_GOAL_CHARS),
        "",
        "## Outcomes (evaluate each branch against its own 'instruction:')",
        _format_outcomes(outcomes),
        "",
        "## Diff report",
        _format_diff_report(diff_report),
    ]
    text = "\n".join(parts)
    return _truncate(text, _MAX_JUDGE_PROMPT_CHARS)


def compute_confidence(
    signals: ConfidenceSignals,
    judge_confidence: float,
) -> float:
    """Combine the three signals with the judge's self-reported confidence.

    Heuristic = `0.4 * quality_spread + 0.4 * test_pass_ratio + 0.2 *
    internal_consistency`. If `signals.test_pass_ratio is None` the
    test slot is treated as `0.0` for the weighted sum AND the heuristic is
    capped at `0.65` before multiplying by `judge_confidence` - the
    safety rail that keeps `auto_with_fallback` defaulting to manual when
    the test signal is missing. The product is clamped to `[0.0, 1.0]`.
    """
    test_component = signals.test_pass_ratio if signals.test_pass_ratio is not None else 0.0
    heuristic = (
        signals.quality_spread * _QUALITY_SPREAD_WEIGHT
        + test_component * _TEST_RATIO_WEIGHT
        + signals.internal_consistency * _INTERNAL_CONSISTENCY_WEIGHT
    )
    if signals.test_pass_ratio is None:
        heuristic = min(heuristic, _NO_TEST_HEURISTIC_CAP)
    combined = heuristic * judge_confidence
    return max(0.0, min(1.0, combined))


def _majority_pick(verdicts: list[JudgeVerdict]) -> JudgeVerdict:
    """Pick the winning :class:`JudgeVerdict` for `"vote"` mode.

    Majority rule: highest count of `winner_branch_id` wins. Ties are broken
    by the highest-confidence verdict among the tied candidates (per the
    issue's "Tie → highest-confidence judge breaks the tie" spec). The
    returned verdict is **synthetic**: `reasoning` summarises the vote,
    `confidence` is the mean confidence over every verdict that selected
    the winning branch (not only the tie-break candidate set), and the
    other fields merge from those same verdicts (caveats union'd,
    `rejected_with_reasons` taking the highest-confidence entry per branch).
    """
    if not verdicts:
        raise ValueError("_majority_pick requires at least one verdict.")
    counts = Counter(v.winner_branch_id for v in verdicts)
    top_count = max(counts.values())
    tied_winners = [bid for bid, c in counts.items() if c == top_count]
    candidates = [v for v in verdicts if v.winner_branch_id in tied_winners]
    # Highest-confidence verdict among the tied set is the tie-breaker.
    best = max(candidates, key=lambda v: v.confidence)
    winner_id = best.winner_branch_id
    same_winner_verdicts = [v for v in verdicts if v.winner_branch_id == winner_id]
    mean_confidence = sum(v.confidence for v in same_winner_verdicts) / len(same_winner_verdicts)
    caveats: list[str] = []
    seen: set[str] = set()
    for v in same_winner_verdicts:
        for c in v.caveats:
            if c not in seen:
                caveats.append(c)
                seen.add(c)
    rejected: dict[str, str] = {}
    for v in sorted(verdicts, key=lambda x: x.confidence, reverse=True):
        for bid, reason in v.rejected_with_reasons.items():
            rejected.setdefault(bid, reason)
    reasoning = (
        f"{top_count} of {len(verdicts)} judges picked {winner_id}. "
        f"Tie-break by highest confidence ({best.confidence:.2f}). "
        f"{best.reasoning}"
    )
    return JudgeVerdict(
        winner_branch_id=winner_id,
        confidence=mean_confidence,
        reasoning=reasoning,
        rejected_with_reasons=rejected,
        caveats=caveats,
        recommended_followup=best.recommended_followup,
    )


def _iter_retry_parts(messages: list[Any]) -> Iterator[RetryPromptPart]:
    """Yield every :class:`RetryPromptPart` in `messages` in order.

    Shared scaffold for :func:`count_stuck_loop_hits` and
    :func:`count_retry_parts` so the message-walking loop has one home - if
    pydantic-ai's message shape ever changes, only this helper needs updating.
    """
    for msg in messages:
        if not isinstance(msg, ModelRequest):
            continue
        for part in msg.parts:
            if isinstance(part, RetryPromptPart):
                yield part


def count_stuck_loop_hits(messages: list[Any]) -> int:
    """Count `RetryPromptPart` parts in `messages` that match a stuck-loop marker.

    Best-effort heuristic - relies on the marker strings in
    :data:`_STUCK_LOOP_MARKERS` matching the `ModelRetry` messages raised by
    :class:`StuckLoopDetection`. If the stuck-loop module's message wording
    changes, update the markers list.
    """
    hits = 0
    for part in _iter_retry_parts(messages):
        content = part.content
        if not isinstance(content, str):
            continue
        if any(marker in content for marker in _STUCK_LOOP_MARKERS):
            hits += 1
    return hits


def count_retry_parts(messages: list[Any]) -> int:
    """Count every `RetryPromptPart` in `messages` (any source - stuck-loop or other)."""
    return sum(1 for _ in _iter_retry_parts(messages))


class JudgeAgent:
    """Thin :class:`Agent` wrapper that picks the winning branch via structured output.

    Holds an internal pydantic-ai :class:`Agent` with
    :class:`JudgeVerdict` as `output_type`. The agent is built once at
    construction; concurrent `evaluate` calls reuse the same underlying
    agent. The system prompt is the module-level
    :data:`JUDGE_SYSTEM_PROMPT`; per-call context is composed by
    :func:`_build_judge_prompt`.
    """

    def __init__(self, model: str | Model) -> None:
        self.agent: Agent[None, JudgeVerdict] = Agent(
            model,
            output_type=JudgeVerdict,
            system_prompt=JUDGE_SYSTEM_PROMPT,
        )

    async def evaluate(
        self,
        goal: str,
        diff_report: BranchDiffReport,
        outcomes: list[BranchOutcome],
    ) -> tuple[JudgeVerdict, Any]:
        """Run the judge and return `(verdict, usage)`.

        `usage` is the `result.usage` property value (pydantic-ai exposes
        it as a property, not a method) - the coordinator bubbles it up via
        :attr:`ResolveOutcome.judge_usage` for cost attribution. The judge
        never receives full per-branch message history, only the goal + diff
        + outcome summaries.
        """
        prompt = _build_judge_prompt(goal, diff_report, outcomes)
        result = await self.agent.run(prompt)
        usage = getattr(result, "usage", None)
        return result.output, usage


__all__ = [
    "JUDGE_SYSTEM_PROMPT",
    "JudgeAgent",
    "compute_confidence",
    "count_retry_parts",
    "count_stuck_loop_hits",
]
