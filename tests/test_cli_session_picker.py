"""Tests for the /load session picker (async load, mtime sort, fuzzy filter)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from apps.cli.app import DeepApp
from apps.cli.modals import session_picker as sp
from apps.cli.modals.session_picker import SessionPickerModal


def _make_session(root: Path, sid: str, first_prompt: str, mtime: float) -> None:
    d = root / sid
    d.mkdir(parents=True)
    msgs = [
        {"parts": [{"part_kind": "user-prompt", "content": first_prompt}]},
        {"parts": [{"part_kind": "text", "content": "ok"}]},
    ]
    f = d / "messages.json"
    f.write_text(json.dumps(msgs))
    os.utime(f, (mtime, mtime))


@pytest.fixture
def sessions_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "sessions"
    root.mkdir()
    _make_session(root, "aaaa", "older session about cats", mtime=1000)
    _make_session(root, "zzzz", "newer session about dogs", mtime=2000)
    monkeypatch.setattr(sp, "get_sessions_dir", lambda: root)
    return root


@pytest.fixture
def app() -> DeepApp:
    return DeepApp(model="test", version="0.0.0")


class TestLoadSessions:
    def test_sorts_by_mtime_newest_first(self, sessions_dir: Path) -> None:
        sessions = sp._load_sessions()
        assert [s["id"] for s in sessions] == ["zzzz", "aaaa"]

    def test_extracts_preview_and_count(self, sessions_dir: Path) -> None:
        sessions = sp._load_sessions()
        newest = sessions[0]
        assert newest["preview"] == "newer session about dogs"
        assert newest["messages"] == "2"

    def test_empty_when_no_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sp, "get_sessions_dir", lambda: tmp_path / "nope")
        assert sp._load_sessions() == []


class TestSessionPickerModal:
    async def test_loads_async_then_filters(self, app: DeepApp, sessions_dir: Path) -> None:
        from textual.widgets import OptionList

        modal = SessionPickerModal()
        async with app.run_test(size=(120, 40)) as pilot:
            await app.push_screen(modal)
            option_list = modal.query_one("#session-list", OptionList)
            for _ in range(50):
                await pilot.pause()
                if option_list.option_count == 2:
                    break
            assert option_list.option_count == 2

            # Fuzzy filter narrows to the matching session.
            modal.query_one("#session-filter").value = "dogs"  # type: ignore[attr-defined]
            await pilot.pause()
            assert option_list.option_count == 1
