"""Tests for persistent agent memory."""

from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import RunContext
from pydantic_ai.usage import RunUsage
from pydantic_ai_backends import StateBackend, WriteResult, ensure_async

from pydantic_deep import (
    DEFAULT_MAX_MEMORY_LINES,
    DEFAULT_MEMORY_DIR,
    DEFAULT_MEMORY_FILENAME,
    AgentMemoryToolset,
    DeepAgentDeps,
    MemoryFile,
    create_deep_agent,
    format_memory_prompt,
    get_memory_path,
    load_memory,
)

TEST_MODEL = TestModel()


def _make_ctx(backend: StateBackend | None = None) -> RunContext[DeepAgentDeps]:
    """Create a RunContext with DeepAgentDeps for testing."""
    b = backend or StateBackend()
    deps = DeepAgentDeps(backend=b)
    return RunContext(
        deps=deps,
        model=TEST_MODEL,
        usage=RunUsage(),
    )


class TestMemoryFile:
    """Tests for MemoryFile dataclass."""

    def test_create(self):
        """Test creating a MemoryFile."""
        mf = MemoryFile(
            agent_name="main",
            path="/.deep/memory/main/MEMORY.md",
            content="# Memory",
        )
        assert mf.agent_name == "main"
        assert mf.path == "/.deep/memory/main/MEMORY.md"
        assert mf.content == "# Memory"

    def test_create_subagent(self):
        """Test creating a MemoryFile for a subagent."""
        mf = MemoryFile(
            agent_name="code-reviewer",
            path="/.deep/memory/code-reviewer/MEMORY.md",
            content="Prefer Python 3.12",
        )
        assert mf.agent_name == "code-reviewer"


class TestGetMemoryPath:
    """Tests for get_memory_path function."""

    def test_default_dir(self):
        """Test path with default memory directory."""
        path = get_memory_path("/.deep/memory", "main")
        assert path == "/.deep/memory/main/MEMORY.md"

    def test_custom_dir(self):
        """Test path with custom memory directory."""
        path = get_memory_path("/workspace/.memory", "main")
        assert path == "/workspace/.memory/main/MEMORY.md"

    def test_subagent_name(self):
        """Test path with subagent name."""
        path = get_memory_path("/.deep/memory", "code-reviewer")
        assert path == "/.deep/memory/code-reviewer/MEMORY.md"

    def test_trailing_slash(self):
        """Test that trailing slash is handled correctly."""
        path = get_memory_path("/.deep/memory/", "main")
        assert path == "/.deep/memory/main/MEMORY.md"


class TestLoadMemory:
    """Tests for load_memory function."""

    async def test_load_existing(self):
        """Test loading an existing memory file."""
        backend = StateBackend()
        backend.write("/.deep/memory/main/MEMORY.md", "# Memory\n- item 1")

        mem = await load_memory(ensure_async(backend), "/.deep/memory/main/MEMORY.md", "main")
        assert mem is not None
        assert mem.agent_name == "main"
        assert mem.path == "/.deep/memory/main/MEMORY.md"
        assert "item 1" in mem.content

    async def test_load_missing(self):
        """Test loading a missing memory file returns None."""
        backend = StateBackend()
        mem = await load_memory(ensure_async(backend), "/.deep/memory/main/MEMORY.md", "main")
        assert mem is None

    async def test_load_utf8(self):
        """Test loading memory with non-ASCII content."""
        backend = StateBackend()
        backend.write("/.deep/memory/main/MEMORY.md", "Polskie znaki: ąęćżź")

        mem = await load_memory(ensure_async(backend), "/.deep/memory/main/MEMORY.md", "main")
        assert mem is not None
        assert "ąęćżź" in mem.content

    async def test_load_default_agent_name(self):
        """Test load_memory with default agent_name."""
        backend = StateBackend()
        backend.write("/mem/MEMORY.md", "content")

        mem = await load_memory(ensure_async(backend), "/mem/MEMORY.md")
        assert mem is not None
        assert mem.agent_name == "main"


