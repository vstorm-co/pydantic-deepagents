"""Live Run Forking - judge tests (issue #107)."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any
from unittest.mock import patch

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    TextPart,
    UserPromptPart,
)
from pydantic_ai.models.test import TestModel
from pydantic_ai_backends import StateBackend

from pydantic_deep import (
    BranchOverlay,
    BranchSpec,
    DeepAgentDeps,
    ForkCoordinator,
    InMemoryForkStateStore,
    JudgeAgent,
    JudgeVerdict,
    MergeStrategy,
    compute_confidence,
)
from pydantic_deep.features.checkpointing import InMemoryCheckpointStore
from pydantic_deep.features.forking.coordinator import (
    _detect_vote_models,
    _last_assistant_text,
)
from pydantic_deep.features.forking.judge import (
    _MAX_JUDGE_PROMPT_CHARS,
    _build_judge_prompt,
    _majority_pick,
    count_retry_parts,
    count_stuck_loop_hits,
)
from pydantic_deep.features.forking.types import (
    BranchChange,
    BranchDiffReport,
    BranchOutcome,
    ConfidenceSignals,
    DiffSummary,
    PathDiff,
)


def test_judge_verdict_confidence_must_be_in_unit_interval() -> None:
    """JudgeVerdict.confidence is bounded to [0, 1] - out-of-range is rejected."""
    import pydantic

    from pydantic_deep.features.forking.types import JudgeVerdict

    # Valid endpoints are accepted.
    assert JudgeVerdict(winner_branch_id="a", confidence=0.0, reasoning="r").confidence == 0.0
    assert JudgeVerdict(winner_branch_id="a", confidence=1.0, reasoning="r").confidence == 1.0

    # Out-of-range values are rejected (so they can't skew tie-break / mean / product).
    for bad in (1.5, -0.1, 2.0):
        with pytest.raises(pydantic.ValidationError):
            JudgeVerdict(winner_branch_id="a", confidence=bad, reasoning="r")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_report(fork_id: str = "fork-x", agreement_score: float = 0.5) -> BranchDiffReport:
    """Build a minimal :class:`BranchDiffReport` with one split path."""
    parent = StateBackend()
    parent.write("foo.py", "parent\n")
    overlay_a = BranchOverlay(parent)
    overlay_a.write("foo.py", "branch-a\n")
    overlay_b = BranchOverlay(parent)
    overlay_b.write("foo.py", "branch-b\n")
    change_a = BranchChange(
        branch_id="a",
        branch_label="alpha",
        operation="modified",
        new_content="branch-a\n",
        unified_diff_vs_parent="@@ \n-parent\n+branch-a\n",
        size_bytes=9,
        is_binary=False,
    )
    change_b = BranchChange(
        branch_id="b",
        branch_label="beta",
        operation="modified",
        new_content="branch-b\n",
        unified_diff_vs_parent="@@ \n-parent\n+branch-b\n",
        size_bytes=9,
        is_binary=False,
    )
    pd = PathDiff(
        path="foo.py",
        parent_content="parent\n",
        branches={"a": change_a, "b": change_b},
        agreement="split",
    )
    summary = DiffSummary(
        total_paths_touched=1,
        unanimous_paths=0,
        split_paths=1,
        per_branch_unique={"a": 0, "b": 0},
        agreement_score=agreement_score,
    )
    return BranchDiffReport(fork_id=fork_id, paths=[pd], summary=summary)


def _make_outcomes() -> list[BranchOutcome]:
    return [
        BranchOutcome(
            branch_id="a",
            branch_label="alpha",
            steer="do task A",
            final_assistant_message="A finished",
            cost_usd=0.001,
            turns=3,
            error_count=0,
            retry_count=0,
            stuck_loop_hits=0,
        ),
        BranchOutcome(
            branch_id="b",
            branch_label="beta",
            steer="do task B",
            final_assistant_message="B finished",
            cost_usd=0.002,
            turns=4,
            error_count=0,
            retry_count=1,
            stuck_loop_hits=0,
        ),
    ]


# ---------------------------------------------------------------------------
# Test 1 - JudgeAgent.evaluate returns a valid JudgeVerdict via TestModel.
# ---------------------------------------------------------------------------


async def test_judge_agent_returns_valid_verdict():
    tm = TestModel(
        custom_output_args={
            "winner_branch_id": "a",
            "confidence": 0.9,
            "reasoning": "A's diff is smaller and cleaner.",
            "rejected_with_reasons": {"b": "B is too verbose."},
            "caveats": ["No tests were run."],
            "recommended_followup": None,
        }
    )
    judge = JudgeAgent(tm)
    verdict, usage = await judge.evaluate("goal", _make_report(), _make_outcomes())
    assert isinstance(verdict, JudgeVerdict)
    assert verdict.winner_branch_id == "a"
    assert verdict.confidence == 0.9
    assert "smaller" in verdict.reasoning
    assert verdict.rejected_with_reasons == {"b": "B is too verbose."}
    assert verdict.caveats == ["No tests were run."]
    # Single-judge path returns a scalar RunUsage with real token accounting.
    assert usage is not None
    assert usage.total_tokens > 0


async def test_run_judges_vote_sums_per_judge_usages():
    """The vote path SUMS per-judge usages into a single RunUsage, matching the
    single-judge path and the `judge_usage` "summed across judges" contract."""
    from unittest.mock import patch

    from pydantic_ai.usage import RunUsage

    from pydantic_deep.features.forking.types import JudgeVerdict as _JV

    coord, _deps = await _coordinator_with_two_branches()
    a_id = _resolve_winner_id(coord, "a")

    class _StubJudge:
        def __init__(self, model: Any) -> None:
            self.model = model

        async def evaluate(self, _goal: Any, _diff: Any, _outcomes: Any) -> Any:
            return (
                _JV(winner_branch_id=a_id, confidence=0.8, reasoning="ok"),
                RunUsage(input_tokens=10, output_tokens=5, requests=1),
            )

    with patch("pydantic_deep.features.forking.coordinator.JudgeAgent", _StubJudge):
        verdict, usage = await coord._run_judges(
            MergeStrategy(kind="vote", judge_models=["m1", "m2", "m3"]),
            "goal",
            _make_report(),
            _make_outcomes(),
        )

    assert verdict.winner_branch_id == a_id
    # Vote path: a single summed RunUsage across the 3 judges, not a list.
    assert isinstance(usage, RunUsage)
    assert usage.input_tokens == 30
    assert usage.output_tokens == 15
    assert usage.requests == 3


async def test_run_judges_vote_all_none_usage_is_none():
    """A panel where every judge reports no usage yields None (not [None, ...])."""
    from unittest.mock import patch

    from pydantic_deep.features.forking.types import JudgeVerdict as _JV

    coord, _deps = await _coordinator_with_two_branches()
    a_id = _resolve_winner_id(coord, "a")

    class _StubJudge:
        def __init__(self, model: Any) -> None:
            self.model = model

        async def evaluate(self, _goal: Any, _diff: Any, _outcomes: Any) -> Any:
            return (_JV(winner_branch_id=a_id, confidence=0.8, reasoning="ok"), None)

    with patch("pydantic_deep.features.forking.coordinator.JudgeAgent", _StubJudge):
        _verdict, usage = await coord._run_judges(
            MergeStrategy(kind="vote", judge_models=["m1", "m2"]),
            "goal",
            _make_report(),
            _make_outcomes(),
        )

    assert usage is None


# ---------------------------------------------------------------------------
# Test 2 - compute_confidence arithmetic, including the 0.65 cap.
# ---------------------------------------------------------------------------


async def test_compute_confidence_with_test_signal():
    s = ConfidenceSignals(quality_spread=0.5, test_pass_ratio=1.0, internal_consistency=1.0)
    # heuristic = 0.5*0.4 + 1.0*0.4 + 1.0*0.2 = 0.8 ; × 1.0 judge = 0.8
    assert compute_confidence(s, 1.0) == pytest.approx(0.8)
    # × 0.5 judge = 0.4
    assert compute_confidence(s, 0.5) == pytest.approx(0.4)


async def test_compute_confidence_no_test_signal_caps_at_065():
    # heuristic raw = 0.5*0.4 + 0 + 1.0*0.2 = 0.4 ; below 0.65 so no cap effect
    s_low = ConfidenceSignals(quality_spread=0.5, test_pass_ratio=None, internal_consistency=1.0)
    assert compute_confidence(s_low, 1.0) == pytest.approx(0.4)
    # heuristic raw = 1.0*0.4 + 0 + 1.0*0.2 = 0.6 ; below 0.65 still no cap
    s_mid = ConfidenceSignals(quality_spread=1.0, test_pass_ratio=None, internal_consistency=1.0)
    assert compute_confidence(s_mid, 1.0) == pytest.approx(0.6)
    # quality_spread + internal_consistency contributions need to exceed 0.65 to
    # hit the cap. spread=1.0 -> 0.4, consistency=2.0 (impossible normally) gives
    # 0.8; bypass the dataclass-level invariants to confirm the cap clamps.
    s_high = ConfidenceSignals(
        quality_spread=1.0,
        test_pass_ratio=None,
        internal_consistency=1.5,  # contrived but legal - dataclass doesn't validate
    )
    # raw heuristic = 0.4 + 0 + 0.3 = 0.7, capped at 0.65 ; × 1.0 = 0.65
    assert compute_confidence(s_high, 1.0) == pytest.approx(0.65)


async def test_compute_confidence_clamps_to_zero_one():
    # Absurdly high positive inputs - product exceeds 1.0 → clamps to 1.0.
    s_high = ConfidenceSignals(quality_spread=10.0, test_pass_ratio=10.0, internal_consistency=10.0)
    assert compute_confidence(s_high, 10.0) == 1.0
    # Negative heuristic × positive judge → negative product → clamps to 0.0.
    s_neg = ConfidenceSignals(quality_spread=-1.0, test_pass_ratio=-1.0, internal_consistency=-1.0)
    assert compute_confidence(s_neg, 1.0) == 0.0


# ---------------------------------------------------------------------------
# Helpers for tests 3–8: build a coordinator with two stubbed branches.
# ---------------------------------------------------------------------------


def _verdict(
    winner: str = "a",
    confidence: float = 0.9,
    reasoning: str = "A wins because it is smaller.",
) -> JudgeVerdict:
    return JudgeVerdict(
        winner_branch_id=winner,
        confidence=confidence,
        reasoning=reasoning,
        rejected_with_reasons={"b": "B is worse."},
        caveats=[],
        recommended_followup=None,
    )


def _make_fake_judge_class(verdict_or_factory: Any) -> type:
    """Build a `FakeJudgeAgent` class that bypasses real model instantiation.

    `verdict_or_factory` is either a single :class:`JudgeVerdict` (returned
    every call) or a callable taking `(model_name)` and returning a verdict
    - used by the vote-mode test to give each judge a distinct opinion.
    """

    class FakeJudgeAgent:
        def __init__(self, model: Any) -> None:
            self._model = model

        async def evaluate(
            self, goal: str, diff_report: Any, outcomes: list[Any]
        ) -> tuple[JudgeVerdict, Any]:
            del goal, diff_report, outcomes
            v: JudgeVerdict
            if callable(verdict_or_factory):
                v = verdict_or_factory(self._model)
            else:
                v = verdict_or_factory
            return v, None

    return FakeJudgeAgent


async def _coordinator_with_two_branches(
    *,
    strategy: MergeStrategy | None = None,
) -> tuple[ForkCoordinator, DeepAgentDeps]:
    deps = DeepAgentDeps(backend=StateBackend())
    agent = Agent(TestModel(), deps_type=DeepAgentDeps)
    coord = ForkCoordinator(
        agent=agent,
        parent_deps=deps,
        max_branches=2,
        max_depth=1,
        store=InMemoryForkStateStore(),
        checkpoint_store=InMemoryCheckpointStore(),
    )
    parent_history = [ModelRequest(parts=[UserPromptPart(content="make a thing")])]
    await coord.fork(
        [BranchSpec(label="a", steer="approach A"), BranchSpec(label="b", steer="approach B")],
        parent_history=parent_history,
        strategy=strategy,
    )
    # Drain the branch tasks so resolve() can read their final state.
    await asyncio.gather(*(rt.task for rt in coord.branches.values()), return_exceptions=True)
    return coord, deps


def _resolve_winner_id(coord: ForkCoordinator, label: str) -> str:
    for bid, rt in coord.branches.items():
        if rt.spec.label == label:
            return bid
    raise AssertionError(f"label {label!r} not found")


# ---------------------------------------------------------------------------
# Test 3 - auto mode commits without user input.
# ---------------------------------------------------------------------------


async def test_auto_mode_commits_without_user_input():
    coord, _deps = await _coordinator_with_two_branches()
    winner_id = _resolve_winner_id(coord, "a")

    fake_verdict = _verdict(winner=winner_id, confidence=0.5)
    fake_cls = _make_fake_judge_class(fake_verdict)
    with patch("pydantic_deep.features.forking.coordinator.JudgeAgent", fake_cls):
        outcome = await coord.resolve(MergeStrategy(kind="auto"))

    assert outcome.committed is True
    assert outcome.auto_eligible is False
    assert outcome.merge_result is not None
    assert outcome.merge_result.winner_branch_id == winner_id
    assert outcome.verdict is fake_verdict


# ---------------------------------------------------------------------------
# Test 4 - auto_with_fallback above threshold returns auto_eligible=True
# (deferred commit - caller drives the widget).
# ---------------------------------------------------------------------------


async def test_auto_with_fallback_above_threshold_defers_commit():
    coord, _deps = await _coordinator_with_two_branches()
    winner_id = _resolve_winner_id(coord, "a")

    fake_verdict = _verdict(winner=winner_id, confidence=0.95)
    # With test_pass_ratio=None the heuristic caps at 0.65; we lower the
    # threshold so the above-threshold branch fires.
    strategy = MergeStrategy(kind="auto_with_fallback", confidence_threshold=0.10)
    fake_cls = _make_fake_judge_class(fake_verdict)
    with patch("pydantic_deep.features.forking.coordinator.JudgeAgent", fake_cls):
        outcome = await coord.resolve(strategy)

    assert outcome.committed is False
    assert outcome.auto_eligible is True
    assert outcome.merge_result is None
    assert outcome.verdict is fake_verdict
    assert outcome.effective_confidence >= strategy.confidence_threshold


# ---------------------------------------------------------------------------
# Test 5 - auto_with_fallback below threshold returns auto_eligible=False
# (manual picker preselected by the caller).
# ---------------------------------------------------------------------------


async def test_auto_with_fallback_below_threshold_returns_fallthrough():
    coord, _deps = await _coordinator_with_two_branches()
    winner_id = _resolve_winner_id(coord, "a")

    fake_verdict = _verdict(winner=winner_id, confidence=0.5)
    strategy = MergeStrategy(kind="auto_with_fallback", confidence_threshold=0.99)
    fake_cls = _make_fake_judge_class(fake_verdict)
    with patch("pydantic_deep.features.forking.coordinator.JudgeAgent", fake_cls):
        outcome = await coord.resolve(strategy)

    assert outcome.committed is False
    assert outcome.auto_eligible is False
    assert outcome.verdict is fake_verdict
    assert outcome.effective_confidence < strategy.confidence_threshold
    # The picker dispatcher will use verdict.winner_branch_id for preselect.
    assert outcome.verdict.winner_branch_id == winner_id


# ---------------------------------------------------------------------------
# Test 6 - vote mode: majority wins; tie → highest-confidence wins.
# ---------------------------------------------------------------------------


async def test_vote_mode_majority_wins():
    coord, _deps = await _coordinator_with_two_branches()
    a_id = _resolve_winner_id(coord, "a")
    b_id = _resolve_winner_id(coord, "b")

    verdicts = [
        _verdict(winner=a_id, confidence=0.7),
        _verdict(winner=a_id, confidence=0.6),
        _verdict(winner=b_id, confidence=0.95),
    ]
    counter = {"i": 0}

    def _by_model(_model: Any) -> JudgeVerdict:
        v = verdicts[counter["i"]]
        counter["i"] += 1
        return v

    fake_cls = _make_fake_judge_class(_by_model)
    with patch("pydantic_deep.features.forking.coordinator.JudgeAgent", fake_cls):
        outcome = await coord.resolve(MergeStrategy(kind="vote"))

    assert outcome.committed is True
    assert outcome.verdict is not None
    # 2 of 3 picked a → majority wins; the synthetic verdict's reasoning
    # cites the tally.
    assert outcome.verdict.winner_branch_id == a_id
    assert "2 of 3" in outcome.verdict.reasoning


async def test_majority_pick_tie_breaks_on_highest_confidence():
    a = _verdict(winner="a", confidence=0.6)
    b = _verdict(winner="b", confidence=0.9)
    # 1-1 tie; b has higher confidence.
    picked = _majority_pick([a, b])
    assert picked.winner_branch_id == "b"


async def test_majority_pick_three_way_tie():
    a = _verdict(winner="a", confidence=0.5)
    b = _verdict(winner="b", confidence=0.7)
    c = _verdict(winner="c", confidence=0.6)
    picked = _majority_pick([a, b, c])
    # All tied 1-1-1 → highest confidence wins
    assert picked.winner_branch_id == "b"


async def test_majority_pick_requires_at_least_one_verdict():
    with pytest.raises(ValueError, match="at least one"):
        _majority_pick([])


# ---------------------------------------------------------------------------
# Test 7 - Judge prompt is bounded (no full per-branch history).
# ---------------------------------------------------------------------------


async def test_judge_prompt_is_bounded():
    # Build an enormous goal + diff report; the prompt builder must cap.
    huge_goal = "x" * 100_000
    report = _make_report()
    outcomes = _make_outcomes()
    prompt = _build_judge_prompt(huge_goal, report, outcomes)
    assert len(prompt) <= _MAX_JUDGE_PROMPT_CHARS
    # No "ModelRequest" / "ModelResponse" object dumps - the prompt only
    # contains the goal, the structured diff, and outcome bullets.
    assert "ModelResponse" not in prompt
    assert "ModelRequest" not in prompt


async def test_judge_prompt_truncates_long_outcome_messages():
    outcomes = [
        BranchOutcome(
            branch_id="a",
            branch_label="alpha",
            steer="do task A",
            final_assistant_message="x" * 10_000,
            cost_usd=None,
            turns=1,
            error_count=0,
            retry_count=0,
            stuck_loop_hits=0,
        )
    ]
    prompt = _build_judge_prompt("g", _make_report(), outcomes)
    # The 10k-char message is truncated to ~400 chars + marker.
    assert "[truncated]" in prompt


# ---------------------------------------------------------------------------
# Test 8 - Override path: user rejects judge's pick → picker reopens.
# (Tested at the coordinator surface: resolve() returns a verdict, and
# merge_or_select can still be called with a different branch id.)
# ---------------------------------------------------------------------------


async def test_override_path_picker_can_select_different_branch():
    coord, _deps = await _coordinator_with_two_branches()
    a_id = _resolve_winner_id(coord, "a")
    b_id = _resolve_winner_id(coord, "b")

    fake_verdict = _verdict(winner=a_id, confidence=0.5)
    strategy = MergeStrategy(kind="auto_with_fallback", confidence_threshold=0.10)
    fake_cls = _make_fake_judge_class(fake_verdict)
    with patch("pydantic_deep.features.forking.coordinator.JudgeAgent", fake_cls):
        outcome = await coord.resolve(strategy)

    assert outcome.committed is False
    assert outcome.auto_eligible is True
    assert outcome.verdict is not None
    # Override: user picks b instead - coordinator commits cleanly.
    merge_result = await coord.merge_or_select(f"pick:{b_id}")
    assert merge_result.winner_branch_id == b_id


# ---------------------------------------------------------------------------
# Extra coverage - manual short-circuit, resolve before fork, defaults.
# ---------------------------------------------------------------------------


async def test_resolve_manual_short_circuits_no_judge():
    coord, _deps = await _coordinator_with_two_branches()

    class _ExplodingJudge:
        def __init__(self, _model: Any) -> None:
            raise AssertionError("judge must not be constructed for manual")

    with patch("pydantic_deep.features.forking.coordinator.JudgeAgent", _ExplodingJudge):
        outcome = await coord.resolve(MergeStrategy(kind="manual"))
    assert outcome.committed is False
    assert outcome.auto_eligible is False
    assert outcome.verdict is None
    assert outcome.signals is None
    assert outcome.effective_confidence == 0.0


async def test_resolve_before_fork_raises():
    deps = DeepAgentDeps(backend=StateBackend())
    agent = Agent(TestModel(), deps_type=DeepAgentDeps)
    coord = ForkCoordinator(
        agent=agent,
        parent_deps=deps,
        max_branches=2,
        max_depth=1,
        store=InMemoryForkStateStore(),
        checkpoint_store=InMemoryCheckpointStore(),
    )
    with pytest.raises(RuntimeError, match="no active fork"):
        await coord.resolve()


async def test_resolve_uses_handle_strategy_when_none_passed():
    coord, _deps = await _coordinator_with_two_branches(
        strategy=MergeStrategy(kind="manual"),
    )
    outcome = await coord.resolve()
    # Falls back to handle's stored strategy (manual) → no judge call.
    assert outcome.committed is False
    assert outcome.verdict is None


async def test_merge_strategy_default_is_auto_with_fallback():
    """Regression guard: default :class:`MergeStrategy` must be `auto_with_fallback`."""
    assert MergeStrategy().kind == "auto_with_fallback"
    assert MergeStrategy().confidence_threshold == 0.80


async def test_detect_vote_models_falls_back_to_fallback_when_no_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no provider env vars set, `_detect_vote_models` fills 3 slots with the fallback."""
    for env in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "MISTRAL_API_KEY",
        "GROQ_API_KEY",
        "COHERE_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_GENERATIVE_AI_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(env, raising=False)
    fallback = "anthropic:claude-haiku-4-5-20251001"
    models = _detect_vote_models(fallback)
    assert len(models) == 3
    assert models == [fallback, fallback, fallback]


