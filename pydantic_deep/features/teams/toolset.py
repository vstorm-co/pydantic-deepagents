"""The `create_team_toolset` factory and its tool descriptions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets.function import FunctionToolset
from pydantic_ai_backends import StateBackend
from subagents_pydantic_ai import SubAgentConfig
from subagents_pydantic_ai.toolset import _compile_subagent

from pydantic_deep.features.teams.primitives import (
    AgentTeam,
    TeamMember,
    TeamMemberSpec,
)

SPAWN_TEAM_DESCRIPTION = """\
Create and start an agent team for parallel multi-agent collaboration.

Each member runs as an independent agent with its own model and instructions. \
Use teams when a task benefits from parallel work by specialists \
(e.g., one member writes code while another writes tests).

You must provide a list of members, each with 'name', 'role', 'description', \
and 'instructions' keys. Only one team can be active at a time - dissolve \
the current team before creating a new one."""

ASSIGN_TASK_DESCRIPTION = """\
Assign a task to a specific team member and start execution.

The member's agent runs the task in the background. Use check_teammates \
to monitor progress and see results when complete."""

CHECK_TEAMMATES_DESCRIPTION = """\
Check the status of all team members and shared tasks.

Returns each member's current status (idle/running/completed/failed), \
result preview for completed members, and the shared task list."""

MESSAGE_TEAMMATE_DESCRIPTION = """\
Send a message to a specific team member.

Use this to provide additional context, clarifications, or instructions \
to a running team member. The member must exist in the active team."""

DISSOLVE_TEAM_DESCRIPTION = """\
Shut down the active team and clean up all resources.

Call this when all team tasks are complete or the team is no longer needed. \
This stops all running members and releases resources."""


