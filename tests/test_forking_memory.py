"""Branch-local memory: `BranchMemoryStore`, deps resolution and merge flush."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import pytest
from pydantic_ai_harness.memory import InMemoryStore

from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.features.forking.coordinator import ForkCoordinator
from pydantic_deep.features.forking.isolation import clone_for_branch
from pydantic_deep.features.forking.memory import BranchMemoryStore
from pydantic_deep.features.forking.store import InMemoryForkStateStore
from pydantic_deep.features.forking.types import BranchIsolation, BranchSpec
from pydantic_deep.features.memory.store import deps_store_resolver

MAX = 100_000


async def _read(store: Any, path: str) -> str | None:
    file = await store.read(path, max_chars=MAX)
    return None if file is None else file.content


async def _seed_parent(content: str = "parent note\n") -> InMemoryStore:
    parent = InMemoryStore()
    await parent.write("main/MEMORY.md", content, expected_version=None)
    return parent


async def _overwrite(store: Any, path: str, content: str) -> None:
    """Write `content` at `path`, honouring the store's current version."""
    current = await store.read(path, max_chars=MAX)
    await store.write(path, content, expected_version=None if current is None else current.version)


@dataclass
class _FakeCtx:
    deps: Any


class TestDepsStoreResolver:
    def test_deps_store_wins_over_agent_store(self):
        agent_store, per_run = InMemoryStore(), InMemoryStore()
        resolve = deps_store_resolver(agent_store)
        deps = DeepAgentDeps(memory_store=per_run)

        assert resolve(_FakeCtx(deps)) is per_run

    def test_unset_deps_are_seeded_with_the_agent_store(self):
        agent_store = InMemoryStore()
        resolve = deps_store_resolver(agent_store)
        deps = DeepAgentDeps()

        assert resolve(_FakeCtx(deps)) is agent_store
        # Seeding is what gives `clone_for_branch` a parent store to wrap.
        assert deps.memory_store is agent_store

    def test_deps_without_the_field_still_resolve(self):
        agent_store = InMemoryStore()
        resolve = deps_store_resolver(agent_store)

        assert resolve(_FakeCtx(object())) is agent_store


class TestCloneForBranch:
    def test_copy_wraps_the_parent_store(self):
        parent = InMemoryStore()
        deps = DeepAgentDeps(memory_store=parent)

        branch = clone_for_branch(deps, BranchIsolation(memory="copy"))

        assert isinstance(branch.memory_store, BranchMemoryStore)
        assert branch.memory_store.parent is parent
        assert deps.memory_store is parent

    def test_share_hands_over_the_parent_store(self):
        parent = InMemoryStore()
        deps = DeepAgentDeps(memory_store=parent)

        branch = clone_for_branch(deps, BranchIsolation(memory="share"))

        assert branch.memory_store is parent

    def test_unresolved_memory_stays_none(self):
        branch = clone_for_branch(DeepAgentDeps(), BranchIsolation(memory="copy"))

        assert branch.memory_store is None

    def test_copy_is_the_default(self):
        deps = DeepAgentDeps(memory_store=InMemoryStore())

        branch = clone_for_branch(deps, BranchIsolation())

        assert isinstance(branch.memory_store, BranchMemoryStore)


