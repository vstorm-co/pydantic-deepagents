"""Plan toolset for interactive implementation planning.

Provides Claude Code-style plan mode with:
- ``ask_user``: Ask questions with predefined options during planning
- ``save_plan``: Save implementation plans to markdown files
- Built-in planner subagent instructions
"""

from pydantic_deep.toolsets.plan.toolset import (
    DEFAULT_PLANS_DIR,
    PLANNER_DESCRIPTION,
    PLANNER_INSTRUCTIONS,
    create_plan_toolset,
)

__all__ = [
    "create_plan_toolset",
    "PLANNER_DESCRIPTION",
    "PLANNER_INSTRUCTIONS",
    "DEFAULT_PLANS_DIR",
]
