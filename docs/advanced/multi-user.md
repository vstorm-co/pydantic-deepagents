# Multi-user / multi-tenant

One agent, many users — without their state ever touching.

The trick is already built in: **workspaces and dependencies are per-run, not per-agent.** You create the agent once, then hand each `agent.run()` the workspace and the `DeepAgentDeps` of *that* user. Same model, same tools, same instructions — different files, different memory, different sandbox.

## The one rule

Every stateful feature — files, memory, plans, evicted output, uploads — reads and writes through the run's workspace, `ctx.workspace`. So the question "do two users share state?" has exactly one answer: *do they share a workspace?*

Give each user their own, and they're isolated. That's the whole idea.

```python
from pydantic_ai.workspaces import Workspace, LocalWorkspaceBackend
from pydantic_deep import ConfinedWorkspace, create_deep_agent, DeepAgentDeps

agent = create_deep_agent(workspace=False, include_memory=True)  # (1)!


async def handle_request(user_id: str, message: str) -> str:
    workspace = ConfinedWorkspace(Workspace(LocalWorkspaceBackend(f"/workspaces/{user_id}")))  # (2)!
    result = await agent.run(message, deps=DeepAgentDeps(), workspace=workspace)  # (3)!
    return result.output
```

1. The agent is built **once**, at import time. `workspace=False` means it holds no workspace of its own: every run must bring one.
2. The workspace is chosen **per request**, scoped to one user.
3. You pass it in at run time — so every user gets the same agent with their own world.

## Dissect it

### One agent, built once

```python hl_lines="1"
agent = create_deep_agent(workspace=False, include_memory=True)
```

`create_deep_agent()` returns a stateless object. It knows *how* to use a filesystem, memory, and a shell — but not *whose*. Create it at module scope and reuse it for every request. It keeps the shell tool; pass `include_execute=False` when your runs bring a workspace without commands, such as `StateWorkspace`.

### A workspace per user

```python hl_lines="1"
workspace = ConfinedWorkspace(Workspace(LocalWorkspaceBackend(f"/workspaces/{user_id}")))
```

This is where isolation happens. Point each run at a per-user directory, confined, and the file tools of user `alice` cannot reach user `bob`'s files: a path outside her directory - absolute, `..`, or through a symlink - is refused.

!!! warning "The shell is not confined"
    `ConfinedWorkspace` keeps the **file tools** in the directory. A shell
    command reaches whatever the server process can, `bob`'s folder included.
    For users you don't trust with your server, give each one a container -
    the Docker tab below - or turn the shell off with `include_execute=False`.

!!! info "Why this works"
    Pydantic AI hands every tool the run's workspace as `ctx.workspace`. The
    agent literally cannot reach a workspace you didn't give it. Isolation isn't a
    feature you enable — it's a consequence of choosing the workspace per run.

## Choosing a workspace

The workspace is the dial you turn for the isolation-vs-persistence trade-off. Same `handle_request` shape every time — only the workspace line changes.

=== "Ephemeral (in memory)"

    ```python
    from pydantic_ai.workspaces import Workspace
    from pydantic_deep import StateWorkspace

    workspace = Workspace(StateWorkspace().backend())  # gone with the request
    ```

    Full isolation, zero setup, no commands. Nothing survives between
    sessions — good for one-shot tasks or testing.

=== "Persistent (on disk)"

    ```python
    from pydantic_ai.workspaces import Workspace, LocalWorkspaceBackend
    from pydantic_deep import ConfinedWorkspace

    workspace = ConfinedWorkspace(Workspace(LocalWorkspaceBackend(f"/workspaces/{user_id}")))
    ```

    Persistence — a user's memory and files are still there next session — and
    file tools confined to their directory. No process-level sandbox, so the
    shell is not isolated: don't run untrusted code here.