class TestFormatMemoryPrompt:
    """Tests for format_memory_prompt function."""

    def test_short_content(self):
        """Test formatting memory that fits within max_lines."""
        mem = MemoryFile(agent_name="main", path="/m", content="line1\nline2\nline3")
        result = format_memory_prompt(mem, max_lines=200)

        assert "## Agent Memory (main)" in result
        assert "line1" in result
        assert "line2" in result
        assert "line3" in result
        assert "more lines" not in result

    def test_truncation_keeps_most_recent_lines(self):
        """Long memory keeps the most recent lines (the tail), not the oldest.

        Regression for #157: `write_memory` appends, so the newest entries are
        at the bottom of the file and must survive truncation.
        """
        lines = [f"line {i}" for i in range(300)]
        content = "\n".join(lines)
        mem = MemoryFile(agent_name="main", path="/m", content=content)
        result = format_memory_prompt(mem, max_lines=100)

        assert "## Agent Memory (main)" in result
        assert "line 299" in result  # newest kept
        assert "line 200" in result  # start of the kept tail (last 100 lines)
        assert "line 0" not in result  # oldest dropped
        assert "line 199" not in result  # just before the tail, dropped
        assert "200 more lines in memory" in result

    def test_pinned_head_survives_truncation(self):
        """Content above the pin marker is always injected; the body is tailed."""
        from pydantic_deep.features.memory import DEFAULT_PIN_END_MARKER

        head = f"# Identity\nfoundational note\n{DEFAULT_PIN_END_MARKER}\n"
        body = "\n".join(f"obs {i}" for i in range(50))
        mem = MemoryFile(agent_name="main", path="/m", content=head + body)
        result = format_memory_prompt(mem, max_lines=3)

        assert "# Identity" in result  # pinned head kept
        assert "foundational note" in result
        assert "obs 49" in result  # newest body line kept
        assert "obs 0" not in result  # oldest body line dropped
        assert DEFAULT_PIN_END_MARKER not in result  # marker itself not injected
        assert "47 more lines in memory" in result

    def test_pinned_head_only_empty_body(self):
        """A file that is only a pinned head injects the head with no marker."""
        from pydantic_deep.features.memory import DEFAULT_PIN_END_MARKER

        mem = MemoryFile(
            agent_name="main",
            path="/m",
            content=f"# Identity\nonly head here\n{DEFAULT_PIN_END_MARKER}",
        )
        result = format_memory_prompt(mem, max_lines=3)

        assert "# Identity" in result
        assert "only head here" in result
        assert "more lines in memory" not in result

    def test_max_tokens_takes_precedence(self):
        """`max_tokens` budgets the body and overrides `max_lines`."""
        lines = [f"line {i}" for i in range(300)]
        mem = MemoryFile(agent_name="main", path="/m", content="\n".join(lines))
        # ~7 chars/line, NUM_CHARS_PER_TOKEN=4 → 10 tokens ≈ 40 chars ≈ 5 lines.
        result = format_memory_prompt(mem, max_lines=300, max_tokens=10)

        assert "line 299" in result  # newest kept
        assert "line 0" not in result  # oldest dropped despite max_lines=300
        assert "more lines in memory" in result

    def test_max_tokens_large_budget_keeps_all(self):
        """A generous `max_tokens` keeps the whole body untruncated."""
        mem = MemoryFile(agent_name="main", path="/m", content="a\nb\nc")
        result = format_memory_prompt(mem, max_lines=2, max_tokens=10_000)

        assert "a" in result and "b" in result and "c" in result
        assert "more lines in memory" not in result

    def test_max_tokens_keeps_at_least_one_line(self):
        """A single line larger than the token budget is still kept."""
        mem = MemoryFile(
            agent_name="main",
            path="/m",
            content="old\n" + "x" * 1000,
        )
        result = format_memory_prompt(mem, max_lines=200, max_tokens=1)

        assert "x" * 1000 in result  # newest line kept even though it overflows
        assert "1 more lines in memory" in result

    def test_zero_max_lines_drops_all_body(self):
        """`max_lines=0` keeps no body lines, only the dropped-count marker."""
        mem = MemoryFile(agent_name="main", path="/m", content="a\nb\nc")
        result = format_memory_prompt(mem, max_lines=0)

        assert "3 more lines in memory" in result
        assert "## Agent Memory (main)" in result

    def test_exact_limit(self):
        """Test content at exactly max_lines."""
        lines = [f"line {i}" for i in range(10)]
        content = "\n".join(lines)
        mem = MemoryFile(agent_name="main", path="/m", content=content)
        result = format_memory_prompt(mem, max_lines=10)

        assert "more lines" not in result
        assert "line 9" in result

    def test_subagent_label(self):
        """Test that subagent name appears in prompt."""
        mem = MemoryFile(agent_name="code-reviewer", path="/m", content="review notes")
        result = format_memory_prompt(mem, max_lines=200)
        assert "## Agent Memory (code-reviewer)" in result

    def test_empty_content(self):
        """Test formatting empty memory content."""
        mem = MemoryFile(agent_name="main", path="/m", content="")
        result = format_memory_prompt(mem, max_lines=200)
        assert "## Agent Memory (main)" in result


