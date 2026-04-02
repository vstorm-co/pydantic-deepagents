"""Agent teams capability for pydantic-deep agents."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets import AbstractToolset

from pydantic_deep.toolsets.teams import create_team_toolset


@dataclass
class TeamCapability(AbstractCapability[Any]):
    """Capability for multi-agent team coordination.

    When ``registry`` and ``task_fn`` are provided, team members
    are registered as subagents and tasks execute via the subagent engine.

    Example:
        ```python
        from pydantic_ai import Agent
        from pydantic_deep.capabilities.teams import TeamCapability

        agent = Agent("anthropic:claude-sonnet-4-6", capabilities=[TeamCapability()])
        ```
    """

    registry: Any | None = None
    agent_factory: Callable[..., Any] | None = None
    task_fn: Any | None = None
    task_manager: Any | None = None
    _toolset: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._toolset = create_team_toolset(
            registry=self.registry,
            agent_factory=self.agent_factory,
            task_fn=self.task_fn,
            task_manager=self.task_manager,
        )

    def get_toolset(self) -> AbstractToolset[Any] | None:
        return self._toolset  # type: ignore[no-any-return]