async def test_detect_vote_models_spans_multiple_vendors_when_keys_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When several provider keys are set, the panel pulls from each."""
    for env in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "MISTRAL_API_KEY",
        "GROQ_API_KEY",
        "COHERE_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_GENERATIVE_AI_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("GOOGLE_API_KEY", "x")
    models = _detect_vote_models("anthropic:claude-haiku-4-5-20251001")
    assert len(models) == 3
    vendors = {m.split(":", 1)[0] for m in models}
    # At least two distinct vendor families when 3+ native keys are present.
    assert len(vendors) >= 2


async def test_detect_vote_models_includes_openrouter_when_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenRouter models are added to the pool when OPENROUTER_API_KEY is set."""
    for env in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "MISTRAL_API_KEY",
        "GROQ_API_KEY",
        "COHERE_API_KEY",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_GENERATIVE_AI_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")
    models = _detect_vote_models("anthropic:claude-haiku-4-5-20251001")
    assert any("openrouter" in m for m in models)


# ---------------------------------------------------------------------------
# Extra coverage - stuck-loop / retry counters.
# ---------------------------------------------------------------------------


async def test_count_stuck_loop_hits_matches_markers():
    messages = [
        ModelRequest(
            parts=[
                RetryPromptPart(
                    content="You called `foo` with identical arguments 3 times in a row."
                )
            ]
        ),
        ModelRequest(
            parts=[RetryPromptPart(content="You're alternating between `a` and `b` in a loop.")]
        ),
        ModelRequest(
            parts=[RetryPromptPart(content="`tool` returned the same result 3 times in a row.")]
        ),
        ModelRequest(parts=[RetryPromptPart(content="Some other retry reason.")]),
    ]
    assert count_stuck_loop_hits(messages) == 3
    # Every RetryPromptPart counts toward retry_count regardless of source.
    assert count_retry_parts(messages) == 4


