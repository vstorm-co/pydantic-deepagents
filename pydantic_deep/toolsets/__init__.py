"""Toolsets for pydantic-deep agents."""

from pydantic_ai_backends import (
    ConsoleDeps,
    create_console_toolset,
    get_console_system_prompt,
)
from pydantic_ai_todo import create_todo_toolset as TodoToolset
from subagents_pydantic_ai import SubAgentToolset

from pydantic_deep.features.liteparse import LiteparseToolset
from pydantic_deep.features.plan import PlanOption, create_plan_toolset
from pydantic_deep.features.skills import SkillsToolset
from pydantic_deep.features.teams import TeamMemberSpec, create_team_toolset

__all__ = [
    "TodoToolset",
    "create_console_toolset",
    "get_console_system_prompt",
    "ConsoleDeps",
    "SubAgentToolset",
    "SkillsToolset",
    "LiteparseToolset",
    "PlanOption",
    "create_plan_toolset",
    "TeamMemberSpec",
    "create_team_toolset",
]
