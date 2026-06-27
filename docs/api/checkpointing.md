# Checkpointing API

Conversation checkpointing lets an agent snapshot its state and rewind to an
earlier turn. Enable it via `include_checkpoints=True` on
[`create_deep_agent`][pydantic_deep.agent.create_deep_agent]. See
[Checkpointing](../learn/sessions.md) for the conceptual overview.

## Checkpoint

::: pydantic_deep.features.checkpointing.Checkpoint
    options:
      show_source: false

## CheckpointStore

::: pydantic_deep.features.checkpointing.CheckpointStore
    options:
      show_source: false

## InMemoryCheckpointStore

::: pydantic_deep.features.checkpointing.InMemoryCheckpointStore
    options:
      show_source: false

## FileCheckpointStore

::: pydantic_deep.features.checkpointing.FileCheckpointStore
    options:
      show_source: false

## CheckpointMiddleware

::: pydantic_deep.features.checkpointing.CheckpointMiddleware
    options:
      show_source: false

## CheckpointToolset

::: pydantic_deep.features.checkpointing.CheckpointToolset
    options:
      show_source: false

## RewindRequested

::: pydantic_deep.features.checkpointing.RewindRequested
    options:
      show_source: false

## fork_from_checkpoint

::: pydantic_deep.features.checkpointing.fork_from_checkpoint
    options:
      show_source: false
