# Checkpointing

pydantic-deep supports conversation checkpointing — saving snapshots of conversation state at key points so the agent (or user) can **rewind** to any checkpoint or **fork** from a checkpoint into a new session.

## Quick Start

```python
from pydantic_deep import create_deep_agent, InMemoryCheckpointStore

store = InMemoryCheckpointStore()
agent = create_deep_agent(
    include_checkpoints=True,
    checkpoint_store=store,
    checkpoint_frequency="every_tool",  # auto-save after each tool call
)
```

The agent now has three tools:

| Tool | Description |
|------|-------------|
| `save_checkpoint` | Label the most recent auto-checkpoint with a custom name |
| `list_checkpoints` | Show all saved checkpoints with labels and metadata |
| `rewind_to` | Rewind conversation to a checkpoint (raises `RewindRequested`) |

## Configuration

### `create_deep_agent()` Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `include_checkpoints` | `bool` | `False` | Enable checkpointing |
| `checkpoint_frequency` | `str` | `"every_tool"` | When to auto-save: `"every_tool"`, `"every_turn"`, or `"manual_only"` |
| `max_checkpoints` | `int` | `20` | Maximum checkpoints to keep (oldest pruned first) |
| `checkpoint_store` | `CheckpointStore` | `InMemoryCheckpointStore()` | Storage backend for checkpoints |

### Checkpoint Frequencies

=== "every_tool"
    Saves a checkpoint after each tool call. Provides the finest granularity for rewinding.

    ```python
    agent = create_deep_agent(
        include_checkpoints=True,
        checkpoint_frequency="every_tool",
    )
    ```

=== "every_turn"
    Saves a checkpoint before each model request (i.e. at the start of each turn).

    ```python
    agent = create_deep_agent(
        include_checkpoints=True,
        checkpoint_frequency="every_turn",
    )
    ```

=== "manual_only"
    No auto-checkpoints. The agent must explicitly call `save_checkpoint`.

    ```python
    agent = create_deep_agent(
        include_checkpoints=True,
        checkpoint_frequency="manual_only",
    )
    ```

## Checkpoint Stores

### InMemoryCheckpointStore

Default store. Checkpoints are kept in a Python dict — fast, but lost when the process exits.

```python
from pydantic_deep import InMemoryCheckpointStore

store = InMemoryCheckpointStore()
```

### FileCheckpointStore

Persists checkpoints as JSON files on disk. Each checkpoint is a separate file in the given directory.

```python
from pydantic_deep import FileCheckpointStore

store = FileCheckpointStore("/path/to/checkpoints")
```

Messages are serialized using pydantic-ai's `ModelMessagesTypeAdapter`, so all message types (text, tool calls, tool results) are preserved.

### Custom Store

Implement the [`CheckpointStore`][pydantic_deep.toolsets.checkpointing.CheckpointStore] protocol:

```python
from pydantic_deep.toolsets.checkpointing import Checkpoint, CheckpointStore

class RedisCheckpointStore:
    async def save(self, checkpoint: Checkpoint) -> None: ...
    async def get(self, checkpoint_id: str) -> Checkpoint | None: ...
    async def get_by_label(self, label: str) -> Checkpoint | None: ...
    async def list_all(self) -> list[Checkpoint]: ...
    async def remove(self, checkpoint_id: str) -> bool: ...
    async def remove_oldest(self) -> bool: ...
    async def count(self) -> int: ...
    async def clear(self) -> None: ...
```

## Rewinding

When the agent calls `rewind_to`, a [`RewindRequested`][pydantic_deep.toolsets.checkpointing.RewindRequested] exception propagates out of `agent.run()`. Your application loop catches it and restores the conversation:

```python
from pydantic_deep import create_deep_agent, DeepAgentDeps, RewindRequested
from pydantic_ai_backends import StateBackend

agent = create_deep_agent(include_checkpoints=True)
deps = DeepAgentDeps(backend=StateBackend())
message_history = []

while True:
    user_input = input("> ")
    try:
        result = await agent.run(
            user_input,
            deps=deps,
            message_history=message_history,
        )
        message_history = result.all_messages()
        print(result.output)
    except RewindRequested as e:
        print(f"Rewinding to '{e.label}'...")
        message_history = e.messages
```

## Session Forking

Fork creates a new session from a checkpoint — the original session stays unchanged.

```python
from pydantic_deep import fork_from_checkpoint, InMemoryCheckpointStore

store = InMemoryCheckpointStore()
# ... after some conversation with checkpoints saved ...

# Fork from a specific checkpoint
messages = await fork_from_checkpoint(store, checkpoint_id="abc123")

# Start a new session with the forked history
new_result = await agent.run(
    "Try a different approach",
    deps=new_deps,
    message_history=messages,
)
```

## Per-Session Stores

For multi-user applications, set `checkpoint_store` on deps at runtime:

```python
from pydantic_deep import DeepAgentDeps, FileCheckpointStore

# Each user gets their own checkpoint store
deps = DeepAgentDeps(
    backend=backend,
    checkpoint_store=FileCheckpointStore(f"/checkpoints/{user_id}"),
)
```

The middleware resolves the store from `deps.checkpoint_store` first, falling back to the store passed at agent creation time.

!!! warning "Multi-User Applications"
    Always create a fresh `CheckpointStore` per user session. A shared
    `InMemoryCheckpointStore` means all users see each other's checkpoints.
    See [Multi-User Guide](multi-user.md).

## Components

| Component | Description |
|-----------|-------------|
| [`Checkpoint`][pydantic_deep.toolsets.checkpointing.Checkpoint] | Immutable snapshot: id, label, turn, messages, metadata |
| [`CheckpointStore`][pydantic_deep.toolsets.checkpointing.CheckpointStore] | Protocol for storage backends |
| [`InMemoryCheckpointStore`][pydantic_deep.toolsets.checkpointing.InMemoryCheckpointStore] | Default in-memory store |
| [`FileCheckpointStore`][pydantic_deep.toolsets.checkpointing.FileCheckpointStore] | Persistent JSON file store |
| [`CheckpointMiddleware`][pydantic_deep.toolsets.checkpointing.CheckpointMiddleware] | Auto-save middleware |
| [`CheckpointToolset`][pydantic_deep.toolsets.checkpointing.CheckpointToolset] | Agent tools (save, list, rewind) |
| [`RewindRequested`][pydantic_deep.toolsets.checkpointing.RewindRequested] | Exception for app-level rewind |
| [`fork_from_checkpoint`][pydantic_deep.toolsets.checkpointing.fork_from_checkpoint] | Utility for session forking |

## Next Steps

- [Teams](teams.md) — Multi-agent collaboration with shared state
- [Hooks](hooks.md) — Claude Code-style lifecycle hooks
- [Human-in-the-Loop](human-in-the-loop.md) — Approval workflows
