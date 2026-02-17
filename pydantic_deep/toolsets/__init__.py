"""Toolsets for pydantic-deep agents."""

from pydantic_ai_backends import (
    ConsoleDeps,
    create_console_toolset,
    get_console_system_prompt,
)
from pydantic_ai_todo import create_todo_toolset as TodoToolset
from subagents_pydantic_ai import SubAgentToolset

from pydantic_deep.toolsets.plan import create_plan_toolset
from pydantic_deep.toolsets.skills import SkillsToolset
from pydantic_deep.toolsets.teams import create_team_toolset

__all__ = [
    "TodoToolset",
    "create_console_toolset",
    "get_console_system_prompt",
    "ConsoleDeps",
    "SubAgentToolset",
    "SkillsToolset",
    "create_plan_toolset",
    "create_team_toolset",
]