=== "Sandboxed (Docker)"

    ```python
    from pydantic_ai.workspaces import Workspace
    from pydantic_deep import DockerWorkspace

    workspace = Workspace(
        DockerWorkspace(
            volumes={f"/workspaces/{user_id}": "/workspace"},
            container_name=f"agent-{user_id}",
        ).backend()
    )
    ```

    A real container per user. Full isolation, persistence, and safe execution
    of untrusted code. Needs Docker; costs more per user.

!!! tip "A named container is reused"
    The same `container_name` reaches the *same* container for a returning user
    instead of spinning up a fresh one — so warm starts come for free. Containers
    are never removed for you: `await DockerWorkspace(...).destroy(ref)` when a
    user's session ends. See [Docker Runtimes](../examples/docker-runtimes.md#a-container-per-user).

## Don't forget the side channels

The workspace covers most state, but two things live outside it. Scope them per user too, or they leak.

| State | Per-user via | If you skip it |
|-------|--------------|----------------|
| Files, memory, plans, evicted output, uploads | `workspace=` | Users see each other's files |
| Checkpoints | `checkpoint_store=` on `DeepAgentDeps` | Users see each other's checkpoints |
| Message history | your own store, keyed by user | Conversations bleed together |

If users must share one workspace, keep their memory apart with `memory_namespace=` — for example `create_deep_agent(memory_namespace=lambda ctx: ctx.deps.user_id)` — which files each user's notebook under its own segment (letters, digits, `_`, `-` and `.` — hash an e-mail address first). Their other files are still shared.

Checkpoints use a separate store. Message history is yours to keep — `agent.run()` doesn't remember anything between calls. A history also carries the ref of the workspace its run worked in, which is what lets an agent *with* a workspace capability come back to the same one; with `workspace=False`, the workspace you pass always wins.

## Putting it together (FastAPI)

A complete tenant-aware endpoint: one agent, a workspace and deps per request, history kept per user.

```python hl_lines="12 13 22"
from fastapi import FastAPI
from pydantic_ai.workspaces import Workspace, LocalWorkspaceBackend
from pydantic_deep import ConfinedWorkspace, create_deep_agent, DeepAgentDeps, FileCheckpointStore

agent = create_deep_agent(
    workspace=False, include_execute=False, include_memory=True, include_checkpoints=True
)
app = FastAPI()

# One conversation history per user. Use a real datastore in production.
user_histories: dict[str, list] = {}


def user_workspace(user_id: str) -> Workspace:
    return ConfinedWorkspace(Workspace(LocalWorkspaceBackend(f"/workspaces/{user_id}")))


@app.post("/chat/{user_id}")
async def chat(user_id: str, message: str):
    deps = DeepAgentDeps(checkpoint_store=FileCheckpointStore(f"/checkpoints/{user_id}"))
    history = user_histories.get(user_id, [])

    result = await agent.run(
        message, deps=deps, message_history=history, workspace=user_workspace(user_id)
    )
    user_histories[user_id] = result.all_messages()  # (1)!

    return {"response": result.output}
```

1. Persist the full message list per user so the next turn continues their
   conversation — and only theirs.

!!! warning "The history dict is per process"
    `user_histories` here is an in-memory dict — fine for a demo, lost on
    restart and not shared across workers. In production, back it with Redis, a
    database, or per-user checkpoints.

## Recap

Multi-tenancy falls out of one design decision: the workspace is per-run.

- Build the **agent once** with `workspace=False`; it's stateless and shared across every request.
- Pass **each run its user's workspace** — that's where isolation lives.
- Pick the **workspace** for your trade-off: `StateWorkspace` (ephemeral), a confined local directory (persistent, file tools only), or a named Docker container (isolated execution).
- Scope the **checkpoint store** and **message history** per user too — they live outside the workspace.

Where to go next:

- [Workspaces](../concepts/workspaces.md) — every workspace, and how to choose
- [Memory & context files](../learn/memory.md) — what persists per user, and where
- [Sessions & checkpoints](../learn/sessions.md) — saving and resuming a user's conversation
