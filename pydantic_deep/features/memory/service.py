"""Pure memory logic: path computation, loading, and prompt formatting.

No agent/toolset dependencies — just the workspace and the data types, so the
toolset and capability can share one source of truth for the prompt.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_deep._text import NUM_CHARS_PER_TOKEN
from pydantic_deep.features.memory.types import MemoryAccessError, MemoryFile

if TYPE_CHECKING:
    from pydantic_ai.workspaces import Workspace

DEFAULT_MEMORY_DIR: str = ".deep/memory"
"""Default base directory for memory files, relative to the workspace's working directory."""

DEFAULT_MEMORY_FILENAME: str = "MEMORY.md"
"""Default filename for memory files."""

DEFAULT_MAX_MEMORY_LINES: int = 200
"""Default max lines to inject into system prompt."""

DEFAULT_PIN_END_MARKER: str = "<!-- deep:pin-end -->"
"""Marker delimiting the pinned memory head from the truncatable body.

Everything above the first occurrence is always injected verbatim, so
foundational notes survive truncation; everything below it is the
recency-truncated body. The default is an HTML comment, invisible in rendered
markdown.
"""


def get_memory_path(memory_dir: str, agent_name: str) -> str:
    """Compute the memory file path for an agent.

    Args:
        memory_dir: Base directory for memory files.
        agent_name: Agent name (e.g., "main", "code-reviewer").

    Returns:
        Full path like ".deep/memory/main/MEMORY.md".
    """
    return f"{memory_dir.rstrip('/')}/{agent_name}/{DEFAULT_MEMORY_FILENAME}"


async def load_memory(
    workspace: Workspace,
    path: str,
    agent_name: str = "main",
) -> MemoryFile | None:
    """Load memory file from the workspace.

    Returns None when the file is genuinely missing or empty. Raises
    `MemoryAccessError` when the workspace refuses the path, so a
    misconfigured memory directory is not silently reported as empty memory
    (issue #135). A workspace that cannot answer at all raises its own error.

    Args:
        workspace: Workspace to read from.
        path: Full path to the memory file.
        agent_name: Name of the agent owning this memory.

    Returns:
        MemoryFile if found, None if missing or empty.

    Raises:
        MemoryAccessError: If the workspace refused the path.
    """
    try:
        raw = await workspace.read_bytes(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except (PermissionError, IsADirectoryError) as exc:
        raise MemoryAccessError(str(exc) or "access denied") from exc
    if not raw:
        return None
    return MemoryFile(
        agent_name=agent_name, path=path, content=raw.decode("utf-8", errors="replace")
    )


def _select_recent_lines(lines: list[str], max_lines: int, max_tokens: int | None) -> int:
    """Return how many trailing lines fit the budget (>=1 when `lines` is non-empty).

    The *most recent* lines are the ones kept, since `write_memory` appends new
    content to the end of the file. `max_tokens` (approximate, via
    `NUM_CHARS_PER_TOKEN`) takes precedence over `max_lines` when provided.
    """
    if not lines:
        return 0
    if max_tokens is None:
        return min(len(lines), max_lines)

    char_budget = max_tokens * NUM_CHARS_PER_TOKEN
    used = 0
    kept = 0
    for line in reversed(lines):
        used += len(line) + 1  # +1 approximates the joining newline
        if used > char_budget and kept >= 1:
            break
        kept += 1
    return kept


def format_memory_prompt(
    memory: MemoryFile,
    max_lines: int,
    *,
    max_tokens: int | None = None,
    pin_marker: str = DEFAULT_PIN_END_MARKER,
) -> str:
    """Format memory content for system prompt injection.

    `write_memory` appends new content, so the newest observations live at the
    end of the file. When memory exceeds the budget, the *most recent* lines are
    kept (the tail), not the oldest. Content above the first `pin_marker` is a
    pinned head that is always injected in full, so foundational notes survive
    truncation. If the body is truncated, a marker noting the dropped lines is
    inserted above the kept tail.

    Args:
        memory: Loaded memory file.
        max_lines: Maximum number of body lines to include.
        max_tokens: Optional approximate token budget for the body. When set it
            takes precedence over `max_lines`, using the `NUM_CHARS_PER_TOKEN`
            heuristic used elsewhere in the library.
        pin_marker: Marker whose first occurrence ends the always-injected head.

    Returns:
        Formatted system prompt section.
    """
    pinned = ""
    body = memory.content
    marker_idx = memory.content.find(pin_marker)
    if marker_idx != -1:
        pinned = memory.content[:marker_idx].rstrip("\n")
        body = memory.content[marker_idx + len(pin_marker) :].lstrip("\n")

    body_lines = body.splitlines()
    keep = _select_recent_lines(body_lines, max_lines, max_tokens)
    if keep < len(body_lines):
        dropped = len(body_lines) - keep
        body = f"... [{dropped} more lines in memory] ..."
        if keep:
            body += "\n\n" + "\n".join(body_lines[-keep:])

    content = f"{pinned}\n\n{body}" if pinned and body else pinned or body

    return f"## Agent Memory ({memory.agent_name})\n\n{content}"
