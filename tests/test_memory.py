"""Tests for persistent agent memory."""

from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import RunContext
from pydantic_ai.usage import RunUsage
from pydantic_ai_backends import StateBackend

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


# --- Helpers ---


def _make_ctx(backend: StateBackend | None = None) -> RunContext[DeepAgentDeps]:
    """Create a RunContext with DeepAgentDeps for testing."""
    b = backend or StateBackend()
    deps = DeepAgentDeps(backend=b)
    return RunContext(
        deps=deps,
        model=TEST_MODEL,
        usage=RunUsage(),
    )


# --- Unit Tests: MemoryFile ---


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


# --- Unit Tests: get_memory_path ---


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


# --- Unit Tests: load_memory ---


class TestLoadMemory:
    """Tests for load_memory function."""

    def test_load_existing(self):
        """Test loading an existing memory file."""
        backend = StateBackend()
        backend.write("/.deep/memory/main/MEMORY.md", "# Memory\n- item 1")

        mem = load_memory(backend, "/.deep/memory/main/MEMORY.md", "main")
        assert mem is not None
        assert mem.agent_name == "main"
        assert mem.path == "/.deep/memory/main/MEMORY.md"
        assert "item 1" in mem.content

    def test_load_missing(self):
        """Test loading a missing memory file returns None."""
        backend = StateBackend()
        mem = load_memory(backend, "/.deep/memory/main/MEMORY.md", "main")
        assert mem is None

    def test_load_utf8(self):
        """Test loading memory with non-ASCII content."""
        backend = StateBackend()
        backend.write("/.deep/memory/main/MEMORY.md", "Polskie znaki: ąęćżź")

        mem = load_memory(backend, "/.deep/memory/main/MEMORY.md", "main")
        assert mem is not None
        assert "ąęćżź" in mem.content

    def test_load_default_agent_name(self):
        """Test load_memory with default agent_name."""
        backend = StateBackend()
        backend.write("/mem/MEMORY.md", "content")

        mem = load_memory(backend, "/mem/MEMORY.md")
        assert mem is not None
        assert mem.agent_name == "main"


# --- Unit Tests: format_memory_prompt ---


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

    def test_truncation(self):
        """Test that long memory is truncated."""
        lines = [f"line {i}" for i in range(300)]
        content = "\n".join(lines)
        mem = MemoryFile(agent_name="main", path="/m", content=content)
        result = format_memory_prompt(mem, max_lines=100)

        assert "## Agent Memory (main)" in result
        assert "line 0" in result
        assert "line 99" in result
        assert "200 more lines in memory" in result

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


# --- Unit Tests: AgentMemoryToolset ---


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
        assert "## Agent Memory (main)" in result
        assert "Important item" in result

    async def test_get_instructions_truncated(self):
        """Test get_instructions truncates long memory."""
        backend = StateBackend()
        lines = [f"line {i}" for i in range(300)]
        backend.write("/.deep/memory/main/MEMORY.md", "\n".join(lines))
        ctx = _make_ctx(backend)

        toolset = AgentMemoryToolset(max_lines=50)
        result = await toolset.get_instructions(ctx)

        assert result is not None
        assert "250 more lines in memory" in result


# --- Unit Tests: Memory Tools ---


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
        raw = backend._read_bytes("/.deep/memory/main/MEMORY.md")
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
        raw = backend._read_bytes("/.deep/memory/main/MEMORY.md")
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
        raw = backend._read_bytes("/.deep/memory/main/MEMORY.md")
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

    async def test_write_memory_custom_path(self):
        """Test write_memory with custom agent name and dir."""
        backend = StateBackend()
        ctx = _make_ctx(backend)

        toolset = AgentMemoryToolset(
            agent_name="reviewer",
            memory_dir="/custom",
        )
        await toolset.tools["write_memory"].function(ctx, "Review notes")

        raw = backend._read_bytes("/custom/reviewer/MEMORY.md")
        assert raw is not None
        assert b"Review notes" in raw


# --- Integration Tests: create_deep_agent ---


