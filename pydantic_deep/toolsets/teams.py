"""Agent teams with shared todos and peer-to-peer messaging.

Teams provide coordination infrastructure on top of the subagent execution
engine. When a ``registry`` is provided, team members are registered as
subagents and ``assign_task`` delegates to the subagent ``task()`` tool
for actual execution.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from pydantic_ai.tools import RunContext
from pydantic_ai.toolsets.function import FunctionToolset
from pydantic_ai_backends import BackendProtocol, StateBackend


@dataclass
class SharedTodoItem:
    """A todo item for team-shared task management.

    Unlike the regular Todo (from pydantic-ai-todo), this includes
    ``assigned_to``, ``blocked_by``, and ``created_by`` fields for
    multi-agent coordination.
    """

    id: str = field(default_factory=lambda: uuid4().hex[:8])
    content: str = ""
    status: str = "pending"  # pending | in_progress | completed
    assigned_to: str | None = None
    blocked_by: list[str] = field(default_factory=list)
    created_by: str | None = None


class SharedTodoList:
    """Asyncio-safe shared TODO list for agent teams.

    Uses ``asyncio.Lock`` for concurrent access safety.
    Supports claiming, dependencies, and auto-unblocking.
    """

    def __init__(self) -> None:
        self._items: dict[str, SharedTodoItem] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    async def add(
        self,
        content: str,
        *,
        blocked_by: list[str] | None = None,
        created_by: str | None = None,
    ) -> str:
        """Add a new item. Returns its ID."""
        async with self._lock:
            item = SharedTodoItem(
                content=content,
                blocked_by=list(blocked_by or []),
                created_by=created_by,
            )
            self._items[item.id] = item
            return item.id

    async def claim(self, item_id: str, agent_name: str) -> bool:
        """Claim an item for an agent.

        Returns ``False`` if already claimed, not found, not pending,
        or blocked by incomplete dependencies.
        """
        async with self._lock:
            item = self._items.get(item_id)
            if item is None or item.assigned_to is not None or item.status != "pending":
                return False
            for dep_id in item.blocked_by:
                dep = self._items.get(dep_id)
                if dep and dep.status != "completed":
                    return False
            item.assigned_to = agent_name
            item.status = "in_progress"
            return True

    async def complete(self, item_id: str) -> None:
        """Mark an item as completed."""
        async with self._lock:
            item = self._items.get(item_id)
            if item is None:
                return
            item.status = "completed"

    async def get_available(self) -> list[SharedTodoItem]:
        """Get items that are pending, unclaimed, and not blocked."""
        async with self._lock:
            result: list[SharedTodoItem] = []
            for item in self._items.values():
                if item.status != "pending" or item.assigned_to is not None:
                    continue
                blocked = False
                for dep_id in item.blocked_by:
                    dep = self._items.get(dep_id)
                    if dep and dep.status != "completed":
                        blocked = True
                        break
                if not blocked:
                    result.append(item)
            return result

    async def get_all(self) -> list[SharedTodoItem]:
        """Get all items."""
        async with self._lock:
            return list(self._items.values())

    async def get(self, item_id: str) -> SharedTodoItem | None:
        """Get a single item by ID."""
        async with self._lock:
            return self._items.get(item_id)

    async def remove(self, item_id: str) -> bool:
        """Remove an item. Returns ``False`` if not found."""
        async with self._lock:
            return self._items.pop(item_id, None) is not None

    async def count(self) -> int:
        """Get the number of items."""
        async with self._lock:
            return len(self._items)


@dataclass
class TeamMessage:
    """A message between team members."""

    id: str = field(default_factory=lambda: uuid4().hex[:8])
    sender: str = ""
    receiver: str = ""  # empty string = broadcast
    content: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


class TeamMessageBus:
    """Peer-to-peer message bus for agent teams.

    Unlike ``InMemoryMessageBus`` (parent-child only), this supports
    any registered agent sending to any other registered agent.
    """

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[TeamMessage]] = {}

    def register(self, agent_name: str) -> None:
        """Register an agent to send/receive messages."""
        if agent_name not in self._queues:
            self._queues[agent_name] = asyncio.Queue()

    def unregister(self, agent_name: str) -> None:
        """Unregister an agent."""
        self._queues.pop(agent_name, None)

    async def send(self, sender: str, receiver: str, content: str) -> None:
        """Send a message to a specific agent.

        Raises ``KeyError`` if the receiver is not registered.
        """
        if receiver not in self._queues:
            raise KeyError(f"Agent '{receiver}' is not registered")
        msg = TeamMessage(sender=sender, receiver=receiver, content=content)
        await self._queues[receiver].put(msg)

    async def broadcast(self, sender: str, content: str) -> None:
        """Send a message to all registered agents except the sender."""
        for name, queue in self._queues.items():
            if name != sender:
                msg = TeamMessage(sender=sender, receiver=name, content=content)
                await queue.put(msg)

    async def receive(
        self,
        agent_name: str,
        timeout: float = 0.0,
    ) -> list[TeamMessage]:
        """Get pending messages for an agent.

        Args:
            agent_name: Agent whose inbox to read.
            timeout: If > 0 and inbox is empty, wait up to this many
                seconds for a message before returning.

        Raises ``KeyError`` if the agent is not registered.
        """
        if agent_name not in self._queues:
            raise KeyError(f"Agent '{agent_name}' is not registered")
        queue = self._queues[agent_name]
        messages: list[TeamMessage] = []
        if timeout > 0 and queue.empty():
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=timeout)
                messages.append(msg)
            except asyncio.TimeoutError:
                return messages
        while not queue.empty():
            try:
                messages.append(queue.get_nowait())
            except asyncio.QueueEmpty:  # pragma: no cover
                break
        return messages

    def registered_agents(self) -> list[str]:
        """Get list of registered agent names."""
        return list(self._queues.keys())


@dataclass
class TeamMember:
    """A member of an agent team."""

    name: str
    role: str
    description: str
    instructions: str
    model: str = "openai:gpt-4.1"
    toolsets: list[Any] = field(default_factory=list)


@dataclass
class TeamMemberHandle:
    """Handle to a running team member."""

    name: str
    task_id: str | None = None
    task: asyncio.Task[Any] | None = None
    status: str = "idle"  # idle | running | completed | failed
    result: str | None = None
    error: str | None = None


@dataclass
class AgentTeam:
    """Multi-agent team with shared state.

    Coordinates shared TODO lists and peer-to-peer messaging
    between team members. Execution is delegated to the subagent
    system via a ``DynamicAgentRegistry``.
    """

    name: str
    members: list[TeamMember]
    shared_todos: SharedTodoList = field(default_factory=SharedTodoList)
    message_bus: TeamMessageBus = field(default_factory=TeamMessageBus)
    shared_backend: BackendProtocol = field(default_factory=StateBackend)
    _handles: dict[str, TeamMemberHandle] = field(default_factory=dict, repr=False)
    _dissolved: bool = field(default=False, repr=False)

    async def spawn(self) -> dict[str, TeamMemberHandle]:
        """Register all members on the message bus and prepare handles."""
        for member in self.members:
            self.message_bus.register(member.name)
            handle = TeamMemberHandle(name=member.name)
            self._handles[member.name] = handle
        return dict(self._handles)

    async def assign(self, member_name: str, task_content: str) -> str:
        """Add a task to the shared todo list and claim it for a member."""
        item_id = await self.shared_todos.add(
            content=task_content,
            created_by="team_lead",
        )
        await self.shared_todos.claim(item_id, member_name)
        return item_id

    async def broadcast(self, message: str) -> None:
        """Send a message to all members."""
        await self.message_bus.broadcast("team_lead", message)

    async def wait_all(self) -> dict[str, str]:
        """Wait for all running member tasks to complete."""
        results: dict[str, str] = {}
        for name, handle in self._handles.items():
            if handle.task is not None and not handle.task.done():
                with contextlib.suppress(Exception):
                    await handle.task
            results[name] = handle.result or handle.error or "no result"
        return results

    async def dissolve(self) -> None:
        """Unregister all members and mark team as dissolved."""
        for handle in self._handles.values():
            if handle.task is not None and not handle.task.done():
                handle.task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await handle.task
            self.message_bus.unregister(handle.name)
        self._handles.clear()
        self._dissolved = True


SPAWN_TEAM_DESCRIPTION = """\
Create and start an agent team for parallel multi-agent collaboration.