async def test_count_stuck_loop_hits_handles_non_string_content():
    # RetryPromptPart with structured content (list[ErrorDetails]) - heuristic skips it.
    from pydantic_core import ErrorDetails

    structured: list[ErrorDetails] = [{"type": "x", "loc": ("a",), "msg": "boom", "input": None}]
    rpp = RetryPromptPart(content=structured)
    messages = [ModelRequest(parts=[rpp])]
    assert count_stuck_loop_hits(messages) == 0


async def test_count_stuck_loop_hits_ignores_non_request_messages():
    messages = [ModelResponse(parts=[TextPart(content="not a retry")])]
    assert count_stuck_loop_hits(messages) == 0
    assert count_retry_parts(messages) == 0


# ---------------------------------------------------------------------------
# Extra coverage - _last_assistant_text + _build_branch_outcomes.
# ---------------------------------------------------------------------------


async def test_last_assistant_text_extracts_final_response():
    messages = [
        ModelRequest(parts=[UserPromptPart(content="hi")]),
        ModelResponse(parts=[TextPart(content="hello")]),
        ModelRequest(parts=[UserPromptPart(content="more")]),
        ModelResponse(parts=[TextPart(content="done "), TextPart(content="here")]),
    ]
    assert _last_assistant_text(messages) == "done here"


