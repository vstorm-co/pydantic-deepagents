"""Tests for the Ctrl+P input-history picker."""

from __future__ import annotations

import pytest

from apps.cli.app import DeepApp
from apps.cli.modals.history_picker import HistoryPickerModal, _recent_unique


@pytest.fixture
def app() -> DeepApp:
    return DeepApp(model="test", version="0.0.0")


class TestRecentUnique:
    def test_most_recent_first(self) -> None:
        assert _recent_unique(["a", "b", "c"]) == ["c", "b", "a"]

    def test_dedupes_keeping_latest(self) -> None:
        # "a" appears twice; only the latest position is kept, most-recent-first.
        assert _recent_unique(["a", "b", "a", "c"]) == ["c", "a", "b"]

    def test_skips_blanks(self) -> None:
        assert _recent_unique(["x", "  ", "", "y"]) == ["y", "x"]

    def test_respects_limit(self) -> None:
        out = _recent_unique([str(i) for i in range(500)], limit=10)
        assert len(out) == 10
        assert out[0] == "499"


class TestHistoryPickerModal:
    async def test_lists_and_filters(self, app: DeepApp) -> None:
        from textual.widgets import OptionList

        modal = HistoryPickerModal(["run tests", "fix the bug", "deploy app"])
        async with app.run_test(size=(120, 40)) as pilot:
            await app.push_screen(modal)
            await pilot.pause()
            option_list = modal.query_one("#history-list", OptionList)
            assert option_list.option_count == 3

            # Fuzzy filter narrows the list.
            filter_input = modal.query_one("#history-filter")
            filter_input.value = "bug"  # type: ignore[attr-defined]
            await pilot.pause()
            assert option_list.option_count == 1

    async def test_select_returns_full_text(self, app: DeepApp) -> None:
        long_prompt = "refactor the authentication module " * 4
        modal = HistoryPickerModal([long_prompt, "short one"])
        result: list[str | None] = []
        async with app.run_test(size=(120, 40)) as pilot:
            app.push_screen(modal, lambda r: result.append(r))
            await pilot.pause()
            modal.dismiss(long_prompt)
            await pilot.pause()
            # The full (untruncated) prompt is returned even though the row label
            # is shortened for display.
            assert result == [long_prompt]


async def test_action_pushes_modal(app: DeepApp) -> None:
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        before = len(app.screen_stack)
        app.screen.action_history_picker()  # type: ignore[attr-defined]
        await pilot.pause()
        assert len(app.screen_stack) > before
        assert isinstance(app.screen, HistoryPickerModal)
