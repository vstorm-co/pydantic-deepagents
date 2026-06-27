"""Agent teams with shared todos and peer-to-peer messaging.

Teams provide coordination infrastructure on top of the subagent execution
engine. When a `registry` is provided, team members are registered as subagents
and `assign_task` delegates to the subagent `task()` tool for actual execution.
"""

from pydantic_deep.features.teams.primitives import (
    AgentTeam,
    SharedTodoItem,
    SharedTodoList,
    TeamMember,
    TeamMemberHandle,
    TeamMemberSpec,
    TeamMessage,
    TeamMessageBus,
)
from pydantic_deep.features.teams.toolset import create_team_toolset
from pydantic_deep.models import DEFAULT_TEAM_MEMBER_MODEL

__all__ = [
    "DEFAULT_TEAM_MEMBER_MODEL",
    "AgentTeam",
    "SharedTodoItem",
    "SharedTodoList",
    "TeamMember",
    "TeamMemberHandle",
    "TeamMemberSpec",
    "TeamMessage",
    "TeamMessageBus",
    "create_team_toolset",
]
