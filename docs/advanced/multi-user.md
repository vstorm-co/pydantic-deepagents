# Multi-user / multi-tenant

One agent, many users — without their state ever touching.

The trick is already built in: **dependencies are per-run, not per-agent.** You create the agent once, then hand each `agent.run()` a fresh `DeepAgentDeps` scoped to *that* user. Same model, same tools, same instructions — different backend, different memory, different sandbox.

## The one rule

Every stateful feature — memory, checkpoints, plans, evicted files — reads and writes through `ctx.deps.backend`. So the question "do two users share state?" has exactly one answer: *do they share a backend?*

Give each user their own, and they're isolated. That's the whole idea.

```python
from pydantic_deep import create_deep_agent, DeepAgentDeps
from pydantic_ai_backends import LocalBackend

agent = create_deep_agent(include_memory=True)  # (1)!


async def handle_request(user_id: str, message: str) -> str:
    deps = DeepAgentDeps(
        backend=LocalBackend(root_dir=f"/workspaces/{user_id}"),  # (2)!
    )
    result = await agent.run(message, deps=deps)  # (3)!
    return result.output
```

1. The agent is built **once**, at import time. It holds no user state.
2. The `deps` are built **per request**, scoped to one user.
3. You pass them in at run time — so every user gets the same agent with their own world.

## Dissect it

### One agent, built once

```python hl_lines="1"
agent = create_deep_agent(include_memory=True)
```

`create_deep_agent()` returns a stateless object. It knows *how* to use a filesystem, memory, and a shell — but not *whose*. Create it at module scope and reuse it for every request.

### Deps, built per user

```python hl_lines="2 3"
deps = DeepAgentDeps(
    backend=LocalBackend(root_dir=f"/workspaces/{user_id}"),
)
```

This is where isolation happens. `DeepAgentDeps` is the per-run bundle of "where state lives." Point its backend at a per-user directory and user `alice` can never read user `bob`'s files — they're in different folders on disk.

!!! info "Why this works"
    Pydantic AI passes `deps` into every tool call as `ctx.deps`. The agent
    literally cannot reach a backend you didn't give it. Isolation isn't a
    feature you enable — it's a consequence of building deps per run.

## Choosing a backend

The backend is the dial you turn for the isolation-vs-persistence trade-off. Same `handle_request` shape every time — only the backend line changes.

=== "Ephemeral (in memory)"

    ```python hl_lines="4"
    from pydantic_deep import DeepAgentDeps, InMemoryCheckpointStore
    from pydantic_ai_backends import StateBackend

    deps = DeepAgentDeps(
        backend=StateBackend(),  # gone when the request ends
        checkpoint_store=InMemoryCheckpointStore(),
    )
    ```

    Full isolation, zero setup. Nothing survives between sessions — good for
    one-shot tasks or testing.

=== "Persistent (on disk)"

    ```python hl_lines="4 5"
    from pydantic_deep import DeepAgentDeps, FileCheckpointStore
    from pydantic_ai_backends import LocalBackend

    deps = DeepAgentDeps(
        backend=LocalBackend(root_dir=f"/workspaces/{user_id}"),
        checkpoint_store=FileCheckpointStore(f"/checkpoints/{user_id}"),
    )
    ```

    Isolation **and** persistence — a user's memory and files are still there
    next session. No process-level sandbox, so don't run untrusted code here.

=== "Sandboxed (Docker)"

    ```python hl_lines="5 6"
    from pydantic_deep import DeepAgentDeps, FileCheckpointStore
    from pydantic_ai_backends import SessionManager

    session_manager = SessionManager(workspace_root="/workspaces")

    sandbox = await session_manager.get_or_create(user_id)
    deps = DeepAgentDeps(
        backend=sandbox,
        checkpoint_store=FileCheckpointStore(f"/checkpoints/{user_id}"),
    )
    ```

    A real container per user. Full isolation, persistence, and safe execution
    of untrusted code. Needs Docker; costs more per user.

!!! tip "SessionManager reuses containers"
    `get_or_create(user_id)` hands back the *same* sandbox for a returning user
    instead of spinning up a fresh one — so persistence and warm starts come for
    free.

## Don't forget the side channels

The backend covers most state, but two things live outside it. Scope them per user too, or they leak.

| State | Per-user via | If you skip it |
|-------|--------------|----------------|
| Files, memory, plans, evicted output | `backend=` | Users see each other's files |
| Checkpoints | `checkpoint_store=` | Users see each other's checkpoints |
| Message history | your own store, keyed by user | Conversations bleed together |

Memory, plans, and evicted files all route through the backend, so a per-user backend handles them in one move. Checkpoints use a separate store. Message history is yours to keep — `agent.run()` doesn't remember anything between calls.

## Putting it together (FastAPI)

A complete tenant-aware endpoint: one agent, deps per request, history kept per user.

```python hl_lines="11 16 21"
from fastapi import FastAPI
from pydantic_deep import create_deep_agent, DeepAgentDeps, FileCheckpointStore
from pydantic_ai_backends import LocalBackend

agent = create_deep_agent(include_memory=True, include_checkpoints=True)
app = FastAPI()

# One conversation history per user. Use a real datastore in production.
user_histories: dict[str, list] = {}


def get_deps(user_id: str) -> DeepAgentDeps:
    """Build isolated dependencies for one user."""
    return DeepAgentDeps(
        backend=LocalBackend(root_dir=f"/workspaces/{user_id}"),
        checkpoint_store=FileCheckpointStore(f"/checkpoints/{user_id}"),
    )


@app.post("/chat/{user_id}")
async def chat(user_id: str, message: str):
    deps = get_deps(user_id)
    history = user_histories.get(user_id, [])

    result = await agent.run(message, deps=deps, message_history=history)
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

Multi-tenancy falls out of one design decision: deps are per-run.

- Build the **agent once**; it's stateless and shared across every request.
- Build **`DeepAgentDeps` per user** — that's where isolation lives.
- Pick the **backend** for your trade-off: `StateBackend` (ephemeral), `LocalBackend(root_dir=...)` (persistent), or a `SessionManager` sandbox (isolated execution).
- Scope the **checkpoint store** and **message history** per user too — they live outside the backend.

Where to go next:

- [Backends](../concepts/backends.md) — the full menu of storage and execution backends
- [Memory & context files](../learn/memory.md) — what persists per user, and where
- [Sessions & checkpoints](../learn/sessions.md) — saving and resuming a user's conversation
