"""TUI tests for the acceptance widget and picker preselect (issue #107).

Covers test cases 9–11 from the issue's Test plan:

9.  :class:`MergeAcceptanceWidget` renders verdict reasoning + caveats correctly.
10. `[d]` opens the diff explorer; returning preserves the verdict context.
11. `[o]` opens the manual picker with the judge's choice preselected.

The :class:`MergeAcceptanceWidget` is exercised directly via Textual's
`run_test` `Pilot`; the dispatcher round-trip for tests 10/11 is verified
against the public action contract (the widget dismisses with a sentinel
string the dispatcher routes on).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.css.query import NoMatches
from textual.widgets import Static

from apps.cli.modals.merge_picker import MergePickerModal
from apps.cli.widgets.merge_acceptance import MergeAcceptanceWidget
from pydantic_deep.features.forking.types import (
    BranchChange,
    BranchDiffReport,
    BranchStatus,
    DiffSummary,
    JudgeVerdict,
    PathDiff,
)

# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------


def _make_verdict(
    *,
    winner: str = "approach_b",
    reasoning: str = "B is smallest (8 vs 12/9 lines), explicit factory, cleanest signature.",
    caveats: list[str] | None = None,
    followup: str | None = "merge B + take thread-safety idea from A.",
) -> JudgeVerdict:
    return JudgeVerdict(
        winner_branch_id=winner,
        confidence=0.87,
        reasoning=reasoning,
        rejected_with_reasons={
            "approach_a": "non-atomic singleton check",
            "approach_c": "module-level mutable state",
        },
        caveats=caveats if caveats is not None else ["No thread-safety stress test was run."],
        recommended_followup=followup,
    )


def _make_report() -> BranchDiffReport:
    """Build a minimal :class:`BranchDiffReport` with two touched branches."""
    change_a = BranchChange(
        branch_id="a-id",
        branch_label="approach_a",
        operation="created",
        new_content="a",
        unified_diff_vs_parent="+a\n",
        size_bytes=1,
        is_binary=False,
    )
    change_b = BranchChange(
        branch_id="b-id",
        branch_label="approach_b",
        operation="created",
        new_content="b",
        unified_diff_vs_parent="+b\n",
        size_bytes=1,
        is_binary=False,
    )
    pd = PathDiff(
        path="thing.py",
        parent_content=None,
        branches={"a-id": change_a, "b-id": change_b},
        agreement="split",
    )
    summary = DiffSummary(
        total_paths_touched=1,
        unanimous_paths=0,
        split_paths=1,
        per_branch_unique={"a-id": 0, "b-id": 0},
        agreement_score=0.0,
    )
    return BranchDiffReport(fork_id="fork-abc12", paths=[pd], summary=summary)


def _make_statuses() -> list[BranchStatus]:
    now = datetime.now(timezone.utc)
    return [
        BranchStatus(
            id="a-id", label="approach_a", state="done", current_turn=1, last_activity_at=now
        ),
        BranchStatus(
            id="b-id", label="approach_b", state="done", current_turn=1, last_activity_at=now
        ),
    ]


def _make_label_to_id() -> dict[str, str]:
    return {"approach_a": "a-id", "approach_b": "b-id"}


class _ProbeApp(App[None]):
    """Minimal Textual app that mounts a single static element.

    Used so we can push the modal screens via `pilot.app.push_screen` and
    inspect the rendered tree.
    """

    def compose(self) -> ComposeResult:
        yield Static("anchor")


# ---------------------------------------------------------------------------
# Test 9 — MergeAcceptanceWidget renders verdict reasoning + caveats.
# ---------------------------------------------------------------------------


async def test_acceptance_widget_renders_verdict_reasoning_and_caveats():
    app = _ProbeApp()
    verdict = _make_verdict()
    captured: dict[str, Any] = {}

    async with app.run_test() as pilot:
        widget = MergeAcceptanceWidget(
            fork_id="fork-abc12",
            winner_label="approach_b",
            effective_confidence=0.87,
            verdict=verdict,
        )

        def _on_dismiss(action: Any) -> None:
            captured["action"] = action

        app.push_screen(widget, _on_dismiss)
        await pilot.pause()

        # Title
        title = widget.query_one("#accept-title", Static)
        assert "fork-abc12" in str(title.render())
        assert "auto-merge ready" in str(title.render())

        # Winner + confidence
        winner = widget.query_one("#accept-winner", Static)
        assert "approach_b" in str(winner.render())
        assert "0.87" in str(winner.render())

        # Reasoning
        reasoning = widget.query_one("#accept-reasoning", Static)
        assert "smallest" in str(reasoning.render())

        # Caveats — bullet-rendered
        caveats = widget.query_one("#accept-caveats", Static)
        assert "thread-safety stress test" in str(caveats.render())

        # Follow-up
        followup = widget.query_one("#accept-followup", Static)
        assert "merge B" in str(followup.render())


async def test_acceptance_widget_omits_followup_section_when_none():
    app = _ProbeApp()
    verdict = _make_verdict(followup=None, caveats=[])
    async with app.run_test() as pilot:
        widget = MergeAcceptanceWidget(
            fork_id="fork-x",
            winner_label="approach_b",
            effective_confidence=0.9,
            verdict=verdict,
        )
        app.push_screen(widget)
        await pilot.pause()
        # The followup Static is not mounted when verdict.recommended_followup is None.
        with pytest.raises(NoMatches):
            widget.query_one("#accept-followup", Static)
        # Caveats section also skipped when verdict.caveats is empty.
        with pytest.raises(NoMatches):
            widget.query_one("#accept-caveats", Static)


# ---------------------------------------------------------------------------
# Test 10 — [d] dismisses with "diff" so the caller can open the diff explorer.
# The widget contract is the dispatch sentinel; the dispatcher's round-trip
# (re-pushing the widget after the diff modal closes) is covered separately.
# ---------------------------------------------------------------------------


async def test_d_key_dismisses_with_diff_action():
    app = _ProbeApp()
    captured: dict[str, Any] = {}

    async with app.run_test() as pilot:
        widget = MergeAcceptanceWidget(
            fork_id="fork-y",
            winner_label="approach_b",
            effective_confidence=0.85,
            verdict=_make_verdict(),
        )

        def _on_dismiss(action: Any) -> None:
            captured["action"] = action

        app.push_screen(widget, _on_dismiss)
        await pilot.pause()
        await pilot.press("d")
        await pilot.pause()

        assert captured["action"] == "diff"


# ---------------------------------------------------------------------------
# Test 11 — [o] dismisses with "override"; the dispatcher then opens the
# manual picker preselected on the judge's pick. We assert both halves:
# (a) the widget produces the "override" sentinel,
# (b) MergePickerModal honours preselected_branch_id by setting _selected_index.
# ---------------------------------------------------------------------------


async def test_o_key_dismisses_with_override_action():
    app = _ProbeApp()
    captured: dict[str, Any] = {}

    async with app.run_test() as pilot:
        widget = MergeAcceptanceWidget(
            fork_id="fork-z",
            winner_label="approach_b",
            effective_confidence=0.85,
            verdict=_make_verdict(),
        )

        def _on_dismiss(action: Any) -> None:
            captured["action"] = action

        app.push_screen(widget, _on_dismiss)
        await pilot.pause()
        await pilot.press("o")
        await pilot.pause()

        assert captured["action"] == "override"


async def test_picker_preselects_judges_branch_when_preselected_id_passed():
    app = _ProbeApp()
    async with app.run_test() as pilot:
        modal = MergePickerModal(
            _make_report(),
            _make_statuses(),
            _make_label_to_id(),
            preselected_branch_id="b-id",
            verdict_subtitle="Judge picked: approach_b — confidence 0.85",
        )
        app.push_screen(modal)
        await pilot.pause()
        # `_ordered_ids` is populated from label_to_id first; the preselect
        # bumps `_selected_index` to point at b-id.
        assert modal._ordered_ids[modal._selected_index] == "b-id"
        # The verdict subtitle is mounted under the existing meta row.
        subtitle = modal.query_one("#merge-verdict", Static)
        assert "approach_b" in str(subtitle.render())


async def test_picker_default_selection_is_zero_when_no_preselect():
    app = _ProbeApp()
    async with app.run_test() as pilot:
        modal = MergePickerModal(
            _make_report(),
            _make_statuses(),
            _make_label_to_id(),
        )
        app.push_screen(modal)
        await pilot.pause()
        assert modal._selected_index == 0
        # No verdict subtitle when not provided.
        with pytest.raises(NoMatches):
            modal.query_one("#merge-verdict", Static)


async def test_picker_preselect_ignores_unknown_branch_id():
    """Defensive: a stale id from a dropped branch falls back to index 0."""
    app = _ProbeApp()
    async with app.run_test() as pilot:
        modal = MergePickerModal(
            _make_report(),
            _make_statuses(),
            _make_label_to_id(),
            preselected_branch_id="ghost-id",
        )
        app.push_screen(modal)
        await pilot.pause()
        assert modal._selected_index == 0


# ---------------------------------------------------------------------------
# Extra coverage — accept/escape semantics + ESCAPE_ACTION constant.
# ---------------------------------------------------------------------------


async def test_enter_key_dismisses_with_accept_action():
    app = _ProbeApp()
    captured: dict[str, Any] = {}

    async with app.run_test() as pilot:
        widget = MergeAcceptanceWidget(
            fork_id="f",
            winner_label="approach_a",
            effective_confidence=0.9,
            verdict=_make_verdict(winner="approach_a"),
        )

        def _on_dismiss(action: Any) -> None:
            captured["action"] = action

        app.push_screen(widget, _on_dismiss)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert captured["action"] == "accept"


async def test_escape_key_dismisses_with_none():
    """Escape on the acceptance widget cancels without committing (dismisses None).

    The dispatcher treats `None` as "do nothing" — the cached judge outcome
    means the next /merge re-shows this widget without re-invoking the judge.
    """
    app = _ProbeApp()
    captured: dict[str, Any] = {}

    async with app.run_test() as pilot:
        widget = MergeAcceptanceWidget(
            fork_id="f",
            winner_label="approach_a",
            effective_confidence=0.9,
            verdict=_make_verdict(),
        )

        def _on_dismiss(action: Any) -> None:
            captured["action"] = action

        app.push_screen(widget, _on_dismiss)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        # Escape cancels — dispatcher receives None and returns without merging.
        assert captured["action"] is None


# ---------------------------------------------------------------------------
# MergePickerModal view_only mode
# ---------------------------------------------------------------------------


async def test_merge_picker_view_only_title_is_browse_diff():
    """view_only=True changes the title to 'Browse diff'."""
    app = _ProbeApp()
    async with app.run_test() as pilot:
        modal = MergePickerModal(
            _make_report(),
            _make_statuses(),
            _make_label_to_id(),
            view_only=True,
        )
        app.push_screen(modal)
        await pilot.pause()
        title = modal.query_one("#merge-title", Static)
        assert "Browse diff" in str(title.render())
        assert "Resolve fork" not in str(title.render())


async def test_merge_picker_view_only_enter_dismisses_with_none():
    """In view_only mode Enter closes the modal (returns None) instead of picking."""
    app = _ProbeApp()
    captured: dict[str, Any] = {}

    async with app.run_test() as pilot:
        modal = MergePickerModal(
            _make_report(),
            _make_statuses(),
            _make_label_to_id(),
            view_only=True,
        )
        app.push_screen(modal, lambda r: captured.update({"result": r}))
        await pilot.pause()
        modal.action_pick_selected()
        await pilot.pause()

    assert captured.get("result") is None


async def test_merge_picker_view_only_pick_by_index_noop():
    """In view_only mode numeric shortcuts do nothing."""
    app = _ProbeApp()
    captured: dict[str, Any] = {}

    async with app.run_test() as pilot:
        modal = MergePickerModal(
            _make_report(),
            _make_statuses(),
            _make_label_to_id(),
            view_only=True,
        )
        app.push_screen(modal, lambda r: captured.update({"result": r}))
        await pilot.pause()
        modal.action_pick_by_index(0)  # should not dismiss
        await pilot.pause()
        assert "result" not in captured
        modal.dismiss(None)
        await pilot.pause()
