"""Checkpoint persistence: the Checkpoint snapshot, the store protocol, and stores."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter


@dataclass
class Checkpoint:
    """Immutable snapshot of conversation state at a point in time.

    Attributes:
        id: Unique identifier (uuid4).
        label: Human-readable label (e.g. `"auto-3"`, `"before-refactor"`).
        turn: Model-request counter when the checkpoint was saved.
        messages: Shallow copy of the message history (ModelMessage is immutable).
        message_count: Number of messages in the snapshot.
        created_at: When the checkpoint was created.
        metadata: Optional metadata (e.g. `{"last_tool": "write_file"}`).
    """

    id: str
    label: str
    turn: int
    messages: list[ModelMessage]
    message_count: int
    created_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


class RewindRequested(Exception):
    """Raised by the `rewind_to` tool to signal app-level rewind.

    This exception propagates out of `agent.run()` / `agent.iter()`
    because pydantic-ai only catches `ModelRetry` and
    `UnexpectedModelBehavior` - arbitrary exceptions propagate to the caller.

    The caller (e.g. the app's run loop) catches this, restores
    `session.message_history` from :attr:`messages`, and restarts.

    Attributes:
        checkpoint_id: ID of the checkpoint to rewind to.
        label: Human-readable label of the checkpoint.
        messages: The message history snapshot to restore.
    """

    def __init__(self, checkpoint_id: str, label: str, messages: list[ModelMessage]) -> None:
        self.checkpoint_id = checkpoint_id
        self.label = label
        self.messages = messages
        super().__init__(f"Rewind requested to checkpoint '{label}' ({checkpoint_id})")


# CheckpointStore protocol + implementations


@runtime_checkable
class CheckpointStore(Protocol):
    """Protocol for checkpoint storage backends."""

    async def save(self, checkpoint: Checkpoint) -> None:
        """Save or overwrite a checkpoint."""
        ...

    async def get(self, checkpoint_id: str) -> Checkpoint | None:
        """Get a checkpoint by ID."""
        ...

    async def get_by_label(self, label: str) -> Checkpoint | None:
        """Get a checkpoint by label (returns first match)."""
        ...

    async def list_all(self) -> list[Checkpoint]:
        """List all checkpoints ordered by creation time."""
        ...

    async def remove(self, checkpoint_id: str) -> bool:
        """Remove a checkpoint by ID. Returns True if it existed."""
        ...

    async def remove_oldest(self) -> bool:
        """Remove the oldest checkpoint. Returns True if one was removed."""
        ...

    async def count(self) -> int:
        """Return the number of stored checkpoints."""
        ...

    async def clear(self) -> None:
        """Remove all checkpoints."""
        ...


class InMemoryCheckpointStore:
    """In-memory checkpoint store (default).

    Checkpoints are stored in a dict keyed by ID. Iteration order
    matches insertion order (Python 3.7+), so `remove_oldest()`
    pops the first key.
    """

    def __init__(self) -> None:
        self._checkpoints: dict[str, Checkpoint] = {}

    async def save(self, checkpoint: Checkpoint) -> None:
        """Save or overwrite a checkpoint."""
        self._checkpoints[checkpoint.id] = checkpoint

    async def get(self, checkpoint_id: str) -> Checkpoint | None:
        """Get a checkpoint by ID."""
        return self._checkpoints.get(checkpoint_id)

    async def get_by_label(self, label: str) -> Checkpoint | None:
        """Get a checkpoint by label (returns first match)."""
        for cp in self._checkpoints.values():
            if cp.label == label:
                return cp
        return None

    async def list_all(self) -> list[Checkpoint]:
        """List all checkpoints ordered by creation time."""
        return sorted(self._checkpoints.values(), key=lambda cp: cp.created_at)

    async def remove(self, checkpoint_id: str) -> bool:
        """Remove a checkpoint by ID."""
        if checkpoint_id in self._checkpoints:
            del self._checkpoints[checkpoint_id]
            return True
        return False

    async def remove_oldest(self) -> bool:
        """Remove the oldest checkpoint by `created_at`.

        Ordered by `created_at` (not insertion order) so this store and
        :class:`FileCheckpointStore` evict the same checkpoint - keeping the
        two interchangeable when clock skew or relabeling reorders entries.
        """
        all_cps = await self.list_all()
        if not all_cps:
            return False
        return await self.remove(all_cps[0].id)

    async def count(self) -> int:
        """Return the number of stored checkpoints."""
        return len(self._checkpoints)

    async def clear(self) -> None:
        """Remove all checkpoints."""
        self._checkpoints.clear()


class FileCheckpointStore:
    """Persistent checkpoint store using JSON files.

    Each checkpoint is stored as `{directory}/{id}.json`. Messages
    are serialized using pydantic-ai's `ModelMessagesTypeAdapter`.

    Args:
        directory: Directory to store checkpoint files.
    """

    def __init__(self, directory: str | Path) -> None:
        self._dir = Path(directory)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, checkpoint_id: str) -> Path:
        return self._dir / f"{checkpoint_id}.json"

    def _serialize(self, checkpoint: Checkpoint) -> bytes:
        messages_json = ModelMessagesTypeAdapter.dump_json(checkpoint.messages)
        data = {
            "id": checkpoint.id,
            "label": checkpoint.label,
            "turn": checkpoint.turn,
            "messages": json.loads(messages_json),
            "message_count": checkpoint.message_count,
            "created_at": checkpoint.created_at.isoformat(),
            "metadata": checkpoint.metadata,
        }
        return json.dumps(data, ensure_ascii=False).encode("utf-8")

    def _deserialize(self, raw: bytes) -> Checkpoint:
        data = json.loads(raw)
        messages_bytes = json.dumps(data["messages"]).encode("utf-8")
        messages = ModelMessagesTypeAdapter.validate_json(messages_bytes)
        return Checkpoint(
            id=data["id"],
            label=data["label"],
            turn=data["turn"],
            messages=messages,
            message_count=data["message_count"],
            created_at=datetime.fromisoformat(data["created_at"]),
            metadata=data.get("metadata", {}),
        )

    async def save(self, checkpoint: Checkpoint) -> None:
        """Save checkpoint to a JSON file."""
        self._path_for(checkpoint.id).write_bytes(self._serialize(checkpoint))

    async def get(self, checkpoint_id: str) -> Checkpoint | None:
        """Load checkpoint from JSON file."""
        path = self._path_for(checkpoint_id)
        if not path.exists():
            return None
        return self._deserialize(path.read_bytes())

    async def get_by_label(self, label: str) -> Checkpoint | None:
        """Find a checkpoint by label (scans all files)."""
        for cp in await self.list_all():
            if cp.label == label:
                return cp
        return None

    async def list_all(self) -> list[Checkpoint]:
        """List all checkpoints ordered by creation time."""
        checkpoints = []
        for path in sorted(self._dir.glob("*.json")):
            checkpoints.append(self._deserialize(path.read_bytes()))
        return sorted(checkpoints, key=lambda cp: cp.created_at)

    async def remove(self, checkpoint_id: str) -> bool:
        """Remove a checkpoint file."""
        path = self._path_for(checkpoint_id)
        if path.exists():
            path.unlink()
            return True
        return False

    async def remove_oldest(self) -> bool:
        """Remove the oldest checkpoint file."""
        all_cps = await self.list_all()
        if not all_cps:
            return False
        return await self.remove(all_cps[0].id)

    async def count(self) -> int:
        """Count checkpoint files."""
        return len(list(self._dir.glob("*.json")))

    async def clear(self) -> None:
        """Remove all checkpoint files."""
        for path in self._dir.glob("*.json"):
            path.unlink()


def _make_checkpoint(
    label: str,
    turn: int,
    messages: list[ModelMessage],
    metadata: dict[str, Any] | None = None,
) -> Checkpoint:
    """Create a Checkpoint with auto-generated ID and timestamp."""
    return Checkpoint(
        id=str(uuid.uuid4()),
        label=label,
        turn=turn,
        messages=list(messages),  # Shallow copy
        message_count=len(messages),
        created_at=datetime.now(timezone.utc),
        metadata=metadata or {},
    )


async def _save_and_prune(
    store: CheckpointStore,
    checkpoint: Checkpoint,
    max_checkpoints: int,
) -> None:
    """Save a checkpoint and prune if over limit."""
    await store.save(checkpoint)
    while await store.count() > max_checkpoints:
        await store.remove_oldest()


async def fork_from_checkpoint(
    store: CheckpointStore,
    checkpoint_id: str,
) -> list[ModelMessage]:
    """Get messages from a checkpoint for forking into a new session.

    This is a utility function for app-level session forking. The caller
    creates a new session and sets its `message_history` to the returned
    messages.

    Args:
        store: The checkpoint store to read from.
        checkpoint_id: ID of the checkpoint to fork from.

    Returns:
        A copy of the checkpoint's message history.

    Raises:
        ValueError: If the checkpoint is not found.

    Example:
        ```python
        messages = await fork_from_checkpoint(store, "abc123")
        new_session = UserSession()
        new_session.message_history = messages
        ```
    """
    checkpoint = await store.get(checkpoint_id)
    if checkpoint is None:
        raise ValueError(f"Checkpoint '{checkpoint_id}' not found.")
    return list(checkpoint.messages)
