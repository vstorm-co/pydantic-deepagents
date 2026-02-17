# Agent Teams

Agent teams enable multi-agent collaboration with **shared TODO lists** and **peer-to-peer messaging**. Unlike subagents (parent-child delegation), teams are flat groups of agents that coordinate through shared state.

## Quick Start

```python
from pydantic_deep import create_deep_agent

agent = create_deep_agent(include_teams=True)
```

The agent gets five team management tools:

| Tool | Description |
|------|-------------|
| `spawn_team` | Create a team and register members |
| `assign_task` | Add a shared task and assign it to a member |
| `check_teammates` | Show member status and shared task progress |
| `message_teammate` | Send a direct message to a team member |
| `dissolve_team` | Shut down the team and clean up |

## How Teams Work

```
┌─────────────────────────────────────────────┐
│                 AgentTeam                    │
│                                             │
│  ┌──────────────┐  ┌──────────────────────┐ │
│  │ SharedTodoList│  │  TeamMessageBus      │ │
│  │              │  │                      │ │
│  │ - add()      │  │ - send(a, b, msg)    │ │
│  │ - claim()    │  │ - broadcast(a, msg)  │ │
│  │ - complete() │  │ - receive(a)         │ │
│  └──────────────┘  └──────────────────────┘ │
│                                             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐    │
│  │ Member A │ │ Member B │ │ Member C │    │
│  └──────────┘ └──────────┘ └──────────┘    │
└─────────────────────────────────────────────┘
```

## Shared TODO List

The [`SharedTodoList`][pydantic_deep.toolsets.teams.SharedTodoList] is an asyncio-safe task tracker with claiming and dependencies.

```python
from pydantic_deep.toolsets.teams import SharedTodoList

todos = SharedTodoList()

# Add tasks
task_a = await todos.add("Design the API schema", created_by="lead")
task_b = await todos.add(
    "Implement endpoints",
    blocked_by=[task_a],  # Can't start until task_a completes
    created_by="lead",
)

# Claim and complete
await todos.claim(task_a, "alice")    # True — alice owns it
await todos.claim(task_b, "bob")      # False — blocked by task_a
await todos.complete(task_a)
await todos.claim(task_b, "bob")      # True — dependency resolved

# Check available tasks
available = await todos.get_available()  # Pending, unclaimed, unblocked
```

### SharedTodoItem Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | `str` | Auto-generated (uuid4 hex[:8]) |
| `content` | `str` | Task description |
| `status` | `str` | `"pending"`, `"in_progress"`, or `"completed"` |
| `assigned_to` | `str \| None` | Name of the agent that claimed this task |
| `blocked_by` | `list[str]` | IDs of tasks that must complete first |
| `created_by` | `str \| None` | Who created this task |

## Message Bus

The [`TeamMessageBus`][pydantic_deep.toolsets.teams.TeamMessageBus] provides peer-to-peer messaging between registered agents.

```python
from pydantic_deep.toolsets.teams import TeamMessageBus

bus = TeamMessageBus()
bus.register("alice")
bus.register("bob")

# Direct message
await bus.send("alice", "bob", "Can you review my changes?")

# Broadcast to all except sender
await bus.broadcast("alice", "I'm starting on the API schema")

# Read inbox
messages = await bus.receive("bob")
for msg in messages:
    print(f"{msg.sender}: {msg.content}")
```

## AgentTeam

The [`AgentTeam`][pydantic_deep.toolsets.teams.AgentTeam] class coordinates team members with shared state:

```python
from pydantic_deep.toolsets.teams import AgentTeam, TeamMember

team = AgentTeam(
    name="backend-team",
    members=[
        TeamMember(
            name="alice",
            role="api-designer",
            description="Designs REST APIs",
            instructions="Focus on clean API design...",
        ),
        TeamMember(
            name="bob",
            role="implementer",
            description="Implements API endpoints",
            instructions="Write clean Python code...",
        ),
    ],
)

# Register members on the message bus
handles = await team.spawn()

# Assign tasks
await team.assign("alice", "Design the user API schema")
await team.assign("bob", "Set up the project structure")

# Broadcast a message
await team.broadcast("Let's sync before starting")

# Clean up
await team.dissolve()
```

## Shared TODOs via deps

For simpler use cases, you can share the parent agent's TODO list with subagents using `share_todos`:

```python
from pydantic_deep import DeepAgentDeps
from pydantic_ai_backends import StateBackend

deps = DeepAgentDeps(
    backend=StateBackend(),
    share_todos=True,  # Subagents share parent's todo list
)
```

When `share_todos=True`, `clone_for_subagent()` passes the same todos list reference instead of creating an empty list.

## Components

| Component | Description |
|-----------|-------------|
| [`SharedTodoItem`][pydantic_deep.toolsets.teams.SharedTodoItem] | Task with assignment, dependencies, and status |
| [`SharedTodoList`][pydantic_deep.toolsets.teams.SharedTodoList] | Asyncio-safe task list with claiming and blocking |
| [`TeamMessage`][pydantic_deep.toolsets.teams.TeamMessage] | Message between team members |
| [`TeamMessageBus`][pydantic_deep.toolsets.teams.TeamMessageBus] | Peer-to-peer message routing |
| [`TeamMember`][pydantic_deep.toolsets.teams.TeamMember] | Member definition (name, role, instructions) |
| [`TeamMemberHandle`][pydantic_deep.toolsets.teams.TeamMemberHandle] | Runtime handle to a team member |
| [`AgentTeam`][pydantic_deep.toolsets.teams.AgentTeam] | Team coordinator with shared state |
| [`create_team_toolset`][pydantic_deep.toolsets.teams.create_team_toolset] | Factory for team management tools |

## Next Steps

- [Checkpointing](checkpointing.md) — Save and rewind conversation state
- [Hooks](hooks.md) — Claude Code-style lifecycle hooks
- [Subagents](subagents.md) — Parent-child delegation