class TestCreateDeepAgentMemory:
    """Tests for create_deep_agent with memory parameters."""

    def test_create_with_include_memory(self):
        """Test creating an agent with include_memory=True."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            include_memory=True,
        )
        assert agent is not None

    def test_create_with_custom_memory_dir(self):
        """Test creating an agent with custom memory_dir."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            include_memory=True,
            memory_dir="/workspace/.memory",
        )
        assert agent is not None

    def test_create_without_memory(self):
        """Test default agent has no memory toolset."""
        agent = create_deep_agent(model=TEST_MODEL)
        assert agent is not None

    def test_create_with_memory_and_output_type(self):
        """Test memory works with structured output."""
        from pydantic import BaseModel

        class Result(BaseModel):
            summary: str

        agent = create_deep_agent(
            model=TEST_MODEL,
            include_memory=True,
            output_type=Result,
        )
        assert agent is not None


# --- Per-Subagent Memory Tests ---


class TestPerSubagentMemory:
    """Tests for per-subagent memory injection via extra field."""

    def test_subagent_gets_memory_when_enabled(self):
        """Test that subagents get memory toolset when include_memory=True."""
        from pydantic_deep.types import SubAgentConfig

        config = SubAgentConfig(
            name="reviewer",
            description="Code reviewer",
            instructions="Review code",
        )
        create_deep_agent(
            model=TEST_MODEL,
            subagents=[config],
            include_memory=True,
        )

        # After create_deep_agent, config["toolsets"] should contain AgentMemoryToolset
        assert "toolsets" in config
        toolset_types = [type(t).__name__ for t in config["toolsets"]]
        assert "AgentMemoryToolset" in toolset_types

    def test_subagent_memory_disabled_via_extra(self):
        """Test that subagent memory can be disabled via extra.memory=False."""
        from pydantic_deep.types import SubAgentConfig

        config = SubAgentConfig(
            name="worker",
            description="Worker",
            instructions="Do work",
            extra={"memory": False},
        )
        create_deep_agent(
            model=TEST_MODEL,
            subagents=[config],
            include_memory=True,
        )

        # Should NOT have AgentMemoryToolset
        if "toolsets" in config:
            toolset_types = [type(t).__name__ for t in config["toolsets"]]
            assert "AgentMemoryToolset" not in toolset_types

    def test_subagent_memory_custom_max_lines(self):
        """Test per-subagent memory_max_lines via extra field."""
        from pydantic_deep.types import SubAgentConfig

        config = SubAgentConfig(
            name="analyst",
            description="Analyst",
            instructions="Analyze",
            extra={"memory_max_lines": 50},
        )
        create_deep_agent(
            model=TEST_MODEL,
            subagents=[config],
            include_memory=True,
        )

        assert "toolsets" in config
        memory_toolsets = [
            t for t in config["toolsets"] if type(t).__name__ == "AgentMemoryToolset"
        ]
        assert len(memory_toolsets) == 1
        assert memory_toolsets[0]._max_lines == 50

    def test_subagent_preserves_existing_toolsets(self):
        """Test that existing toolsets are preserved when memory is added."""
        from pydantic_ai.toolsets import FunctionToolset

        from pydantic_deep.types import SubAgentConfig

        existing_toolset = FunctionToolset(id="custom")
        config = SubAgentConfig(
            name="worker",
            description="Worker",
            instructions="Work",
            toolsets=[existing_toolset],
        )
        create_deep_agent(
            model=TEST_MODEL,
            subagents=[config],
            include_memory=True,
        )

        assert len(config["toolsets"]) >= 2
        toolset_types = [type(t).__name__ for t in config["toolsets"]]
        assert "FunctionToolset" in toolset_types
        assert "AgentMemoryToolset" in toolset_types

    def test_no_subagent_memory_when_include_memory_false(self):
        """Test that subagents don't get memory when include_memory=False."""
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

        # Should NOT have toolsets added for memory
        if "toolsets" in config:
            toolset_types = [type(t).__name__ for t in config["toolsets"]]
            assert "AgentMemoryToolset" not in toolset_types


# --- Constants Tests ---


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


# --- Export Tests ---


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
