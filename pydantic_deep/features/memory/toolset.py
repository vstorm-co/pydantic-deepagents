"""Persistent agent memory toolset with read/write/update tools.

Each agent/subagent can have its own MEMORY.md file stored in the backend.
Memory is auto-loaded into the system prompt (first N lines) and agents
can read, append, and update memory via tools.

Uses FunctionToolset for native pydantic-ai integration:
- `get_instructions()` injects existing memory into the system prompt
- `@toolset.tool` provides read_memory, write_memory, update_memory tools
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.messages import InstructionPart
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai_backends import AsyncBackendProtocol

from pydantic_deep.features.memory.service import (
    DEFAULT_MAX_MEMORY_LINES,
    DEFAULT_MEMORY_DIR,
    DEFAULT_PIN_END_MARKER,
    format_memory_prompt,
    get_memory_path,
    load_memory,
)
from pydantic_deep.features.memory.types import MemoryAccessError

# Tool description constants

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
The old_text must match exactly and must appear exactly once. If it is \
not found, or if it appears more than once, no change is made and an \
error is returned; add surrounding context to old_text to make it unique."""


class AgentMemoryToolset(FunctionToolset[Any]):
    """Toolset for persistent agent memory.

    Provides system prompt injection (via `get_instructions()`) and
    tools for reading, appending, and updating memory.

    Memory is stored as a MEMORY.md file in the backend at
    `{memory_dir}/{agent_name}/MEMORY.md`.

    Tools:
        - `read_memory`: Read full memory content
        - `write_memory`: Append new content to memory
        - `update_memory`: Find and replace text in memory
    """

    def __init__(
        self,
        *,
        agent_name: str = "main",
        memory_dir: str = DEFAULT_MEMORY_DIR,
        max_lines: int = DEFAULT_MAX_MEMORY_LINES,
        max_tokens: int | None = None,
        pin_marker: str = DEFAULT_PIN_END_MARKER,
        descriptions: dict[str, str] | None = None,
    ) -> None:
        """Initialize the memory toolset.

        Args:
            agent_name: Name of the agent (used for path and prompt label).
            memory_dir: Base directory for memory files in the backend.
            max_lines: Max body lines to inject into the system prompt. The most
                recent lines are kept (`write_memory` appends to the end).
            max_tokens: Optional approximate token budget for injection. When set
                it takes precedence over `max_lines`.
            pin_marker: Marker whose first occurrence ends the always-injected
                pinned head, so foundational notes survive truncation.
            descriptions: Optional mapping of tool name to custom description.
                Supported keys: `read_memory`, `write_memory`, `update_memory`.
                Any key not present falls back to the built-in description constant.
        """
        super().__init__(id="deep-memory")
        self._agent_name = agent_name
        self._memory_dir = memory_dir
        self._max_lines = max_lines
        self._max_tokens = max_tokens
        self._pin_marker = pin_marker
        self._descs = descriptions or {}
        self._path = get_memory_path(memory_dir, agent_name)

        # Register tools
        @self.tool(description=self._descs.get("read_memory", READ_MEMORY_DESCRIPTION))
        async def read_memory(ctx: RunContext[Any]) -> str:
            """Read your persistent memory."""
            backend: AsyncBackendProtocol = ctx.deps.backend
            try:
                mem = await load_memory(backend, self._path, self._agent_name)
            except MemoryAccessError as exc:
                return f"Error: cannot read memory at '{self._path}': {exc}"
            if mem is None:
                return "No memory saved yet."
            return mem.content

        @self.tool(description=self._descs.get("write_memory", WRITE_MEMORY_DESCRIPTION))
        async def write_memory(ctx: RunContext[Any], content: str) -> str:
            """Append new content to your persistent memory.

            Args:
                content: Text to append to memory (markdown recommended).
            """
            backend: AsyncBackendProtocol = ctx.deps.backend
            try:
                existing = await load_memory(backend, self._path, self._agent_name)
            except MemoryAccessError as exc:
                return f"Error: cannot access memory at '{self._path}': {exc}"
            new_content = existing.content.rstrip("\n") + "\n\n" + content if existing else content
            result = await backend.write(self._path, new_content.encode("utf-8"))
            if result.error:
                return f"Error: failed to save memory to '{self._path}': {result.error}"
            line_count = len(new_content.splitlines())
            return f"Memory updated ({line_count} lines total)."

        @self.tool(description=self._descs.get("update_memory", UPDATE_MEMORY_DESCRIPTION))
        async def update_memory(
            ctx: RunContext[Any],
            old_text: str,
            new_text: str,
        ) -> str:
            """Find and replace text in your persistent memory.

            `old_text` must match exactly once. If it is not found, or if
            it appears more than once, no change is made and an error string
            is returned.

            Args:
                old_text: The exact text to find in memory (must be unique).
                new_text: The text to replace it with.
            """
            backend: AsyncBackendProtocol = ctx.deps.backend
            try:
                mem = await load_memory(backend, self._path, self._agent_name)
            except MemoryAccessError as exc:
                return f"Error: cannot access memory at '{self._path}': {exc}"
            if mem is None:
                return "No memory exists yet. Use write_memory to create it."
            count = mem.content.count(old_text)
            if count == 0:
                return f"Text not found in memory: '{old_text[:100]}'"
            if count > 1:
                return (
                    f"Text appears {count} times in memory; old_text must be "
                    f"unique. Add more surrounding context to '{old_text[:100]}' "
                    "so it matches exactly once."
                )
            updated = mem.content.replace(old_text, new_text, 1)
            result = await backend.write(self._path, updated.encode("utf-8"))
            if result.error:
                return f"Error: failed to save memory to '{self._path}': {result.error}"
            line_count = len(updated.splitlines())
            return f"Memory updated ({line_count} lines total)."

    async def get_instructions(self, ctx: RunContext[Any]) -> list[InstructionPart] | None:
        """Load and inject memory into system prompt.

        Args:
            ctx: The run context with access to backend via deps.

        Returns:
            Formatted memory prompt, or None if no memory exists.
        """
        backend: AsyncBackendProtocol = ctx.deps.backend
        try:
            mem = await load_memory(backend, self._path, self._agent_name)
        except MemoryAccessError:
            # Prompt injection runs on every request; a denied path must not
            # abort the run. Skip injection here — the failure is surfaced
            # loudly through the read_memory/write_memory tool results instead.
            return None
        if mem is None:
            return None
        result = format_memory_prompt(
            mem,
            self._max_lines,
            max_tokens=self._max_tokens,
            pin_marker=self._pin_marker,
        )
        return [InstructionPart(content=result, dynamic=True)] if result else None
