"""Regression tests for the /model and /keys pickers: focus + live search."""

from __future__ import annotations

import pytest
from textual.app import App
from textual.widgets import Input, OptionList


@pytest.fixture
def seeded_openrouter(monkeypatch, tmp_path):
    """Seed an OpenRouter cache so the model picker has models to filter."""
    from apps.cli import openrouter_models

    monkeypatch.setattr(openrouter_models, "get_global_dir", lambda: tmp_path)
    openrouter_models._write_cache(
        {
            "data": [
                {"id": "deepseek/deepseek-v4-flash", "context_length": 1_000_000, "pricing": {}},
                {"id": "deepseek/deepseek-v4-pro", "context_length": 1_000_000, "pricing": {}},
                {"id": "anthropic/claude-sonnet-4.6", "context_length": 200_000, "pricing": {}},
            ]
        }
    )
    # No recent-model history for a clean count.
    monkeypatch.setattr("apps.cli.model_history.get_global_dir", lambda: tmp_path / "nohist")


async def _open(modal):
    class _Harness(App):
        async def on_mount(self) -> None:
            await self.push_screen(modal)

    return _Harness()


class TestModelPicker:
    async def test_input_focused_and_search_filters(self, seeded_openrouter) -> None:
        from apps.cli.modals.model_picker import ModelPickerModal

        app = await _open(ModelPickerModal("x"))
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            scr = pilot.app.screen
            inp = scr.query_one("#custom-input", Input)
            ol = scr.query_one("#model-list", OptionList)
            assert pilot.app.focused is inp  # can type immediately
            before = ol.option_count
            for ch in "deepseek":
                await pilot.press(ch)
            await pilot.pause()
            assert inp.value == "deepseek"
            ids = [
                ol.get_option_at_index(i).id
                for i in range(ol.option_count)
                if ol.get_option_at_index(i).id
            ]
            assert ids and all("deepseek" in i for i in ids)
            assert ol.option_count < before  # filtered down

    async def test_enter_after_filter_returns_highlighted_model(self, seeded_openrouter) -> None:
        # Regression: typing a bare term + Enter must resolve to a real model
        # string, not the literal term (which infer_model rejects as unknown).
        from apps.cli.modals.model_picker import ModelPickerModal

        result: dict[str, str | None] = {}

        class _Harness(App):
            async def on_mount(self) -> None:
                def _cb(r: str | None) -> None:
                    result["r"] = r
                    self.exit()

                self.push_screen(ModelPickerModal("x"), _cb)

        async with _Harness().run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            for ch in "deepseek":
                await pilot.press(ch)
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()

        assert result["r"] and ":" in result["r"] and "deepseek" in result["r"]


class TestKeysPicker:
    async def test_input_focused_and_search_filters(self) -> None:
        from apps.cli.modals.keys_picker import KeysPickerModal

        app = await _open(KeysPickerModal())
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            scr = pilot.app.screen
            inp = scr.query_one("#keys-filter", Input)
            ol = scr.query_one("#keys-list", OptionList)
            assert pilot.app.focused is inp
            for ch in "openrouter":
                await pilot.press(ch)
            await pilot.pause()
            ids = [
                ol.get_option_at_index(i).id
                for i in range(ol.option_count)
                if ol.get_option_at_index(i).id
            ]
            assert ids == ["OPENROUTER_API_KEY"]
