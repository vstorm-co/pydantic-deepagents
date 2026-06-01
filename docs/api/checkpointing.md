# Checkpointing API

Conversation checkpointing lets an agent snapshot its state and rewind to an
earlier turn. Enable it via `include_checkpoints=True` on
[`create_deep_agent`][pydantic_deep.agent.create_deep_agent]. See
[Checkpointing](../advanced/checkpointing.md) for the conceptual overview.

## Checkpoint

::: pydantic_deep.toolsets.checkpointing.Checkpoint
    options:
      show_source: false

## CheckpointStore

::: pydantic_deep.toolsets.checkpointing.CheckpointStore
    options:
      show_source: false

## InMemoryCheckpointStore

::: pydantic_deep.toolsets.checkpointing.InMemoryCheckpointStore
    options:
      show_source: false

## FileCheckpointStore

::: pydantic_deep.toolsets.checkpointing.FileCheckpointStore
    options:
      show_source: false

## CheckpointMiddleware

::: pydantic_deep.toolsets.checkpointing.CheckpointMiddleware
    options:
      show_source: false

## CheckpointToolset

::: pydantic_deep.toolsets.checkpointing.CheckpointToolset
    options:
      show_source: false

## RewindRequested

::: pydantic_deep.toolsets.checkpointing.RewindRequested
    options:
      show_source: false

## fork_from_checkpoint

::: pydantic_deep.toolsets.checkpointing.fork_from_checkpoint
    options:
      show_source: false