class TestAgentMemoryToolset:
    """Tests for AgentMemoryToolset class."""

    def test_has_tools(self):
        """Test that toolset has read, write, update tools."""
        toolset = AgentMemoryToolset()
        tool_names = set(toolset.tools.keys())
        assert "read_memory" in tool_names
        assert "write_memory" in tool_names
        assert "update_memory" in tool_names

    def test_id(self):
        """Test toolset ID."""
        toolset = AgentMemoryToolset()
        assert toolset.id == "deep-memory"

    def test_default_params(self):
        """Test default constructor parameters."""
        toolset = AgentMemoryToolset()
        assert toolset._agent_name == "main"
        assert toolset._memory_dir == DEFAULT_MEMORY_DIR
        assert toolset._max_lines == DEFAULT_MAX_MEMORY_LINES

    def test_custom_params(self):
        """Test custom constructor parameters."""
        toolset = AgentMemoryToolset(
            agent_name="reviewer",
            memory_dir="/custom/mem",
            max_lines=50,
        )
        assert toolset._agent_name == "reviewer"
        assert toolset._memory_dir == "/custom/mem"
        assert toolset._max_lines == 50
        assert toolset._path == "/custom/mem/reviewer/MEMORY.md"

    async def test_get_instructions_no_memory(self):
        """Test get_instructions when no memory file exists."""
        ctx = _make_ctx()
        toolset = AgentMemoryToolset()
        result = await toolset.get_instructions(ctx)
        assert result is None

    async def test_get_instructions_with_memory(self):
        """Test get_instructions injects existing memory."""
        backend = StateBackend()
        backend.write("/.deep/memory/main/MEMORY.md", "# Notes\n- Important item")
        ctx = _make_ctx(backend)

        toolset = AgentMemoryToolset()
        result = await toolset.get_instructions(ctx)

        assert result is not None
        joined = "\n\n".join(p.content for p in result)
        assert "## Agent Memory (main)" in joined
        assert "Important item" in joined

    async def test_get_instructions_truncated(self):
        """Test get_instructions truncates long memory."""
        backend = StateBackend()
        lines = [f"line {i}" for i in range(300)]
        backend.write("/.deep/memory/main/MEMORY.md", "\n".join(lines))
        ctx = _make_ctx(backend)

        toolset = AgentMemoryToolset(max_lines=50)
        result = await toolset.get_instructions(ctx)

        assert result is not None
        joined = "\n\n".join(p.content for p in result)
        assert "250 more lines in memory" in joined


