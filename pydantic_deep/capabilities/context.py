"""Context files capability for pydantic-deep agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability

from pydantic_deep.toolsets.context import ContextToolset


@dataclass
class ContextFilesCapability(AbstractCapability[Any]):
    """Capability that injects project context files into the agent's system prompt.

    Loads files like DEEP.md, AGENT.md, CLAUDE.md and injects their content
    as instructions.

    Example:
        ```python
        from pydantic_ai import Agent
        from pydantic_deep.capabilities.context import ContextFilesCapability

        agent = Agent("openai:gpt-4.1", capabilities=[ContextFilesCapability(
            context_files=["/workspace/DEEP.md"],
        )])
        ```
    """

    context_files: list[str] | None = None
    context_discovery: bool = False
    is_subagent: bool = False
    max_chars: int = 20_000
    _toolset: ContextToolset | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.context_files or self.context_discovery:
            self._toolset = ContextToolset(
                context_files=self.context_files,
                context_discovery=self.context_discovery,
                is_subagent=self.is_subagent,
                max_chars=self.max_chars,
            )

    def get_instructions(self) -> Any:
        toolset = self._toolset

        async def _instructions(ctx: RunContext[Any]) -> str | None:
            if toolset is None or not hasattr(ctx.deps, "backend"):
                return None
            parts = await toolset.get_instructions(ctx)  # pragma: no cover
            return "\n\n".join(parts) if parts else None  # pragma: no cover

        return _instructions
