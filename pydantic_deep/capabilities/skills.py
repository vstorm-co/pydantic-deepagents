"""Capability wrapper for SkillsToolset."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets import AgentToolset

from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.toolsets.skills import SkillsToolset


@dataclass
class SkillsCapability(AbstractCapability[DeepAgentDeps]):
    """Capability that provides skills tools and instructions.

    Wraps a SkillsToolset so that both its tools and dynamic instructions
    are delivered through the pydantic-ai capabilities API.
    """

    toolset: SkillsToolset = field(default_factory=SkillsToolset)

    def get_instructions(self) -> Any:
        return self.toolset.get_instructions

    def get_toolset(self) -> AgentToolset[DeepAgentDeps] | None:
        return self.toolset  # type: ignore[return-value]