class TestMemoryTools:
    """Tests for individual memory tool functions."""

    async def test_read_memory_empty(self):
        """Test read_memory when no memory exists."""
        ctx = _make_ctx()
        toolset = AgentMemoryToolset()
        result = await toolset.tools["read_memory"].function(ctx)
        assert result == "No memory saved yet."

    async def test_read_memory_existing(self):
        """Test read_memory with existing memory."""
        backend = StateBackend()
        backend.write("/.deep/memory/main/MEMORY.md", "# My Notes\nImportant")
        ctx = _make_ctx(backend)

        toolset = AgentMemoryToolset()
        result = await toolset.tools["read_memory"].function(ctx)
        assert "My Notes" in result
        assert "Important" in result

    async def test_write_memory_new(self):
        """Test write_memory creates new memory file."""
        backend = StateBackend()
        ctx = _make_ctx(backend)

        toolset = AgentMemoryToolset()
        result = await toolset.tools["write_memory"].function(ctx, "# First entry")

        assert "Memory updated" in result
        # Verify file was created
        # read_bytes is the sync read that AsyncBackendAdapter delegates to.
        raw = backend.read_bytes("/.deep/memory/main/MEMORY.md")
        assert raw is not None
        assert b"First entry" in raw

    async def test_write_memory_append(self):
        """Test write_memory appends to existing memory."""
        backend = StateBackend()
        backend.write("/.deep/memory/main/MEMORY.md", "# Existing")
        ctx = _make_ctx(backend)

        toolset = AgentMemoryToolset()
        result = await toolset.tools["write_memory"].function(ctx, "New entry")

        assert "Memory updated" in result
        raw = backend.read_bytes("/.deep/memory/main/MEMORY.md")
        assert raw is not None
        content = raw.decode("utf-8")
        assert "Existing" in content
        assert "New entry" in content
        # Should be separated by double newline
        assert "# Existing\n\nNew entry" in content

    async def test_update_memory_success(self):
        """Test update_memory replaces text."""
        backend = StateBackend()
        backend.write("/.deep/memory/main/MEMORY.md", "Use Python 3.11")
        ctx = _make_ctx(backend)

        toolset = AgentMemoryToolset()
        result = await toolset.tools["update_memory"].function(ctx, "Python 3.11", "Python 3.12")

        assert "Memory updated" in result
        raw = backend.read_bytes("/.deep/memory/main/MEMORY.md")
        assert raw is not None
        assert b"Python 3.12" in raw
        assert b"Python 3.11" not in raw

    async def test_update_memory_not_found(self):
        """Test update_memory when old_text is not found."""
        backend = StateBackend()
        backend.write("/.deep/memory/main/MEMORY.md", "Some content")
        ctx = _make_ctx(backend)

        toolset = AgentMemoryToolset()
        result = await toolset.tools["update_memory"].function(ctx, "nonexistent", "replacement")

        assert "Text not found" in result

    async def test_update_memory_no_file(self):
        """Test update_memory when no memory file exists."""
        ctx = _make_ctx()
        toolset = AgentMemoryToolset()
        result = await toolset.tools["update_memory"].function(ctx, "old", "new")
        assert "No memory exists yet" in result

    async def test_update_memory_multiple_matches(self):
        """Test update_memory refuses to replace a non-unique old_text."""
        backend = StateBackend()
        backend.write("/.deep/memory/main/MEMORY.md", "foo\nfoo\nbar")
        ctx = _make_ctx(backend)

        toolset = AgentMemoryToolset()
        result = await toolset.tools["update_memory"].function(ctx, "foo", "baz")

        assert "appears 2 times" in result
        assert "must be" in result
        # Memory is left unchanged.
        raw = backend.read_bytes("/.deep/memory/main/MEMORY.md")
        assert raw == b"foo\nfoo\nbar"

    async def test_write_memory_custom_path(self):
        """Test write_memory with custom agent name and dir."""
        backend = StateBackend()
        ctx = _make_ctx(backend)

        toolset = AgentMemoryToolset(
            agent_name="reviewer",
            memory_dir="/custom",
        )
        await toolset.tools["write_memory"].function(ctx, "Review notes")

        raw = backend.read_bytes("/custom/reviewer/MEMORY.md")
        assert raw is not None
        assert b"Review notes" in raw


def _agent_memories(agent: Any) -> list[Any]:
    """Return the harness `Memory` capabilities registered on an agent."""
    from pydantic_ai_harness.memory import Memory

    caps = getattr(agent._root_capability, "capabilities", [])
    return [c for c in caps if isinstance(c, Memory)]


