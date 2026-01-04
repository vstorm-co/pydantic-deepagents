"""Agent checkpointing for resuming long-running tasks.

This module provides checkpointing capabilities to save and restore agent state,
enabling recovery from failures and resumption of long-running tasks.

Example:
    ```python
    from pathlib import Path
    from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend
    from pydantic_deep.checkpointing import (
        CheckpointManager,
        FileCheckpointBackend,
        run_with_checkpointing,
    )

    # Create checkpoint manager
    backend = FileCheckpointBackend(Path("/tmp/checkpoints"))
    manager = CheckpointManager(backend=backend, frequency="iteration")

    # Run with automatic checkpointing
    agent = create_deep_agent(model="openai:gpt-4o")
    deps = DeepAgentDeps(backend=StateBackend())

    result = await run_with_checkpointing(
        agent=agent,
        prompt="Long running task",
        deps=deps,
        checkpoint_manager=manager,
    )

    # Resume from checkpoint if needed
    checkpoint_id = manager.last_checkpoint_id
    result = await run_with_checkpointing(
        agent=agent,
        prompt="Long running task",
        deps=deps,
        checkpoint_manager=manager,
        resume_from=checkpoint_id,
    )
    ```
"""

from pydantic_deep.checkpointing.backends import (
    FileCheckpointBackend,
    StateCheckpointBackend,
)
from pydantic_deep.checkpointing.manager import (
    CheckpointManager,
    create_manual_checkpoint,
    run_with_checkpointing,
)
from pydantic_deep.checkpointing.types import (
    Checkpoint,
    CheckpointError,
    CheckpointNotFoundError,
    CheckpointProtocol,
    CheckpointValidationError,
    CheckpointVersionError,
    generate_checkpoint_id,
    validate_checkpoint,
)

__all__ = [
    # Manager
    "CheckpointManager",
    "run_with_checkpointing",
    "create_manual_checkpoint",
    # Backends
    "FileCheckpointBackend",
    "StateCheckpointBackend",
    # Types
    "Checkpoint",
    "CheckpointProtocol",
    # Exceptions
    "CheckpointError",
    "CheckpointNotFoundError",
    "CheckpointValidationError",
    "CheckpointVersionError",
    # Utilities
    "generate_checkpoint_id",
    "validate_checkpoint",
]
