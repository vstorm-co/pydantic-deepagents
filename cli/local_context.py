"""Local context injection — git, project, runtime, and directory tree.

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

# Lock file → package manager mapping (checked in priority order)
_PACKAGE_MANAGER_MARKERS: list[tuple[str, str]] = [
    # Python
    ("uv.lock", "uv"),
    ("poetry.lock", "poetry"),
    ("Pipfile", "pipenv"),
    ("pyproject.toml", "pip"),
    ("requirements.txt", "pip"),
    # JavaScript / TypeScript
    ("bun.lockb", "bun"),
    ("bun.lock", "bun"),
    ("pnpm-lock.yaml", "pnpm"),
    ("yarn.lock", "yarn"),
    ("package-lock.json", "npm"),
    ("package.json", "npm"),
    # Rust
    ("Cargo.lock", "cargo"),
    # Go
    ("go.sum", "go modules"),
]

# Config file → language mapping
_LANGUAGE_MARKERS: list[tuple[str, str]] = [
    ("pyproject.toml", "Python"),
    ("setup.py", "Python"),
    ("setup.cfg", "Python"),
    ("package.json", "JavaScript/TypeScript"),
    ("tsconfig.json", "TypeScript"),
    ("Cargo.toml", "Rust"),
    ("go.mod", "Go"),
    ("pom.xml", "Java"),
    ("build.gradle", "Java"),
    ("build.gradle.kts", "Kotlin"),
    ("Gemfile", "Ruby"),
    ("mix.exs", "Elixir"),
    ("composer.json", "PHP"),
    ("*.csproj", "C#"),
]

# Monorepo markers
_MONOREPO_MARKERS: list[tuple[str, str]] = [
    ("lerna.json", "Lerna"),
    ("pnpm-workspace.yaml", "pnpm workspace"),
    ("nx.json", "Nx"),
    ("turbo.json", "Turborepo"),
]


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

        # Uncommitted changes count
        uncommitted = 0
        result = subprocess.run(
            [git_path, "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=3,
            cwd=str(root),
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            uncommitted = len(result.stdout.strip().splitlines())

        return {
            "branch": current_branch,
            "main_branches": main_branches,
            "uncommitted": uncommitted,
        }
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return {}


def detect_package_manager(root: Path) -> str | None:
    """Detect the package manager used in the project.

    Checks for lock files in priority order. Returns the first match.
    """
    for filename, manager in _PACKAGE_MANAGER_MARKERS:
        if (root / filename).exists():
            return manager
    return None


def detect_language(root: Path) -> str | None:
    """Detect the primary language of the project from config files."""
    for marker, language in _LANGUAGE_MARKERS:
        if marker.startswith("*"):
            # Glob pattern (e.g. *.csproj)
            if any(root.glob(marker)):
                return language
        elif (root / marker).exists():
            return language
    return None


def detect_monorepo(root: Path) -> str | None:
    """Detect if the project is a monorepo and which type."""
    for marker, name in _MONOREPO_MARKERS:
        if (root / marker).exists():
            return name
    # Heuristic: packages/ + apps/ dirs
    if (root / "packages").is_dir() and (root / "apps").is_dir():
        return "workspaces"
    return None


def _run_version_cmd(cmd: str) -> str | None:
    """Run a version command and return trimmed output, or None."""
    exe = shutil.which(cmd)
    if not exe:
        return None
    try:
        result = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().splitlines()[0]
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        pass
    return None


def detect_runtimes(root: Path) -> dict[str, str]:
    """Detect available runtime versions relevant to the project.

    Only checks runtimes that match detected project files to avoid
    unnecessary subprocess calls.
    """
    runtimes: dict[str, str] = {}

    # Python — check if project has Python markers
    py_markers = ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile")
    if any((root / m).exists() for m in py_markers):
        ver = _run_version_cmd("python3") or _run_version_cmd("python")
        if ver:
            runtimes["Python"] = ver

    # Node — check if project has JS/TS markers
    node_markers = ("package.json", "tsconfig.json")
    if any((root / m).exists() for m in node_markers):
        ver = _run_version_cmd("node")
        if ver:
            runtimes["Node"] = ver

    # Go
    if (root / "go.mod").exists():
        ver = _run_version_cmd("go")
        if ver:
            runtimes["Go"] = ver

    # Rust
    if (root / "Cargo.toml").exists():
        ver = _run_version_cmd("rustc")
        if ver:
            runtimes["Rust"] = ver

    return runtimes


def detect_test_command(root: Path) -> str | None:
    """Detect the likely test command for the project."""
    # Makefile with test target
    makefile = root / "Makefile"
    if makefile.exists():
        try:
            content = makefile.read_text(errors="ignore")
            for line in content.splitlines():
                if line.startswith("test:") or line.startswith("test "):
                    return "make test"
        except OSError:
            pass

    # Python: pytest
    pyproject = root / "pyproject.toml"
    if pyproject.exists():
        try:
            content = pyproject.read_text(errors="ignore")
            if "[tool.pytest" in content:
                return "pytest"
        except OSError:
            pass

    # Node: npm test
    pkg_json = root / "package.json"
    if pkg_json.exists():
        try:
            content = pkg_json.read_text(errors="ignore")
            if '"test"' in content:
                pm = detect_package_manager(root)
                if pm == "bun":
                    return "bun test"
                if pm == "pnpm":
                    return "pnpm test"
                if pm == "yarn":
                    return "yarn test"
                return "npm test"
        except OSError:
            pass

    return None


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
    *,
    language: str | None = None,
    package_manager: str | None = None,
    monorepo: str | None = None,
    runtimes: dict[str, str] | None = None,
    test_command: str | None = None,
) -> str:
    """Format local context as a markdown block for system prompt injection.

    Args:
        root: Working directory.
        git_info: Git state information.
        tree: Directory tree string.
        language: Detected primary language.
        package_manager: Detected package manager.
        monorepo: Detected monorepo type, if any.
        runtimes: Detected runtime versions.
        test_command: Detected test command.

    Returns:
        Formatted markdown context block.
    """
    parts: list[str] = ["### Local Context"]

    # Git info
    if git_info:
        branch = git_info.get("branch", "unknown")
        uncommitted = git_info.get("uncommitted", 0)
        suffix = f" ({uncommitted} uncommitted)" if uncommitted else ""
        parts.append(f"\n**Git branch**: `{branch}`{suffix}")
        main_branches = git_info.get("main_branches", [])
        if main_branches:
            parts.append(f"**Main branch**: `{main_branches[0]}`")

    # Project info
    if language:
        parts.append(f"**Language**: {language}")
    if package_manager:
        parts.append(f"**Package manager**: {package_manager}")
    if monorepo:
        parts.append(f"**Monorepo**: {monorepo}")
    if test_command:
        parts.append(f"**Test command**: `{test_command}`")

    # Runtime versions
    if runtimes:
        for name, version in runtimes.items():
            parts.append(f"**{name}**: {version}")

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
                language=detect_language(self._root),
                package_manager=detect_package_manager(self._root),
                monorepo=detect_monorepo(self._root),
                runtimes=detect_runtimes(self._root),
                test_command=detect_test_command(self._root),
            )
        return self._cached_context

    def get_instructions(self, ctx: RunContext[DeepAgentDeps]) -> str:
        """Inject local context into the system prompt."""
        return self._build_context()


__all__ = [
    "IGNORE_PATTERNS",
    "LocalContextToolset",
    "detect_language",
    "detect_monorepo",
    "detect_package_manager",
    "detect_runtimes",
    "detect_test_command",
    "format_local_context",
    "get_directory_tree",
    "get_git_info",
]