Each member runs as an independent agent with its own model and instructions. \
Use teams when a task benefits from parallel work by specialists \
(e.g., one member writes code while another writes tests).

You must provide a list of members, each with 'name', 'role', 'description', \
and 'instructions' keys. Only one team can be active at a time — dissolve \
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

    When ``registry`` and ``task_fn`` are provided, team members are
    registered as subagents and ``assign_task`` delegates execution to
    the subagent system.

    Args:
        id: Toolset identifier. Defaults to ``"deep-team"``.
        descriptions: Optional mapping of tool name to custom description.
        registry: ``DynamicAgentRegistry`` for registering team members
            as subagents at runtime.
        agent_factory: Callable ``(SubAgentConfig) -> Agent`` used to
            create member agents. Passed as ``agent_factory`` on the
            SubAgentConfig so ``_compile_subagent`` uses it.
        task_fn: The subagent ``task()`` tool function. When provided,
            ``assign_task`` calls it to execute via the subagent engine.
        task_manager: Subagent ``TaskManager`` for checking task status.

    Returns:
        A ``FunctionToolset`` with team management tools.
    """
    toolset: FunctionToolset[Any] = FunctionToolset(id=id or "deep-team")
    _descs = descriptions or {}

    _team: list[AgentTeam | None] = [None]

    @toolset.tool(description=_descs.get("spawn_team", SPAWN_TEAM_DESCRIPTION))
    async def spawn_team(
        ctx: RunContext[Any],
        team_name: str,
        members: list[dict[str, str]],
    ) -> str:
        """Create and start an agent team."""
        if _team[0] is not None:
            return "Error: A team is already active. Dissolve it first."

        team_members = [
            TeamMember(
                name=m["name"],
                role=m.get("role", "worker"),
                description=m.get("description", ""),
                instructions=m.get("instructions", ""),
                model=m.get("model", "openai:gpt-4.1"),
            )
            for m in members
        ]

        backend = getattr(ctx.deps, "backend", None) or StateBackend()
        team = AgentTeam(
            name=team_name,
            members=team_members,
            shared_backend=backend,
        )
        _team[0] = team
        handles = await team.spawn()

        # Register members as subagents for execution
        if registry is not None:
            from subagents_pydantic_ai import SubAgentConfig

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
                    config["agent_factory"] = agent_factory  # type: ignore[typeddict-unknown-key]
                from subagents_pydantic_ai.toolset import _compile_subagent

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
