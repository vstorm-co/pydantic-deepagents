"""Capability wrapper for ContextToolset."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic_ai.capabilities import AbstractCapability

from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.toolsets.context import ContextToolset


@dataclass
class ContextCapability(AbstractCapability[DeepAgentDeps]):
    """Capability that injects project context files into the system prompt.

    Wraps a ContextToolset. Has no tools — only provides dynamic instructions
    loaded from the runtime backend.
    """

    toolset: ContextToolset

    def get_instructions(self) -> Any:
        return self.toolset.get_instructions