class TestCreateDeepAgentMemory:
    """Tests for create_deep_agent with the harness Memory capability."""

    def test_include_memory_adds_main_capability(self):
        """include_memory=True registers one Memory capability scoped to "main"."""
        agent = create_deep_agent(model=TEST_MODEL, include_memory=True, include_subagents=False)
        memories = _agent_memories(agent)
        assert len(memories) == 1
        assert memories[0].agent_name == "main"

    def test_custom_memory_dir_uses_file_store(self, tmp_path):
        """memory_dir builds a FileStore rooted at that directory."""
        from pydantic_ai_harness.memory import FileStore

        agent = create_deep_agent(
            model=TEST_MODEL,
            include_memory=True,
            include_subagents=False,
            memory_dir=str(tmp_path / ".memory"),
        )
        (memory,) = _agent_memories(agent)
        assert isinstance(memory.store, FileStore)

    def test_memory_dir_none_uses_in_memory_store(self):
        """No memory_dir (and no store) yields an ephemeral InMemoryStore."""
        from pydantic_ai_harness.memory import InMemoryStore

        agent = create_deep_agent(model=TEST_MODEL, include_memory=True, include_subagents=False)
        (memory,) = _agent_memories(agent)
        assert isinstance(memory.store, InMemoryStore)

    def test_memory_store_param_wins_over_memory_dir(self, tmp_path):
        """An explicit memory_store takes precedence over memory_dir."""
        from pydantic_ai_harness.memory import SqliteMemoryStore

        store = SqliteMemoryStore(database=str(tmp_path / "mem.db"))
        agent = create_deep_agent(
            model=TEST_MODEL,
            include_memory=True,
            include_subagents=False,
            memory_dir=str(tmp_path / "ignored"),
            memory_store=store,
        )
        (memory,) = _agent_memories(agent)
        assert memory.store is store

    def test_without_memory_has_no_capability(self):
        """A default agent with include_memory=False has no Memory capability."""
        agent = create_deep_agent(model=TEST_MODEL, include_memory=False, include_subagents=False)
        assert _agent_memories(agent) == []

    def test_memory_with_output_type(self):
        """Memory works alongside structured output."""
        from pydantic import BaseModel

        class Result(BaseModel):
            summary: str

        agent = create_deep_agent(
            model=TEST_MODEL,
            include_memory=True,
            include_subagents=False,
            output_type=Result,
        )
        assert len(_agent_memories(agent)) == 1


class TestPerSubagentMemory:
    """Tests for per-subagent memory built by the default subagent factory."""

    @staticmethod
    def _subagent(cfg: dict[str, Any], *, store: Any) -> Any:
        """Build a subagent via the default factory over a shared store."""
        from pydantic_deep.agent import _make_default_deep_agent_factory

        factory = _make_default_deep_agent_factory(
            model=TEST_MODEL,
            edit_format=None,
            context_files=None,
            context_discovery=False,
            include_memory=True,
            memory_store=store,
            memory_namespace="",
            tool_search=False,
            web_search=False,
            web_fetch=False,
        )
        return factory(cfg)

    def test_subagent_gets_memory_scoped_to_its_name(self):
        """Each subagent gets a Memory capability scoped to its own name, sharing the store."""
        from pydantic_ai_harness.memory import InMemoryStore

        store = InMemoryStore()
        sub = self._subagent({"name": "reviewer", "instructions": "Review code"}, store=store)
        (memory,) = _agent_memories(sub)
        assert memory.agent_name == "reviewer"
        assert memory.store is store

    def test_subagent_memory_disabled_via_extra(self):
        """extra={"memory": False} suppresses the subagent Memory capability."""
        from pydantic_ai_harness.memory import InMemoryStore

        sub = self._subagent(
            {"name": "worker", "instructions": "Do work", "extra": {"memory": False}},
            store=InMemoryStore(),
        )
        assert _agent_memories(sub) == []

    def test_subagent_memory_custom_max_lines(self):
        """Per-subagent memory_max_lines via extra is forwarded to the capability."""
        from pydantic_ai_harness.memory import InMemoryStore

        sub = self._subagent(
            {"name": "analyst", "instructions": "Analyze", "extra": {"memory_max_lines": 50}},
            store=InMemoryStore(),
        )
        (memory,) = _agent_memories(sub)
        assert memory.max_lines == 50

    def test_subagent_memory_custom_max_tokens(self):
        """Per-subagent memory_max_tokens via extra is forwarded to the capability."""
        from pydantic_ai_harness.memory import InMemoryStore

        sub = self._subagent(
            {"name": "analyst", "instructions": "Analyze", "extra": {"memory_max_tokens": 500}},
            store=InMemoryStore(),
        )
        (memory,) = _agent_memories(sub)
        assert memory.max_tokens == 500

    def test_subagent_preserves_existing_toolsets(self):
        """A subagent's own toolsets survive alongside the memory capability."""
        from pydantic_ai.toolsets import FunctionToolset
        from pydantic_ai_harness.memory import InMemoryStore

        existing_toolset = FunctionToolset(id="custom")
        sub = self._subagent(
            {"name": "worker", "instructions": "Work", "toolsets": [existing_toolset]},
            store=InMemoryStore(),
        )
        assert len(_agent_memories(sub)) == 1

    def test_no_subagent_memory_when_include_memory_false(self):
        """create_deep_agent(include_memory=False) never mutates the caller's config dict."""
        from pydantic_deep.types import SubAgentConfig

        config = SubAgentConfig(
            name="worker",
            description="Worker",
            instructions="Work",
        )
        create_deep_agent(
            model=TEST_MODEL,
            subagents=[config],
            include_memory=False,
        )

        # Caller's dict is left untouched (no toolsets key injected at all).
        if "toolsets" in config:
            toolset_types = [type(t).__name__ for t in config["toolsets"]]
            assert "AgentMemoryToolset" not in toolset_types


