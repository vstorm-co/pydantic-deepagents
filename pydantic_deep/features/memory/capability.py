"""Agent memory capability for pydantic-deep agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets import AbstractToolset

from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.features.memory.service import DEFAULT_MEMORY_DIR, DEFAULT_PIN_END_MARKER
from pydantic_deep.features.memory.toolset import AgentMemoryToolset


@dataclass
class MemoryCapability(AbstractCapability[DeepAgentDeps]):
    """Capability providing persistent agent memory across sessions.

    Provides read_memory, write_memory, update_memory tools and injects
    existing memory into the system prompt.

    Example:
        ```python
        from pydantic_ai import Agent
        from pydantic_deep.features.memory import MemoryCapability

        agent = Agent("anthropic:claude-sonnet-4-6", capabilities=[MemoryCapability()])
        ```
    """

    agent_name: str = "main"
    memory_dir: str = DEFAULT_MEMORY_DIR
    max_lines: int = 200
    max_tokens: int | None = None
    pin_marker: str = DEFAULT_PIN_END_MARKER
    _toolset: AgentMemoryToolset | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._toolset = AgentMemoryToolset(
            agent_name=self.agent_name,
            memory_dir=self.memory_dir,
            max_lines=self.max_lines,
            max_tokens=self.max_tokens,
            pin_marker=self.pin_marker,
        )

    def get_toolset(self) -> AbstractToolset[Any] | None:
        return self._toolset

    def get_instructions(self) -> Any:
        toolset = self._toolset

        async def _instructions(ctx: RunContext[DeepAgentDeps]) -> str | None:
            if toolset is None or not hasattr(ctx.deps, "backend"):
                return None
            parts = await toolset.get_instructions(ctx)  # pragma: no cover
            return "\n\n".join(p.content for p in parts) if parts else None  # pragma: no cover

        return _instructions