class TestBranchMemoryStore:
    async def test_reads_fall_through_to_the_parent(self):
        branch = BranchMemoryStore(await _seed_parent())

        assert await _read(branch, "main/MEMORY.md") == "parent note\n"
        assert await _read(branch, "main/absent.md") is None

    async def test_writes_are_staged_not_visible_to_the_parent(self):
        parent = await _seed_parent()
        branch = BranchMemoryStore(parent)

        await _overwrite(branch, "main/MEMORY.md", "branch note\n")

        assert await _read(branch, "main/MEMORY.md") == "branch note\n"
        assert await _read(parent, "main/MEMORY.md") == "parent note\n"

    async def test_discarding_the_branch_leaves_the_parent_untouched(self):
        parent = await _seed_parent()
        branch = BranchMemoryStore(parent)

        await _overwrite(branch, "main/MEMORY.md", "note from an abandoned branch\n")
        del branch  # No flush: exactly what a losing branch gets.

        assert await _read(parent, "main/MEMORY.md") == "parent note\n"

    async def test_flush_applies_the_branch_write(self):
        parent = await _seed_parent()
        branch = BranchMemoryStore(parent)
        await _overwrite(branch, "main/MEMORY.md", "branch note\n")

        report = await branch.flush_to()

        assert report.applied_paths == ["main/MEMORY.md"]
        assert not report.conflicts
        assert await _read(parent, "main/MEMORY.md") == "branch note\n"

    async def test_flush_creates_a_file_the_parent_never_had(self):
        parent = await _seed_parent()
        branch = BranchMemoryStore(parent)
        await branch.write("main/new.md", "fresh\n", expected_version=None)

        await branch.flush_to()

        assert await _read(parent, "main/new.md") == "fresh\n"

    async def test_flush_propagates_a_delete(self):
        parent = await _seed_parent()
        branch = BranchMemoryStore(parent)
        staged = await branch.read("main/MEMORY.md", max_chars=MAX)
        assert staged is not None
        await branch.delete("main/MEMORY.md", expected_version=staged.version)

        assert await _read(branch, "main/MEMORY.md") is None

        report = await branch.flush_to()

        assert report.deleted_paths == ["main/MEMORY.md"]
        assert await _read(parent, "main/MEMORY.md") is None

    async def test_flush_of_a_branch_only_file_that_was_also_deleted(self):
        # Created and dropped inside the branch: there is nothing in the parent
        # to delete, so the flush must record it without issuing a delete.
        parent = await _seed_parent()
        branch = BranchMemoryStore(parent)
        await branch.write("main/scratch.md", "temp\n", expected_version=None)
        staged = await branch.read("main/scratch.md", max_chars=MAX)
        assert staged is not None
        await branch.delete("main/scratch.md", expected_version=staged.version)

        report = await branch.flush_to()

        assert report.deleted_paths == ["main/scratch.md"]
        assert report.conflicts == []
        assert await _read(parent, "main/scratch.md") is None

    async def test_search_skips_paths_the_branch_deleted(self):
        parent = await _seed_parent("shared marker\n")
        await parent.write("main/keep.md", "shared marker\n", expected_version=None)
        branch = BranchMemoryStore(parent)
        staged = await branch.read("main/MEMORY.md", max_chars=MAX)
        assert staged is not None
        await branch.delete("main/MEMORY.md", expected_version=staged.version)

        result = await branch.search(
            "main/",
            "marker",
            limit=10,
            max_files=10,
            max_chars=MAX,
            max_file_chars=MAX,
        )

        # The parent still lists MEMORY.md; the branch must not resurrect it.
        assert [match.path for match in result.matches] == ["main/keep.md"]

    async def test_untouched_paths_are_not_replayed(self):
        parent = await _seed_parent()
        branch = BranchMemoryStore(parent)
        await branch.read("main/MEMORY.md", max_chars=MAX)  # read-only

        report = await branch.flush_to()

        assert report.applied_paths == []
        assert branch.touched() == []

    async def test_a_diverged_parent_wins_and_is_reported(self):
        parent = await _seed_parent()
        branch = BranchMemoryStore(parent)
        await _overwrite(branch, "main/MEMORY.md", "branch note\n")
        # A third actor writes the same path after the fork.
        await _overwrite(parent, "main/MEMORY.md", "someone else's note\n")

        report = await branch.flush_to()

        assert report.conflicts == ["main/MEMORY.md"]
        assert report.applied_paths == []
        assert await _read(parent, "main/MEMORY.md") == "someone else's note\n"

    async def test_branch_writes_survive_a_concurrent_parent_write_mid_run(self):
        """CAS is branch-local, so the parent cannot break a branch's own writes."""
        parent = await _seed_parent()
        branch = BranchMemoryStore(parent)
        await _overwrite(branch, "main/MEMORY.md", "first\n")
        await _overwrite(parent, "main/MEMORY.md", "parent moved on\n")

        await _overwrite(branch, "main/MEMORY.md", "second\n")

        assert await _read(branch, "main/MEMORY.md") == "second\n"

    async def test_list_paths_merges_and_hides_deletes(self):
        parent = await _seed_parent()
        await parent.write("main/other.md", "o\n", expected_version=None)
        branch = BranchMemoryStore(parent)
        await branch.write("main/new.md", "n\n", expected_version=None)
        staged = await branch.read("main/other.md", max_chars=MAX)
        assert staged is not None
        await branch.delete("main/other.md", expected_version=staged.version)

        paths = await branch.list_paths("main/", limit=10)

        assert paths == ["main/MEMORY.md", "main/new.md"]

    async def test_search_finds_parent_content_not_yet_read(self):
        parent = await _seed_parent("a distinctive parent fact\n")
        branch = BranchMemoryStore(parent)

        result = await branch.search(
            "main", "distinctive", limit=5, max_files=10, max_chars=MAX, max_file_chars=MAX
        )

        assert [m.path for m in result.matches] == ["main/MEMORY.md"]

    async def test_operation_receipts_are_branch_local(self):
        from pydantic_ai_harness.memory import MemoryOperation

        parent = await _seed_parent()
        op = MemoryOperation(id="op-1", fingerprint="fp")
        await parent.write("main/p.md", "x\n", expected_version=None, operation=op)
        branch = BranchMemoryStore(parent)

        # A pre-fork receipt must not make the branch skip its own write.
        assert await branch.get_operation(op) is None

    async def test_fork_of_fork_flushes_into_the_outer_branch(self):
        parent = await _seed_parent()
        outer = BranchMemoryStore(parent)
        inner = BranchMemoryStore(outer)
        await _overwrite(inner, "main/MEMORY.md", "inner note\n")

        await inner.flush_to()

        assert await _read(outer, "main/MEMORY.md") == "inner note\n"
        assert await _read(parent, "main/MEMORY.md") == "parent note\n"

        await outer.flush_to()

        assert await _read(parent, "main/MEMORY.md") == "inner note\n"


