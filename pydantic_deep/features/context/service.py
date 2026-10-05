"""Pure context-file logic: discovery, loading, and prompt formatting.

No agent/toolset dependencies — just the workspace and the data type, so the
toolset and capability share one source of truth.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic_deep._text import truncate_text
from pydantic_deep.features.context.types import ContextFile

if TYPE_CHECKING:
    from pydantic_ai.workspaces import Workspace

DEFAULT_CONTEXT_FILENAMES: list[str] = [
    "AGENTS.md",
    "CLAUDE.md",
    "SOUL.md",
    ".cursorrules",
    ".github/copilot-instructions.md",
    "CONVENTIONS.md",
    "CODING_GUIDELINES.md",
]
"""Default filenames to scan for during auto-discovery.

- `AGENTS.md` — Project instructions, conventions, architecture.
  Compatible with the `agents.md spec <https://agents.md/>`_.
  Visible to main agent and subagents.
- `CLAUDE.md` — Claude Code project instructions.
  Visible to main agent and subagents.
- `SOUL.md` — Agent personality, style, user preferences.
  Visible to main agent only (filtered for subagents).
- `.cursorrules` — Cursor editor conventions.
- `.github/copilot-instructions.md` — GitHub Copilot instructions.
- `CONVENTIONS.md` — Project coding conventions.
- `CODING_GUIDELINES.md` — Coding guidelines.
"""

SUBAGENT_CONTEXT_ALLOWLIST: frozenset[str] = frozenset(
    {
        "AGENTS.md",
        "CLAUDE.md",
    }
)
"""Context files that subagents are allowed to see.

Subagents see AGENTS.md and CLAUDE.md (project instructions) but not
SOUL.md (personality/preferences intended for the main agent only),
.cursorrules, or other editor-specific conventions.
"""

DEFAULT_MAX_CONTEXT_CHARS: int = 20_000
"""Default max chars per context file before truncation."""

logger = logging.getLogger(__name__)


async def _read_context_file(workspace: Workspace, path: str) -> str | None:
    """The text of the context file at `path`, or `None` when there is none to use.

    Context files are optional, so a missing or empty one is skipped, and so is
    one the workspace refuses to read - with a warning, since that is a setup
    mistake rather than an absent file. A workspace that cannot answer at all
    raises.
    """
    try:
        raw = await workspace.read_bytes(path)
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
        return None
    except PermissionError as exc:
        logger.warning("Skipping context file %s: %s", path, exc)
        return None
    return raw.decode("utf-8", errors="replace") if raw else None


async def load_context_files(
    workspace: Workspace,
    paths: list[str],
) -> list[ContextFile]:
    """Load context files from the workspace.

    Missing, empty and unreadable files are skipped.

    Args:
        workspace: Workspace to read files from.
        paths: List of file paths to load.

    Returns:
        List of loaded context files.
    """
    result: list[ContextFile] = []
    for path in paths:
        content = await _read_context_file(workspace, path)
        if content is None:
            continue
        name = path.rsplit("/", 1)[-1]
        result.append(ContextFile(name=name, path=path, content=content))
    return result


def _context_path(search_path: str, name: str) -> str:
    """Join a search root and filename into a workspace path.

    The workspace root is its working directory, so at the root the path is
    *relative* (``AGENTS.md``, no leading slash): an absolute ``/AGENTS.md``
    names the top of the filesystem in a workspace with a real one, which is
    not where a project keeps its instructions.
    """
    prefix = search_path.rstrip("/")
    return f"{prefix}/{name}" if prefix else name


async def discover_context_files(
    workspace: Workspace,
    search_path: str = "/",
    filenames: list[str] | None = None,
) -> list[str]:
    """Auto-discover context files at the workspace root.

    Args:
        workspace: Workspace to search in.
        search_path: Root path to search (default: "/", the working directory).
        filenames: Filenames to look for (default: DEFAULT_CONTEXT_FILENAMES).

    Returns:
        List of paths to found context files.
    """
    return [file.path for file in await _discover_and_load(workspace, search_path, filenames)]


async def _discover_and_load(
    workspace: Workspace,
    search_path: str = "/",
    filenames: list[str] | None = None,
) -> list[ContextFile]:
    """Discover and load context files in a single pass.

    Unlike calling `discover_context_files` followed by `load_context_files`,
    this reads each file's bytes only once. Missing files are skipped.

    Args:
        workspace: Workspace to search and read from.
        search_path: Root path to search (default: "/", the working directory).
        filenames: Filenames to look for (default: DEFAULT_CONTEXT_FILENAMES).

    Returns:
        List of loaded context files.
    """
    filenames = filenames or DEFAULT_CONTEXT_FILENAMES
    paths = [_context_path(search_path, name) for name in filenames]
    return await load_context_files(workspace, paths)


def format_context_prompt(
    files: list[ContextFile],
    *,
    is_subagent: bool = False,
    subagent_allowlist: frozenset[str] = SUBAGENT_CONTEXT_ALLOWLIST,
    max_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> str:
    """Format context files for system prompt injection.

    Args:
        files: Loaded context files.
        is_subagent: Whether this is for a subagent (applies filtering).
        subagent_allowlist: Filenames allowed for subagents.
        max_chars: Max chars per file before truncation.

    Returns:
        Formatted system prompt section, or empty string if no files.
    """
    if is_subagent:
        files = [f for f in files if f.name in subagent_allowlist]

    if not files:
        return ""

    parts = ["## Project Context"]
    for f in files:
        content = truncate_text(f.content, max_chars)
        parts.append(f"### {f.name}\n\n{content}")

    return "\n\n".join(parts)