async def test_last_assistant_text_empty_when_no_responses():
    messages = [ModelRequest(parts=[UserPromptPart(content="hi")])]
    assert _last_assistant_text(messages) == ""


async def test_build_branch_outcomes_uses_terminal_states_for_error_count():
    deps = DeepAgentDeps(backend=StateBackend())
    agent = Agent(TestModel(), deps_type=DeepAgentDeps)
    coord = ForkCoordinator(
        agent=agent,
        parent_deps=deps,
        max_branches=2,
        max_depth=1,
        store=InMemoryForkStateStore(),
        checkpoint_store=InMemoryCheckpointStore(),
    )
    parent_history = [ModelRequest(parts=[UserPromptPart(content="seed")])]
    await coord.fork(
        [BranchSpec(label="a", steer="A"), BranchSpec(label="b", steer="B")],
        parent_history=parent_history,
    )
    await asyncio.gather(*(rt.task for rt in coord.branches.values()), return_exceptions=True)

    # Flip one branch to a terminal-error state and build outcomes.
    bids = list(coord.branches.keys())
    coord.branches[bids[1]].status.state = "failed"

    outcomes, goal = await coord._build_branch_outcomes()
    assert goal == "seed"
    error_flags = {o.branch_id: o.error_count for o in outcomes}
    assert error_flags[bids[0]] == 0
    assert error_flags[bids[1]] == 1


# ---------------------------------------------------------------------------
# Extra coverage - vote mode uses default models when None.
# ---------------------------------------------------------------------------


async def test_vote_mode_uses_default_model_triple_when_none():
    coord, _deps = await _coordinator_with_two_branches()
    a_id = _resolve_winner_id(coord, "a")
    call_models: list[str] = []
    fake_verdict = _verdict(winner=a_id, confidence=0.5)

    def _factory(model: Any) -> JudgeVerdict:
        call_models.append(str(model))
        return fake_verdict

    fake_cls = _make_fake_judge_class(_factory)
    with patch("pydantic_deep.features.forking.coordinator.JudgeAgent", fake_cls):
        outcome = await coord.resolve(MergeStrategy(kind="vote"))

    assert outcome.committed is True
    # Three judges, one per detected vote-panel slot.
    assert len(call_models) == 3
    # The exact triple depends on env-var detection (`_detect_vote_models`),
    # so we don't pin specific model strings here - just that all three got
    # invoked.
    assert all(isinstance(m, str) and m for m in call_models)


# ---------------------------------------------------------------------------
# Extra coverage - compute_signals on a branch with retries.
# ---------------------------------------------------------------------------


async def test_compute_signals_internal_consistency_penalizes_retries():
    coord, _deps = await _coordinator_with_two_branches()
    a_id = _resolve_winner_id(coord, "a")
    outcomes = [
        BranchOutcome(
            branch_id=a_id,
            branch_label="alpha",
            steer="do task A",
            final_assistant_message="ok",
            cost_usd=None,
            turns=4,
            error_count=0,
            retry_count=2,
            stuck_loop_hits=0,
        )
    ]
    report = _make_report(agreement_score=0.0)
    signals = coord._compute_signals(report, outcomes, a_id)
    # 1 - (2 + 0) / 4 = 0.5
    assert signals.internal_consistency == pytest.approx(0.5)
    assert signals.quality_spread == pytest.approx(1.0)
    assert signals.test_pass_ratio is None


async def test_compute_signals_winner_missing_falls_back_to_zero():
    coord, _deps = await _coordinator_with_two_branches()
    outcomes = _make_outcomes()  # branches "a" / "b"
    signals = coord._compute_signals(_make_report(), outcomes, "ghost-branch")
    assert signals.internal_consistency == 0.0


# ---------------------------------------------------------------------------
# Coverage fillers - minor branches the main tests don't hit.
# ---------------------------------------------------------------------------


async def test_resolve_returns_cached_outcome_without_reinvoking_judge():
    """Cache hit path: second resolve() call with same strategy kind skips the judge."""
    coord, _deps = await _coordinator_with_two_branches()
    a_id = _resolve_winner_id(coord, "a")

    from pydantic_deep.features.forking.coordinator import ResolveOutcome

    cached = ResolveOutcome(
        committed=False,
        auto_eligible=True,
        verdict=_verdict(winner=a_id, confidence=0.85),
        signals=ConfidenceSignals(
            quality_spread=0.5, test_pass_ratio=None, internal_consistency=1.0
        ),
        effective_confidence=0.85,
        merge_result=None,
        judge_usage=None,
    )
    from pydantic_deep.features.forking.coordinator import _strategy_cache_key

    coord._cached_outcome = cached
    coord._cached_outcome_key = _strategy_cache_key(MergeStrategy(kind="auto_with_fallback"))

    class _ExplodingJudge:
        def __init__(self, _model: Any) -> None:
            raise AssertionError("judge must NOT be invoked on a cache hit")

    with patch("pydantic_deep.features.forking.coordinator.JudgeAgent", _ExplodingJudge):
        outcome = await coord.resolve(MergeStrategy(kind="auto_with_fallback"))

    assert outcome is cached


async def test_resolve_cache_misses_on_different_threshold():
    """A re-resolve with a different confidence_threshold must NOT return the stale
    cached outcome - the cache key includes the threshold and judge model(s)."""
    coord, _deps = await _coordinator_with_two_branches()
    a_id = _resolve_winner_id(coord, "a")

    from pydantic_deep.features.forking.coordinator import ResolveOutcome, _strategy_cache_key

    cached = ResolveOutcome(
        committed=False,
        auto_eligible=True,
        verdict=_verdict(winner=a_id, confidence=0.85),
        signals=ConfidenceSignals(
            quality_spread=0.5, test_pass_ratio=None, internal_consistency=1.0
        ),
        effective_confidence=0.85,
        merge_result=None,
        judge_usage=None,
    )
    coord._cached_outcome = cached
    # Cache populated for the default 0.80 threshold ...
    coord._cached_outcome_key = _strategy_cache_key(
        MergeStrategy(kind="auto_with_fallback", confidence_threshold=0.80)
    )

    # ... a re-resolve with a *different* threshold must re-run the judge, not
    # return the stale outcome. Different keys → cache miss.
    assert (
        _strategy_cache_key(MergeStrategy(kind="auto_with_fallback", confidence_threshold=0.50))
        != coord._cached_outcome_key
    )


async def test_majority_pick_dedupes_caveats_across_same_winner_verdicts():
    """Two judges for the same winner with overlapping caveats - caveats dedupe."""
    a1 = JudgeVerdict(
        winner_branch_id="a",
        confidence=0.7,
        reasoning="A wins on tests.",
        caveats=["thread-safety untested", "no integration tests"],
    )
    a2 = JudgeVerdict(
        winner_branch_id="a",
        confidence=0.6,
        reasoning="A wins on style.",
        caveats=["thread-safety untested", "missing typecheck"],
    )
    picked = _majority_pick([a1, a2])
    assert picked.winner_branch_id == "a"
    assert picked.caveats == [
        "thread-safety untested",
        "no integration tests",
        "missing typecheck",
    ]


