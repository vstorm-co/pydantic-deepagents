"""Checkpoint manager for automatic checkpointing and recovery.

This module provides the main interface for managing agent checkpoints,
including automatic checkpointing triggers and recovery logic.
"""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic_ai import Agent

from pydantic_deep.checkpointing.types import (
    Checkpoint,
    CheckpointProtocol,
    generate_checkpoint_id,
)
from pydantic_deep.deps import DeepAgentDeps


class CheckpointManager:
    """Manages agent checkpointing and recovery.

    The CheckpointManager handles automatic checkpoint creation at configurable
    frequencies and provides methods for restoring agent state from checkpoints.

    Example:
        ```python
        from pydantic_deep.checkpointing import CheckpointManager, FileCheckpointBackend

        backend = FileCheckpointBackend(Path("/tmp/checkpoints"))
        manager = CheckpointManager(
            backend=backend,
            frequency="iteration",
            auto_save=True,
        )

        # Checkpoints are created automatically during execution
        ```
    """

    def __init__(
        self,
        backend: CheckpointProtocol,
        frequency: Literal["iteration", "time", "manual"] = "iteration",
        auto_save: bool = True,
        save_interval_seconds: float = 60.0,
        auto_cleanup: bool = True,
        keep_last: int = 5,
    ):
        """Initialize checkpoint manager.

        Args:
            backend: Storage backend for checkpoints
            frequency: When to create checkpoints ("iteration", "time", "manual")
            auto_save: Whether to automatically save checkpoints
            save_interval_seconds: Seconds between time-based checkpoints
            auto_cleanup: Whether to automatically clean up old checkpoints
            keep_last: Number of recent checkpoints to keep when cleaning up
        """
        self.backend = backend
        self.frequency = frequency
        self.auto_save = auto_save
        self.save_interval_seconds = save_interval_seconds
        self.auto_cleanup = auto_cleanup
        self.keep_last = keep_last

        # Runtime state
        self.last_checkpoint_time: datetime | None = None
        self.last_checkpoint_id: str | None = None
        self.current_run_id: str | None = None

    async def create_checkpoint(
        self,
        agent_name: str,
        run_id: str,
        messages: list[dict[str, Any]],
        iteration_count: int,
        total_tokens: int = 0,
        total_cost_usd: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Create a checkpoint of current agent state.

        Args:
            agent_name: Name of the agent
            run_id: Unique run identifier
            messages: Current message history
            iteration_count: Current iteration number
            total_tokens: Total tokens used
            total_cost_usd: Total cost in USD
            metadata: Additional checkpoint metadata

        Returns:
            The checkpoint ID
        """
        # Generate checkpoint ID
        checkpoint_id = generate_checkpoint_id(agent_name, run_id, iteration_count)

        # Create checkpoint
        checkpoint = Checkpoint(
            checkpoint_id=checkpoint_id,
            agent_name=agent_name,
            run_id=run_id,
            timestamp=datetime.now(),
            messages=messages,
            iteration_count=iteration_count,
            total_tokens=total_tokens,
            total_cost_usd=total_cost_usd,
            metadata=metadata or {},
        )

        # Save checkpoint
        saved_id = await self.backend.save_checkpoint(checkpoint)

        # Update state
        self.last_checkpoint_time = checkpoint.timestamp
        self.last_checkpoint_id = saved_id
        self.current_run_id = run_id

        # Cleanup old checkpoints if enabled
        if self.auto_cleanup:  # pragma: no branch
            await self.backend.cleanup_old_checkpoints(run_id, keep_last=self.keep_last)

        return saved_id

    async def restore_checkpoint(self, checkpoint_id: str) -> Checkpoint:
        """Restore agent state from checkpoint.

        Args:
            checkpoint_id: ID of the checkpoint to restore

        Returns:
            The loaded checkpoint
        """
        return await self.backend.load_checkpoint(checkpoint_id)

    async def get_latest_checkpoint(
        self,
        run_id: str | None = None,
        agent_name: str | None = None,
    ) -> Checkpoint | None:
        """Get the most recent checkpoint.

        Args:
            run_id: Filter by run ID (optional)
            agent_name: Filter by agent name (optional)

        Returns:
            The latest checkpoint, or None if no checkpoints exist
        """
        checkpoints = await self.backend.list_checkpoints(
            agent_name=agent_name,
            run_id=run_id,
            limit=1,
        )
        return checkpoints[0] if checkpoints else None

    def should_checkpoint(
        self,
        iteration: int,
        elapsed_seconds: float,
    ) -> bool:
        """Determine if a checkpoint should be created.

        Args:
            iteration: Current iteration number
            elapsed_seconds: Seconds since last checkpoint

        Returns:
            True if a checkpoint should be created
        """
        if not self.auto_save:  # pragma: no branch
            return False

        if self.frequency == "manual":  # pragma: no branch
            return False

        if self.frequency == "iteration":  # pragma: no branch
            # Checkpoint every iteration
            return True

        if self.frequency == "time":  # pragma: no branch
            # Checkpoint based on time interval
            if self.last_checkpoint_time is None:  # pragma: no branch
                return True
            return elapsed_seconds >= self.save_interval_seconds

        return False  # pragma: no cover

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
            List of checkpoints
        """
        return await self.backend.list_checkpoints(
            agent_name=agent_name,
            run_id=run_id,
            limit=limit,
        )

    async def delete_checkpoint(self, checkpoint_id: str) -> None:  # pragma: no cover
        """Delete a checkpoint.

        Args:
            checkpoint_id: ID of the checkpoint to delete
        """
        await self.backend.delete_checkpoint(checkpoint_id)

    async def cleanup_run_checkpoints(self, run_id: str, keep_last: int | None = None) -> int:  # pragma: no cover
        """Clean up checkpoints for a specific run.

        Args:
            run_id: Run ID to clean up
            keep_last: Number of checkpoints to keep (uses default if None)

        Returns:
            Number of checkpoints deleted
        """
        keep = keep_last if keep_last is not None else self.keep_last
        return await self.backend.cleanup_old_checkpoints(run_id, keep_last=keep)


# Helper functions for common use cases
async def run_with_checkpointing(
    agent: Agent[DeepAgentDeps, Any],
    prompt: str,
    deps: DeepAgentDeps,
    checkpoint_manager: CheckpointManager,
    run_id: str | None = None,
    resume_from: str | None = None,
) -> Any:
    """Run agent with automatic checkpointing.

    This is a convenience function that wraps agent.run() and handles
    checkpointing automatically based on the manager configuration.

    Args:
        agent: The agent to run
        prompt: User prompt
        deps: Agent dependencies
        checkpoint_manager: Checkpoint manager instance
        run_id: Run ID (generated if not provided)
        resume_from: Checkpoint ID to resume from (optional)

    Returns:
        Agent result

    Example:
        ```python
        result = await run_with_checkpointing(
            agent=agent,
            prompt="Long task",
            deps=deps,
            checkpoint_manager=manager,
        )
        ```
    """
    # Generate run ID if not provided
    if run_id is None:  # pragma: no branch
        run_id = str(uuid.uuid4())

    # Resume from checkpoint if specified
    message_history = None
    if resume_from:  # pragma: no cover
        checkpoint = await checkpoint_manager.restore_checkpoint(resume_from)
        message_history = checkpoint.messages  # type: ignore[assignment]

    # Run the agent
    # Note: Actual automatic checkpointing would require integration
    # with the agent's execution loop. This is a simplified version.
    result = await agent.run(
        prompt,
        deps=deps,
        message_history=message_history,  # type: ignore[arg-type]
    )

    # Create final checkpoint
    agent_name = getattr(agent, "name", "agent")
    messages = result.all_messages()

    # Get token usage
    total_tokens = 0
    usage = result.usage()
    if usage:  # pragma: no branch
        total_tokens = usage.total_tokens or 0

    # Serialize messages - handle different message types
    serialized_messages = []
    for msg in messages:
        if hasattr(msg, "model_dump"):  # pragma: no branch
            serialized_messages.append(msg.model_dump())  # type: ignore[union-attr]
        elif isinstance(msg, dict):  # pragma: no cover
            serialized_messages.append(msg)
        else:  # pragma: no cover
            # Fallback: convert to dict representation
            serialized_messages.append({"content": str(msg)})

    await checkpoint_manager.create_checkpoint(
        agent_name=agent_name,
        run_id=run_id,
        messages=serialized_messages,
        iteration_count=1,  # Simplified - would need actual iteration tracking
        total_tokens=total_tokens,
    )

    return result


async def create_manual_checkpoint(
    agent_name: str,
    run_id: str,
    messages: list[dict[str, Any]],
    checkpoint_manager: CheckpointManager,
    **kwargs: Any,
) -> str:
    """Create a manual checkpoint.

    Args:
        agent_name: Name of the agent
        run_id: Run ID
        messages: Message history
        checkpoint_manager: Checkpoint manager
        **kwargs: Additional checkpoint parameters

    Returns:
        Checkpoint ID
    """
    iteration = kwargs.get("iteration_count", 0)
    tokens = kwargs.get("total_tokens", 0)
    cost = kwargs.get("total_cost_usd", 0.0)
    metadata = kwargs.get("metadata", {})

    return await checkpoint_manager.create_checkpoint(
        agent_name=agent_name,
        run_id=run_id,
        messages=messages,
        iteration_count=iteration,
        total_tokens=tokens,
        total_cost_usd=cost,
        metadata=metadata,
    )
