"""Tests for the interactive /settings modal."""

from __future__ import annotations

import pytest

from apps.cli.app import DeepApp
from apps.cli.modals.settings_view import _THINKING_CYCLE, SettingsModal


@pytest.fixture
def app():
    return DeepApp(model="test", version="0.3.3")


class TestSettingsModal:
    async def test_lists_value_rows_and_feature_toggles(self, app):
        async with app.run_test(size=(120, 40)) as pilot:
            await app.push_screen(SettingsModal())
            await pilot.pause()

            from textual.widgets import Static

            body = str(app.screen.query_one("#settings-body", Static).render())
            # Value rows.
            assert "Model" in body and "Thinking" in body and "Theme" in body
            # A few feature toggles.
            assert "Skills" in body and "Memory" in body and "Web search" in body

    async def test_navigation_wraps(self, app):
        async with app.run_test(size=(120, 40)) as pilot:
            await app.push_screen(SettingsModal())
            await pilot.pause()
            modal = app.screen
            assert modal._sel == 0
            modal.action_move(-1)  # wrap to last
            assert modal._sel == len(modal._rows) - 1
            modal.action_move(1)  # wrap back to first
            assert modal._sel == 0

    async def test_toggle_persists_and_applies_live(self, app, monkeypatch):
        calls: list[tuple[str, str]] = []
        monkeypatch.setattr(
            "apps.cli.modals.settings_view.set_config_value",
            lambda _path, key, value: calls.append((key, value)),
        )
        reconfigured: list[bool] = []
        monkeypatch.setattr(app, "reconfigure_agent", lambda *a, **k: reconfigured.append(True))
        async with app.run_test(size=(120, 40)) as pilot:
            await app.push_screen(SettingsModal())
            await pilot.pause()
            modal = app.screen
            # Move to the first toggle row (after the 3 value rows).
            modal._sel = 3
            kind, key, _label = modal._rows[3]
            assert kind == "toggle"
            modal.action_activate()
            assert calls and calls[-1][0] == key
            assert calls[-1][1] in ("true", "false")
            # The change is applied immediately, not deferred to a restart.
            assert reconfigured == [True]

    async def test_thinking_cycles_to_next(self, app, monkeypatch):
        calls: list[tuple[str, str]] = []
        monkeypatch.setattr(
            "apps.cli.modals.settings_view.set_config_value",
            lambda _path, key, value: calls.append((key, value)),
        )
        reconfigured: list[bool] = []
        monkeypatch.setattr(app, "reconfigure_agent", lambda *a, **k: reconfigured.append(True))
        async with app.run_test(size=(120, 40)) as pilot:
            await app.push_screen(SettingsModal())
            await pilot.pause()
            modal = app.screen
            modal._sel = 1  # Thinking row
            modal.action_activate()
            assert calls and calls[-1][0] == "thinking_effort"
            assert calls[-1][1] in _THINKING_CYCLE
            assert reconfigured == [True]