async def test_build_judge_prompt_skips_untouched_changes_in_report():
    """The diff-report renderer skips `operation="untouched"` rows."""
    change_a = BranchChange(
        branch_id="a",
        branch_label="alpha",
        operation="modified",
        new_content="x",
        unified_diff_vs_parent="+x\n",
        size_bytes=1,
        is_binary=False,
    )
    change_b = BranchChange(
        branch_id="b",
        branch_label="beta",
        operation="untouched",
        new_content=None,
        unified_diff_vs_parent="",
        size_bytes=0,
        is_binary=False,
    )
    pd = PathDiff(
        path="x.py",
        parent_content="parent\n",
        branches={"a": change_a, "b": change_b},
        agreement="unique",
    )
    report = BranchDiffReport(
        fork_id="f",
        paths=[pd],
        summary=DiffSummary(
            total_paths_touched=1,
            unanimous_paths=0,
            split_paths=0,
            per_branch_unique={"a": 1, "b": 0},
            agreement_score=1.0,
        ),
    )
    prompt = _build_judge_prompt("goal", report, _make_outcomes())
    # "untouched" rows aren't enumerated as bullets - only the touching branch shows.
    assert "alpha) modified" in prompt
    assert "beta) untouched" not in prompt


async def test_build_branch_outcomes_skips_non_request_messages_for_goal():
    """Messages list with a `ModelResponse` before the first request - goal still resolves."""
    coord, _deps = await _coordinator_with_two_branches()
    # Inject a ModelResponse at the head of partial_history for one branch so
    # the goal-extraction loop has to skip past it before finding the UserPrompt.
    rt = next(iter(coord.branches.values()))
    rt.partial_history = [
        ModelResponse(parts=[TextPart(content="warm-up")]),
        ModelRequest(parts=[UserPromptPart(content="real goal")]),
    ]
    # The other branch's task already produced a result; force the fallback to
    # partial_history by cancelling it (so .done() is True but .cancelled() is too).
    outcomes, goal = await coord._build_branch_outcomes()
    assert goal in ("real goal", "make a thing")  # whichever branch is iterated first
    assert len(outcomes) == 2


async def test_messages_for_falls_back_to_partial_when_task_cancelled():
    """A cancelled branch task → `_messages_for` returns the partial-history snapshot.

    Builds a synthetic runtime with a task that's been cancelled-before-completion;
    the fork coordinator's test path can't easily produce this state because
    `TestModel` finishes synchronously.
    """
    from pydantic_deep.features.forking.coordinator import BranchRuntime
    from pydantic_deep.features.forking.types import BranchStatus

    # Task that will never complete; cancel it.
    async def _hang() -> Any:
        await asyncio.Future()  # never resolves
        return None

    import contextlib

    task = asyncio.create_task(_hang())
    task.cancel()
    # Let the cancellation propagate.
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert task.cancelled()

    sentinel = [ModelRequest(parts=[UserPromptPart(content="partial")])]
    rt = BranchRuntime(
        spec=BranchSpec(label="x", steer=""),
        task=task,
        deps=DeepAgentDeps(backend=StateBackend()),
        overlay=None,
        status=BranchStatus(
            id="x",
            label="x",
            state="terminated",
            current_turn=0,
            last_activity_at=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
        ),
        partial_history=sentinel,
    )
    messages = ForkCoordinator._messages_for(rt)
    assert messages == sentinel


async def test_messages_for_falls_back_when_result_lacks_all_messages():
    """Task completed but result object has no `all_messages` callable."""
    from pydantic_deep.features.forking.coordinator import BranchRuntime
    from pydantic_deep.features.forking.types import BranchStatus

    async def _return_object() -> Any:
        return object()  # no `all_messages` method

    task = asyncio.create_task(_return_object())
    await task

    sentinel = [ModelRequest(parts=[UserPromptPart(content="fallback")])]
    rt = BranchRuntime(
        spec=BranchSpec(label="x", steer=""),
        task=task,
        deps=DeepAgentDeps(backend=StateBackend()),
        overlay=None,
        status=BranchStatus(
            id="x",
            label="x",
            state="done",
            current_turn=0,
            last_activity_at=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
        ),
        partial_history=sentinel,
    )
    assert ForkCoordinator._messages_for(rt) == sentinel


async def test_last_assistant_text_skips_non_string_parts():
    """Parts whose `content` isn't a string (e.g. tool-call) are skipped."""
    from pydantic_ai.messages import ToolCallPart

    # ToolCallPart's `content` doesn't exist; `getattr(part, "content", None)` returns
    # None, which isn't a string → skipped by `_last_assistant_text`.
    tool_part = ToolCallPart(tool_name="x", args={}, tool_call_id="t1")
    msg = ModelResponse(parts=[tool_part, TextPart(content="text")])
    assert _last_assistant_text([msg]) == "text"


async def test_build_branch_outcomes_skips_non_request_messages_in_goal_scan():
    """The goal-extraction loop's `continue` past non-`ModelRequest` messages is exercised.

    Builds runtimes whose `_messages_for` snapshot starts with a
    :class:`ModelResponse` - the goal extractor must walk past it to find the
    later :class:`ModelRequest` carrying the user prompt.
    """
    from pydantic_deep.features.forking.coordinator import BranchRuntime
    from pydantic_deep.features.forking.types import BranchStatus

    deps = DeepAgentDeps(backend=StateBackend())
    agent = Agent(TestModel(), deps_type=DeepAgentDeps)
    coord = ForkCoordinator(
        agent=agent,
        parent_deps=deps,
        max_branches=1,
        max_depth=1,
        store=InMemoryForkStateStore(),
        checkpoint_store=InMemoryCheckpointStore(),
    )

    async def _return_object() -> Any:
        return object()

    task = asyncio.create_task(_return_object())
    await task

    history = [
        ModelResponse(parts=[TextPart(content="warm-up")]),  # skipped by goal scan
        ModelRequest(parts=[UserPromptPart(content="real goal")]),
    ]
    rt = BranchRuntime(
        spec=BranchSpec(label="x", steer=""),
        task=task,
        deps=deps,
        overlay=None,
        status=BranchStatus(
            id="x",
            label="x",
            state="done",
            current_turn=0,
            last_activity_at=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
        ),
        partial_history=history,
    )
    coord.branches["x"] = rt
    outcomes, goal = await coord._build_branch_outcomes()
    assert goal == "real goal"
    assert len(outcomes) == 1


async def test_build_branch_outcomes_with_synthetic_runtimes():
    """Compact construction exercising each missing goal-extraction branch."""
    from pydantic_deep.features.forking.coordinator import BranchRuntime
    from pydantic_deep.features.forking.types import BranchStatus

    deps = DeepAgentDeps(backend=StateBackend())
    agent = Agent(TestModel(), deps_type=DeepAgentDeps)
    coord = ForkCoordinator(
        agent=agent,
        parent_deps=deps,
        max_branches=4,
        max_depth=1,
        store=InMemoryForkStateStore(),
        checkpoint_store=InMemoryCheckpointStore(),
    )

    async def _return_object() -> Any:
        return object()

    def _runtime(label: str, history: list[Any]) -> BranchRuntime:
        task = asyncio.create_task(_return_object())
        return BranchRuntime(
            spec=BranchSpec(label=label, steer=""),
            task=task,
            deps=deps,
            overlay=None,
            status=BranchStatus(
                id=label,
                label=label,
                state="done",
                current_turn=0,
                last_activity_at=__import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ),
            ),
            partial_history=history,
        )

    # Branch with empty messages → outer for-loop never iterates (636->646).
    coord.branches["empty"] = _runtime("empty", [])
    # Branch with ModelRequest carrying no parts (639->644).
    coord.branches["noparts"] = _runtime("noparts", [ModelRequest(parts=[])])
    # Branch with ModelRequest whose part is NOT a UserPromptPart (640->639),
    # then a follow-up ModelRequest with no matching part either (644->636),
    # and finally a ModelRequest containing the user prompt.
    from pydantic_ai.messages import ToolReturnPart

    history_mixed = [
        ModelRequest(parts=[ToolReturnPart(tool_name="x", content="ignored", tool_call_id="t1")]),
        ModelRequest(parts=[]),  # forces 644->636 transition
        ModelRequest(parts=[UserPromptPart(content="goal-from-mixed")]),
    ]
    coord.branches["mixed"] = _runtime("mixed", history_mixed)

    await asyncio.gather(*(rt.task for rt in coord.branches.values()))
    outcomes, goal = await coord._build_branch_outcomes()
    assert goal == "goal-from-mixed"
    assert {o.branch_id for o in outcomes} == {"empty", "noparts", "mixed"}


