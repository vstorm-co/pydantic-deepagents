"""Local context injection — git info and directory tree.

Injects into the system prompt so the agent starts with full awareness
of its environment, reducing discovery errors on benchmarks.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from pydantic_deep.deps import DeepAgentDeps

# Directories to ignore in tree views
IGNORE_PATTERNS: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".coverage",
        ".eggs",
        "dist",
        "build",
        ".next",
        ".nuxt",
        "target",
        ".idea",
        ".vscode",
    }
)


def _get_git_executable() -> str | None:
    """Get full path to git executable."""
    return shutil.which("git")


def get_git_info(root: Path) -> dict[str, Any]:
    """Gather git state information.

    Args:
        root: Directory to check for git repo.

    Returns:
        Dict with 'branch' and 'main_branches' keys, or empty if not a git repo.
    """
    git_path = _get_git_executable()
    if not git_path:
        return {}

    try:
        result = subprocess.run(
            [git_path, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=str(root),
            check=False,
        )
        if result.returncode != 0:
            return {}

        current_branch = result.stdout.strip()

        # Check for main/master branches
        main_branches: list[str] = []
        result = subprocess.run(
            [git_path, "branch", "--list", "main", "master"],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=str(root),
            check=False,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                branch = line.strip().lstrip("* ")
                if branch in ("main", "master"):
                    main_branches.append(branch)

        return {
            "branch": current_branch,
            "main_branches": main_branches,
        }
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return {}


def get_directory_tree(
    root: Path,
    *,
    max_depth: int = 3,
    max_entries: int = 30,
) -> str:
    """Build a directory tree string.

    Args:
        root: Root directory to scan.
        max_depth: Maximum depth to traverse.
        max_entries: Maximum total entries to include.

    Returns:
        Formatted tree string.
    """
    lines: list[str] = []
    count = 0

    def _walk(path: Path, prefix: str, depth: int) -> None:
        nonlocal count
        if depth > max_depth or count >= max_entries:
            return

        try:
            entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name))
        except PermissionError:
            return

        filtered = [e for e in entries if e.name not in IGNORE_PATTERNS]

        for i, entry in enumerate(filtered):
            if count >= max_entries:
                lines.append(f"{prefix}... ({len(filtered) - i} more)")
                break

            is_last = i == len(filtered) - 1
            connector = "└── " if is_last else "├── "
            suffix = "/" if entry.is_dir() else ""
            lines.append(f"{prefix}{connector}{entry.name}{suffix}")
            count += 1

            if entry.is_dir():
                extension = "    " if is_last else "│   "
                _walk(entry, prefix + extension, depth + 1)

    _walk(root, "", 0)
    return "\n".join(lines)


def format_local_context(
    root: Path,
    git_info: dict[str, Any],
    tree: str,
) -> str:
    """Format local context as a markdown block for system prompt injection.

    Args:
        root: Working directory.
        git_info: Git state information.
        tree: Directory tree string.

    Returns:
        Formatted markdown context block.
    """
    parts: list[str] = ["### Local Context"]

    # Git info
    if git_info:
        branch = git_info.get("branch", "unknown")
        parts.append(f"\n**Git branch**: `{branch}`")
        main_branches = git_info.get("main_branches", [])
        if main_branches:
            parts.append(f"**Main branch**: `{main_branches[0]}`")

    # Directory tree
    if tree:
        parts.append(f"\n**Directory structure** of `{root.resolve()}`:\n```\n{tree}\n```")

    return "\n".join(parts)


class LocalContextToolset(FunctionToolset[DeepAgentDeps]):
    """Toolset that injects local git/directory context into the system prompt.

    Uses the ``get_instructions()`` hook to inject context at each model
    request, following the same pattern as ContextToolset.
    """

    def __init__(self, root_dir: Path | None = None) -> None:
        super().__init__()
        self._root = root_dir or Path.cwd()
        # Cache the context since it doesn't change during a run
        self._cached_context: str | None = None

    def _build_context(self) -> str:
        """Build the local context string (cached after first call)."""
        if self._cached_context is None:
            git_info = get_git_info(self._root)
            tree = get_directory_tree(self._root)
            self._cached_context = format_local_context(
                self._root,
                git_info,
                tree,
            )
        return self._cached_context

    def get_instructions(self, ctx: RunContext[DeepAgentDeps]) -> str:
        """Inject local context into the system prompt."""
        return self._build_context()


__all__ = [
    "IGNORE_PATTERNS",
    "LocalContextToolset",
    "format_local_context",
    "get_directory_tree",
    "get_git_info",
]
