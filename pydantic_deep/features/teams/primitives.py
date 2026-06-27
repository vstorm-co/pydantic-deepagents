"""Team primitives: shared todos, peer-to-peer messaging, and the team model."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel
from pydantic_ai_backends import BackendProtocol, StateBackend

from pydantic_deep.models import DEFAULT_TEAM_MEMBER_MODEL


class TeamMemberSpec(BaseModel):
    """A team member supplied to the `spawn_team` tool."""

    name: str
    role: str = "worker"
    description: str = ""
    instructions: str = ""
    model: str = DEFAULT_TEAM_MEMBER_MODEL


@dataclass
class SharedTodoItem:
    """A todo item for team-shared task management.

    Unlike the regular Todo (from pydantic-ai-todo), this includes
    `assigned_to`, `blocked_by`, and `created_by` fields for
    multi-agent coordination.
    """

    id: str = field(default_factory=lambda: uuid4().hex[:8])
    content: str = ""
    status: Literal["pending", "in_progress", "completed"] = "pending"
    assigned_to: str | None = None
    blocked_by: list[str] = field(default_factory=list)
    created_by: str | None = None


class SharedTodoList:
    """Asyncio-safe shared TODO list for agent teams.

    Uses `asyncio.Lock` for concurrent access safety.
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

        Returns `False` if already claimed, not found, not pending,
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
        """Remove an item. Returns `False` if not found."""
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

    Unlike `InMemoryMessageBus` (parent-child only), this supports
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

        Raises `KeyError` if the receiver is not registered.
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

        Raises `KeyError` if the agent is not registered.
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
    model: str = DEFAULT_TEAM_MEMBER_MODEL
    toolsets: list[Any] = field(default_factory=list)


@dataclass
class TeamMemberHandle:
    """Handle to a running team member."""

    name: str
    task_id: str | None = None
    task: asyncio.Task[Any] | None = None
    status: Literal["idle", "running", "completed", "failed"] = "idle"
    result: str | None = None
    error: str | None = None


@dataclass
class AgentTeam:
    """Multi-agent team with shared state.

    Coordinates shared TODO lists and peer-to-peer messaging
    between team members. Execution is delegated to the subagent
    system via a `DynamicAgentRegistry`.
    """

    name: str
    members: list[TeamMember]
    shared_todos: SharedTodoList = field(default_factory=SharedTodoList)
    message_bus: TeamMessageBus = field(default_factory=TeamMessageBus)
    shared_backend: BackendProtocol = field(default_factory=StateBackend)
    # Subagent `TaskManager`. When set, `wait_all`/`dissolve` manage the
    # real background subagent tasks via `handle.task_id` (the actual flow set
    # up by `assign_task`), rather than the rarely-set `handle.task` field.
    task_manager: Any | None = field(default=None, repr=False)
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

    def _refresh_from_manager(self, handle: TeamMemberHandle) -> None:
        """Sync a handle's result/error/status from the subagent TaskManager."""
        if not (handle.task_id and self.task_manager is not None):
            return
        th = self.task_manager.get_handle(handle.task_id)
        if th is None:
            return
        if th.result:
            handle.result = th.result
            handle.status = "completed"
        elif th.error:
            handle.error = th.error
            handle.status = "failed"

    async def wait_all(self) -> dict[str, str]:
        """Wait for all running member tasks to complete."""
        results: dict[str, str] = {}
        for name, handle in self._handles.items():
            # Legacy / programmatic path: a directly-attached asyncio.Task.
            if handle.task is not None and not handle.task.done():
                with contextlib.suppress(Exception):
                    await handle.task
            # Real subagent flow: await the background task by id, then sync
            # the result/error the runner recorded on the TaskManager handle.
            elif handle.task_id and self.task_manager is not None:
                task = getattr(self.task_manager, "tasks", {}).get(handle.task_id)
                if task is not None and not task.done():
                    with contextlib.suppress(Exception):
                        await task
                self._refresh_from_manager(handle)
            results[name] = handle.result or handle.error or "no result"
        return results

    async def dissolve(self) -> None:
        """Unregister all members, cancel running tasks, mark team dissolved."""
        for handle in self._handles.values():
            # Legacy / programmatic path: a directly-attached asyncio.Task.
            if handle.task is not None and not handle.task.done():
                handle.task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await handle.task
            # Real subagent flow: cancel the background task via the manager.
            elif handle.task_id and self.task_manager is not None:
                with contextlib.suppress(Exception):
                    await self.task_manager.hard_cancel(handle.task_id)
            self.message_bus.unregister(handle.name)
        self._handles.clear()
        self._dissolved = True