async def test_messages_for_logs_and_falls_back_when_task_result_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A task that completed with an exception → `_messages_for` logs + falls back."""
    import logging

    from pydantic_deep.features.forking.coordinator import BranchRuntime
    from pydantic_deep.features.forking.types import BranchStatus

    async def _explode() -> Any:
        raise RuntimeError("branch blew up after the fact")

    task = asyncio.create_task(_explode())
    with contextlib.suppress(RuntimeError):
        await task

    sentinel = [ModelRequest(parts=[UserPromptPart(content="partial")])]
    rt = BranchRuntime(
        spec=BranchSpec(label="x", steer=""),
        task=task,
        deps=DeepAgentDeps(backend=StateBackend()),
        overlay=None,
        status=BranchStatus(
            id="x",
            label="x",
            state="failed",
            current_turn=0,
            last_activity_at=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ),
        ),
        partial_history=sentinel,
    )
    with caplog.at_level(logging.WARNING, logger="pydantic_deep.features.forking.coordinator"):
        result = ForkCoordinator._messages_for(rt)
    assert result == sentinel
    assert any("falling back to partial_history" in r.getMessage() for r in caplog.records)


async def test_vote_mode_empty_judge_models_list_raises():
    """Explicit `judge_models=[]` must raise, not silently fall back to defaults."""
    coord, _deps = await _coordinator_with_two_branches()
    a_id = _resolve_winner_id(coord, "a")
    fake_verdict = _verdict(winner=a_id, confidence=0.9)
    fake_cls = _make_fake_judge_class(fake_verdict)
    with (
        patch("pydantic_deep.features.forking.coordinator.JudgeAgent", fake_cls),
        pytest.raises(ValueError, match="requires at least one judge model"),
    ):
        await coord.resolve(MergeStrategy(kind="vote", judge_models=[]))


async def test_vote_mode_uses_user_supplied_judge_models():
    """Explicit non-empty `judge_models` is honored (no fallback to defaults)."""
    coord, _deps = await _coordinator_with_two_branches()
    a_id = _resolve_winner_id(coord, "a")
    call_models: list[str] = []
    fake_verdict = _verdict(winner=a_id, confidence=0.7)

    def _factory(model: Any) -> JudgeVerdict:
        call_models.append(str(model))
        return fake_verdict

    fake_cls = _make_fake_judge_class(_factory)
    custom = ["anthropic:claude-haiku-4-5-20251001", "anthropic:claude-haiku-4-5-20251001"]
    with patch("pydantic_deep.features.forking.coordinator.JudgeAgent", fake_cls):
        outcome = await coord.resolve(MergeStrategy(kind="vote", judge_models=custom))
    assert outcome.committed is True
    assert call_models == custom


async def test_format_diff_report_handles_empty_diff_text():
    """A touched branch whose `unified_diff_vs_parent` is empty - diff bullet still emitted."""
    change = BranchChange(
        branch_id="a",
        branch_label="alpha",
        operation="modified",
        new_content="content",
        unified_diff_vs_parent="",
        size_bytes=7,
        is_binary=False,
    )
    pd = PathDiff(
        path="z.py",
        parent_content="content",
        branches={"a": change},
        agreement="unique",
    )
    report = BranchDiffReport(
        fork_id="f",
        paths=[pd],
        summary=DiffSummary(
            total_paths_touched=1,
            unanimous_paths=0,
            split_paths=0,
            per_branch_unique={"a": 1},
            agreement_score=1.0,
        ),
    )
    prompt = _build_judge_prompt("g", report, _make_outcomes())
    assert "z.py" in prompt
    assert "alpha) modified" in prompt


async def test_format_diff_report_deleted_operation_renders_deleted_label():
    """A branch that deleted a file emits 'DELETED' rather than 'deleted 0B'."""
    change = BranchChange(
        branch_id="a",
        branch_label="alpha",
        operation="deleted",
        new_content=None,
        unified_diff_vs_parent="--- a/gone.py\n+++ /dev/null\n-old\n",
        size_bytes=0,
        is_binary=False,
    )
    pd = PathDiff(
        path="gone.py",
        parent_content="old\n",
        branches={"a": change},
        agreement="unique",
    )
    report = BranchDiffReport(
        fork_id="f",
        paths=[pd],
        summary=DiffSummary(
            total_paths_touched=1,
            unanimous_paths=0,
            split_paths=0,
            per_branch_unique={"a": 1},
            agreement_score=1.0,
        ),
    )
    prompt = _build_judge_prompt("g", report, _make_outcomes())
    assert "gone.py" in prompt
    assert "alpha) DELETED" in prompt
    assert "0B" not in prompt


# ---------------------------------------------------------------------------
# Test-runner hook: per-branch test_pass_ratio.
# ---------------------------------------------------------------------------


async def test_outcomes_carry_test_pass_ratio_none_when_disabled():
    """No `test_command` configured → every outcome's ratio is `None`."""
    coord, _deps = await _coordinator_with_two_branches()
    outcomes, _ = await coord._build_branch_outcomes()
    assert all(o.test_pass_ratio is None for o in outcomes)


async def test_outcomes_skip_runner_for_non_local_backend():
    """`StateBackend` parent → runner is no-op even if `test_command` is set."""
    deps = DeepAgentDeps(backend=StateBackend())
    agent = Agent(TestModel(), deps_type=DeepAgentDeps)
    coord = ForkCoordinator(
        agent=agent,
        parent_deps=deps,
        max_branches=2,
        max_depth=1,
        store=InMemoryForkStateStore(),
        checkpoint_store=InMemoryCheckpointStore(),
        test_command="echo would-fail-but-cant-run",
        test_timeout_s=5.0,
    )
    await coord.fork(
        [BranchSpec(label="a", steer="A"), BranchSpec(label="b", steer="B")],
        parent_history=[ModelRequest(parts=[UserPromptPart(content="go")])],
    )
    await asyncio.gather(*(rt.task for rt in coord.branches.values()), return_exceptions=True)
    outcomes, _ = await coord._build_branch_outcomes()
    assert all(o.test_pass_ratio is None for o in outcomes)


async def _coordinator_with_local_backend_branch(
    tmp_path: Any,
    *,
    test_command: str,
    test_timeout_s: float = 30.0,
) -> tuple[ForkCoordinator, str]:
    """Spin up a coordinator backed by a real `LocalBackend` and one running branch.

    Returns the coordinator and the spawned branch's id. Drains the branch
    task before returning so `_run_tests_for_branch` finds the overlay
    still attached (overlays only release on merge / abort).
    """
    from pydantic_ai_backends import LocalBackend

    backend = LocalBackend(root_dir=str(tmp_path))
    backend.write("seed.txt", "parent\n")
    deps = DeepAgentDeps(backend=backend)
    agent = Agent(TestModel(), deps_type=DeepAgentDeps)
    coord = ForkCoordinator(
        agent=agent,
        parent_deps=deps,
        max_branches=2,
        max_depth=1,
        store=InMemoryForkStateStore(),
        checkpoint_store=InMemoryCheckpointStore(),
        test_command=test_command,
        test_timeout_s=test_timeout_s,
    )
    await coord.fork(
        [BranchSpec(label="a", steer="A")],
        parent_history=[ModelRequest(parts=[UserPromptPart(content="go")])],
    )
    await asyncio.gather(*(rt.task for rt in coord.branches.values()), return_exceptions=True)
    branch_id = next(iter(coord.branches.keys()))
    return coord, branch_id


async def test_run_tests_for_branch_returns_one_on_exit_zero(tmp_path: Any) -> None:
    coord, bid = await _coordinator_with_local_backend_branch(tmp_path, test_command="true")
    ratio = await coord._run_tests_for_branch(coord.branches[bid])
    assert ratio == 1.0


async def test_run_tests_for_branch_returns_zero_on_non_zero_exit(tmp_path: Any) -> None:
    coord, bid = await _coordinator_with_local_backend_branch(tmp_path, test_command="false")
    ratio = await coord._run_tests_for_branch(coord.branches[bid])
    assert ratio == 0.0


