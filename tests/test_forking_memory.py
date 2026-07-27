"""Branch-local memory: `BranchMemoryStore`, deps resolution and merge flush."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from pydantic_ai_harness.memory import InMemoryStore

from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.features.forking.isolation import clone_for_branch
from pydantic_deep.features.forking.memory import BranchMemoryStore
from pydantic_deep.features.forking.types import BranchIsolation
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
        await branch.delete("main/MEMORY.md", expected_version=staged.version)

        assert await _read(branch, "main/MEMORY.md") is None

        report = await branch.flush_to()

        assert report.deleted_paths == ["main/MEMORY.md"]
        assert await _read(parent, "main/MEMORY.md") is None

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


@pytest.mark.parametrize("flag", ["copy", "share"])
def test_memory_flag_is_read_not_merely_recorded(flag: str):
    deps = DeepAgentDeps(memory_store=InMemoryStore())

    branch = clone_for_branch(deps, BranchIsolation(memory=flag))

    assert isinstance(branch.memory_store, BranchMemoryStore) is (flag == "copy")
