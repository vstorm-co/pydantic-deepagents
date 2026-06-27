"""Tests for the non-blocking /diff modal."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from apps.cli.app import DeepApp
from apps.cli.modals.diff_view import DiffViewModal, _colorize_diff


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@t.test")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "f.txt").write_text("one\n")
    _git(tmp_path, "add", "f.txt")
    _git(tmp_path, "commit", "-m", "init")
    # Introduce an uncommitted change.
    (tmp_path / "f.txt").write_text("one\ntwo\n")
    return tmp_path


@pytest.fixture
def app() -> DeepApp:
    return DeepApp(model="test", version="0.0.0")


def test_colorize_diff_marks_lines() -> None:
    out = _colorize_diff("+added\n-removed\n@@ hunk @@")
    assert "[green]+added[/green]" in out
    assert "[red]-removed[/red]" in out
    assert "[cyan]" in out


def test_gather_diff_shows_changes(repo: Path) -> None:
    modal = DiffViewModal(working_dir=str(repo))
    text = modal._gather_diff()
    assert "Git Changes" in text
    assert "f.txt" in text  # the changed file shows up in the stat/diff
    assert "two" in text  # the added line


async def test_modal_loads_without_blocking(app: DeepApp, repo: Path) -> None:
    from textual.widgets import Static

    modal = DiffViewModal(working_dir=str(repo))
    async with app.run_test(size=(120, 40)) as pilot:
        await app.push_screen(modal)
        await pilot.pause()
        content = modal.query_one("#diff-content", Static)
        # The worker replaces the "Loading…" placeholder with the real diff.
        for _ in range(50):
            await pilot.pause()
            if "f.txt" in str(content.render()):
                break
        assert "f.txt" in str(content.render())


async def test_modal_handles_non_git_dir(app: DeepApp, tmp_path: Path) -> None:
    from textual.widgets import Static

    modal = DiffViewModal(working_dir=str(tmp_path))
    async with app.run_test(size=(120, 40)) as pilot:
        await app.push_screen(modal)
        for _ in range(50):
            await pilot.pause()
            rendered = str(modal.query_one("#diff-content", Static).render())
            if rendered and "Loading" not in rendered:
                break
        # Should not crash — either an error or empty-state message renders.
        assert "Loading" not in str(modal.query_one("#diff-content", Static).render())
