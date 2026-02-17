# Multi-User Applications

All stateful features (memory, checkpoints, plans, evicted files) write to `ctx.deps.backend`. If two users share the same backend instance, they share **all** state. This page explains how to isolate per-user state in web applications.

## The Problem

By default, `create_deep_agent()` is single-user:

```python
from pydantic_deep import create_deep_agent, DeepAgentDeps
from pydantic_ai_backends import StateBackend

agent = create_deep_agent(include_memory=True)

# One backend = one shared state
deps = DeepAgentDeps(backend=StateBackend())  # (1)!
```

1. If two users share this `deps`, they share the same memory, plans, and evicted files.

Features that write to the backend:

| Feature | Storage Path | Risk |
|---------|-------------|------|
| Memory | `/.deep/memory/{agent}/MEMORY.md` | Users see each other's memories |
| Plans | `/plans/{slug}-{uuid}.md` | Low — UUIDs prevent collisions, but users see all plans |
| Eviction | `/large_tool_results/{call_id}` | Low — unique IDs, but files accumulate |
| Context files | `/DEEP.md`, `/AGENTS.md` | None — typically read-only, shared by design |
| Checkpoints | `CheckpointStore` (separate) | Users see each other's checkpoints |

## Isolation Strategies

### Pattern A: Fresh StateBackend per Session

Simplest approach. Each user/session gets its own in-memory backend:

```python
from pydantic_deep import create_deep_agent, DeepAgentDeps, InMemoryCheckpointStore
from pydantic_ai_backends import StateBackend

agent = create_deep_agent(include_memory=True, include_checkpoints=True)

async def handle_request(user_id: str, message: str):
    # Each session gets isolated state
    deps = DeepAgentDeps(
        backend=StateBackend(),
        checkpoint_store=InMemoryCheckpointStore(),
    )
    result = await agent.run(message, deps=deps)
    return result.output
```

**Pros:** Full isolation, no setup.
**Cons:** State lost between sessions — memory, files, and checkpoints don't persist.

### Pattern B: LocalBackend with User Prefix

Each user gets a separate directory on the host filesystem:

```python
from pydantic_deep import create_deep_agent, DeepAgentDeps, FileCheckpointStore
from pydantic_ai_backends import LocalBackend

agent = create_deep_agent(include_memory=True, include_checkpoints=True)

async def handle_request(user_id: str, message: str):
    deps = DeepAgentDeps(
        backend=LocalBackend(root_dir=f"/workspaces/{user_id}"),
        checkpoint_store=FileCheckpointStore(f"/checkpoints/{user_id}"),
    )
    result = await agent.run(message, deps=deps)
    return result.output
```

**Pros:** Isolation + persistence. Memory survives across sessions.
**Cons:** No process-level sandboxing — agents can't run untrusted code safely.

### Pattern C: DockerSandbox + SessionManager

Full isolation with per-user Docker containers. Best for production:

```python
from pydantic_deep import create_deep_agent, DeepAgentDeps, FileCheckpointStore
from pydantic_ai_backends import DockerSandbox, SessionManager

agent = create_deep_agent(include_memory=True, include_checkpoints=True)
session_manager = SessionManager(workspace_root="/workspaces")

async def handle_request(user_id: str, message: str):
    sandbox = await session_manager.get_or_create(user_id)
    deps = DeepAgentDeps(
        backend=sandbox,
        checkpoint_store=FileCheckpointStore(f"/checkpoints/{user_id}"),
    )
    result = await agent.run(message, deps=deps)
    return result.output
```

**Pros:** Full isolation, persistence, sandboxed code execution.
**Cons:** Requires Docker. Higher resource usage per user.

## Complete Example (FastAPI)

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends
from pydantic_deep import create_deep_agent, DeepAgentDeps, InMemoryCheckpointStore
from pydantic_ai_backends import LocalBackend

agent = create_deep_agent(
    include_memory=True,
    include_checkpoints=True,
)

# Store per-user message histories in memory
user_histories: dict[str, list] = {}


def get_deps(user_id: str) -> DeepAgentDeps:
    """Create isolated deps for each user."""
    return DeepAgentDeps(
        backend=LocalBackend(root_dir=f"/workspaces/{user_id}"),
        checkpoint_store=InMemoryCheckpointStore(),
    )


app = FastAPI()


@app.post("/chat/{user_id}")
async def chat(user_id: str, message: str):
    deps = get_deps(user_id)
    history = user_histories.get(user_id, [])

    result = await agent.run(message, deps=deps, message_history=history)
    user_histories[user_id] = result.all_messages()

    return {"response": result.output}
```

## Checklist

When building a multi-user application:

- [ ] Create a **separate `backend`** per user (or per session)
- [ ] Create a **separate `CheckpointStore`** per user if using checkpoints
- [ ] Store **message histories** per user (don't share `message_history` across users)
- [ ] Consider whether **memory should persist** across sessions (Pattern B/C) or be ephemeral (Pattern A)
- [ ] Use **DockerSandbox** if agents execute untrusted code

## Next Steps

- [Memory](memory.md) — Persistent agent memory
- [Checkpointing](checkpointing.md) — Conversation checkpointing
- [Backends](../concepts/backends.md) — Backend options
