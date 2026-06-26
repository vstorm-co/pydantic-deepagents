"""Deprecated import location for the checkpointing feature.

The implementation moved to :mod:`pydantic_deep.features.checkpointing` (see the
CHANGELOG). This module re-exports the public names for backward compatibility
and will be removed in the next minor release. Import from
``pydantic_deep.features.checkpointing`` or the top-level ``pydantic_deep``
instead.
"""

from __future__ import annotations

import warnings

from pydantic_deep.features.checkpointing import (
    Checkpoint,
    CheckpointFrequency,
    CheckpointMiddleware,
    CheckpointStore,
    CheckpointToolset,
    FileCheckpointStore,
    InMemoryCheckpointStore,
    RewindRequested,
    fork_from_checkpoint,
)

__all__ = [
    "Checkpoint",
    "CheckpointFrequency",
    "CheckpointMiddleware",
    "CheckpointStore",
    "CheckpointToolset",
    "FileCheckpointStore",
    "InMemoryCheckpointStore",
    "RewindRequested",
    "fork_from_checkpoint",
]

warnings.warn(
    "pydantic_deep.toolsets.checkpointing has moved to "
    "pydantic_deep.features.checkpointing; update your imports "
    "(this shim will be removed in the next minor release).",
    DeprecationWarning,
    stacklevel=2,
)
