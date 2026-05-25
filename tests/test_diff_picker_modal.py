"""Tests for :class:`apps.cli.modals.diff_picker.DiffPickerModal`.

Covers navigation (path + branch), branch toggling, ``initial_branch_id``
behaviour, the "Pick at least one branch" guard, and result shape on
confirm vs cancel.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from pydantic_ai_backends import StateBackend
from textual.widgets import Static

from apps.cli.app import DeepApp
from apps.cli.modals.diff_picker import DiffPickerModal, DiffPickerResult
from pydantic_deep import DeepAgentDeps, create_deep_agent
from pydantic_deep.types import (
    BranchChange,
    BranchDiffReport,
    BranchStatus,
    DiffSummary,
    PathDiff,
)


def _make_agent() -> Agent[DeepAgentDeps, str]:
    return create_deep_agent(
        model=TestModel(call_tools=[]),
        forking=True,
        include_skills=False,
        include_plan=False,
        include_memory=False,
        include_subagents=False,
        include_teams=False,
        include_todo=False,
        web_search=False,
        web_fetch=False,
        cost_tracking=False,
        context_manager=False,
        stuck_loop_detection=False,
        context_discovery=False,
    )


def _make_app() -> DeepApp:
    return DeepApp(
        agent=_make_agent(),
        deps=DeepAgentDeps(backend=StateBackend()),
        model="test",
        version="0.3.3",
    )


def _change(
    branch_id: str, label: str, op: str = "modified", diff: str = "+ delta"
) -> BranchChange:
    return BranchChange(
        branch_id=branch_id,
        branch_label=label,
        operation=op,
        new_content="updated",
        unified_diff_vs_parent=diff,
        size_bytes=10,
        is_binary=False,
    )


def _report(touched: bool = True) -> BranchDiffReport:
    """Two branches a/b — single touched path + one untouched path."""
    paths: list[PathDiff] = []
    if touched:
        paths.append(
            PathDiff(
                path="cat.md",
                parent_content="cats",
                branches={
                    "id-a": _change("id-a", "a"),
                    "id-b": _change("id-b", "b"),
                },
                agreement="split",
            )
        )
    # An untouched path must be filtered out by the modal — the picker
    # has no use for a row where nothing happened.
    paths.append(
        PathDiff(
            path="untouched.md",
            parent_content="x",
            branches={
                "id-a": _change("id-a", "a", op="untouched", diff=""),
                "id-b": _change("id-b", "b", op="untouched", diff=""),
            },
            agreement="identical",
        )
    )
    return BranchDiffReport(
        fork_id="fork-x",
        paths=paths,
        summary=DiffSummary(
            total_paths_touched=1 if touched else 0,
            unanimous_paths=0,
            split_paths=1 if touched else 0,
            per_branch_unique={"id-a": 1 if touched else 0, "id-b": 0},
            agreement_score=0.0,
        ),
    )


def _statuses() -> list[BranchStatus]:
    now = datetime.now(timezone.utc)
    return [
        BranchStatus(id="id-a", label="a", state="done", current_turn=0, last_activity_at=now),
        BranchStatus(id="id-b", label="b", state="done", current_turn=0, last_activity_at=now),
    ]


@pytest.mark.asyncio
async def test_modal_lists_only_touched_paths() -> None:
    app = _make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        modal = DiffPickerModal(_report(), _statuses(), {"a": "id-a", "b": "id-b"})
        app.push_screen(modal)
        await pilot.pause()
        assert modal.selected_path == "cat.md"
        # The untouched path must not show up.
        assert modal._paths == ["cat.md"]
        modal.dismiss(None)
        await pilot.pause()


@pytest.mark.asyncio
async def test_default_all_branches_enabled() -> None:
    app = _make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        modal = DiffPickerModal(_report(), _statuses(), {"a": "id-a", "b": "id-b"})
        app.push_screen(modal)
        await pilot.pause()
        assert modal.enabled_branch_ids == ["id-a", "id-b"]
        modal.dismiss(None)
        await pilot.pause()


@pytest.mark.asyncio
async def test_initial_branch_id_pre_checks_only_that_branch() -> None:
    app = _make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        modal = DiffPickerModal(
            _report(),
            _statuses(),
            {"a": "id-a", "b": "id-b"},
            initial_branch_id="id-b",
        )
        app.push_screen(modal)
        await pilot.pause()
        assert modal.enabled_branch_ids == ["id-b"]
        modal.dismiss(None)
        await pilot.pause()


@pytest.mark.asyncio
async def test_toggle_branch_and_confirm_yields_subset() -> None:
    app = _make_app()
    captured: list[DiffPickerResult | None] = []

    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        modal = DiffPickerModal(_report(), _statuses(), {"a": "id-a", "b": "id-b"})
        # ModalScreen[T].dismiss does not natively return through a
        # callback when invoked programmatically; pass the callback via
        # push_screen instead.
        app.push_screen(modal, lambda r: captured.append(r))
        await pilot.pause()
        # Move focus to the second branch and toggle it off.
        modal.action_move_branch_next()
        modal.action_toggle_branch()
        assert modal.enabled_branch_ids == ["id-a"]
        modal.action_confirm()
        await pilot.pause()

    assert captured == [DiffPickerResult(path="cat.md", branch_ids=["id-a"])]


@pytest.mark.asyncio
async def test_confirm_with_no_branches_does_not_dismiss() -> None:
    app = _make_app()
    captured: list[DiffPickerResult | None] = []

    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        modal = DiffPickerModal(_report(), _statuses(), {"a": "id-a", "b": "id-b"})
        app.push_screen(modal, lambda r: captured.append(r))
        await pilot.pause()

        # Toggle both branches off.
        modal.action_toggle_branch()
        modal.action_move_branch_next()
        modal.action_toggle_branch()
        assert modal.enabled_branch_ids == []

        modal.action_confirm()
        await pilot.pause()
        # Modal must still be open; no callback fired.
        assert captured == []
        assert app.screen is modal
        modal.dismiss(None)
        await pilot.pause()


@pytest.mark.asyncio
async def test_empty_report_confirms_with_none() -> None:
    app = _make_app()
    captured: list[DiffPickerResult | None] = []

    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        modal = DiffPickerModal(_report(touched=False), _statuses(), {"a": "id-a", "b": "id-b"})
        app.push_screen(modal, lambda r: captured.append(r))
        await pilot.pause()
        assert modal.selected_path is None
        modal.action_confirm()
        await pilot.pause()
    assert captured == [None]


@pytest.mark.asyncio
async def test_cancel_returns_none() -> None:
    app = _make_app()
    captured: list[DiffPickerResult | None] = []

    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        modal = DiffPickerModal(_report(), _statuses(), {"a": "id-a", "b": "id-b"})
        app.push_screen(modal, lambda r: captured.append(r))
        await pilot.pause()
        modal.action_cancel()
        await pilot.pause()
    assert captured == [None]


@pytest.mark.asyncio
async def test_path_navigation_wraps() -> None:
    """Add a second touched path so we can verify ↑/↓ wraparound."""
    app = _make_app()
    report = _report()
    extra = PathDiff(
        path="dog.md",
        parent_content="dogs",
        branches={
            "id-a": _change("id-a", "a", op="created", diff="+ delta"),
            "id-b": _change("id-b", "b", op="untouched", diff=""),
        },
        agreement="split",
    )
    report = BranchDiffReport(
        fork_id=report.fork_id,
        paths=[*report.paths, extra],
        summary=report.summary,
    )

    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        modal = DiffPickerModal(report, _statuses(), {"a": "id-a", "b": "id-b"})
        app.push_screen(modal)
        await pilot.pause()
        assert modal.selected_path == "cat.md"
        modal.action_move_path_down()
        assert modal.selected_path == "dog.md"
        modal.action_move_path_down()
        # Wraps back to the first entry.
        assert modal.selected_path == "cat.md"
        modal.action_move_path_up()
        assert modal.selected_path == "dog.md"
        modal.dismiss(None)
        await pilot.pause()


@pytest.mark.asyncio
async def test_empty_paths_navigation_is_noop() -> None:
    """Cover the early-return guards on path nav when nothing is touched."""
    app = _make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        modal = DiffPickerModal(_report(touched=False), _statuses(), {"a": "id-a", "b": "id-b"})
        app.push_screen(modal)
        await pilot.pause()
        modal.action_move_path_up()
        modal.action_move_path_down()
        assert modal.selected_path is None
        modal.dismiss(None)
        await pilot.pause()


@pytest.mark.asyncio
async def test_empty_branch_set_navigation_is_noop() -> None:
    """Cover the guards when no branches exist in label_to_id or statuses."""
    app = _make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        modal = DiffPickerModal(_report(), [], {})
        app.push_screen(modal)
        await pilot.pause()
        modal.action_move_branch_prev()
        modal.action_move_branch_next()
        modal.action_toggle_branch()
        assert modal.enabled_branch_ids == []
        modal.dismiss(None)
        await pilot.pause()


@pytest.mark.asyncio
async def test_status_supplies_missing_label() -> None:
    """If ``label_to_id`` is missing a branch, ``branches`` fills the label."""
    app = _make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        modal = DiffPickerModal(_report(), _statuses(), {"a": "id-a"})
        app.push_screen(modal)
        await pilot.pause()
        # "b" was not in label_to_id; status row should still surface it.
        assert "id-b" in modal._ordered_branch_ids
        assert modal._id_to_label["id-b"] == "b"
        modal.dismiss(None)
        await pilot.pause()


@pytest.mark.asyncio
async def test_toggle_parent_changes_include_parent() -> None:
    """``p`` toggles parent inclusion; default is True."""
    app = _make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        modal = DiffPickerModal(_report(), _statuses(), {"a": "id-a", "b": "id-b"})
        app.push_screen(modal)
        await pilot.pause()
        assert modal.parent_included is True
        modal.action_toggle_parent()
        assert modal.parent_included is False
        modal.action_toggle_parent()
        assert modal.parent_included is True
        modal.dismiss(None)
        await pilot.pause()


@pytest.mark.asyncio
async def test_confirm_without_parent_sets_include_parent_false() -> None:
    """When parent is toggled off the confirmed result carries include_parent=False."""
    app = _make_app()
    captured: list[DiffPickerResult | None] = []

    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        modal = DiffPickerModal(_report(), _statuses(), {"a": "id-a", "b": "id-b"})
        app.push_screen(modal, lambda r: captured.append(r))
        await pilot.pause()
        modal.action_toggle_parent()
        assert modal.parent_included is False
        modal.action_confirm()
        await pilot.pause()

    assert len(captured) == 1
    result = captured[0]
    assert result is not None
    assert result.include_parent is False
    assert result.path == "cat.md"
    assert result.branch_ids == ["id-a", "id-b"]


@pytest.mark.asyncio
async def test_browse_merge_view_pushes_merge_picker_modal() -> None:
    """'m' keybinding pushes MergePickerModal in view-only mode."""
    from apps.cli.modals.merge_picker import MergePickerModal

    app = _make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        modal = DiffPickerModal(_report(), _statuses(), {"a": "id-a", "b": "id-b"})
        app.push_screen(modal)
        await pilot.pause()

        modal.action_browse_merge_view()
        await pilot.pause()

        # MergePickerModal should now be on top of the screen stack —
        # assert via the observable title ("Browse diff" vs "Resolve fork")
        # rather than the modal's private ``_view_only`` attribute.
        assert isinstance(app.screen, MergePickerModal)
        title = app.screen.query_one("#merge-title", Static)
        assert "Browse diff" in str(title.render())

        # Dismiss both to clean up.
        app.screen.dismiss(None)
        await pilot.pause()
        modal.dismiss(None)
        await pilot.pause()


@pytest.mark.asyncio
async def test_action_hint_contains_browse_hint() -> None:
    """Action hint includes 'm browse' after the new binding was added."""
    app = _make_app()
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        modal = DiffPickerModal(_report(), _statuses(), {"a": "id-a", "b": "id-b"})
        app.push_screen(modal)
        await pilot.pause()
        hint = modal.query_one("#diff-actions", Static)
        assert "m browse" in str(hint.render())
        modal.dismiss(None)
        await pilot.pause()
