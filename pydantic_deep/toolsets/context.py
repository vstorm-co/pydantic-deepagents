"""Project context file loading and injection.

Discovers and loads project context files (AGENTS.md, SOUL.md) from the
backend and injects them into the agent's system prompt.

Uses FunctionToolset.get_instructions() for native pydantic-ai integration.
Works with both main agents and subagents (with configurable filtering).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.messages import InstructionPart
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai_backends import AsyncBackendProtocol

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


@dataclass
class ContextFile:
    """A loaded project context file."""

    name: str
    """Filename: "AGENTS.md"."""
    path: str
    """Full path: "/project/AGENTS.md"."""
    content: str
    """File content."""


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


def _truncate_content(content: str, max_chars: int) -> str:
    """Truncate content preserving head (70%) and tail (30%).

    Args:
        content: Content to truncate.
        max_chars: Maximum character count.

    Returns:
        Original content if within limit, otherwise truncated with marker.
    """
    if len(content) <= max_chars:
        return content
    head_len = int(max_chars * 0.7)
    tail_len = max_chars - head_len
    truncated = len(content) - max_chars
    head = content[:head_len]
    tail = content[-tail_len:] if tail_len > 0 else ""
    return head + f"\n\n... [{truncated} chars truncated] ...\n\n" + tail


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
        content = _truncate_content(f.content, max_chars)
        parts.append(f"### {f.name}\n\n{content}")

    return "\n\n".join(parts)


class ContextToolset(FunctionToolset[Any]):
    """Toolset that injects project context files into agent system prompt.

    Has no tools - only provides instructions via get_instructions().
    Uses runtime backend (ctx.deps.backend) to load files.

    Works with both main agents and subagents.
    """

    def __init__(
        self,
        *,
        context_files: list[str] | None = None,
        context_discovery: bool = False,
        is_subagent: bool = False,
        max_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
    ) -> None:
        """Initialize the context toolset.

        Args:
            context_files: Explicit list of file paths to load.
            context_discovery: Whether to auto-discover context files.
            is_subagent: Whether this is for a subagent (applies filtering).
            max_chars: Max chars per file before truncation.
        """
        super().__init__(id="deep-context")
        self._context_files = context_files or []
        self._context_discovery = context_discovery
        self._is_subagent = is_subagent
        self._max_chars = max_chars

    async def get_instructions(self, ctx: RunContext[Any]) -> list[InstructionPart] | None:
        """Load and format context files for system prompt injection.

        Args:
            ctx: The run context with access to backend via deps.

        Returns:
            Formatted context prompt, or None if no files found.
        """
        backend: AsyncBackendProtocol | None = getattr(ctx.deps, "backend", None)
        if backend is None:
            return None

        if self._context_discovery:
            loaded = await _discover_and_load(backend)
        elif self._context_files:
            loaded = await load_context_files(backend, self._context_files)
        else:
            return None

        if not loaded:
            return None

        result = format_context_prompt(
            loaded,
            is_subagent=self._is_subagent,
            max_chars=self._max_chars,
        )
        return [InstructionPart(content=result, dynamic=True)] if result else None
