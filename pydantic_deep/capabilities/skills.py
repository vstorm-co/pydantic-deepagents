"""Skills capability for pydantic-deep agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets import AbstractToolset

from pydantic_deep.toolsets.skills import (
    BackendSkillsDirectory,
    Skill,
    SkillsDirectory,
    SkillsToolset,
)


@dataclass
class SkillsCapability(AbstractCapability[Any]):
    """Capability providing skill discovery, loading, and execution.

    Wraps ``SkillsToolset`` as a pydantic-ai capability with automatic
    instruction injection listing available skills.

    Example:
        ```python
        from pydantic_ai import Agent
        from pydantic_deep.capabilities.skills import SkillsCapability

        agent = Agent("openai:gpt-4.1", capabilities=[SkillsCapability(
            directories=["./skills"],
        )])
        ```
    """

    skills: list[Skill] | None = None
    directories: list[str | Path | SkillsDirectory | BackendSkillsDirectory] | None = None
    validate: bool = True
    max_depth: int | None = 3
    instruction_template: str | None = None
    exclude_tools: set[str] | list[str] | None = None
    _toolset: SkillsToolset | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._toolset = SkillsToolset(
            skills=self.skills,
            directories=self.directories,
            validate=self.validate,
            max_depth=self.max_depth,
            instruction_template=self.instruction_template,
            exclude_tools=self.exclude_tools,
        )

    def get_toolset(self) -> AbstractToolset[Any] | None:
        return self._toolset

    def get_instructions(self) -> Any:
        toolset = self._toolset

        async def _instructions(ctx: RunContext[Any]) -> str | None:  # pragma: no cover
            if toolset is None:
                return None
            parts = await toolset.get_instructions(ctx)  # pragma: no cover
            return "\n\n".join(parts) if parts else None  # pragma: no cover

        return _instructions
