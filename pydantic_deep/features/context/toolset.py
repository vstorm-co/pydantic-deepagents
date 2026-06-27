"""Project context file injection toolset.

Discovers and loads project context files (AGENTS.md, SOUL.md, …) from the
backend and injects them into the agent's system prompt via
`FunctionToolset.get_instructions()`. Has no model-callable tools.
Works with both main agents and subagents (with configurable filtering).
"""

from __future__ import annotations

from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.messages import InstructionPart
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai_backends import AsyncBackendProtocol

from pydantic_deep.features.context.service import (
    DEFAULT_MAX_CONTEXT_CHARS,
    _discover_and_load,
    format_context_prompt,
    load_context_files,
)


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
