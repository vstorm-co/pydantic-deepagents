"""Types for agent checkpointing.

This module defines the data structures and protocols used for
saving and restoring agent state during long-running tasks.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


@dataclass
class Checkpoint:
    """Represents a saved agent state.

    A checkpoint captures the complete state of an agent at a specific point
    in time, allowing execution to be resumed from that point if interrupted.

    Attributes:
        checkpoint_id: Unique identifier for this checkpoint
        agent_name: Name of the agent that created this checkpoint
        run_id: Unique identifier for the agent run
        timestamp: When this checkpoint was created
        messages: Message history at checkpoint time
        iteration_count: Number of iterations completed
        total_tokens: Total tokens used up to this point
        total_cost_usd: Total cost in USD up to this point
        metadata: Additional checkpoint-specific data
        version: Checkpoint format version for compatibility
    """

    checkpoint_id: str
    agent_name: str
    run_id: str
    timestamp: datetime
    messages: list[dict[str, Any]]
    iteration_count: int
    total_tokens: int
    total_cost_usd: float
    metadata: dict[str, Any] = field(default_factory=dict)
    version: str = "1.0"

    def to_dict(self) -> dict[str, Any]:
        """Convert checkpoint to dictionary for serialization."""
        return {
            "checkpoint_id": self.checkpoint_id,
            "agent_name": self.agent_name,
            "run_id": self.run_id,
            "timestamp": self.timestamp.isoformat(),
            "messages": self.messages,
            "iteration_count": self.iteration_count,
            "total_tokens": self.total_tokens,
            "total_cost_usd": self.total_cost_usd,
            "metadata": self.metadata,
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Checkpoint":
        """Create checkpoint from dictionary."""
        return cls(
            checkpoint_id=data["checkpoint_id"],
            agent_name=data["agent_name"],
            run_id=data["run_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            messages=data["messages"],
            iteration_count=data["iteration_count"],
            total_tokens=data["total_tokens"],
            total_cost_usd=data["total_cost_usd"],
            metadata=data.get("metadata", {}),
            version=data.get("version", "1.0"),
        )


class CheckpointProtocol(Protocol):
    """Protocol for checkpoint storage backends.

    Implementations provide different storage mechanisms (filesystem, database, S3, etc.)
    for persisting and retrieving checkpoints.
    """

    async def save_checkpoint(self, checkpoint: Checkpoint) -> str:
        """Save a checkpoint and return its ID.

        Args:
            checkpoint: The checkpoint to save

        Returns:
            The checkpoint ID

        Raises:
            CheckpointError: If save fails
        """
        ...

    async def load_checkpoint(self, checkpoint_id: str) -> Checkpoint:
        """Load a checkpoint by ID.

        Args:
            checkpoint_id: ID of the checkpoint to load

        Returns:
            The loaded checkpoint

        Raises:
            CheckpointNotFoundError: If checkpoint doesn't exist
            CheckpointError: If load fails
        """
        ...

    async def list_checkpoints(
        self,
        agent_name: str | None = None,
        run_id: str | None = None,
        limit: int | None = None,
    ) -> list[Checkpoint]:
        """List available checkpoints.

        Args:
            agent_name: Filter by agent name (optional)
            run_id: Filter by run ID (optional)
            limit: Maximum number of checkpoints to return (optional)

        Returns:
            List of checkpoints, sorted by timestamp (newest first)
        """
        ...

    async def delete_checkpoint(self, checkpoint_id: str) -> None:
        """Delete a checkpoint.

        Args:
            checkpoint_id: ID of the checkpoint to delete

        Raises:
            CheckpointNotFoundError: If checkpoint doesn't exist
        """
        ...

    async def cleanup_old_checkpoints(
        self,
        run_id: str,
        keep_last: int = 5,
    ) -> int:
        """Clean up old checkpoints for a run, keeping only the most recent.

        Args:
            run_id: Run ID to clean up checkpoints for
            keep_last: Number of most recent checkpoints to keep

        Returns:
            Number of checkpoints deleted
        """
        ...


class CheckpointError(Exception):
    """Base exception for checkpoint-related errors."""

    pass


class CheckpointNotFoundError(CheckpointError):
    """Checkpoint was not found."""

    def __init__(self, checkpoint_id: str):
        super().__init__(f"Checkpoint not found: {checkpoint_id}")
        self.checkpoint_id = checkpoint_id


class CheckpointValidationError(CheckpointError):
    """Checkpoint failed validation."""

    pass


class CheckpointVersionError(CheckpointError):
    """Checkpoint version is incompatible."""

    def __init__(self, expected: str, actual: str):
        super().__init__(f"Checkpoint version mismatch: expected {expected}, got {actual}")
        self.expected = expected
        self.actual = actual


# Helper functions
def generate_checkpoint_id(agent_name: str, run_id: str, iteration: int) -> str:
    """Generate a unique checkpoint ID.

    Args:
        agent_name: Name of the agent
        run_id: Run ID
        iteration: Current iteration number

    Returns:
        Checkpoint ID in format: agent_name-run_id-iteration-timestamp
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return f"{agent_name}-{run_id}-{iteration}-{timestamp}"


def validate_checkpoint(checkpoint: Checkpoint, expected_version: str = "1.0") -> None:
    """Validate a checkpoint.

    Args:
        checkpoint: Checkpoint to validate
        expected_version: Expected checkpoint version

    Raises:
        CheckpointValidationError: If validation fails
        CheckpointVersionError: If version is incompatible
    """
    if checkpoint.version != expected_version:
        raise CheckpointVersionError(expected_version, checkpoint.version)

    if not checkpoint.checkpoint_id:
        raise CheckpointValidationError("Checkpoint ID is required")

    if not checkpoint.agent_name:
        raise CheckpointValidationError("Agent name is required")

    if not checkpoint.run_id:
        raise CheckpointValidationError("Run ID is required")

    if checkpoint.iteration_count < 0:
        raise CheckpointValidationError("Iteration count must be non-negative")

    if checkpoint.total_tokens < 0:
        raise CheckpointValidationError("Total tokens must be non-negative")

    if checkpoint.total_cost_usd < 0:
        raise CheckpointValidationError("Total cost must be non-negative")
