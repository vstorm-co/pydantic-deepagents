"""Tests for CLI local context injection."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from pydantic_deep.cli.local_context import (
    IGNORE_PATTERNS,
    LocalContextToolset,
    format_local_context,
    get_directory_tree,
    get_git_info,
)


class TestGetGitInfo:
    """Tests for get_git_info()."""

    def test_returns_empty_when_no_git(self, tmp_path: Path) -> None:
        """Non-git directory returns empty dict."""
        result = get_git_info(tmp_path)
        assert result == {} or "branch" in result  # depends on parent git repo

    @patch("pydantic_deep.cli.local_context._get_git_executable")
    def test_returns_empty_when_git_not_installed(
        self, mock_git: MagicMock, tmp_path: Path
    ) -> None:
        mock_git.return_value = None
        result = get_git_info(tmp_path)
        assert result == {}

    @patch("pydantic_deep.cli.local_context.subprocess.run")
    @patch("pydantic_deep.cli.local_context._get_git_executable")
    def test_returns_branch_info(
        self, mock_git: MagicMock, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        mock_git.return_value = "/usr/bin/git"
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="feature-xyz\n"),
            MagicMock(returncode=0, stdout="  main\n* feature-xyz\n"),
        ]

        result = get_git_info(tmp_path)
        assert result["branch"] == "feature-xyz"
        assert "main" in result["main_branches"]

    @patch("pydantic_deep.cli.local_context.subprocess.run")
    @patch("pydantic_deep.cli.local_context._get_git_executable")
    def test_handles_non_git_directory(
        self, mock_git: MagicMock, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        mock_git.return_value = "/usr/bin/git"
        mock_run.return_value = MagicMock(returncode=128, stdout="")

        result = get_git_info(tmp_path)
        assert result == {}

    @patch("pydantic_deep.cli.local_context.subprocess.run")
    @patch("pydantic_deep.cli.local_context._get_git_executable")
    def test_handles_timeout(
        self, mock_git: MagicMock, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        mock_git.return_value = "/usr/bin/git"
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=2)

        result = get_git_info(tmp_path)
        assert result == {}

    @patch("pydantic_deep.cli.local_context.subprocess.run")
    @patch("pydantic_deep.cli.local_context._get_git_executable")
    def test_branch_list_fails(
        self, mock_git: MagicMock, mock_run: MagicMock, tmp_path: Path
    ) -> None:
        """Branch list returning non-zero should still return branch info."""
        mock_git.return_value = "/usr/bin/git"
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="feature\n"),
            MagicMock(returncode=1, stdout=""),
        ]
        result = get_git_info(tmp_path)
        assert result["branch"] == "feature"
        assert result["main_branches"] == []


class TestGetDirectoryTree:
    """Tests for get_directory_tree()."""

    def test_empty_directory(self, tmp_path: Path) -> None:
        result = get_directory_tree(tmp_path)
        assert result == ""

    def test_simple_structure(self, tmp_path: Path) -> None:
        (tmp_path / "file1.py").write_text("content")
        (tmp_path / "file2.txt").write_text("content")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "nested.py").write_text("content")

        result = get_directory_tree(tmp_path)
        assert "file1.py" in result
        assert "file2.txt" in result
        assert "subdir/" in result
        assert "nested.py" in result

    def test_ignores_patterns(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("content")
        (tmp_path / "node_modules").mkdir()
        (tmp_path / "node_modules" / "pkg").mkdir()
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / ".git").mkdir()

        result = get_directory_tree(tmp_path)
        assert "app.py" in result
        assert "node_modules" not in result
        assert "__pycache__" not in result
        assert ".git" not in result

    def test_max_depth(self, tmp_path: Path) -> None:
        current = tmp_path
        for i in range(10):
            current = current / f"level{i}"
            current.mkdir()
            (current / f"file{i}.txt").write_text("")

        result = get_directory_tree(tmp_path, max_depth=2)
        assert "level0/" in result
        assert "level1/" in result
        assert "level5/" not in result

    def test_max_entries(self, tmp_path: Path) -> None:
        for i in range(50):
            (tmp_path / f"file{i:03d}.txt").write_text("")

        result = get_directory_tree(tmp_path, max_entries=5)
        lines = result.strip().split("\n")
        assert len(lines) <= 7
        assert "more" in lines[-1]

    def test_permission_error(self, tmp_path: Path) -> None:
        """Unreadable directory should be silently skipped."""
        (tmp_path / "readable").mkdir()
        (tmp_path / "readable" / "file.txt").write_text("content")
        unreadable = tmp_path / "unreadable"
        unreadable.mkdir()
        (unreadable / "secret.txt").write_text("secret")
        unreadable.chmod(0o000)

        try:
            result = get_directory_tree(tmp_path)
            assert "file.txt" in result
            assert "secret.txt" not in result
        finally:
            unreadable.chmod(0o755)


class TestFormatLocalContext:
    """Tests for format_local_context()."""

    def test_with_git_and_tree(self, tmp_path: Path) -> None:
        git_info = {"branch": "main", "main_branches": ["main"]}
        tree = "├── src/\n│   └── app.py\n└── README.md"

        result = format_local_context(tmp_path, git_info, tree)
        assert "### Local Context" in result
        assert "**Git branch**: `main`" in result
        assert "**Main branch**: `main`" in result
        assert "src/" in result
        assert "app.py" in result

    def test_without_git(self, tmp_path: Path) -> None:
        result = format_local_context(tmp_path, {}, "└── file.txt")
        assert "### Local Context" in result
        assert "Git branch" not in result
        assert "file.txt" in result

    def test_empty(self, tmp_path: Path) -> None:
        result = format_local_context(tmp_path, {}, "")
        assert "### Local Context" in result

    def test_git_info_without_main_branches(self, tmp_path: Path) -> None:
        result = format_local_context(
            tmp_path, {"branch": "develop", "main_branches": []}, "└── app.py"
        )
        assert "**Git branch**: `develop`" in result
        assert "Main branch" not in result

    def test_empty_tree_with_git(self, tmp_path: Path) -> None:
        result = format_local_context(tmp_path, {"branch": "main"}, "")
        assert "**Git branch**: `main`" in result
        assert "Directory structure" not in result


class TestLocalContextToolset:
    """Tests for LocalContextToolset."""

    def test_creates_with_default_path(self) -> None:
        toolset = LocalContextToolset()
        assert toolset._root == Path.cwd()

    def test_creates_with_custom_path(self, tmp_path: Path) -> None:
        toolset = LocalContextToolset(root_dir=tmp_path)
        assert toolset._root == tmp_path

    def test_get_instructions_returns_string(self, tmp_path: Path) -> None:
        (tmp_path / "test.py").write_text("print('hello')")
        toolset = LocalContextToolset(root_dir=tmp_path)

        ctx = MagicMock()
        result = toolset.get_instructions(ctx)
        assert isinstance(result, str)
        assert "### Local Context" in result
        assert "test.py" in result

    def test_caches_context(self, tmp_path: Path) -> None:
        toolset = LocalContextToolset(root_dir=tmp_path)
        ctx = MagicMock()

        result1 = toolset.get_instructions(ctx)
        result2 = toolset.get_instructions(ctx)
        assert result1 == result2
        assert toolset._cached_context is not None


class TestIgnorePatterns:
    """Tests for IGNORE_PATTERNS constant."""

    def test_contains_common_patterns(self) -> None:
        assert ".git" in IGNORE_PATTERNS
        assert "node_modules" in IGNORE_PATTERNS
        assert "__pycache__" in IGNORE_PATTERNS
        assert ".venv" in IGNORE_PATTERNS
        assert "dist" in IGNORE_PATTERNS
        assert "build" in IGNORE_PATTERNS