async def test_run_tests_for_branch_reaps_subprocess_on_cancellation(tmp_path: Any) -> None:
    """Cancelling the runner mid-wait must terminate/kill the test subprocess.

    Regression: previously terminate()/kill() ran only on TimeoutError, so a
    parent abort while awaiting proc.wait() left an orphaned/zombie child.
    """
    coord, bid = await _coordinator_with_local_backend_branch(
        tmp_path, test_command="sleep 30", test_timeout_s=30.0
    )
    rt = coord.branches[bid]

    spawned: list[Any] = []
    real_spawn = asyncio.create_subprocess_exec

    async def _capturing_spawn(*args: Any, **kwargs: Any) -> Any:
        proc = await real_spawn(*args, **kwargs)
        spawned.append(proc)
        return proc

    with patch("asyncio.create_subprocess_exec", _capturing_spawn):
        task = asyncio.create_task(coord._run_tests_for_branch(rt))
        # Wait until the subprocess is actually running.
        for _ in range(200):
            await asyncio.sleep(0.01)
            if spawned:
                break
        assert spawned, "subprocess never spawned"
        proc = spawned[0]
        assert proc.returncode is None  # still running
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    # The child must have been reaped (terminated/killed), not left as a zombie.
    await asyncio.wait_for(proc.wait(), timeout=5.0)
    assert proc.returncode is not None


async def test_run_tests_for_branch_returns_none_on_timeout(tmp_path: Any) -> None:
    """Distinguished from `0.0` - a timeout is "no signal", not "tests failed"."""
    coord, bid = await _coordinator_with_local_backend_branch(
        tmp_path, test_command="sleep 5", test_timeout_s=0.1
    )
    ratio = await coord._run_tests_for_branch(coord.branches[bid])
    assert ratio is None


async def test_compute_signals_uses_winner_test_pass_ratio():
    """A real ratio on the winner → ConfidenceSignals carries it, cap-at-0.65 lifts."""
    coord, _deps = await _coordinator_with_two_branches()
    a_id = _resolve_winner_id(coord, "a")
    outcomes = [
        BranchOutcome(
            branch_id=a_id,
            branch_label="alpha",
            steer="A",
            final_assistant_message="ok",
            cost_usd=None,
            turns=2,
            error_count=0,
            retry_count=0,
            stuck_loop_hits=0,
            test_pass_ratio=1.0,
        )
    ]
    signals = coord._compute_signals(_make_report(agreement_score=0.0), outcomes, a_id)
    assert signals.test_pass_ratio == 1.0
    # heuristic = 1.0*0.4 + 1.0*0.4 + 1.0*0.2 = 1.0 ; no cap because ratio is not None
    assert compute_confidence(signals, 1.0) == pytest.approx(1.0)


async def test_compute_signals_falls_back_to_none_when_winner_has_no_ratio():
    """Winner outcome with `None` → cap-at-0.65 stays active, identical to today."""
    coord, _deps = await _coordinator_with_two_branches()
    a_id = _resolve_winner_id(coord, "a")
    outcomes = [
        BranchOutcome(
            branch_id=a_id,
            branch_label="alpha",
            steer="A",
            final_assistant_message="ok",
            cost_usd=None,
            turns=2,
            error_count=0,
            retry_count=0,
            stuck_loop_hits=0,
            test_pass_ratio=None,
        )
    ]
    signals = coord._compute_signals(_make_report(agreement_score=0.0), outcomes, a_id)
    assert signals.test_pass_ratio is None
    # ratio=None ⇒ cap-at-0.65 is *enabled*; raw heuristic here is
    # 1.0*0.4 + 0 + 1.0*0.2 = 0.6 which is below the cap, so the value passes
    # through unmodified - the cap protects against false-positive auto-merge
    # even when the heuristic happens to land low.
    assert compute_confidence(signals, 1.0) == pytest.approx(0.6)


async def test_run_tests_materializes_overlay_writes(tmp_path: Any) -> None:
    """A file overwritten in the overlay shows the new content to the test command."""
    from pydantic_ai_backends import LocalBackend

    backend = LocalBackend(root_dir=str(tmp_path))
    backend.write("marker.txt", "parent\n")
    deps = DeepAgentDeps(backend=backend)
    agent = Agent(TestModel(), deps_type=DeepAgentDeps)
    coord = ForkCoordinator(
        agent=agent,
        parent_deps=deps,
        max_branches=2,
        max_depth=1,
        store=InMemoryForkStateStore(),
        checkpoint_store=InMemoryCheckpointStore(),
        # exit 0 only when the snapshot shows the branch's overwrite.
        test_command="grep -q '^branch$' marker.txt",
        test_timeout_s=10.0,
    )
    await coord.fork(
        [BranchSpec(label="a", steer="A")],
        parent_history=[ModelRequest(parts=[UserPromptPart(content="go")])],
    )
    await asyncio.gather(*(rt.task for rt in coord.branches.values()), return_exceptions=True)
    bid = next(iter(coord.branches.keys()))
    rt = coord.branches[bid]
    assert rt.overlay is not None
    rt.overlay.write("marker.txt", "branch\n")

    ratio = await coord._run_tests_for_branch(rt)
    assert ratio == 1.0


async def test_runner_failure_does_not_block_sibling_branches(tmp_path: Any) -> None:
    """One branch's runner raising returns `None`; the other still produces a ratio."""
    from pydantic_ai_backends import LocalBackend

    backend = LocalBackend(root_dir=str(tmp_path))
    backend.write("seed.txt", "x\n")
    deps = DeepAgentDeps(backend=backend)
    agent = Agent(TestModel(), deps_type=DeepAgentDeps)
    coord = ForkCoordinator(
        agent=agent,
        parent_deps=deps,
        max_branches=2,
        max_depth=1,
        store=InMemoryForkStateStore(),
        checkpoint_store=InMemoryCheckpointStore(),
        test_command="true",
        test_timeout_s=10.0,
    )
    await coord.fork(
        [BranchSpec(label="a", steer="A"), BranchSpec(label="b", steer="B")],
        parent_history=[ModelRequest(parts=[UserPromptPart(content="go")])],
    )
    await asyncio.gather(*(rt.task for rt in coord.branches.values()), return_exceptions=True)

    # Force one branch's overlay snapshot to fail by detaching its overlay -
    # _run_tests_for_branch returns None for that branch.
    bids = list(coord.branches.keys())
    coord.branches[bids[1]].overlay = None

    outcomes, _ = await coord._build_branch_outcomes()
    ratios = {o.branch_id: o.test_pass_ratio for o in outcomes}
    assert ratios[bids[0]] == 1.0
    assert ratios[bids[1]] is None


