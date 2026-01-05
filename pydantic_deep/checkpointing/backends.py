"""Checkpoint storage backends.

This module provides different storage implementations for checkpoints,
including filesystem, in-memory (for testing), and cloud storage.
"""

import json
from pathlib import Path

from pydantic_deep.checkpointing.types import (
    Checkpoint,
    CheckpointError,
    CheckpointNotFoundError,
    validate_checkpoint,
)


class StateCheckpointBackend:
    """In-memory checkpoint backend for testing.

    Stores checkpoints in memory. Data is lost when the process ends.
    Useful for testing and development.
    """

    def __init__(self):
        """Initialize in-memory storage."""
        self._checkpoints: dict[str, Checkpoint] = {}

    async def save_checkpoint(self, checkpoint: Checkpoint) -> str:
        """Save checkpoint to memory."""
        validate_checkpoint(checkpoint)
        self._checkpoints[checkpoint.checkpoint_id] = checkpoint
        return checkpoint.checkpoint_id

    async def load_checkpoint(self, checkpoint_id: str) -> Checkpoint:
        """Load checkpoint from memory."""
        if checkpoint_id not in self._checkpoints:
            raise CheckpointNotFoundError(checkpoint_id)
        return self._checkpoints[checkpoint_id]

    async def list_checkpoints(
        self,
        agent_name: str | None = None,
        run_id: str | None = None,
        limit: int | None = None,
    ) -> list[Checkpoint]:
        """List checkpoints from memory."""
        checkpoints = list(self._checkpoints.values())

        # Apply filters
        if agent_name:
            checkpoints = [cp for cp in checkpoints if cp.agent_name == agent_name]
        if run_id:
            checkpoints = [cp for cp in checkpoints if cp.run_id == run_id]

        # Sort by timestamp (newest first)
        checkpoints.sort(key=lambda cp: cp.timestamp, reverse=True)

        # Apply limit
        if limit is not None:
            checkpoints = checkpoints[:limit]

        return checkpoints

    async def delete_checkpoint(self, checkpoint_id: str) -> None:
        """Delete checkpoint from memory."""
        if checkpoint_id not in self._checkpoints:
            raise CheckpointNotFoundError(checkpoint_id)
        del self._checkpoints[checkpoint_id]

    async def cleanup_old_checkpoints(self, run_id: str, keep_last: int = 5) -> int:
        """Clean up old checkpoints from memory."""
        # Get checkpoints for this run
        run_checkpoints = [cp for cp in self._checkpoints.values() if cp.run_id == run_id]

        # Sort by timestamp (newest first)
        run_checkpoints.sort(key=lambda cp: cp.timestamp, reverse=True)

        # Delete old ones
        deleted_count = 0
        for checkpoint in run_checkpoints[keep_last:]:
            del self._checkpoints[checkpoint.checkpoint_id]
            deleted_count += 1

        return deleted_count

    def clear(self) -> None:  # pragma: no cover
        """Clear all checkpoints (testing helper)."""
        self._checkpoints.clear()


class FileCheckpointBackend:
    """Filesystem-based checkpoint backend.

    Stores checkpoints as JSON files in a directory structure organized by
    agent name and run ID.
    """

    def __init__(self, directory: Path | str):
        """Initialize filesystem backend.

        Args:
            directory: Root directory for checkpoint storage
        """
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _get_checkpoint_path(self, checkpoint_id: str) -> Path:
        """Get filesystem path for a checkpoint.

        Format: directory/checkpoint_id.json
        """
        return self.directory / f"{checkpoint_id}.json"

    async def save_checkpoint(self, checkpoint: Checkpoint) -> str:
        """Save checkpoint to filesystem."""
        validate_checkpoint(checkpoint)

        checkpoint_path = self._get_checkpoint_path(checkpoint.checkpoint_id)

        try:
            # Serialize checkpoint
            data = checkpoint.to_dict()

            # Write to file
            with checkpoint_path.open("w") as f:
                json.dump(data, f, indent=2)

            return checkpoint.checkpoint_id

        except Exception as e:  # pragma: no cover
            raise CheckpointError(f"Failed to save checkpoint: {e}") from e

    async def load_checkpoint(self, checkpoint_id: str) -> Checkpoint:
        """Load checkpoint from filesystem."""
        checkpoint_path = self._get_checkpoint_path(checkpoint_id)

        if not checkpoint_path.exists():
            raise CheckpointNotFoundError(checkpoint_id)

        try:
            # Read from file
            with checkpoint_path.open("r") as f:
                data = json.load(f)

            # Deserialize checkpoint
            checkpoint = Checkpoint.from_dict(data)
            validate_checkpoint(checkpoint)

            return checkpoint

        except CheckpointNotFoundError:  # pragma: no cover
            raise
        except Exception as e:  # pragma: no cover
            raise CheckpointError(f"Failed to load checkpoint: {e}") from e

    async def list_checkpoints(
        self,
        agent_name: str | None = None,
        run_id: str | None = None,
        limit: int | None = None,
    ) -> list[Checkpoint]:
        """List checkpoints from filesystem."""
        checkpoints = []

        # Scan directory for checkpoint files
        for checkpoint_file in self.directory.glob("*.json"):
            try:
                with checkpoint_file.open("r") as f:
                    data = json.load(f)
                checkpoint = Checkpoint.from_dict(data)

                # Apply filters
                if agent_name and checkpoint.agent_name != agent_name:  # pragma: no branch
                    continue
                if run_id and checkpoint.run_id != run_id:  # pragma: no branch
                    continue

                checkpoints.append(checkpoint)

            except Exception:  # pragma: no cover
                # Skip invalid checkpoint files
                continue

        # Sort by timestamp (newest first)
        checkpoints.sort(key=lambda cp: cp.timestamp, reverse=True)

        # Apply limit
        if limit is not None:  # pragma: no branch
            checkpoints = checkpoints[:limit]

        return checkpoints

    async def delete_checkpoint(self, checkpoint_id: str) -> None:
        """Delete checkpoint from filesystem."""
        checkpoint_path = self._get_checkpoint_path(checkpoint_id)

        if not checkpoint_path.exists():  # pragma: no branch
            raise CheckpointNotFoundError(checkpoint_id)

        try:
            checkpoint_path.unlink()
        except Exception as e:  # pragma: no cover
            raise CheckpointError(f"Failed to delete checkpoint: {e}") from e

    async def cleanup_old_checkpoints(self, run_id: str, keep_last: int = 5) -> int:
        """Clean up old checkpoints from filesystem."""
        # Get checkpoints for this run
        run_checkpoints = await self.list_checkpoints(run_id=run_id)

        # Delete old ones (already sorted newest first)
        deleted_count = 0
        for checkpoint in run_checkpoints[keep_last:]:
            try:
                await self.delete_checkpoint(checkpoint.checkpoint_id)
                deleted_count += 1
            except Exception:  # pragma: no cover
                # Continue on error
                continue

        return deleted_count