class TestMemoryConstants:
    """Tests for memory module constants."""

    def test_default_memory_dir(self):
        """Test DEFAULT_MEMORY_DIR value."""
        assert DEFAULT_MEMORY_DIR == "/.deep/memory"

    def test_default_memory_filename(self):
        """Test DEFAULT_MEMORY_FILENAME value."""
        assert DEFAULT_MEMORY_FILENAME == "MEMORY.md"

    def test_default_max_memory_lines(self):
        """Test DEFAULT_MAX_MEMORY_LINES value."""
        assert DEFAULT_MAX_MEMORY_LINES == 200


class TestMemoryExports:
    """Tests for memory exports from the package."""

    def test_agent_memory_toolset_exported(self):
        """Test AgentMemoryToolset is importable from package."""
        from pydantic_deep import AgentMemoryToolset as exported

        assert exported is AgentMemoryToolset

    def test_memory_file_exported(self):
        """Test MemoryFile is importable from package."""
        from pydantic_deep import MemoryFile as exported

        assert exported is MemoryFile

    def test_load_memory_exported(self):
        """Test load_memory is importable from package."""
        from pydantic_deep import load_memory as exported

        assert exported is load_memory

    def test_get_memory_path_exported(self):
        """Test get_memory_path is importable from package."""
        from pydantic_deep import get_memory_path as exported

        assert exported is get_memory_path

    def test_format_memory_prompt_exported(self):
        """Test format_memory_prompt is importable from package."""
        from pydantic_deep import format_memory_prompt as exported

        assert exported is format_memory_prompt

    def test_constants_exported(self):
        """Test all memory constants are importable."""
        from pydantic_deep import (
            DEFAULT_MAX_MEMORY_LINES,
            DEFAULT_MEMORY_DIR,
            DEFAULT_MEMORY_FILENAME,
        )

        assert DEFAULT_MEMORY_DIR is not None
        assert DEFAULT_MEMORY_FILENAME is not None
        assert DEFAULT_MAX_MEMORY_LINES is not None


def _write_deny_backend(seed_path: str | None = None, seed: bytes = b"") -> Any:
    """A StateBackend whose reads work but whose writes are always rejected.

    Isolates the "memory is readable but the backend refuses to persist the
    write" path (issue #135). When `seed_path` is given, content is written
    (via the real `write`) before write-denial is installed, so the read side
    still returns it.
    """
    backend = StateBackend()
    if seed_path is not None:
        backend.write(seed_path, seed)

    def _deny(path: str, content: bytes | str) -> WriteResult:
        return WriteResult(error="disk quota exceeded")

    backend.write = _deny
    return backend


def _denied_backend_and_dir(tmp_path: Path) -> tuple[Any, str]:
    """A LocalBackend whose allowed dir excludes the memory directory."""
    from pydantic_ai_backends import LocalBackend

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    backend = LocalBackend(root_dir=str(workspace), allowed_directories=[str(workspace)])
    memory_dir = str(tmp_path / "outside-memory")
    return backend, memory_dir


