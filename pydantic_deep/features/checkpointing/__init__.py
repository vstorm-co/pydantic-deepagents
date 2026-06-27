"""Conversation checkpointing: snapshots, stores, auto-checkpoint capability, tools.

`Checkpoint` is an immutable snapshot of conversation state; `CheckpointStore`
is the persistence protocol (in-memory and file-backed implementations);
`CheckpointMiddleware` auto-saves checkpoints; `CheckpointToolset` exposes
save/list/rewind tools; `fork_from_checkpoint` forks a session from a snapshot.
"""

from pydantic_deep.features.checkpointing.store import (
    Checkpoint,
    CheckpointStore,
    FileCheckpointStore,
    InMemoryCheckpointStore,
    RewindRequested,
    fork_from_checkpoint,
)
from pydantic_deep.features.checkpointing.toolset import (
    CheckpointFrequency,
    CheckpointMiddleware,
    CheckpointToolset,
)

__all__ = [
    "Checkpoint",
    "CheckpointStore",
    "FileCheckpointStore",
    "InMemoryCheckpointStore",
    "RewindRequested",
    "fork_from_checkpoint",
    "CheckpointFrequency",
    "CheckpointMiddleware",
    "CheckpointToolset",
]
