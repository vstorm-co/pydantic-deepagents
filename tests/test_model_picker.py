"""Regression tests for the /model and /keys pickers: focus + live search."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from textual.app import App
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList


@pytest.fixture
def seeded_openrouter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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


@pytest.fixture(autouse=True)
def no_local_servers(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Nothing discovered locally, unless a test says otherwise - a developer's
    running Ollama must not change what these tests see."""
    discovered: list[str] = []
    monkeypatch.setattr("apps.cli.local_models.openai_compatible_models", lambda base_url: [])
    monkeypatch.setattr("apps.cli.local_models.ollama_models", lambda: list(discovered))
    return discovered


async def _open(modal: ModalScreen[Any]) -> App[None]:
    class _Harness(App[None]):
        async def on_mount(self) -> None:
            await self.push_screen(modal)

    return _Harness()


class TestModelPicker:
    async def test_input_focused_and_search_filters(self, seeded_openrouter: None) -> None:
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
                oid
                for i in range(ol.option_count)
                if (oid := ol.get_option_at_index(i).id) is not None
            ]
            assert ids and all("deepseek" in i for i in ids)
            assert ol.option_count < before  # filtered down

    async def test_enter_after_filter_returns_highlighted_model(
        self, seeded_openrouter: None
    ) -> None:
        # Regression: typing a bare term + Enter must resolve to a real model
        # string, not the literal term (which infer_model rejects as unknown).
        from apps.cli.modals.model_picker import ModelPickerModal

        result: dict[str, str | None] = {}

        class _Harness(App[None]):
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


class TestLocalDiscovery:
    async def test_what_a_local_server_serves_is_offered(
        self, seeded_openrouter: None, no_local_servers: list[str]
    ) -> None:
        """#216: models a local server serves are listed, not typed by hand."""
        from apps.cli.modals.model_picker import ModelPickerModal

        no_local_servers.extend(["ollama:llama3.3", "ollama:qwen3:8b"])
        app = await _open(ModelPickerModal("x"))
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.app.workers.wait_for_complete()
            await pilot.pause()
            ol = pilot.app.screen.query_one("#model-list", OptionList)
            ids = [ol.get_option_at_index(i).id for i in range(ol.option_count)]

        assert "ollama:llama3.3" in ids
        assert "ollama:qwen3:8b" in ids


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
                oid
                for i in range(ol.option_count)
                if (oid := ol.get_option_at_index(i).id) is not None
            ]
            assert ids == ["OPENROUTER_API_KEY"]