def create_team_toolset(  # noqa: C901
    *,
    id: str | None = None,
    descriptions: dict[str, str] | None = None,
    registry: Any | None = None,
    agent_factory: Callable[..., Any] | None = None,
    task_fn: Any | None = None,
    task_manager: Any | None = None,
) -> FunctionToolset[Any]:
    """Create a toolset for managing agent teams.

    When `registry` and `task_fn` are provided, team members are
    registered as subagents and `assign_task` delegates execution to
    the subagent system.

    Args:
        id: Toolset identifier. Defaults to `"deep-team"`.
        descriptions: Optional mapping of tool name to custom description.
        registry: `DynamicAgentRegistry` for registering team members
            as subagents at runtime.
        agent_factory: Callable `(SubAgentConfig) -> Agent` used to
            create member agents. Passed as `agent_factory` on the
            SubAgentConfig so `_compile_subagent` uses it.
        task_fn: The subagent `task()` tool function. When provided,
            `assign_task` calls it to execute via the subagent engine.
        task_manager: Subagent `TaskManager` for checking task status.

    Returns:
        A `FunctionToolset` with team management tools.
    """
    toolset: FunctionToolset[Any] = FunctionToolset(id=id or "deep-team")
    _descs = descriptions or {}

    _team: list[AgentTeam | None] = [None]

    @toolset.tool(description=_descs.get("spawn_team", SPAWN_TEAM_DESCRIPTION))
    async def spawn_team(
        ctx: RunContext[Any],
        team_name: str,
        members: list[TeamMemberSpec],
    ) -> str:
        """Create and start an agent team."""
        if _team[0] is not None:
            return "Error: A team is already active. Dissolve it first."

        team_members = [
            TeamMember(
                name=m.name,
                role=m.role,
                description=m.description,
                instructions=m.instructions,
                model=m.model,
            )
            for m in members
        ]

        backend = getattr(ctx.deps, "backend", None) or StateBackend()
        team = AgentTeam(
            name=team_name,
            members=team_members,
            shared_backend=backend,
            task_manager=task_manager,
        )
        _team[0] = team
        handles = await team.spawn()

        # Register members as subagents for execution
        if registry is not None:
            for member in team_members:
                if registry.exists(member.name):
                    continue
                config = SubAgentConfig(
                    name=member.name,
                    description=f"[Team {team_name}] {member.description}",
                    instructions=member.instructions,
                    model=member.model,
                )
                if agent_factory is not None:
                    config["agent_factory"] = agent_factory
                compiled = _compile_subagent(config, member.model)
                registry.register(config, compiled.agent)

        lines = [f"Team '{team_name}' created with {len(handles)} members:"]
        for name in handles:
            lines.append(f"- {name}")
        if registry is not None:
            lines.append("\nMembers registered as subagents. Use assign_task to start execution.")
        return "\n".join(lines)

    @toolset.tool(description=_descs.get("assign_task", ASSIGN_TASK_DESCRIPTION))
    async def assign_task(
        ctx: RunContext[Any],
        member_name: str,
        task_description: str,
    ) -> str:
        """Assign a task to a team member and start execution."""
        if _team[0] is None:
            return "Error: No team is active. Use spawn_team first."
        team = _team[0]
        if member_name not in team._handles:
            available = ", ".join(team._handles.keys())
            return f"Error: Member '{member_name}' not found. Available: {available}"

        handle = team._handles[member_name]
        if handle.status == "running":
            return f"Error: Member '{member_name}' is already running. Check status first."

        # Add to shared todos
        item_id = await team.assign(member_name, task_description)

        # Delegate execution to subagent system
        if task_fn is not None:
            try:
                result = await task_fn(
                    ctx,
                    description=task_description,
                    subagent_type=member_name,
                    mode="async",
                )
                handle.status = "running"
                # Extract task_id from subagent result if available
                if "Task ID:" in str(result):
                    for part in str(result).split():
                        if len(part) == 8 and part.isalnum():
                            handle.task_id = part
                            break
                return (
                    f"Task assigned to '{member_name}' (todo: {item_id}). "
                    f"Agent running in background.\n{result}"
                )
            except Exception as e:
                handle.status = "failed"
                handle.error = str(e)
                return f"Error starting task for '{member_name}': {e}"

        return f"Task assigned to '{member_name}' (ID: {item_id})"

    @toolset.tool(description=_descs.get("check_teammates", CHECK_TEAMMATES_DESCRIPTION))
    async def check_teammates(
        ctx: RunContext[Any],
    ) -> str:
        """Check the status of all team members and shared tasks."""
        if _team[0] is None:
            return "No team is active."
        team = _team[0]

        lines = [f"Team '{team.name}' status:"]
        lines.append("")

        lines.append("Members:")
        for name, handle in team._handles.items():
            status = handle.status

            # If running and task_manager available, get live status
            if handle.task_id and task_manager is not None:
                th = task_manager.get_handle(handle.task_id)
                if th is not None:
                    status = th.status.value
                    if th.result:
                        handle.result = th.result
                        handle.status = "completed"
                        status = "completed"
                    elif th.error:
                        handle.error = th.error
                        handle.status = "failed"
                        status = "failed"

            status_line = f"- {name}: {status}"
            if handle.status == "completed" and handle.result:
                preview = handle.result[:200]
                if len(handle.result) > 200:
                    preview += "..."
                status_line += f"\n  Result: {preview}"
            elif handle.status == "failed" and handle.error:
                status_line += f"\n  Error: {handle.error}"
            lines.append(status_line)

        todos = await team.shared_todos.get_all()
        if todos:
            lines.append("")
            lines.append("Shared tasks:")
            for item in todos:
                assignee = f" (@{item.assigned_to})" if item.assigned_to else ""
                lines.append(f"- [{item.status}] {item.content}{assignee}")

        return "\n".join(lines)

    @toolset.tool(description=_descs.get("message_teammate", MESSAGE_TEAMMATE_DESCRIPTION))
    async def message_teammate(
        ctx: RunContext[Any],
        member_name: str,
        message: str,
    ) -> str:
        """Send a message to a specific team member."""
        if _team[0] is None:
            return "Error: No team is active."
        team = _team[0]
        if member_name not in team._handles:
            available = ", ".join(team._handles.keys())
            return f"Error: Member '{member_name}' not found. Available: {available}"

        await team.message_bus.send("team_lead", member_name, message)
        return f"Message sent to '{member_name}'"

    @toolset.tool(description=_descs.get("dissolve_team", DISSOLVE_TEAM_DESCRIPTION))
    async def dissolve_team(
        ctx: RunContext[Any],
    ) -> str:
        """Shut down the team and clean up resources."""
        if _team[0] is None:
            return "No team is active."

        team_name = _team[0].name

        # Clean up registry entries
        if registry is not None:
            for name in _team[0]._handles:
                registry.remove(name)

        await _team[0].dissolve()
        _team[0] = None
        return f"Team '{team_name}' dissolved."

    return toolset