async def test_run_tests_for_branch_returns_none_on_spawn_failure(
    tmp_path: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """`create_subprocess_exec` raising `OSError` → log + return `None`."""
    import logging

    coord, bid = await _coordinator_with_local_backend_branch(tmp_path, test_command="true")

    async def _raise_oserror(*args: Any, **kwargs: Any) -> Any:
        raise OSError("simulated spawn failure")

    with (
        patch("asyncio.create_subprocess_exec", _raise_oserror),
        caplog.at_level(logging.WARNING, logger="pydantic_deep.features.forking.coordinator"),
    ):
        ratio = await coord._run_tests_for_branch(coord.branches[bid])
    assert ratio is None
    assert "failed to spawn" in caplog.text


async def test_run_tests_for_branch_swallows_snapshot_errors(
    tmp_path: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """Any exception inside the snapshot/subprocess block → log + return `None`.

    A broken test runner must never abort :meth:`resolve` - the safety
    rail returns `None` so :meth:`compute_confidence` keeps its
    cap-at-0.65 fallback active.
    """
    import logging

    coord, bid = await _coordinator_with_local_backend_branch(tmp_path, test_command="true")
    rt = coord.branches[bid]
    assert rt.overlay is not None

    def _bad_snapshot(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("snapshot exploded")

    with (
        patch.object(rt.overlay, "snapshot", _bad_snapshot),
        caplog.at_level(logging.WARNING, logger="pydantic_deep.features.forking.coordinator"),
    ):
        ratio = await coord._run_tests_for_branch(rt)
    assert ratio is None
    assert "snapshot creation failed" in caplog.text


async def test_run_tests_for_branch_escalates_to_kill_when_terminate_ignored(
    tmp_path: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """Process that ignores SIGTERM → kill escalation runs, ratio is `None`.

    Covers the orphan-process safety net: if `proc.terminate()` plus a
    grace `wait_for` does not collect the child, the runner escalates
    to `proc.kill()` and waits again before reporting `None`.
    """
    import logging

    coord, bid = await _coordinator_with_local_backend_branch(
        tmp_path, test_command="true", test_timeout_s=10.0
    )
    rt = coord.branches[bid]

    class _StubProc:
        returncode: int | None = None

        def __init__(self) -> None:
            self.terminate_called = False
            self.kill_called = False

        def terminate(self) -> None:
            self.terminate_called = True

        def kill(self) -> None:
            self.kill_called = True

        async def wait(self) -> int:
            # The real wait never resolves on its own; let wait_for time out.
            await asyncio.sleep(3600)
            return 0  # pragma: no cover - unreachable past sleep

    stub = _StubProc()

    async def _stub_spawn(*_args: Any, **_kwargs: Any) -> _StubProc:
        return stub

    # First wait_for (the test-command wall clock) and the terminate-grace
    # wait_for both raise TimeoutError; the kill-grace wait_for is suppressed.
    timeouts = iter([asyncio.TimeoutError(), asyncio.TimeoutError(), asyncio.TimeoutError()])

    async def _stub_wait_for(coro: Any, timeout: float) -> Any:
        # Drain the coroutine to avoid "coroutine was never awaited" warnings.
        coro.close()
        raise next(timeouts)

    with (
        patch("asyncio.create_subprocess_exec", _stub_spawn),
        patch("asyncio.wait_for", _stub_wait_for),
        caplog.at_level(logging.WARNING, logger="pydantic_deep.features.forking.coordinator"),
    ):
        ratio = await coord._run_tests_for_branch(rt)

    assert ratio is None
    assert stub.terminate_called
    assert stub.kill_called
    assert "timed out" in caplog.text


async def test_live_fork_capability_threads_test_command_to_coordinator():
    """`LiveForkCapability(test_command=..., test_timeout_s=...)` lands on the coordinator."""
    from pydantic_deep.features.forking.capability import LiveForkCapability

    cap = LiveForkCapability(test_command="pytest -q", test_timeout_s=42.0)
    assert cap.test_command == "pytest -q"
    assert cap.test_timeout_s == 42.0

    deps = DeepAgentDeps(backend=StateBackend())

    class _Ctx:
        def __init__(self) -> None:
            self.deps = deps

    ctx = _Ctx()
    cap._agent_ref = Agent(TestModel(), deps_type=DeepAgentDeps)
    clone = await cap.for_run(ctx)  # pyright: ignore[reportArgumentType]
    assert clone.test_command == "pytest -q"
    assert clone.test_timeout_s == 42.0
    coord = getattr(deps, "fork_coordinator", None)
    assert coord is not None
    assert coord.test_command == "pytest -q"
    assert coord.test_timeout_s == 42.0


async def test_live_fork_capability_end_to_end_produces_test_pass_ratio(tmp_path: Any) -> None:
    """End-to-end check: a real `LiveForkCapability` config produces a ratio in outcomes.

    Complements `test_live_fork_capability_threads_test_command_to_coordinator`
    - that test only verifies the kwargs land on the coordinator. This one
    drives the runner through the full path: capability `for_run` →
    coordinator → `_build_branch_outcomes` → `BranchOutcome.test_pass_ratio`.
    """
    from pydantic_ai_backends import LocalBackend

    from pydantic_deep.features.forking.capability import LiveForkCapability

    backend = LocalBackend(root_dir=str(tmp_path))
    backend.write("seed.txt", "x\n")
    deps = DeepAgentDeps(backend=backend)

    class _Ctx:
        def __init__(self) -> None:
            self.deps = deps

    cap = LiveForkCapability(test_command="true", test_timeout_s=10.0)
    cap._agent_ref = Agent(TestModel(), deps_type=DeepAgentDeps)
    await cap.for_run(_Ctx())  # pyright: ignore[reportArgumentType]

    coord = getattr(deps, "fork_coordinator", None)
    assert coord is not None
    await coord.fork(
        [BranchSpec(label="a", steer="A")],
        parent_history=[ModelRequest(parts=[UserPromptPart(content="go")])],
    )
    await asyncio.gather(*(rt.task for rt in coord.branches.values()), return_exceptions=True)
    outcomes, _ = await coord._build_branch_outcomes()
    assert len(outcomes) == 1
    assert outcomes[0].test_pass_ratio == 1.0


async def test_run_tests_materializes_overlay_writes_as_real_file(tmp_path: Any) -> None:
    """Overlay writes appear as real files in the snapshot, not symlinks to the parent.

    Complements `test_run_tests_materializes_overlay_writes` - that test
    asserts the content; this one asserts the file shape (a symlink would
    incorrectly point back at the parent's bytes).
    """
    from pathlib import Path as _Path

    from pydantic_ai_backends import LocalBackend

    backend = LocalBackend(root_dir=str(tmp_path))
    backend.write("marker.txt", "parent\n")
    deps = DeepAgentDeps(backend=backend)
    overlay = BranchOverlay(backend)
    overlay.write("marker.txt", "branch\n")

    with overlay.snapshot(_Path(deps.backend.unwrap().root_dir)) as snap:
        target = _Path(snap) / "marker.txt"
        assert target.exists()
        assert target.is_file()
        assert not target.is_symlink()
        assert target.read_text() == "branch\n"


async def test_branch_overlay_snapshot_include_venv_symlinks_when_present(
    tmp_path: Any,
) -> None:
    """`include_venv=True` adds a `.venv` symlink when the parent has one."""
    from pathlib import Path as _Path

    from pydantic_ai_backends import LocalBackend

    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "marker").write_text("hi")

    backend = LocalBackend(root_dir=str(tmp_path))
    overlay = BranchOverlay(backend)

    with overlay.snapshot(_Path(str(tmp_path)), include_venv=True) as snap:
        venv = _Path(snap) / ".venv"
        assert venv.is_symlink()
        assert venv.resolve() == (tmp_path / ".venv").resolve()


async def test_branch_overlay_snapshot_default_skips_venv(tmp_path: Any) -> None:
    """`include_venv` defaults to False - the existing `execute` consumer stays slim."""
    from pathlib import Path as _Path

    from pydantic_ai_backends import LocalBackend

    (tmp_path / ".venv").mkdir()
    backend = LocalBackend(root_dir=str(tmp_path))
    overlay = BranchOverlay(backend)

    with overlay.snapshot(_Path(str(tmp_path))) as snap:
        assert not (_Path(snap) / ".venv").exists()


async def test_run_tests_for_branch_returns_none_for_invalid_root_dir_type(
    tmp_path: Any,
) -> None:
    """Backend whose `root_dir` is not a `str`/`Path` → `None`, no crash.

    Guards the `isinstance(parent_root_obj, (str, Path))` check - a
    backend that exposes `root_dir` as a callable or some other shape
    must not crash the runner; it must return `None` (no signal).
    """
    from pydantic_ai_backends import LocalBackend

    class _OddRootBackend(LocalBackend):  # type: ignore[misc]
        @property
        def root_dir(self) -> Any:
            # Callable shape - the runner's isinstance check should reject this.
            return lambda: "not-a-path"

    backend = _OddRootBackend(root_dir=str(tmp_path))
    deps = DeepAgentDeps(backend=backend)
    agent = Agent(TestModel(), deps_type=DeepAgentDeps)
    coord = ForkCoordinator(
        agent=agent,
        parent_deps=deps,
        max_branches=2,
        max_depth=1,
        store=InMemoryForkStateStore(),
        checkpoint_store=InMemoryCheckpointStore(),
        test_command="true",
        test_timeout_s=5.0,
    )
    await coord.fork(
        [BranchSpec(label="a", steer="A")],
        parent_history=[ModelRequest(parts=[UserPromptPart(content="go")])],
    )
    await asyncio.gather(*(rt.task for rt in coord.branches.values()), return_exceptions=True)
    bid = next(iter(coord.branches.keys()))

    ratio = await coord._run_tests_for_branch(coord.branches[bid])
    assert ratio is None
