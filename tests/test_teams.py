"""Tests for agent teams with shared todos and peer-to-peer messaging."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import RunContext
from pydantic_ai.usage import RunUsage
from pydantic_ai_backends import StateBackend

from pydantic_deep import (
    AgentTeam,
    DeepAgentDeps,
    SharedTodoItem,
    SharedTodoList,
    TeamMember,
    TeamMemberHandle,
    TeamMessage,
    TeamMessageBus,
    create_deep_agent,
    create_team_toolset,
)
from pydantic_deep.types import Todo

TEST_MODEL = TestModel()


# --- Helpers ---


def _make_ctx(backend: StateBackend | None = None) -> RunContext[DeepAgentDeps]:
    """Create a RunContext with DeepAgentDeps for testing."""
    b = backend or StateBackend()
    deps = DeepAgentDeps(backend=b)
    return RunContext(
        deps=deps,
        model=TEST_MODEL,
        usage=RunUsage(),
    )


def _minimal_agent(**kwargs: Any) -> Any:
    """Create agent with minimal toolsets for fast tests."""
    defaults = {
        "model": TEST_MODEL,
        "include_subagents": False,
        "include_skills": False,
        "cost_tracking": False,
        "context_manager": False,
    }
    defaults.update(kwargs)
    return create_deep_agent(**defaults)


# --- Unit Tests: SharedTodoItem ---


class TestSharedTodoItem:
    """Tests for SharedTodoItem dataclass."""

    def test_create_default(self):
        """Default fields are set correctly."""
        item = SharedTodoItem()
        assert len(item.id) == 8
        assert item.content == ""
        assert item.status == "pending"
        assert item.assigned_to is None
        assert item.blocked_by == []
        assert item.created_by is None

    def test_create_with_all_fields(self):
        """All fields can be set explicitly."""
        item = SharedTodoItem(
            id="abc12345",
            content="Implement feature X",
            status="in_progress",
            assigned_to="alice",
            blocked_by=["dep1"],
            created_by="bob",
        )
        assert item.id == "abc12345"
        assert item.content == "Implement feature X"
        assert item.status == "in_progress"
        assert item.assigned_to == "alice"
        assert item.blocked_by == ["dep1"]
        assert item.created_by == "bob"

    def test_auto_generated_id(self):
        """Each item gets a unique auto-generated ID."""
        item1 = SharedTodoItem()
        item2 = SharedTodoItem()
        assert item1.id != item2.id


# --- Unit Tests: SharedTodoList ---


class TestSharedTodoList:
    """Tests for SharedTodoList."""

    async def test_add_item(self):
        """Adding an item returns its ID."""
        todos = SharedTodoList()
        item_id = await todos.add("Task 1")
        assert isinstance(item_id, str)
        assert len(item_id) == 8

    async def test_add_with_blocked_by(self):
        """Items can have dependencies."""
        todos = SharedTodoList()
        dep_id = await todos.add("Dependency")
        item_id = await todos.add("Blocked task", blocked_by=[dep_id])
        item = await todos.get(item_id)
        assert item is not None
        assert item.blocked_by == [dep_id]

    async def test_add_with_created_by(self):
        """Items track who created them."""
        todos = SharedTodoList()
        item_id = await todos.add("Task", created_by="alice")
        item = await todos.get(item_id)
        assert item is not None
        assert item.created_by == "alice"

    async def test_claim_success(self):
        """Agent can claim a pending item."""
        todos = SharedTodoList()
        item_id = await todos.add("Task")
        result = await todos.claim(item_id, "alice")
        assert result is True
        item = await todos.get(item_id)
        assert item is not None
        assert item.assigned_to == "alice"
        assert item.status == "in_progress"

    async def test_claim_already_claimed(self):
        """Cannot claim an already-claimed item."""
        todos = SharedTodoList()
        item_id = await todos.add("Task")
        await todos.claim(item_id, "alice")
        result = await todos.claim(item_id, "bob")
        assert result is False

    async def test_claim_not_found(self):
        """Claiming a nonexistent item returns False."""
        todos = SharedTodoList()
        result = await todos.claim("nonexistent", "alice")
        assert result is False

    async def test_claim_not_pending(self):
        """Cannot claim a completed item."""
        todos = SharedTodoList()
        item_id = await todos.add("Task")
        await todos.claim(item_id, "alice")
        await todos.complete(item_id)
        result = await todos.claim(item_id, "bob")
        assert result is False

    async def test_claim_blocked_item(self):
        """Cannot claim a blocked item."""
        todos = SharedTodoList()
        dep_id = await todos.add("Dependency")
        item_id = await todos.add("Blocked", blocked_by=[dep_id])
        result = await todos.claim(item_id, "alice")
        assert result is False

    async def test_claim_after_dependency_complete(self):
        """Can claim item after its dependency is completed."""
        todos = SharedTodoList()
        dep_id = await todos.add("Dependency")
        item_id = await todos.add("Blocked", blocked_by=[dep_id])
        # Complete the dependency
        await todos.claim(dep_id, "alice")
        await todos.complete(dep_id)
        # Now the blocked item should be claimable
        result = await todos.claim(item_id, "bob")
        assert result is True

    async def test_complete(self):
        """Completing an item sets status to completed."""
        todos = SharedTodoList()
        item_id = await todos.add("Task")
        await todos.claim(item_id, "alice")
        await todos.complete(item_id)
        item = await todos.get(item_id)
        assert item is not None
        assert item.status == "completed"

    async def test_complete_not_found(self):
        """Completing a nonexistent item is a no-op."""
        todos = SharedTodoList()
        await todos.complete("nonexistent")  # Should not raise

    async def test_get_available_empty(self):
        """Empty list returns no available items."""
        todos = SharedTodoList()
        available = await todos.get_available()
        assert available == []

    async def test_get_available_filters_claimed(self):
        """Available items exclude claimed ones."""
        todos = SharedTodoList()
        id1 = await todos.add("Task 1")
        await todos.add("Task 2")
        await todos.claim(id1, "alice")
        available = await todos.get_available()
        assert len(available) == 1
        assert available[0].content == "Task 2"

    async def test_get_available_filters_blocked(self):
        """Available items exclude blocked ones."""
        todos = SharedTodoList()
        dep_id = await todos.add("Dependency")
        await todos.add("Blocked", blocked_by=[dep_id])
        available = await todos.get_available()
        assert len(available) == 1
        assert available[0].content == "Dependency"

    async def test_get_available_with_completed_dep_and_pending_dep(self):
        """Item blocked by both completed and pending deps is still blocked."""
        todos = SharedTodoList()
        dep1 = await todos.add("Dep 1 (will complete)")
        dep2 = await todos.add("Dep 2 (still pending)")
        item_id = await todos.add("Blocked by both", blocked_by=[dep1, dep2])
        # Complete first dep
        await todos.claim(dep1, "alice")
        await todos.complete(dep1)
        # Item should still be blocked by dep2
        available = await todos.get_available()
        available_ids = [i.id for i in available]
        assert item_id not in available_ids
        assert dep2 in available_ids

    async def test_get_available_skips_non_pending(self):
        """Available items exclude non-pending items."""
        todos = SharedTodoList()
        id1 = await todos.add("Task 1")
        await todos.add("Task 2")
        await todos.claim(id1, "alice")
        await todos.complete(id1)
        available = await todos.get_available()
        assert len(available) == 1
        assert available[0].content == "Task 2"

    async def test_get_all(self):
        """Get all items regardless of status."""
        todos = SharedTodoList()
        await todos.add("Task 1")
        await todos.add("Task 2")
        all_items = await todos.get_all()
        assert len(all_items) == 2

    async def test_get_by_id(self):
        """Get a specific item by ID."""
        todos = SharedTodoList()
        item_id = await todos.add("Task")
        item = await todos.get(item_id)
        assert item is not None
        assert item.content == "Task"

    async def test_get_not_found(self):
        """Get returns None for nonexistent ID."""
        todos = SharedTodoList()
        item = await todos.get("nonexistent")
        assert item is None

    async def test_remove(self):
        """Remove an item by ID."""
        todos = SharedTodoList()
        item_id = await todos.add("Task")
        result = await todos.remove(item_id)
        assert result is True
        assert await todos.count() == 0

    async def test_remove_not_found(self):
        """Remove returns False for nonexistent ID."""
        todos = SharedTodoList()
        result = await todos.remove("nonexistent")
        assert result is False

    async def test_count(self):
        """Count returns number of items."""
        todos = SharedTodoList()
        assert await todos.count() == 0
        await todos.add("Task 1")
        assert await todos.count() == 1
        await todos.add("Task 2")
        assert await todos.count() == 2


# --- Unit Tests: TeamMessage ---


class TestTeamMessage:
    """Tests for TeamMessage dataclass."""

    def test_create(self):
        """Message creation with all fields."""
        msg = TeamMessage(
            id="msg1",
            sender="alice",
            receiver="bob",
            content="Hello",
        )
        assert msg.sender == "alice"
        assert msg.receiver == "bob"
        assert msg.content == "Hello"

    def test_auto_id(self):
        """Messages get auto-generated IDs."""
        msg1 = TeamMessage()
        msg2 = TeamMessage()
        assert msg1.id != msg2.id
        assert len(msg1.id) == 8

    def test_defaults(self):
        """Default fields are set correctly."""
        msg = TeamMessage()
        assert msg.sender == ""
        assert msg.receiver == ""
        assert msg.content == ""
        assert msg.timestamp is not None


# --- Unit Tests: TeamMessageBus ---


class TestTeamMessageBus:
    """Tests for TeamMessageBus."""

    def test_register(self):
        """Register an agent."""
        bus = TeamMessageBus()
        bus.register("alice")
        assert "alice" in bus.registered_agents()

    def test_register_idempotent(self):
        """Registering same agent twice is a no-op."""
        bus = TeamMessageBus()
        bus.register("alice")
        bus.register("alice")
        assert bus.registered_agents().count("alice") == 1

    def test_unregister(self):
        """Unregister an agent."""
        bus = TeamMessageBus()
        bus.register("alice")
        bus.unregister("alice")
        assert "alice" not in bus.registered_agents()

    def test_unregister_not_found(self):
        """Unregistering a non-registered agent is a no-op."""
        bus = TeamMessageBus()
        bus.unregister("nobody")  # Should not raise

    def test_registered_agents(self):
        """List all registered agents."""
        bus = TeamMessageBus()
        bus.register("alice")
        bus.register("bob")
        agents = bus.registered_agents()
        assert set(agents) == {"alice", "bob"}

    async def test_send(self):
        """Send a message to a registered agent."""
        bus = TeamMessageBus()
        bus.register("alice")
        bus.register("bob")
        await bus.send("alice", "bob", "Hello!")
        messages = await bus.receive("bob")
        assert len(messages) == 1
        assert messages[0].sender == "alice"
        assert messages[0].receiver == "bob"
        assert messages[0].content == "Hello!"

    async def test_send_unregistered_receiver(self):
        """Sending to unregistered agent raises KeyError."""
        bus = TeamMessageBus()
        bus.register("alice")
        with pytest.raises(KeyError, match="'nobody'"):
            await bus.send("alice", "nobody", "Hello!")

    async def test_broadcast(self):
        """Broadcast sends to all except sender."""
        bus = TeamMessageBus()
        bus.register("alice")
        bus.register("bob")
        bus.register("charlie")
        await bus.broadcast("alice", "Announcement")
        bob_msgs = await bus.receive("bob")
        charlie_msgs = await bus.receive("charlie")
        alice_msgs = await bus.receive("alice")
        assert len(bob_msgs) == 1
        assert len(charlie_msgs) == 1
        assert len(alice_msgs) == 0

    async def test_broadcast_excludes_sender(self):
        """Broadcast does not send to sender."""
        bus = TeamMessageBus()
        bus.register("alice")
        await bus.broadcast("alice", "Hello")
        messages = await bus.receive("alice")
        assert len(messages) == 0

    async def test_receive_empty(self):
        """Receive from empty inbox returns empty list."""
        bus = TeamMessageBus()
        bus.register("alice")
        messages = await bus.receive("alice")
        assert messages == []

    async def test_receive_with_messages(self):
        """Receive returns all pending messages."""
        bus = TeamMessageBus()
        bus.register("alice")
        bus.register("bob")
        await bus.send("bob", "alice", "Msg 1")
        await bus.send("bob", "alice", "Msg 2")
        messages = await bus.receive("alice")
        assert len(messages) == 2
        assert messages[0].content == "Msg 1"
        assert messages[1].content == "Msg 2"

    async def test_receive_timeout(self):
        """Receive with timeout returns empty when no messages arrive."""
        bus = TeamMessageBus()
        bus.register("alice")
        messages = await bus.receive("alice", timeout=0.05)
        assert messages == []

    async def test_receive_timeout_gets_message(self):
        """Receive with timeout gets message that arrives during wait."""
        bus = TeamMessageBus()
        bus.register("alice")
        bus.register("bob")

        async def send_delayed():
            await asyncio.sleep(0.01)
            await bus.send("bob", "alice", "Delayed msg")

        asyncio.create_task(send_delayed())
        messages = await bus.receive("alice", timeout=1.0)
        assert len(messages) == 1
        assert messages[0].content == "Delayed msg"

    async def test_receive_unregistered(self):
        """Receive from unregistered agent raises KeyError."""
        bus = TeamMessageBus()
        with pytest.raises(KeyError, match="'nobody'"):
            await bus.receive("nobody")


# --- Unit Tests: TeamMember ---


class TestTeamMember:
    """Tests for TeamMember dataclass."""

    def test_create(self):
        """Create a team member with all fields."""
        member = TeamMember(
            name="alice",
            role="developer",
            description="Frontend developer",
            instructions="Write clean code",
        )
        assert member.name == "alice"
        assert member.role == "developer"

    def test_defaults(self):
        """Default fields are set correctly."""
        member = TeamMember(
            name="bob",
            role="tester",
            description="QA tester",
            instructions="Test thoroughly",
        )
        assert member.model == "openai:gpt-4.1"
        assert member.toolsets == []


# --- Unit Tests: TeamMemberHandle ---


class TestTeamMemberHandle:
    """Tests for TeamMemberHandle dataclass."""

    def test_create(self):
        """Create a handle with all fields."""
        handle = TeamMemberHandle(
            name="alice",
            status="running",
            result="done",
        )
        assert handle.name == "alice"
        assert handle.status == "running"
        assert handle.result == "done"

    def test_defaults(self):
        """Default fields are set correctly."""
        handle = TeamMemberHandle(name="bob")
        assert handle.task is None
        assert handle.status == "idle"
        assert handle.result is None
        assert handle.error is None


# --- Unit Tests: AgentTeam ---


class TestAgentTeam:
    """Tests for AgentTeam."""

    def _make_team(self, n_members: int = 2) -> AgentTeam:
        """Create a team with N members."""
        members = [
            TeamMember(
                name=f"agent-{i}",
                role="worker",
                description=f"Worker {i}",
                instructions="Work hard",
            )
            for i in range(n_members)
        ]
        return AgentTeam(name="test-team", members=members)

    async def test_spawn(self):
        """Spawn registers all members on bus and returns handles."""
        team = self._make_team(3)
        handles = await team.spawn()
        assert len(handles) == 3
        assert set(handles.keys()) == {"agent-0", "agent-1", "agent-2"}
        assert set(team.message_bus.registered_agents()) == {"agent-0", "agent-1", "agent-2"}

    async def test_assign(self):
        """Assign creates a shared todo and claims it."""
        team = self._make_team()
        await team.spawn()
        item_id = await team.assign("agent-0", "Build feature X")
        item = await team.shared_todos.get(item_id)
        assert item is not None
        assert item.content == "Build feature X"
        assert item.assigned_to == "agent-0"
        assert item.status == "in_progress"
        assert item.created_by == "team_lead"

    async def test_broadcast(self):
        """Broadcast sends to all members."""
        team = self._make_team(2)
        await team.spawn()
        await team.broadcast("Start working!")
        msgs_0 = await team.message_bus.receive("agent-0")
        msgs_1 = await team.message_bus.receive("agent-1")
        assert len(msgs_0) == 1
        assert len(msgs_1) == 1
        assert msgs_0[0].content == "Start working!"

    async def test_wait_all_no_tasks(self):
        """wait_all with no running tasks returns 'no result'."""
        team = self._make_team()
        await team.spawn()
        results = await team.wait_all()
        assert results == {"agent-0": "no result", "agent-1": "no result"}

    async def test_wait_all_with_result(self):
        """wait_all returns results from completed handles."""
        team = self._make_team(1)
        await team.spawn()
        team._handles["agent-0"].result = "done"
        results = await team.wait_all()
        assert results == {"agent-0": "done"}

    async def test_wait_all_with_error(self):
        """wait_all returns errors from failed handles."""
        team = self._make_team(1)
        await team.spawn()
        team._handles["agent-0"].error = "something failed"
        results = await team.wait_all()
        assert results == {"agent-0": "something failed"}

    async def test_wait_all_with_running_task(self):
        """wait_all awaits a running task and returns its result."""
        team = self._make_team(1)
        await team.spawn()

        async def worker():
            await asyncio.sleep(0.01)
            team._handles["agent-0"].result = "task done"

        task = asyncio.create_task(worker())
        team._handles["agent-0"].task = task
        results = await team.wait_all()
        assert results == {"agent-0": "task done"}

    async def test_wait_all_with_failing_task(self):
        """wait_all handles a task that raises an exception."""
        team = self._make_team(1)
        await team.spawn()

        async def failing_worker():
            raise ValueError("boom")

        task = asyncio.create_task(failing_worker())
        team._handles["agent-0"].task = task
        team._handles["agent-0"].error = "boom"
        results = await team.wait_all()
        assert results == {"agent-0": "boom"}

    async def test_dissolve(self):
        """Dissolve unregisters all and clears handles."""
        team = self._make_team()
        await team.spawn()
        await team.dissolve()
        assert team._dissolved is True
        assert team._handles == {}
        assert team.message_bus.registered_agents() == []

    async def test_dissolve_cancels_running_tasks(self):
        """Dissolve cancels running asyncio tasks."""
        team = self._make_team(1)
        await team.spawn()

        async def long_task():
            await asyncio.sleep(100)

        task = asyncio.create_task(long_task())
        team._handles["agent-0"].task = task

        await team.dissolve()
        # Allow cancellation to propagate
        await asyncio.sleep(0)
        assert task.cancelled()

    async def test_double_dissolve(self):
        """Dissolving twice is safe."""
        team = self._make_team()
        await team.spawn()
        await team.dissolve()
        await team.dissolve()  # Should not raise
        assert team._dissolved is True


# --- Unit Tests: create_team_toolset ---


class TestCreateTeamToolset:
    """Tests for create_team_toolset function."""

    def test_has_all_tools(self):
        """Toolset has all expected tools."""
        toolset = create_team_toolset()
        tool_names = set(toolset.tools.keys())
        assert tool_names == {
            "spawn_team",
            "assign_task",
            "check_teammates",
            "message_teammate",
            "dissolve_team",
        }

    def test_custom_id(self):
        """Toolset respects custom ID."""
        toolset = create_team_toolset(id="custom-team")
        assert toolset._id == "custom-team"

    async def test_spawn_team(self):
        """spawn_team creates a team."""
        toolset = create_team_toolset()
        ctx = _make_ctx()
        result = await toolset.tools["spawn_team"].function(
            ctx,
            "engineering",
            [
                {"name": "alice", "role": "dev", "description": "Frontend dev"},
                {"name": "bob", "role": "tester"},
            ],
        )
        assert "engineering" in result
        assert "alice" in result
        assert "bob" in result

    async def test_spawn_team_already_active(self):
        """spawn_team errors if team already exists."""
        toolset = create_team_toolset()
        ctx = _make_ctx()
        await toolset.tools["spawn_team"].function(ctx, "team1", [{"name": "alice"}])
        result = await toolset.tools["spawn_team"].function(ctx, "team2", [{"name": "bob"}])
        assert "Error" in result
        assert "already active" in result

    async def test_assign_task(self):
        """assign_task creates and assigns a shared todo."""
        toolset = create_team_toolset()
        ctx = _make_ctx()
        await toolset.tools["spawn_team"].function(ctx, "team1", [{"name": "alice"}])
        result = await toolset.tools["assign_task"].function(ctx, "alice", "Build the homepage")
        assert "alice" in result
        assert "ID:" in result

    async def test_assign_task_no_team(self):
        """assign_task errors if no team is active."""
        toolset = create_team_toolset()
        ctx = _make_ctx()
        result = await toolset.tools["assign_task"].function(ctx, "alice", "Build something")
        assert "Error" in result
        assert "No team" in result

    async def test_assign_task_unknown_member(self):
        """assign_task errors for unknown member."""
        toolset = create_team_toolset()
        ctx = _make_ctx()
        await toolset.tools["spawn_team"].function(ctx, "team1", [{"name": "alice"}])
        result = await toolset.tools["assign_task"].function(ctx, "nobody", "Build something")
        assert "Error" in result
        assert "not found" in result
        assert "alice" in result

    async def test_check_teammates(self):
        """check_teammates shows team status."""
        toolset = create_team_toolset()
        ctx = _make_ctx()
        await toolset.tools["spawn_team"].function(
            ctx, "team1", [{"name": "alice"}, {"name": "bob"}]
        )
        result = await toolset.tools["check_teammates"].function(ctx)
        assert "team1" in result
        assert "alice" in result
        assert "bob" in result

    async def test_check_teammates_no_team(self):
        """check_teammates shows message when no team."""
        toolset = create_team_toolset()
        ctx = _make_ctx()
        result = await toolset.tools["check_teammates"].function(ctx)
        assert "No team" in result

    async def test_check_teammates_with_todos(self):
        """check_teammates shows shared tasks."""
        toolset = create_team_toolset()
        ctx = _make_ctx()
        await toolset.tools["spawn_team"].function(ctx, "team1", [{"name": "alice"}])
        await toolset.tools["assign_task"].function(ctx, "alice", "Build feature")
        result = await toolset.tools["check_teammates"].function(ctx)
        assert "Build feature" in result
        assert "@alice" in result

    async def test_message_teammate(self):
        """message_teammate sends a message."""
        toolset = create_team_toolset()
        ctx = _make_ctx()
        await toolset.tools["spawn_team"].function(ctx, "team1", [{"name": "alice"}])
        result = await toolset.tools["message_teammate"].function(
            ctx, "alice", "Please review this"
        )
        assert "Message sent" in result
        assert "alice" in result

    async def test_message_teammate_no_team(self):
        """message_teammate errors if no team."""
        toolset = create_team_toolset()
        ctx = _make_ctx()
        result = await toolset.tools["message_teammate"].function(ctx, "alice", "Hello")
        assert "Error" in result
        assert "No team" in result

    async def test_message_teammate_unknown(self):
        """message_teammate errors for unknown member."""
        toolset = create_team_toolset()
        ctx = _make_ctx()
        await toolset.tools["spawn_team"].function(ctx, "team1", [{"name": "alice"}])
        result = await toolset.tools["message_teammate"].function(ctx, "nobody", "Hello")
        assert "Error" in result
        assert "not found" in result

    async def test_dissolve_team(self):
        """dissolve_team cleans up the team."""
        toolset = create_team_toolset()
        ctx = _make_ctx()
        await toolset.tools["spawn_team"].function(ctx, "team1", [{"name": "alice"}])
        result = await toolset.tools["dissolve_team"].function(ctx)
        assert "team1" in result
        assert "dissolved" in result

    async def test_dissolve_team_no_team(self):
        """dissolve_team handles no active team."""
        toolset = create_team_toolset()
        ctx = _make_ctx()
        result = await toolset.tools["dissolve_team"].function(ctx)
        assert "No team" in result

    async def test_spawn_after_dissolve(self):
        """Can spawn a new team after dissolving."""
        toolset = create_team_toolset()
        ctx = _make_ctx()
        await toolset.tools["spawn_team"].function(ctx, "team1", [{"name": "alice"}])
        await toolset.tools["dissolve_team"].function(ctx)
        result = await toolset.tools["spawn_team"].function(ctx, "team2", [{"name": "bob"}])
        assert "team2" in result
        assert "bob" in result


# --- Integration Tests: share_todos ---


class TestShareTodosIntegration:
    """Tests for share_todos field on DeepAgentDeps."""

    def test_share_todos_default_false(self):
        """share_todos defaults to False."""
        deps = DeepAgentDeps()
        assert deps.share_todos is False

    def test_clone_shares_todos_reference(self):
        """When share_todos=True, cloned deps share the same todos list."""
        deps = DeepAgentDeps(share_todos=True)
        deps.todos.append(Todo(content="shared task", status="pending", active_form="Sharing"))
        cloned = deps.clone_for_subagent()
        assert cloned.todos is deps.todos
        assert len(cloned.todos) == 1

    def test_clone_isolated_by_default(self):
        """By default, cloned deps get an empty todos list."""
        deps = DeepAgentDeps()
        deps.todos.append(Todo(content="parent task", status="pending", active_form="Working"))
        cloned = deps.clone_for_subagent()
        assert cloned.todos is not deps.todos
        assert len(cloned.todos) == 0

    def test_share_todos_propagates(self):
        """share_todos flag propagates to nested clones."""
        deps = DeepAgentDeps(share_todos=True)
        deps.todos.append(Todo(content="task", status="pending", active_form="Doing"))
        cloned = deps.clone_for_subagent()
        assert cloned.share_todos is True
        # Double-clone also shares
        cloned2 = cloned.clone_for_subagent()
        assert cloned2.share_todos is True
        assert cloned2.todos is deps.todos

    def test_share_todos_false_not_propagated(self):
        """share_todos=False propagates as False."""
        deps = DeepAgentDeps(share_todos=False)
        cloned = deps.clone_for_subagent()
        assert cloned.share_todos is False


# --- Integration Tests: create_deep_agent ---


class TestCreateDeepAgentTeams:
    """Tests for include_teams parameter in create_deep_agent."""

    def test_default_no_teams(self):
        """By default, team toolset is not included."""
        agent = _minimal_agent()
        toolset_ids = [getattr(t, "_id", "") for t in agent.toolsets]
        assert "deep-team" not in toolset_ids

    def test_include_teams_adds_toolset(self):
        """include_teams=True adds the team toolset."""
        agent = _minimal_agent(include_teams=True)
        toolset_ids = [getattr(t, "_id", "") for t in agent.toolsets]
        assert "deep-team" in toolset_ids


# --- Integration Tests: Exports ---


class TestTeamsExports:
    """Tests for team-related exports from pydantic_deep."""

    def test_all_team_types_exported(self):
        """All team types are importable from pydantic_deep."""
        from pydantic_deep import (
            AgentTeam,
            SharedTodoItem,
            SharedTodoList,
            TeamMember,
            TeamMemberHandle,
            TeamMessage,
            TeamMessageBus,
            create_team_toolset,
        )

        assert all(
            cls is not None
            for cls in [
                AgentTeam,
                SharedTodoItem,
                SharedTodoList,
                TeamMember,
                TeamMemberHandle,
                TeamMessage,
                TeamMessageBus,
                create_team_toolset,
            ]
        )

    def test_create_team_toolset_from_toolsets(self):
        """create_team_toolset is importable from pydantic_deep.toolsets."""
        from pydantic_deep.toolsets import create_team_toolset

        assert create_team_toolset is not None