class TestMultiTenantScoping:
    """The same `store_resolver` restores build-once / deps-per-user isolation."""

    async def test_per_run_stores_do_not_leak(self):
        agent_store = InMemoryStore()
        resolve = deps_store_resolver(agent_store)
        tenant_a, tenant_b = InMemoryStore(), InMemoryStore()

        store_a = resolve(_FakeCtx(DeepAgentDeps(memory_store=tenant_a)))
        await store_a.write("main/MEMORY.md", "tenant A secret\n", expected_version=None)
        store_b = resolve(_FakeCtx(DeepAgentDeps(memory_store=tenant_b)))

        assert await _read(store_b, "main/MEMORY.md") is None
        assert await _read(agent_store, "main/MEMORY.md") is None


class _StubResult:
    def all_messages(self) -> list[Any]:
        return []


class _MemoryWritingAgent:
    """Agent stub whose only side effect is a branch-local memory write."""

    model = "anthropic:claude-sonnet-4-6"
    _root_capability = None

    async def run(
        self, steer: str, *, message_history: Any = None, deps: Any = None
    ) -> _StubResult:
        await _overwrite(deps.memory_store, "main/MEMORY.md", f"{steer} note\n")
        return _StubResult()


class TestMergeFlush:
    """The coordinator replays the winner's memory and reports divergence."""

    @staticmethod
    def _coordinator(parent_store: InMemoryStore, tmp_path: Any) -> ForkCoordinator:
        return ForkCoordinator(
            agent=_MemoryWritingAgent(),
            parent_deps=DeepAgentDeps(memory_store=parent_store),
            max_branches=2,
            max_depth=1,
            store=InMemoryForkStateStore(),
            materializer_root=tmp_path / "forks",
        )

    async def _run_one_branch(self, coord: ForkCoordinator) -> str:
        handle = await coord.fork(
            [BranchSpec(label="alpha", steer="alpha")],
            parent_history=[],
            isolation=BranchIsolation(),
        )
        await asyncio.gather(*[rt.task for rt in coord.branches.values()])
        return handle.branches[0]

    async def test_winner_memory_lands_on_the_parent(self, tmp_path):
        parent_store = await _seed_parent()
        coord = self._coordinator(parent_store, tmp_path)

        winner = await self._run_one_branch(coord)
        assert await _read(parent_store, "main/MEMORY.md") == "parent note\n"

        await coord.merge_or_select(f"pick:{winner}")

        assert await _read(parent_store, "main/MEMORY.md") == "alpha note\n"

    async def test_diverged_memory_is_skipped_and_logged(self, tmp_path, caplog):
        parent_store = await _seed_parent()
        coord = self._coordinator(parent_store, tmp_path)

        winner = await self._run_one_branch(coord)
        # A third actor rewrites the same path while the branch is in flight.
        await _overwrite(parent_store, "main/MEMORY.md", "someone else's note\n")

        with caplog.at_level(logging.WARNING):
            await coord.merge_or_select(f"pick:{winner}")

        assert "memory flush skipped 1 diverged path(s): main/MEMORY.md" in caplog.text
        assert await _read(parent_store, "main/MEMORY.md") == "someone else's note\n"


@pytest.mark.parametrize("flag", ["copy", "share"])
def test_memory_flag_is_read_not_merely_recorded(flag: str) -> None:
    deps = DeepAgentDeps(memory_store=InMemoryStore())

    branch = clone_for_branch(deps, BranchIsolation(memory=flag))

    assert isinstance(branch.memory_store, BranchMemoryStore) is (flag == "copy")
