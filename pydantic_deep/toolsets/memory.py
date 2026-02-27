"""Persistent agent memory with read/write tools.

Each agent/subagent can have its own MEMORY.md file stored in the backend.
Memory is auto-loaded into the system prompt (first N lines) and agents
can read, append, and update memory via tools.

Uses FunctionToolset for native pydantic-ai integration:
- ``get_instructions()`` injects existing memory into the system prompt
- ``@toolset.tool`` provides read_memory, write_memory, update_memory tools
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai_backends import BackendProtocol

DEFAULT_MEMORY_DIR: str = "/.deep/memory"
"""Default base directory for memory files in the backend."""

DEFAULT_MEMORY_FILENAME: str = "MEMORY.md"
"""Default filename for memory files."""

DEFAULT_MAX_MEMORY_LINES: int = 200
"""Default max lines to inject into system prompt."""

# ── Tool description constants ────────────────────────────────────────────

READ_MEMORY_DESCRIPTION = """\
Read your persistent memory from previous sessions.

Returns the full content of your MEMORY.md file. Use this to recall \
what you've learned, user preferences, project patterns, and observations \
from earlier sessions."""

WRITE_MEMORY_DESCRIPTION = """\
Append new content to your persistent memory.

Use this to save important observations that should persist across sessions:
- User preferences and coding style
- Project-specific patterns and conventions
- Key decisions and their rationale
- Recurring issues and their solutions

Each write appends to the existing memory file. Use markdown for structure."""

UPDATE_MEMORY_DESCRIPTION = """\
Find and replace text in your persistent memory.

Use this to correct outdated information or update specific entries. \
The old_text must match exactly."""


@dataclass
class MemoryFile:
    """A loaded agent memory file."""

    agent_name: str
    """Agent that owns this memory: "main", "code-reviewer", etc."""
    path: str
    """Full path in backend: "/.deep/memory/main/MEMORY.md"."""
    content: str
    """Memory file content."""


def get_memory_path(memory_dir: str, agent_name: str) -> str:
    """Compute the memory file path for an agent.

    Args:
        memory_dir: Base directory for memory files.
        agent_name: Agent name (e.g., "main", "code-reviewer").

    Returns:
        Full path like "/.deep/memory/main/MEMORY.md".
    """
    return f"{memory_dir.rstrip('/')}/{agent_name}/{DEFAULT_MEMORY_FILENAME}"


def load_memory(
    backend: BackendProtocol,
    path: str,
    agent_name: str = "main",
) -> MemoryFile | None:
    """Load memory file from backend.

    Returns None if the file doesn't exist.

    Args:
        backend: Backend to read from.
        path: Full path to the memory file.
        agent_name: Name of the agent owning this memory.

    Returns:
        MemoryFile if found, None otherwise.
    """
    raw = backend._read_bytes(path)
    if not raw:
        return None
    content = raw.decode("utf-8", errors="replace")
    return MemoryFile(agent_name=agent_name, path=path, content=content)


def format_memory_prompt(memory: MemoryFile, max_lines: int) -> str:
    """Format memory content for system prompt injection.

    Only the first ``max_lines`` lines are included to stay within
    token budget. If truncated, a marker is added.

    Args:
        memory: Loaded memory file.
        max_lines: Maximum number of lines to include.

    Returns:
        Formatted system prompt section.
    """
    lines = memory.content.splitlines()
    if len(lines) > max_lines:
        truncated_count = len(lines) - max_lines
        content = "\n".join(lines[:max_lines])
        content += f"\n\n... [{truncated_count} more lines in memory] ..."
    else:
        content = memory.content

    return f"## Agent Memory ({memory.agent_name})\n\n{content}"


class AgentMemoryToolset(FunctionToolset[Any]):
    """Toolset for persistent agent memory.

    Provides system prompt injection (via ``get_instructions()``) and
    tools for reading, appending, and updating memory.

    Memory is stored as a MEMORY.md file in the backend at
    ``{memory_dir}/{agent_name}/MEMORY.md``.

    Tools:
        - ``read_memory``: Read full memory content
        - ``write_memory``: Append new content to memory
        - ``update_memory``: Find and replace text in memory
    """

    def __init__(
        self,
        *,
        agent_name: str = "main",
        memory_dir: str = DEFAULT_MEMORY_DIR,
        max_lines: int = DEFAULT_MAX_MEMORY_LINES,
        descriptions: dict[str, str] | None = None,
    ) -> None:
        """Initialize the memory toolset.

        Args:
            agent_name: Name of the agent (used for path and prompt label).
            memory_dir: Base directory for memory files in the backend.
            max_lines: Max lines to inject into system prompt.
            descriptions: Optional mapping of tool name to custom description.
                Supported keys: ``read_memory``, ``write_memory``, ``update_memory``.
                Any key not present falls back to the built-in description constant.
        """
        super().__init__(id="deep-memory")
        self._agent_name = agent_name
        self._memory_dir = memory_dir
        self._max_lines = max_lines
        self._descs = descriptions or {}
        self._path = get_memory_path(memory_dir, agent_name)

        # Register tools
        @self.tool(description=self._descs.get("read_memory", READ_MEMORY_DESCRIPTION))
        async def read_memory(ctx: RunContext[Any]) -> str:
            """Read your persistent memory."""
            backend: BackendProtocol = ctx.deps.backend
            mem = load_memory(backend, self._path, self._agent_name)
            if mem is None:
                return "No memory saved yet."
            return mem.content

        @self.tool(description=self._descs.get("write_memory", WRITE_MEMORY_DESCRIPTION))
        async def write_memory(ctx: RunContext[Any], content: str) -> str:
            """Append new content to your persistent memory.

            Args:
                content: Text to append to memory (markdown recommended).
            """
            backend: BackendProtocol = ctx.deps.backend
            existing = load_memory(backend, self._path, self._agent_name)
            new_content = existing.content.rstrip("\n") + "\n\n" + content if existing else content
            backend.write(self._path, new_content.encode("utf-8"))
            line_count = len(new_content.splitlines())
            return f"Memory updated ({line_count} lines total)."

        @self.tool(description=self._descs.get("update_memory", UPDATE_MEMORY_DESCRIPTION))
        async def update_memory(
            ctx: RunContext[Any],
            old_text: str,
            new_text: str,
        ) -> str:
            """Find and replace text in your persistent memory.

            Args:
                old_text: The exact text to find in memory.
                new_text: The text to replace it with.
            """
            backend: BackendProtocol = ctx.deps.backend
            mem = load_memory(backend, self._path, self._agent_name)
            if mem is None:
                return "No memory exists yet. Use write_memory to create it."
            if old_text not in mem.content:
                return f"Text not found in memory: '{old_text[:100]}'"
            updated = mem.content.replace(old_text, new_text, 1)
            backend.write(self._path, updated.encode("utf-8"))
            line_count = len(updated.splitlines())
            return f"Memory updated ({line_count} lines total)."

    async def get_instructions(self, ctx: RunContext[Any]) -> str | None:
        """Load and inject memory into system prompt.

        Args:
            ctx: The run context with access to backend via deps.

        Returns:
            Formatted memory prompt, or None if no memory exists.
        """
        backend: BackendProtocol = ctx.deps.backend
        mem = load_memory(backend, self._path, self._agent_name)
        if mem is None:
            return None
        return format_memory_prompt(mem, self._max_lines)
