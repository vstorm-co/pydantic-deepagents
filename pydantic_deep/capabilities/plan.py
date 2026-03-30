"""Plan mode capability for pydantic-deep agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.toolsets import AbstractToolset

from pydantic_deep.toolsets.plan.toolset import create_plan_toolset


@dataclass
class PlanCapability(AbstractCapability[Any]):
    """Capability providing interactive planning tools.

    Provides ask_user and save_plan tools for structured planning workflow.

    Example:
        ```python
        from pydantic_ai import Agent
        from pydantic_deep.capabilities.plan import PlanCapability

        agent = Agent("openai:gpt-4.1", capabilities=[PlanCapability()])
        ```
    """

    plans_dir: str = "/plans"
    _toolset: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._toolset = create_plan_toolset(
            plans_dir=self.plans_dir,
        )

    def get_toolset(self) -> AbstractToolset[Any] | None:
        return self._toolset  # type: ignore[no-any-return]
