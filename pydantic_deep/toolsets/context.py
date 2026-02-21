"""Project context file loading and injection.

Loads the project context file (AGENT.md) from the backend and injects
it into the agent's system prompt.

Uses FunctionToolset.get_instructions() for native pydantic-ai integration.
Works with both main agents and subagents (with configurable filtering).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai_backends import BackendProtocol

DEFAULT_CONTEXT_FILENAMES: list[str] = [
    "AGENT.md",
]
"""Default filenames to scan for during auto-discovery."""

SUBAGENT_CONTEXT_ALLOWLIST: frozenset[str] = frozenset(
    {
        "AGENT.md",
    }
)
"""Context files that subagents are allowed to see."""

DEFAULT_MAX_CONTEXT_CHARS: int = 20_000
"""Default max chars per context file before truncation."""


@dataclass
class ContextFile:
    """A loaded project context file."""

    name: str
    """Filename: "DEEP.md"."""
    path: str
    """Full path: "/project/DEEP.md"."""
    content: str
    """File content."""


def load_context_files(
    backend: BackendProtocol,
    paths: list[str],
) -> list[ContextFile]:
    """Load context files from backend.

    Missing files are silently skipped.

    Args:
        backend: Backend to read files from.
        paths: List of file paths to load.

    Returns:
        List of loaded context files.
    """
    result: list[ContextFile] = []
    for path in paths:
        raw = backend._read_bytes(path)
        if not raw:
            continue
        content = raw.decode("utf-8", errors="replace")
        name = path.rsplit("/", 1)[-1]
        result.append(ContextFile(name=name, path=path, content=content))
    return result


def discover_context_files(
    backend: BackendProtocol,
    search_path: str = "/",
    filenames: list[str] | None = None,
) -> list[str]:
    """Auto-discover context files in backend root.

    Args:
        backend: Backend to search in.
        search_path: Root path to search (default: "/").
        filenames: Filenames to look for (default: DEFAULT_CONTEXT_FILENAMES).

    Returns:
        List of paths to found context files.
    """
    filenames = filenames or DEFAULT_CONTEXT_FILENAMES
    found: list[str] = []
    for name in filenames:
        path = f"{search_path.rstrip('/')}/{name}"
        raw = backend._read_bytes(path)
        if raw:
            found.append(path)
    return found


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
    return (
        content[:head_len] + f"\n\n... [{truncated} chars truncated] ...\n\n" + content[-tail_len:]
    )


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

    Has no tools — only provides instructions via get_instructions().
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

    async def get_instructions(self, ctx: RunContext[Any]) -> str | None:
        """Load and format context files for system prompt injection.

        Args:
            ctx: The run context with access to backend via deps.

        Returns:
            Formatted context prompt, or None if no files found.
        """
        backend: BackendProtocol = ctx.deps.backend
        if self._context_discovery:
            paths = discover_context_files(backend)
        elif self._context_files:
            paths = self._context_files
        else:
            return None

        loaded = load_context_files(backend, paths)
        if not loaded:
            return None

        result = format_context_prompt(
            loaded,
            is_subagent=self._is_subagent,
            max_chars=self._max_chars,
        )
        return result or None
