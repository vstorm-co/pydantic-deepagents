"""Deprecated import location for the teams feature.

The implementation moved to :mod:`pydantic_deep.features.teams` (see the
CHANGELOG). This module re-exports the public names for backward compatibility
and will be removed in the next minor release. Import from
``pydantic_deep.features.teams`` or the top-level ``pydantic_deep`` instead.
"""

from __future__ import annotations

import warnings

from pydantic_deep.features.teams import (
    DEFAULT_TEAM_MEMBER_MODEL,
    AgentTeam,
    SharedTodoItem,
    SharedTodoList,
    TeamMember,
    TeamMemberHandle,
    TeamMemberSpec,
    TeamMessage,
    TeamMessageBus,
    create_team_toolset,
)

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

warnings.warn(
    "pydantic_deep.toolsets.teams has moved to pydantic_deep.features.teams; "
    "update your imports (this shim will be removed in the next minor release).",
    DeprecationWarning,
    stacklevel=2,
)
