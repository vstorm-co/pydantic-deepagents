# Agent teams

Spin up a flat group of peer agents that work the same problem together — sharing a TODO list, messaging each other, and running in parallel.

[Subagents](../learn/subagents.md) give you a *hierarchy*: a parent hands a subtask down to a child, waits, and gets one answer back. A **team** is the other shape — a group of equals tackling a problem side by side. Reach for a team when the work isn't "do this for me" but "let's split this up and coordinate."

```python
from pydantic_deep import create_deep_agent

agent = create_deep_agent(
    include_teams=True,
    include_subagents=True,  # teams run on the subagent engine
)
```

## Run it

That single flag gives the agent five new tools and the machinery behind them. Ask it to do something collaborative:

<div class="termy">

```console
$ python main.py
```

</div>

The agent spawns a named team, assigns each member a task, lets them run in the background, polls them with `check_teammates`, and dissolves the team when the work is done. You wrote none of the coordination.

!!! note "Why `include_subagents=True`?"
    Teams don't have their own execution engine — they *delegate* to the
    subagent system. Each team member is registered as a subagent and runs as a
    real deep agent in the background. Without subagents enabled, `spawn_team`
    creates the team but `assign_task` has nothing to run.

## The five team tools

Enabling teams registers one toolset on the agent. Here's what the model can reach for:

| Tool | What it does |
|------|--------------|
| `spawn_team` | Create a team and register each member as a subagent. One team active at a time. |
| `assign_task` | Hand a task to a member and start it running in the background. |
| `check_teammates` | Report every member's status, a result preview, and the shared task list. |
| `message_teammate` | Send a direct message to one member. |
| `dissolve_team` | Stop all members and release resources. |

A typical flow is `spawn_team` → `assign_task` (per member) → `check_teammates` (repeat until done) → `dissolve_team`. Members run concurrently, so two `assign_task` calls mean two agents working at once.

!!! tip "Specialists, not clones"
    Each member carries its own `name`, `role`, `description`, `instructions`,
    and `model`. The payoff comes from *specialization* — one member writes the
    code, another writes the tests, a third reviews — not from running the same
    agent three times.

## How it fits together

When the agent calls `spawn_team`, the toolset builds an [`AgentTeam`][pydantic_deep.features.teams.AgentTeam] holding two pieces of shared state and registers each [`TeamMember`][pydantic_deep.features.teams.TeamMember] as a subagent. `assign_task` then drops the task onto the shared TODO list and kicks off the subagent's `task()` tool in async mode.

```
                    Main Agent
                        │
   spawn_team ──► AgentTeam ──► register members as subagents
   assign_task ──► shared TODO + subagent task(async)
   check_teammates ──► reads TaskManager status
   dissolve_team ──► cancels tasks, unregisters everyone
                        │
        ┌───────────────┴───────────────┐
   SharedTodoList                  TeamMessageBus
   (who does what)                 (peer-to-peer chat)
        │                                │
   ┌────┴────┬─────────┬──────────┐
 Member A  Member B  Member C   (real agents, running)
```

The two shared objects — the TODO list and the message bus — are what make a team more than parallel subagents. Let's look at each.

## Shared TODOs with dependencies

[`SharedTodoList`][pydantic_deep.features.teams.SharedTodoList] is an asyncio-safe task tracker. Unlike the regular todo list, its items can be *claimed* by a member and *blocked* on other items — so a team can express "this can't start until that finishes."

```python
from pydantic_deep.features.teams import SharedTodoList

todos = SharedTodoList()

task_a = await todos.add("Design the API schema", created_by="lead")
task_b = await todos.add(
    "Implement the endpoints",
    blocked_by=[task_a],          # waits for task_a
    created_by="lead",
)

await todos.claim(task_a, "alice")   # True  — alice owns it
await todos.claim(task_b, "bob")     # False — still blocked by task_a
await todos.complete(task_a)
await todos.claim(task_b, "bob")     # True  — dependency cleared
```

`claim()` returns `False` (not an error) when an item is already taken, not pending, or blocked by something unfinished — so members can poll for work without stepping on each other. Use [`get_available()`][pydantic_deep.features.teams.SharedTodoList] to list exactly the items a member is allowed to pick up right now.