class TestMemoryFailureSurfacing:
    """Issue #135 — backend write/permission failures must be visible."""

    async def test_load_memory_raises_on_denied_path(self, tmp_path):
        """A denied path raises MemoryAccessError, not a silent None."""
        from pydantic_deep import MemoryAccessError

        backend, memory_dir = _denied_backend_and_dir(tmp_path)
        async_backend = ensure_async(backend)
        path = get_memory_path(memory_dir, "main")
        try:
            await load_memory(async_backend, path, "main")
            raise AssertionError("expected MemoryAccessError")
        except MemoryAccessError as exc:
            assert "denied" in str(exc).lower() or "outside" in str(exc).lower()

    async def test_load_memory_empty_existing_file_returns_none(self):
        """An empty (but accessible) file is missing/empty memory, not an error."""
        backend = StateBackend()
        path = get_memory_path(DEFAULT_MEMORY_DIR, "main")
        backend.write(path, b"")
        assert await load_memory(ensure_async(backend), path, "main") is None

    async def test_read_memory_surfaces_denied_access(self, tmp_path):
        """read_memory reports an error instead of 'No memory saved yet.'."""
        backend, memory_dir = _denied_backend_and_dir(tmp_path)
        toolset = AgentMemoryToolset(agent_name="main", memory_dir=memory_dir)
        ctx = _make_ctx(backend)
        result = await toolset.tools["read_memory"].function(ctx)
        assert result.startswith("Error:")
        assert "No memory saved yet" not in result

    async def test_write_memory_surfaces_denied_access(self, tmp_path):
        """write_memory reports the access failure instead of phantom success."""
        backend, memory_dir = _denied_backend_and_dir(tmp_path)
        toolset = AgentMemoryToolset(agent_name="main", memory_dir=memory_dir)
        ctx = _make_ctx(backend)
        result = await toolset.tools["write_memory"].function(ctx, content="note")
        assert result.startswith("Error:")
        assert "Memory updated" not in result

    async def test_write_memory_surfaces_write_result_error(self):
        """A rejected backend write is not reported as a successful update."""
        backend = _write_deny_backend()
        toolset = AgentMemoryToolset(agent_name="main", memory_dir=DEFAULT_MEMORY_DIR)
        ctx = _make_ctx(backend)
        result = await toolset.tools["write_memory"].function(ctx, content="note")
        assert result.startswith("Error:")
        assert "disk quota exceeded" in result

    async def test_update_memory_surfaces_denied_access(self, tmp_path):
        """update_memory reports the access failure instead of normal-looking output."""
        backend, memory_dir = _denied_backend_and_dir(tmp_path)
        toolset = AgentMemoryToolset(agent_name="main", memory_dir=memory_dir)
        ctx = _make_ctx(backend)
        result = await toolset.tools["update_memory"].function(ctx, old_text="a", new_text="b")
        assert result.startswith("Error:")

    async def test_update_memory_surfaces_write_result_error(self):
        """update_memory does not report success when the backend rejects the write."""
        path = get_memory_path(DEFAULT_MEMORY_DIR, "main")
        # Seed readable content first, then make subsequent writes fail.
        backend = _write_deny_backend(seed_path=path, seed=b"hello world")
        toolset = AgentMemoryToolset(agent_name="main", memory_dir=DEFAULT_MEMORY_DIR)
        ctx = _make_ctx(backend)
        result = await toolset.tools["update_memory"].function(
            ctx, old_text="hello", new_text="bye"
        )
        assert result.startswith("Error:")
        assert "disk quota exceeded" in result

    async def test_get_instructions_skips_denied_memory(self, tmp_path):
        """A denied memory path must not abort the run; instructions are skipped."""
        backend, memory_dir = _denied_backend_and_dir(tmp_path)
        toolset = AgentMemoryToolset(agent_name="main", memory_dir=memory_dir)
        ctx = _make_ctx(backend)
        assert await toolset.get_instructions(ctx) is None

    def test_memory_access_error_exported(self):
        """MemoryAccessError is importable from the package root."""
        from pydantic_deep import MemoryAccessError
        from pydantic_deep.toolsets.memory import MemoryAccessError as direct

        assert MemoryAccessError is direct


