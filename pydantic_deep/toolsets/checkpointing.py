"""Conversation checkpointing, rewind, and session forking.

Checkpointing saves conversation state at key points so the agent (or user)
can rewind to any checkpoint if an approach fails, or fork from a checkpoint
to try a different approach in a new session.

Building blocks from pydantic-ai:

- ``message_history`` param on ``agent.run()`` / ``agent.iter()`` for restore
- ``result.all_messages()`` → ``list[ModelMessage]`` for snapshot
- ``ModelMessagesTypeAdapter`` for JSON serialization

Components:

- :class:`Checkpoint` — immutable snapshot of conversation state
- :class:`CheckpointStore` — protocol for checkpoint storage backends
- :class:`InMemoryCheckpointStore` — default in-memory store
- :class:`FileCheckpointStore` — persistent store using JSON files
- :class:`CheckpointMiddleware` — auto-checkpoint via middleware hooks
- :class:`CheckpointToolset` — agent tools for manual save/list/rewind
- :class:`RewindRequested` — exception to signal app-level rewind
- :func:`fork_from_checkpoint` — utility for session forking

Example:
    ```python
    from pydantic_deep import create_deep_agent, InMemoryCheckpointStore

    store = InMemoryCheckpointStore()
    agent = create_deep_agent(
        include_checkpoints=True,
        checkpoint_store=store,
        checkpoint_frequency="every_tool",
    )
    ```
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic_ai import RunContext
from pydantic_ai.messages import ModelMessage, ModelMessagesTypeAdapter
from pydantic_ai.toolsets import FunctionToolset

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Checkpoint dataclass
# ---------------------------------------------------------------------------


@dataclass
class Checkpoint:
    """Immutable snapshot of conversation state at a point in time.

    Attributes:
        id: Unique identifier (uuid4).
        label: Human-readable label (e.g. ``"auto-3"``, ``"before-refactor"``).
        turn: Model-request counter when the checkpoint was saved.
        messages: Shallow copy of the message history (ModelMessage is immutable).
        message_count: Number of messages in the snapshot.
        created_at: When the checkpoint was created.
        metadata: Optional metadata (e.g. ``{"last_tool": "write_file"}``).
    """

    id: str
    label: str
    turn: int
    messages: list[ModelMessage]
    message_count: int
    created_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# RewindRequested exception
# ---------------------------------------------------------------------------


class RewindRequested(Exception):
    """Raised by the ``rewind_to`` tool to signal app-level rewind.

    This exception propagates out of ``agent.run()`` / ``agent.iter()``
    because pydantic-ai only catches ``ModelRetry`` and
    ``UnexpectedModelBehavior`` — arbitrary exceptions propagate to the caller.

    The caller (e.g. the app's run loop) catches this, restores
    ``session.message_history`` from :attr:`messages`, and restarts.

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


# ---------------------------------------------------------------------------
# CheckpointStore protocol + implementations
# ---------------------------------------------------------------------------


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
    matches insertion order (Python 3.7+), so ``remove_oldest()``
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
        """Remove the oldest checkpoint (first inserted)."""
        if not self._checkpoints:
            return False
        oldest_key = next(iter(self._checkpoints))
        del self._checkpoints[oldest_key]
        return True

    async def count(self) -> int:
        """Return the number of stored checkpoints."""
        return len(self._checkpoints)

    async def clear(self) -> None:
        """Remove all checkpoints."""
        self._checkpoints.clear()


class FileCheckpointStore:
    """Persistent checkpoint store using JSON files.

    Each checkpoint is stored as ``{directory}/{id}.json``. Messages
    are serialized using pydantic-ai's ``ModelMessagesTypeAdapter``.

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


# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# CheckpointMiddleware
# ---------------------------------------------------------------------------

from pydantic_ai_middleware import AgentMiddleware


class CheckpointMiddleware(AgentMiddleware["Any"]):  # type: ignore[type-arg]
    """Middleware that auto-saves conversation checkpoints.

    Uses ``before_model_request`` (for ``every_turn`` frequency) and
    ``after_tool_call`` (for ``every_tool`` frequency) hooks to
    automatically snapshot the conversation.

    The checkpoint store is resolved at runtime from ``deps.checkpoint_store``
    (falling back to the ``store`` passed at init). This allows a shared
    agent to use per-session stores.

    Args:
        store: Fallback checkpoint store (used if deps has no store).
        frequency: When to auto-checkpoint:
            ``"every_turn"`` — before each model request,
            ``"every_tool"`` — after each tool call,
            ``"manual_only"`` — no auto-checkpoints.
        max_checkpoints: Maximum number of checkpoints to keep.
    """

    def __init__(
        self,
        store: CheckpointStore | None = None,
        frequency: str = "every_tool",
        max_checkpoints: int = 20,
    ) -> None:
        self._fallback_store = store
        self.frequency = frequency
        self.max_checkpoints = max_checkpoints
        self._turn_counter = 0
        self._latest_messages: list[ModelMessage] = []

    def _resolve_store(self, deps: Any) -> CheckpointStore | None:
        """Get checkpoint store from deps or fallback."""
        store = getattr(deps, "checkpoint_store", None)
        return store or self._fallback_store

    async def before_model_request(
        self,
        messages: list[ModelMessage],
        deps: Any,
        ctx: Any = None,
    ) -> list[ModelMessage]:
        """Track messages and optionally auto-checkpoint before model calls."""
        self._turn_counter += 1
        self._latest_messages = list(messages)

        if self.frequency == "every_turn":
            store = self._resolve_store(deps)
            if store is not None:
                cp = _make_checkpoint(
                    label=f"turn-{self._turn_counter}",
                    turn=self._turn_counter,
                    messages=messages,
                )
                await _save_and_prune(store, cp, self.max_checkpoints)

        return messages

    async def after_tool_call(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        result: Any,
        deps: Any,
        ctx: Any = None,
    ) -> Any:
        """Auto-checkpoint after tool calls (when frequency is every_tool)."""
        if self.frequency == "every_tool":
            store = self._resolve_store(deps)
            if store is not None:
                cp = _make_checkpoint(
                    label=f"tool-{self._turn_counter}-{tool_name}",
                    turn=self._turn_counter,
                    messages=self._latest_messages,
                    metadata={"last_tool": tool_name},
                )
                await _save_and_prune(store, cp, self.max_checkpoints)

        return result


# ---------------------------------------------------------------------------
# CheckpointToolset
# ---------------------------------------------------------------------------


class CheckpointToolset(FunctionToolset[Any]):
    """Toolset giving the agent manual checkpoint controls.

    Tools:
        - ``save_checkpoint``: Label the most recent auto-checkpoint
        - ``list_checkpoints``: Show all saved checkpoints
        - ``rewind_to``: Rewind conversation to a checkpoint (raises RewindRequested)
    """

    def __init__(
        self,
        *,
        store: CheckpointStore | None = None,
        id: str = "deep-checkpoints",
    ) -> None:
        super().__init__(id=id)
        self._fallback_store = store

        @self.tool
        async def save_checkpoint(ctx: RunContext[Any], label: str) -> str:
            """Save a named checkpoint of the current conversation state.

            Labels the most recent auto-checkpoint with the given name.
            Use this before risky operations so you can rewind later.

            Args:
                label: A descriptive name for the checkpoint (e.g. "before-refactor").

            Returns:
                Confirmation message with checkpoint details.
            """
            s = _resolve_toolset_store(ctx, self._fallback_store)
            if s is None:
                return "Checkpointing is not enabled."

            all_cps = await s.list_all()
            if not all_cps:
                return "No checkpoint available to label yet. Try again after a tool call."

            latest = all_cps[-1]
            # Create a new checkpoint with the user's label but same data
            labeled = Checkpoint(
                id=latest.id,
                label=label,
                turn=latest.turn,
                messages=latest.messages,
                message_count=latest.message_count,
                created_at=latest.created_at,
                metadata=latest.metadata,
            )
            await s.save(labeled)
            return f"Checkpoint saved: '{label}' (turn {labeled.turn}, {labeled.message_count} messages)"

        @self.tool
        async def list_checkpoints(ctx: RunContext[Any]) -> str:
            """List all saved checkpoints with their labels and metadata.

            Returns:
                Formatted list of checkpoints, or a message if none exist.
            """
            s = _resolve_toolset_store(ctx, self._fallback_store)
            if s is None:
                return "Checkpointing is not enabled."

            all_cps = await s.list_all()
            if not all_cps:
                return "No checkpoints saved."

            lines = ["Saved checkpoints:"]
            for cp in all_cps:
                tool_info = ""
                if cp.metadata.get("last_tool"):
                    tool_info = f", last tool: {cp.metadata['last_tool']}"
                lines.append(
                    f"- **{cp.label}** (id: `{cp.id}`, turn {cp.turn}, "
                    f"{cp.message_count} messages{tool_info})"
                )
            return "\n".join(lines)

        @self.tool
        async def rewind_to(ctx: RunContext[Any], checkpoint_id: str) -> str:
            """Rewind the conversation to a previously saved checkpoint.

            This restores the conversation state to the checkpoint and discards
            all messages after it. Use this when the current approach isn't working
            and you want to try a different strategy.

            Args:
                checkpoint_id: The ID of the checkpoint to rewind to.

            Returns:
                Error message if checkpoint not found (otherwise raises RewindRequested).
            """
            s = _resolve_toolset_store(ctx, self._fallback_store)
            if s is None:
                return "Checkpointing is not enabled."

            checkpoint = await s.get(checkpoint_id)
            if checkpoint is None:
                return f"Checkpoint '{checkpoint_id}' not found. Use list_checkpoints to see available checkpoints."

            raise RewindRequested(
                checkpoint_id=checkpoint.id,
                label=checkpoint.label,
                messages=checkpoint.messages,
            )


def _resolve_toolset_store(
    ctx: RunContext[Any],
    fallback: CheckpointStore | None,
) -> CheckpointStore | None:
    """Resolve checkpoint store from ctx.deps or fallback."""
    store = getattr(ctx.deps, "checkpoint_store", None)
    return store or fallback


# ---------------------------------------------------------------------------
# Fork utility
# ---------------------------------------------------------------------------


async def fork_from_checkpoint(
    store: CheckpointStore,
    checkpoint_id: str,
) -> list[ModelMessage]:
    """Get messages from a checkpoint for forking into a new session.

    This is a utility function for app-level session forking. The caller
    creates a new session and sets its ``message_history`` to the returned
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