Each [`SharedTodoItem`][pydantic_deep.features.teams.SharedTodoItem] carries the coordination fields:

| Field | Type | Meaning |
|-------|------|---------|
| `id` | `str` | Auto-generated short id. |
| `content` | `str` | The task description. |
| `status` | `str` | `"pending"`, `"in_progress"`, or `"completed"`. |
| `assigned_to` | `str \| None` | The member that claimed it. |
| `blocked_by` | `list[str]` | IDs that must complete first. |
| `created_by` | `str \| None` | Who added it. |

## The message bus

[`TeamMessageBus`][pydantic_deep.features.teams.TeamMessageBus] is peer-to-peer: any registered member can message any other, or broadcast to everyone. Each member has its own asyncio inbox.

```python
from pydantic_deep.features.teams import TeamMessageBus

bus = TeamMessageBus()
bus.register("alice")
bus.register("bob")

await bus.send("alice", "bob", "Can you review my changes?")
await bus.broadcast("alice", "Starting on the API schema")  # everyone but alice

for msg in await bus.receive("bob"):
    print(f"{msg.sender}: {msg.content}")
```

`receive()` drains whatever is waiting and returns immediately; pass `timeout=` to block for a message when the inbox is empty. `send()` raises `KeyError` if the recipient was never registered — so members can't message someone who isn't on the team. Behind the `message_teammate` tool, the lead sends as `"team_lead"`.

## A short example

Here's the whole loop the agent runs on your behalf, written out by hand so you can see the shape:

```python hl_lines="6 12 17"
from pydantic_deep.features.teams import AgentTeam, TeamMember

team = AgentTeam(
    name="api-build",
    members=[
        TeamMember(name="builder", role="dev",  description="writes code",  instructions="Implement the endpoints."),
        TeamMember(name="tester",  role="qa",   description="writes tests", instructions="Write pytest coverage."),
    ],
)

await team.spawn()                              # register members + inboxes
await team.assign("builder", "Build /users")    # add to shared todos, claim it
await team.assign("tester", "Test /users")
await team.broadcast("Kickoff — ship by EOD")   # message every member
results = await team.wait_all()                 # block until both finish
await team.dissolve()                           # cancel + clean up
```

In a real run the model calls the *tools* (`spawn_team`, `assign_task`, …) rather than this API directly, and execution flows through the subagent engine. But the primitives are public, so you can drive a team programmatically too.

!!! info "Customizing how members are built"
    By default each member becomes a deep agent with filesystem and todo tools.
    To give members web access, different toolsets, or a different setup, pass an
    `agent_factory` to
    [`create_team_toolset`][pydantic_deep.features.teams.create_team_toolset] —
    it's called with each member's config to build that member's agent.

## A lighter option: shared todos via deps

If you don't need a full team and just want subagents to see the parent's todo list, set `share_todos` on your deps instead:

```python
from pydantic_deep import DeepAgentDeps, StateBackend

deps = DeepAgentDeps(
    backend=StateBackend(),
    share_todos=True,   # subagents share the parent's todo list
)
```

This is the lightweight middle ground between isolated subagents and a coordinating team.

## Recap

- A **team** is a flat group of peer agents working one problem; a **subagent** is a child doing one delegated subtask. Pick the team when the work needs coordination, not just delegation.
- `include_teams=True` (plus `include_subagents=True`) adds five tools: `spawn_team`, `assign_task`, `check_teammates`, `message_teammate`, `dissolve_team`.
- [`SharedTodoList`][pydantic_deep.features.teams.SharedTodoList] gives the team claimable, dependency-aware tasks; `claim()` returns `False` rather than failing when an item isn't available.
- [`TeamMessageBus`][pydantic_deep.features.teams.TeamMessageBus] is peer-to-peer messaging with per-member inboxes and broadcast.
- Need less? `share_todos=True` lets subagents share the parent's todo list without a team.

Where to go next:

- [Subagents →](../learn/subagents.md) — parent-child delegation, the other shape.
- [Hooks →](hooks.md) — react to tool events across the lifecycle.
- [Forking →](forking.md) — branch a live run into parallel explorations.
