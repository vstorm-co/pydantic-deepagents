"""Fork state storage protocol and in-memory implementation.

`InMemoryForkStateStore` is the default store. Persistent stores
(file-backed, SQLite, etc.) are not yet implemented.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic_deep.features.forking.types import ForkHandle


@runtime_checkable
class ForkStateStore(Protocol):
    """Protocol for fork state storage backends.

    Stores `ForkHandle` records keyed by `fork_id`. Forks live for the
    duration of the parent run; on process restart, in-memory state is lost.
    """

    async def save(self, handle: ForkHandle) -> None:
        """Save or overwrite a fork handle."""
        ...

    async def get(self, fork_id: str) -> ForkHandle | None:
        """Return the handle for `fork_id` or `None` if unknown."""
        ...

    async def list_all(self) -> list[ForkHandle]:
        """Return all stored fork handles."""
        ...

    async def remove(self, fork_id: str) -> bool:
        """Remove a handle by id. Returns `True` if it existed."""
        ...


class InMemoryForkStateStore:
    """Default in-memory fork state store."""

    def __init__(self) -> None:
        self._handles: dict[str, ForkHandle] = {}

    async def save(self, handle: ForkHandle) -> None:
        self._handles[handle.fork_id] = handle

    async def get(self, fork_id: str) -> ForkHandle | None:
        return self._handles.get(fork_id)

    async def list_all(self) -> list[ForkHandle]:
        return list(self._handles.values())

    async def remove(self, fork_id: str) -> bool:
        if fork_id in self._handles:
            del self._handles[fork_id]
            return True
        return False


__all__ = ["ForkStateStore", "InMemoryForkStateStore"]
