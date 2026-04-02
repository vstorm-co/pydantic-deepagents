# Agent Teams

Agent teams enable multi-agent collaboration with **shared TODO lists**, **peer-to-peer messaging**, and **real agent execution** via the subagent engine. Unlike plain subagents (parent-child delegation), teams are flat groups of agents that coordinate through shared state.

## Quick Start

```python
from pydantic_deep import create_deep_agent

agent = create_deep_agent(
    include_teams=True,
    include_subagents=True,  # required for execution
)
```

The agent gets five team management tools:

| Tool | Description |
|------|-------------|
| `spawn_team` | Create a team, register members as subagents |
| `assign_task` | Assign a task and start execution in background |
| `check_teammates` | Show member status, results, and shared tasks |
| `message_teammate` | Send a direct message to a team member |
| `dissolve_team` | Shut down the team and clean up |

## How It Works

Teams delegate execution to the subagent engine. When the agent calls `spawn_team`, each member is registered as a subagent. When `assign_task` is called, the subagent `task()` tool runs the member's agent in the background.

```
┌─────────────────────────────────────────────────────────┐
│                     Main Agent                           │
│                                                          │
│  spawn_team(members) ──> registers on DynamicAgentRegistry
│  assign_task(member, description) ──> subagent task(async)
│  check_teammates() ──> reads TaskManager status          │
│  dissolve_team() ──> cleans up registry + team state     │
│                                                          │
│  ┌──────────────┐  ┌──────────────────────┐              │
│  │ SharedTodoList│  │  TeamMessageBus      │              │
│  │  (coordination) │  │  (peer-to-peer)      │              │
│  └──────────────┘  └──────────────────────┘              │
│                                                          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                 │
│  │ Member A │ │ Member B │ │ Member C │  (real agents)   │
│  │ (running)│ │ (idle)   │ │ (done)   │                  │
│  └──────────┘ └──────────┘ └──────────┘                 │
└─────────────────────────────────────────────────────────┘
```

When `include_subagents=True`, team members are created as **deep agents** with filesystem and todo tools. Each member runs independently in the background.

## Custom Agent Factory

By default, team members are created as deep agents with `include_filesystem=True` and `include_todo=True`. You can customize this via `agent_factory`:

```python
from pydantic_deep.toolsets.teams import create_team_toolset

def my_factory(config):
    return create_deep_agent(
        model=config.get("model", "anthropic:claude-sonnet-4-6"),
        instructions=config["instructions"],
        include_filesystem=True,
        include_todo=True,
        web_search=True, web_fetch=True,  # give members web access
    )

team_toolset = create_team_toolset(
    registry=registry,
    agent_factory=my_factory,
    task_fn=task_function,
    task_manager=task_manager,
)
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
await todos.claim(task_a, "alice")    # True -- alice owns it
await todos.claim(task_b, "bob")      # False -- blocked by task_a
await todos.complete(task_a)
await todos.claim(task_b, "bob")      # True -- dependency resolved
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

- [Subagents](subagents.md) -- Parent-child delegation
- [Hooks](hooks.md) -- Claude Code-style lifecycle hooks
- [Checkpointing](checkpointing.md) -- Save and rewind conversation state
