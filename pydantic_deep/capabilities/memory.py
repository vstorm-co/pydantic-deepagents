"""Capability wrapper for AgentMemoryToolset."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets import AgentToolset

from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.toolsets.memory import AgentMemoryToolset


@dataclass
class MemoryCapability(AbstractCapability[DeepAgentDeps]):
    """Capability that provides persistent agent memory tools and instructions.

    Wraps an AgentMemoryToolset so that both its tools (read_memory,
    write_memory, update_memory) and dynamic instructions are delivered
    through the pydantic-ai capabilities API.
    """

    toolset: AgentMemoryToolset

    def get_instructions(self) -> Any:
        return self.toolset.get_instructions

    def get_toolset(self) -> AgentToolset[DeepAgentDeps] | None:
        return self.toolset
