"""Pure context-file logic: discovery, loading, and prompt formatting.

No agent/toolset dependencies — just the backend protocol and the data type, so
the toolset and capability share one source of truth.
"""

from __future__ import annotations

from pydantic_ai_backends import AsyncBackendProtocol

from pydantic_deep._text import truncate_text
from pydantic_deep.features.context.types import ContextFile

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


async def load_context_files(
    backend: AsyncBackendProtocol,
    paths: list[str],
) -> list[ContextFile]:
    """Load context files from backend.

    Missing files are silently skipped.

    Args:
        backend: Async backend to read files from.
        paths: List of file paths to load.

    Returns:
        List of loaded context files.
    """
    result: list[ContextFile] = []
    for path in paths:
        raw = await backend.read_bytes(path)
        if not raw:
            continue
        content = raw.decode("utf-8", errors="replace")
        name = path.rsplit("/", 1)[-1]
        result.append(ContextFile(name=name, path=path, content=content))
    return result


async def discover_context_files(
    backend: AsyncBackendProtocol,
    search_path: str = "/",
    filenames: list[str] | None = None,
) -> list[str]:
    """Auto-discover context files in backend root.

    Args:
        backend: Async backend to search in.
        search_path: Root path to search (default: "/").
        filenames: Filenames to look for (default: DEFAULT_CONTEXT_FILENAMES).

    Returns:
        List of paths to found context files.
    """
    filenames = filenames or DEFAULT_CONTEXT_FILENAMES
    found: list[str] = []
    for name in filenames:
        path = f"{search_path.rstrip('/')}/{name}"
        raw = await backend.read_bytes(path)
        if raw:
            found.append(path)
    return found


async def _discover_and_load(
    backend: AsyncBackendProtocol,
    search_path: str = "/",
    filenames: list[str] | None = None,
) -> list[ContextFile]:
    """Discover and load context files in a single pass.

    Unlike calling `discover_context_files` followed by `load_context_files`,
    this reads each file's bytes only once. Missing files are silently skipped.

    Args:
        backend: Async backend to search and read from.
        search_path: Root path to search (default: "/").
        filenames: Filenames to look for (default: DEFAULT_CONTEXT_FILENAMES).

    Returns:
        List of loaded context files.
    """
    filenames = filenames or DEFAULT_CONTEXT_FILENAMES
    result: list[ContextFile] = []
    for name in filenames:
        path = f"{search_path.rstrip('/')}/{name}"
        raw = await backend.read_bytes(path)
        if not raw:
            continue
        content = raw.decode("utf-8", errors="replace")
        result.append(ContextFile(name=path.rsplit("/", 1)[-1], path=path, content=content))
    return result


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
