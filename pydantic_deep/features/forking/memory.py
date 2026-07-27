"""Copy-on-write memory store for a single branch.

Memory used to live in `deps.backend`, so :class:`BranchOverlay` isolated it for
free: a branch's `MEMORY.md` writes were staged and either flushed on merge or
dropped with the branch. Once memory moved into its own harness `MemoryStore`,
that isolation was lost — branches shared the parent's store and their writes
survived being discarded.

:class:`BranchMemoryStore` restores it at the store layer. It is the memory
counterpart of `BranchOverlay`: reads fall through to the parent, writes are
staged locally, and :meth:`flush_to` replays them onto the parent only when the
branch wins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic_ai_harness.memory import InMemoryStore

if TYPE_CHECKING:
    from pydantic_ai_harness.memory import (
        MemoryFile,
        MemoryMutation,
        MemoryOperation,
        MemorySearchResult,
        MemoryStore,
    )

#: Seeding copies a whole file into the overlay, so it must not truncate. The
#: harness caps a single memory file well below this; `truncated` is checked too.
_SEED_MAX_CHARS = 10_000_000


@dataclass
class MemoryFlushReport:
    """Outcome of replaying a branch's memory writes onto the parent store."""

    applied_paths: list[str] = field(default_factory=list)
    deleted_paths: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)


class BranchMemoryStore:
    """Copy-on-write `MemoryStore` overlay for one branch.

    A path is seeded from the parent on first touch, then lives entirely in a
    private :class:`InMemoryStore`. Seeding keeps compare-and-set coherent: the
    branch reads and writes versions minted by its own overlay, so a concurrent
    parent write cannot make a branch write fail mid-run — the divergence is
    detected once, at flush time, and reported as a conflict instead.
    """

    def __init__(self, parent: MemoryStore) -> None:
        self._parent = parent
        self._overlay = InMemoryStore()
        #: Parent version observed when a path was seeded (`None` = absent).
        self._seeded: dict[str, str | None] = {}
        #: Paths this branch wrote or deleted, in first-touch order.
        self._touched: list[str] = []
        self._deleted: set[str] = set()

    @property
    def parent(self) -> MemoryStore:
        return self._parent

    def touched(self) -> list[str]:
        """Return the paths this branch wrote or deleted."""
        return list(self._touched)

    def _record(self, path: str) -> None:
        if path not in self._touched:
            self._touched.append(path)

    async def _seed(self, path: str) -> None:
        """Copy `path` from the parent into the overlay, once."""
        if path in self._seeded:
            return
        parent_file = await self._parent.read(path, max_chars=_SEED_MAX_CHARS)
        if parent_file is None:
            self._seeded[path] = None
            return
        if parent_file.truncated:  # pragma: no cover - guards against a silent partial copy
            raise RuntimeError(
                f"branch memory seeding read a truncated {path!r}; refusing to stage a "
                "partial copy that flush_to would write back over the parent"
            )
        self._seeded[path] = parent_file.version
        await self._overlay.write(path, parent_file.content, expected_version=None)

    async def read(self, path: str, *, max_chars: int) -> MemoryFile | None:
        if path in self._deleted:
            return None
        await self._seed(path)
        return await self._overlay.read(path, max_chars=max_chars)

    async def get_operation(self, operation: MemoryOperation) -> MemoryMutation | None:
        # Idempotency receipts are branch-local: a replayed operation must not
        # resolve against a receipt the parent minted before the fork.
        return await self._overlay.get_operation(operation)

    async def write(
        self,
        path: str,
        content: str,
        *,
        expected_version: str | None,
        operation: MemoryOperation | None = None,
    ) -> MemoryMutation:
        await self._seed(path)
        mutation = await self._overlay.write(
            path, content, expected_version=expected_version, operation=operation
        )
        self._deleted.discard(path)
        self._record(path)
        return mutation

    async def delete(
        self,
        path: str,
        *,
        expected_version: str | None,
        operation: MemoryOperation | None = None,
    ) -> MemoryMutation:
        await self._seed(path)
        mutation = await self._overlay.delete(
            path, expected_version=expected_version, operation=operation
        )
        self._deleted.add(path)
        self._record(path)
        return mutation

    async def list_paths(self, prefix: str = "", *, limit: int) -> list[str]:
        merged = set(await self._overlay.list_paths(prefix, limit=limit))
        merged.update(await self._parent.list_paths(prefix, limit=limit))
        return sorted(merged - self._deleted)[:limit]

    async def search(
        self,
        prefix: str,
        query: str,
        *,
        limit: int,
        max_files: int,
        max_chars: int,
        max_file_chars: int,
    ) -> MemorySearchResult:
        # The overlay only knows seeded paths, so pull the parent's set under
        # `prefix` in first — otherwise a branch could not find memory it has
        # not already read, which is exactly what search is for.
        for path in await self._parent.list_paths(prefix, limit=max_files):
            if path not in self._deleted:
                await self._seed(path)
        return await self._overlay.search(
            prefix,
            query,
            limit=limit,
            max_files=max_files,
            max_chars=max_chars,
            max_file_chars=max_file_chars,
        )

    async def flush_to(self, parent: MemoryStore | None = None) -> MemoryFlushReport:
        """Replay this branch's memory writes onto `parent`.

        Args:
            parent: Destination store. Defaults to the store this overlay wraps;
                for a fork-of-fork it is the outer branch's overlay, so
                propagation up one level needs no special casing.

        A path whose parent version moved since seeding is reported in
        `conflicts` and **not** replayed, so a third actor's newer memory wins
        over a branch that never saw it.
        """
        destination = parent if parent is not None else self._parent
        report = MemoryFlushReport()
        for path in self._touched:
            current = await destination.read(path, max_chars=_SEED_MAX_CHARS)
            current_version = current.version if current is not None else None
            if current_version != self._seeded.get(path):
                report.conflicts.append(path)
                continue
            if path in self._deleted:
                if current is not None:
                    await destination.delete(path, expected_version=current_version)
                report.deleted_paths.append(path)
                continue
            staged = await self._overlay.read(path, max_chars=_SEED_MAX_CHARS)
            if staged is None:  # pragma: no cover - a touched, undeleted path exists
                continue
            await destination.write(path, staged.content, expected_version=current_version)
            report.applied_paths.append(path)
        return report


__all__ = ["BranchMemoryStore", "MemoryFlushReport"]