class TestMemoryStoreWiring:
    """Regressions from the harness-memory migration review."""

    def test_backend_style_memory_dir_raises_actionable_error(self):
        """`memory_dir` is a host path now; the old backend default must not
        surface as a bare OSError from the first write."""
        from pydantic_deep.features.memory import build_memory_store

        with pytest.raises(ValueError, match="host filesystem path"):
            build_memory_store("/.deep/memory")

    def test_relative_memory_dir_anchors_to_base_dir(self, tmp_path):
        """A relative memory_dir must follow the working dir, not the CWD."""
        from pydantic_deep.features.memory import build_memory_store

        store = build_memory_store(".pydantic-deep", base_dir=tmp_path)
        assert store._root == tmp_path / ".pydantic-deep"

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("code reviewer", "code-reviewer"), ("ok-name_1.2", "ok-name_1.2"), ("!!!", "agent")],
    )
    def test_agent_name_sanitized_for_store_path(self, raw, expected):
        """Names legal under the old backend layout must not break at run time."""
        from pydantic_deep.features.memory import sanitize_agent_name

        assert sanitize_agent_name(raw) == expected

    def test_ephemeral_default_warns(self):
        """Losing persistence by default must not be silent."""
        with pytest.warns(UserWarning, match="ephemeral in-memory store"):
            create_deep_agent(model=TEST_MODEL, include_memory=True, include_subagents=False)

    def test_memory_namespace_reaches_capability(self, tmp_path):
        """Per-tenant isolation must be reachable through create_deep_agent."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            memory_dir=str(tmp_path),
            memory_namespace="tenantA",
            include_subagents=False,
        )
        assert [c.namespace for c in _agent_memories(agent)] == ["tenantA"]

    @pytest.mark.parametrize("tool_search", [True, False])
    def test_tool_search_defers_memory_capability(self, tmp_path, tool_search):
        """Memory rides the capability list, so it must defer itself."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            memory_dir=str(tmp_path),
            tool_search=tool_search,
            include_subagents=False,
        )
        assert [c.defer_loading for c in _agent_memories(agent)] == [tool_search]

    def test_pin_marker_warns_instead_of_being_dropped(self, tmp_path):
        """The harness has no pin concept; the dropped key must not be silent."""
        from pydantic_ai_harness.memory import InMemoryStore

        from pydantic_deep.features.memory import build_memory_capability

        with pytest.warns(DeprecationWarning, match="memory_pin_marker"):
            build_memory_capability(
                store=InMemoryStore(), agent_name="main", pin_marker="<!-- pin -->"
            )

    def test_custom_agent_factory_subagent_keeps_memory_tools(self, tmp_path):
        """A caller-supplied factory never runs the capability wiring, so the
        memory tools must be injected through `toolsets` instead."""
        import pydantic_deep.agent as agent_mod

        captured: dict = {}
        original = agent_mod.create_subagent_toolset

        def spy(*args, **kwargs):
            captured["subagents"] = kwargs.get("subagents")
            return original(*args, **kwargs)

        agent_mod.create_subagent_toolset = spy
        try:
            sub = {
                "name": "custom",
                "description": "d",
                "instructions": "i",
                "agent_factory": lambda cfg: None,
            }
            agent_mod.create_deep_agent(
                model=TEST_MODEL,
                subagents=[sub],
                memory_dir=str(tmp_path),
                include_builtin_subagents=False,
            )
        finally:
            agent_mod.create_subagent_toolset = original

        cfg = next(s for s in captured["subagents"] if s["name"] == "custom")
        tools: set[str] = set()
        for toolset in cfg.get("toolsets") or []:
            tools |= set(getattr(toolset, "tools", {}))
        assert {"read_memory", "write_memory", "delete_memory", "search_memory"} <= tools

    def test_custom_agent_factory_respects_memory_disabled(self, tmp_path):
        """`extra={"memory": False}` must still opt a subagent out."""
        import pydantic_deep.agent as agent_mod

        captured: dict = {}
        original = agent_mod.create_subagent_toolset

        def spy(*args, **kwargs):
            captured["subagents"] = kwargs.get("subagents")
            return original(*args, **kwargs)

        agent_mod.create_subagent_toolset = spy
        try:
            sub = {
                "name": "custom",
                "description": "d",
                "instructions": "i",
                "agent_factory": lambda cfg: None,
                "extra": {"memory": False},
            }
            agent_mod.create_deep_agent(
                model=TEST_MODEL,
                subagents=[sub],
                memory_dir=str(tmp_path),
                include_builtin_subagents=False,
            )
        finally:
            agent_mod.create_subagent_toolset = original

        cfg = next(s for s in captured["subagents"] if s["name"] == "custom")
        assert not (cfg.get("toolsets") or [])
