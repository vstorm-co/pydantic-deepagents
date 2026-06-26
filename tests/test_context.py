"""Tests for project context file loading and injection."""

import pytest
from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import RunContext
from pydantic_ai.usage import RunUsage
from pydantic_ai_backends import StateBackend, ensure_async

from pydantic_deep import (
    DEFAULT_CONTEXT_FILENAMES,
    DEFAULT_MAX_CONTEXT_CHARS,
    SUBAGENT_CONTEXT_ALLOWLIST,
    ContextFile,
    ContextToolset,
    DeepAgentDeps,
    create_deep_agent,
    discover_context_files,
    format_context_prompt,
    load_context_files,
)
from pydantic_deep.features.context.service import _discover_and_load

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


class TestContextFile:
    """Tests for ContextFile dataclass."""

    def test_create(self):
        """Test creating a ContextFile."""
        cf = ContextFile(name="DEEP.md", path="/DEEP.md", content="# Hello")
        assert cf.name == "DEEP.md"
        assert cf.path == "/DEEP.md"
        assert cf.content == "# Hello"


class TestLoadContextFiles:
    """Tests for load_context_files function."""

    async def test_load_existing_file(self):
        """Test loading an existing context file."""
        backend = StateBackend()
        backend.write("/DEEP.md", "# Project Rules\nUse Python 3.12")

        files = await load_context_files(ensure_async(backend), ["/DEEP.md"])
        assert len(files) == 1
        assert files[0].name == "DEEP.md"
        assert files[0].path == "/DEEP.md"
        assert "Project Rules" in files[0].content

    async def test_load_multiple_files(self):
        """Test loading multiple context files."""
        backend = StateBackend()
        backend.write("/DEEP.md", "# Deep rules")
        backend.write("/AGENTS.md", "# Agent instructions")

        files = await load_context_files(ensure_async(backend), ["/DEEP.md", "/AGENTS.md"])
        assert len(files) == 2
        assert files[0].name == "DEEP.md"
        assert files[1].name == "AGENTS.md"

    async def test_skip_missing_files(self):
        """Test that missing files are silently skipped."""
        backend = StateBackend()
        backend.write("/DEEP.md", "# Exists")

        files = await load_context_files(ensure_async(backend), ["/DEEP.md", "/MISSING.md"])
        assert len(files) == 1
        assert files[0].name == "DEEP.md"

    async def test_all_missing(self):
        """Test that all missing files returns empty list."""
        backend = StateBackend()
        files = await load_context_files(ensure_async(backend), ["/MISSING.md", "/ALSO_MISSING.md"])
        assert files == []

    async def test_empty_paths(self):
        """Test with empty paths list."""
        backend = StateBackend()
        files = await load_context_files(ensure_async(backend), [])
        assert files == []

    async def test_utf8_content(self):
        """Test loading file with non-ASCII content."""
        backend = StateBackend()
        backend.write("/DEEP.md", "# Projekt\nUżyj polskich znaków: ąęćżź")

        files = await load_context_files(ensure_async(backend), ["/DEEP.md"])
        assert len(files) == 1
        assert "ąęćżź" in files[0].content

    async def test_nested_path(self):
        """Test loading file from nested path."""
        backend = StateBackend()
        backend.write("/project/config/DEEP.md", "# Nested")

        files = await load_context_files(ensure_async(backend), ["/project/config/DEEP.md"])
        assert len(files) == 1
        assert files[0].name == "DEEP.md"
        assert files[0].path == "/project/config/DEEP.md"


class TestDiscoverContextFiles:
    """Tests for discover_context_files function."""

    async def test_discover_at_root(self):
        """Test discovering context files at root."""
        backend = StateBackend()
        backend.write("/AGENTS.md", "# Agents")

        found = await discover_context_files(ensure_async(backend))
        assert "/AGENTS.md" in found

    async def test_discover_partial(self):
        """Test discovering when only some files exist."""
        backend = StateBackend()
        backend.write("/AGENTS.md", "# Agents")

        found = await discover_context_files(ensure_async(backend))
        assert found == ["/AGENTS.md"]

    async def test_discover_none_found(self):
        """Test discovering when no files exist."""
        backend = StateBackend()
        found = await discover_context_files(ensure_async(backend))
        assert found == []

    async def test_discover_custom_filenames(self):
        """Test discovering with custom filenames."""
        backend = StateBackend()
        backend.write("/CUSTOM.md", "# Custom")
        backend.write("/RULES.md", "# Rules")

        found = await discover_context_files(
            ensure_async(backend), filenames=["CUSTOM.md", "RULES.md", "MISSING.md"]
        )
        assert "/CUSTOM.md" in found
        assert "/RULES.md" in found
        assert len(found) == 2

    async def test_discover_custom_search_path(self):
        """Test discovering at a custom search path."""
        backend = StateBackend()
        backend.write("/project/AGENTS.md", "# Agents")

        found = await discover_context_files(ensure_async(backend), search_path="/project")
        assert found == ["/project/AGENTS.md"]

    async def test_discover_trailing_slash(self):
        """Test that trailing slash is handled correctly."""
        backend = StateBackend()
        backend.write("/project/AGENTS.md", "# Agents")

        found = await discover_context_files(ensure_async(backend), search_path="/project/")
        assert found == ["/project/AGENTS.md"]


class TestDiscoverAndLoad:
    """Tests for the _discover_and_load single-pass helper."""

    async def test_returns_loaded_files(self):
        """Test discovery and loading in one pass."""
        backend = StateBackend()
        backend.write("/AGENTS.md", "# Agents")
        backend.write("/SOUL.md", "# Soul")

        files = await _discover_and_load(ensure_async(backend))
        names = {f.name for f in files}
        assert "AGENTS.md" in names
        assert "SOUL.md" in names

    async def test_none_found(self):
        """Test empty backend returns empty list."""
        backend = StateBackend()
        assert await _discover_and_load(ensure_async(backend)) == []

    async def test_custom_filenames_and_search_path(self):
        """Test custom filenames and search path with trailing slash."""
        backend = StateBackend()
        backend.write("/project/CUSTOM.md", "# Custom")

        files = await _discover_and_load(
            ensure_async(backend), search_path="/project/", filenames=["CUSTOM.md", "MISSING.md"]
        )
        assert len(files) == 1
        assert files[0].name == "CUSTOM.md"
        assert files[0].path == "/project/CUSTOM.md"
        assert files[0].content == "# Custom"


class TestFormatContextPrompt:
    """Tests for format_context_prompt function."""

    def test_single_file(self):
        """Test formatting a single context file."""
        files = [ContextFile(name="DEEP.md", path="/DEEP.md", content="# Rules")]
        result = format_context_prompt(files)

        assert "## Project Context" in result
        assert "### DEEP.md" in result
        assert "# Rules" in result

    def test_multiple_files(self):
        """Test formatting multiple context files."""
        files = [
            ContextFile(name="DEEP.md", path="/DEEP.md", content="# Deep"),
            ContextFile(name="SOUL.md", path="/SOUL.md", content="# Soul"),
        ]
        result = format_context_prompt(files)

        assert "### DEEP.md" in result
        assert "### SOUL.md" in result
        assert "# Deep" in result
        assert "# Soul" in result

    def test_empty_files(self):
        """Test formatting with no files."""
        result = format_context_prompt([])
        assert result == ""

    def test_subagent_filtering(self):
        """Test that subagent mode filters out non-allowed files."""
        files = [
            ContextFile(name="AGENTS.md", path="/AGENTS.md", content="# Agents"),
            ContextFile(name="SOUL.md", path="/SOUL.md", content="# Soul"),
        ]
        result = format_context_prompt(files, is_subagent=True)

        assert "### AGENTS.md" in result
        assert "SOUL.md" not in result

    def test_subagent_all_filtered(self):
        """Test subagent mode when all files are filtered out."""
        files = [
            ContextFile(name="SOUL.md", path="/SOUL.md", content="# Soul"),
        ]
        result = format_context_prompt(files, is_subagent=True)
        assert result == ""

    def test_custom_subagent_allowlist(self):
        """Test custom subagent allowlist."""
        files = [
            ContextFile(name="DEEP.md", path="/DEEP.md", content="# Deep"),
            ContextFile(name="CUSTOM.md", path="/CUSTOM.md", content="# Custom"),
        ]
        result = format_context_prompt(
            files,
            is_subagent=True,
            subagent_allowlist=frozenset({"CUSTOM.md"}),
        )

        assert "DEEP.md" not in result
        assert "### CUSTOM.md" in result

    def test_truncation_applied(self):
        """Test that long content is truncated in output."""
        long_content = "x" * 30_000
        files = [ContextFile(name="DEEP.md", path="/DEEP.md", content=long_content)]
        result = format_context_prompt(files, max_chars=1000)

        assert "chars truncated" in result
        assert len(result) < 30_000

    def test_non_subagent_no_filtering(self):
        """Test that non-subagent mode passes all files through."""
        files = [
            ContextFile(name="SOUL.md", path="/SOUL.md", content="# Soul"),
        ]
        result = format_context_prompt(files, is_subagent=False)
        assert "### SOUL.md" in result


class TestContextToolset:
    """Tests for ContextToolset class."""

    def test_no_tools(self):
        """Test that ContextToolset has no tools."""
        toolset = ContextToolset(context_files=["/DEEP.md"])
        assert toolset.tools == {}

    def test_id(self):
        """Test toolset ID."""
        toolset = ContextToolset()
        assert toolset.id == "deep-context"

    async def test_get_instructions_explicit_files(self):
        """Test get_instructions with explicit context_files."""
        backend = StateBackend()
        backend.write("/DEEP.md", "# Project Rules")
        ctx = _make_ctx(backend)

        toolset = ContextToolset(context_files=["/DEEP.md"])
        result = await toolset.get_instructions(ctx)

        assert result is not None
        joined = "\n\n".join(p.content for p in result)
        assert "## Project Context" in joined
        assert "### DEEP.md" in joined
        assert "# Project Rules" in joined

    async def test_get_instructions_discovery(self):
        """Test get_instructions with auto-discovery."""
        backend = StateBackend()
        backend.write("/AGENTS.md", "# Agent instructions")
        ctx = _make_ctx(backend)

        toolset = ContextToolset(context_discovery=True)
        result = await toolset.get_instructions(ctx)

        assert result is not None
        joined = "\n\n".join(p.content for p in result)
        assert "### AGENTS.md" in joined

    async def test_get_instructions_no_config(self):
        """Test get_instructions with no files or discovery returns None."""
        ctx = _make_ctx()

        toolset = ContextToolset()
        result = await toolset.get_instructions(ctx)
        assert result is None

    async def test_get_instructions_missing_files(self):
        """Test get_instructions when all files are missing returns None."""
        ctx = _make_ctx()

        toolset = ContextToolset(context_files=["/MISSING.md"])
        result = await toolset.get_instructions(ctx)
        assert result is None

    async def test_get_instructions_subagent(self):
        """Test get_instructions with is_subagent=True filters files."""
        backend = StateBackend()
        backend.write("/AGENTS.md", "# Agents")
        backend.write("/SOUL.md", "# Soul")
        ctx = _make_ctx(backend)

        toolset = ContextToolset(
            context_files=["/AGENTS.md", "/SOUL.md"],
            is_subagent=True,
        )
        result = await toolset.get_instructions(ctx)

        assert result is not None
        joined = "\n\n".join(p.content for p in result)
        assert "### AGENTS.md" in joined
        assert "SOUL.md" not in joined

    async def test_get_instructions_subagent_all_filtered(self):
        """Test subagent with only non-allowed files returns None."""
        backend = StateBackend()
        backend.write("/SOUL.md", "# Soul")
        ctx = _make_ctx(backend)

        toolset = ContextToolset(
            context_files=["/SOUL.md"],
            is_subagent=True,
        )
        result = await toolset.get_instructions(ctx)
        assert result is None

    async def test_get_instructions_custom_max_chars(self):
        """Test get_instructions respects max_chars."""
        backend = StateBackend()
        backend.write("/DEEP.md", "x" * 30_000)
        ctx = _make_ctx(backend)

        toolset = ContextToolset(context_files=["/DEEP.md"], max_chars=1000)
        result = await toolset.get_instructions(ctx)

        assert result is not None
        joined = "\n\n".join(p.content for p in result)
        assert "chars truncated" in joined

    async def test_get_instructions_discovery_empty_backend(self):
        """Test discovery on empty backend returns None."""
        ctx = _make_ctx()

        toolset = ContextToolset(context_discovery=True)
        result = await toolset.get_instructions(ctx)
        assert result is None

    async def test_get_instructions_no_backend_returns_none(self):
        """Test get_instructions returns None when deps has no backend attribute."""

        class _NoBackendDeps:
            pass

        ctx = RunContext(
            deps=_NoBackendDeps(),
            model=TEST_MODEL,
            usage=RunUsage(),
        )

        toolset = ContextToolset(context_discovery=True)
        result = await toolset.get_instructions(ctx)
        assert result is None

    async def test_get_instructions_discovery_reads_each_file_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test discovery reads each context file's bytes only once."""
        backend = StateBackend()
        backend.write("/AGENTS.md", "# Agents")
        ctx = _make_ctx(backend)

        read_counts: dict[str, int] = {}
        # read_bytes is the sync read that AsyncBackendAdapter delegates to.
        original_read = backend.read_bytes

        def _counting_read(path: str) -> bytes:
            read_counts[path] = read_counts.get(path, 0) + 1
            data: bytes = original_read(path)
            return data

        monkeypatch.setattr(backend, "read_bytes", _counting_read)

        toolset = ContextToolset(context_discovery=True)
        result = await toolset.get_instructions(ctx)

        assert result is not None
        # Found files must be read exactly once, not once to test existence and
        # again to load contents.
        assert read_counts["/AGENTS.md"] == 1


class TestCreateDeepAgentContext:
    """Tests for create_deep_agent with context parameters."""

    def test_create_with_context_files(self):
        """Test creating an agent with context_files."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            context_files=["/DEEP.md", "/AGENTS.md"],
        )
        assert agent is not None

    def test_create_with_context_discovery(self):
        """Test creating an agent with context_discovery."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            context_discovery=True,
        )
        assert agent is not None

    def test_create_without_context(self):
        """Test default agent has no context toolset."""
        agent = create_deep_agent(model=TEST_MODEL)
        assert agent is not None

    def test_create_with_context_and_output_type(self):
        """Test context works with structured output."""
        from pydantic import BaseModel

        class Result(BaseModel):
            summary: str

        agent = create_deep_agent(
            model=TEST_MODEL,
            context_files=["/DEEP.md"],
            output_type=Result,
        )
        assert agent is not None


class TestPerSubagentContext:
    """Tests for per-subagent context_files in SubAgentConfig."""

    def test_create_with_per_subagent_context_files(self):
        """Test creating agent with subagents that have context_files."""
        from pydantic_deep.types import SubAgentConfig

        subagents = [
            SubAgentConfig(
                name="researcher",
                description="Research expert",
                instructions="You research topics",
                context_files=["/agents/researcher/AGENTS.md"],
            ),
        ]
        agent = create_deep_agent(
            model=TEST_MODEL,
            subagents=subagents,
        )
        assert agent is not None

    def test_per_subagent_context_injects_toolset(self):
        """context_files injection adds a ContextToolset to the config toolsets."""
        from pydantic_deep.agent import _inject_subagent_context_toolset
        from pydantic_deep.types import SubAgentConfig

        config = SubAgentConfig(
            name="coder",
            description="Code writer",
            instructions="Write code",
            context_files=["/agents/coder/AGENTS.md"],
        )
        _inject_subagent_context_toolset(config)

        assert "toolsets" in config
        toolset_types = [type(t).__name__ for t in config["toolsets"]]
        assert "ContextToolset" in toolset_types

    def test_per_subagent_preserves_existing_toolsets(self):
        """Existing config toolsets are not lost when a ContextToolset is added."""
        from pydantic_ai.toolsets import FunctionToolset

        from pydantic_deep.agent import _inject_subagent_context_toolset
        from pydantic_deep.types import SubAgentConfig

        existing_toolset = FunctionToolset(id="custom")

        config = SubAgentConfig(
            name="coder",
            description="Code writer",
            instructions="Write code",
            context_files=["/CODING_RULES.md"],
            toolsets=[existing_toolset],
        )
        _inject_subagent_context_toolset(config)

        toolset_types = [type(t).__name__ for t in config["toolsets"]]
        assert "FunctionToolset" in toolset_types
        assert "ContextToolset" in toolset_types
        assert len(config["toolsets"]) >= 2

    def test_per_subagent_no_context_files_no_context_injection(self):
        """Configs without context_files are left untouched (no ContextToolset)."""
        from pydantic_deep.agent import _inject_subagent_context_toolset
        from pydantic_deep.types import SubAgentConfig

        config = SubAgentConfig(
            name="worker",
            description="Generic worker",
            instructions="Do tasks",
        )
        _inject_subagent_context_toolset(config)

        # No context_files -> early return, no toolsets key injected.
        if "toolsets" in config:
            toolset_types = [type(t).__name__ for t in config["toolsets"]]
            assert "ContextToolset" not in toolset_types

    def test_per_subagent_context_not_filtered(self):
        """Test that per-subagent context is NOT filtered by allowlist.

        Per-subagent context_files are explicitly chosen by the developer,
        so they should not be filtered (unlike shared base context).
        """
        config_toolset = ContextToolset(
            context_files=["/agents/coder/SOUL.md"],  # SOUL.md - normally filtered for subagents
        )
        # is_subagent defaults to False - no filtering
        assert config_toolset._is_subagent is False


class TestContextConstants:
    """Tests for context module constants."""

    def test_default_filenames(self):
        """Test DEFAULT_CONTEXT_FILENAMES contains expected values."""
        assert "AGENTS.md" in DEFAULT_CONTEXT_FILENAMES
        assert "CLAUDE.md" in DEFAULT_CONTEXT_FILENAMES
        assert "SOUL.md" in DEFAULT_CONTEXT_FILENAMES
        assert ".cursorrules" in DEFAULT_CONTEXT_FILENAMES
        assert ".github/copilot-instructions.md" in DEFAULT_CONTEXT_FILENAMES
        assert "CONVENTIONS.md" in DEFAULT_CONTEXT_FILENAMES
        assert "CODING_GUIDELINES.md" in DEFAULT_CONTEXT_FILENAMES

    def test_subagent_allowlist(self):
        """Test SUBAGENT_CONTEXT_ALLOWLIST."""
        assert "AGENTS.md" in SUBAGENT_CONTEXT_ALLOWLIST
        assert "CLAUDE.md" in SUBAGENT_CONTEXT_ALLOWLIST
        assert "SOUL.md" not in SUBAGENT_CONTEXT_ALLOWLIST
        assert ".cursorrules" not in SUBAGENT_CONTEXT_ALLOWLIST

    def test_default_max_chars(self):
        """Test DEFAULT_MAX_CONTEXT_CHARS is 20K."""
        assert DEFAULT_MAX_CONTEXT_CHARS == 20_000


class TestContextExports:
    """Tests for context exports from the package."""

    def test_context_toolset_exported(self):
        """Test ContextToolset is importable from package."""
        from pydantic_deep import ContextToolset as exported

        assert exported is ContextToolset

    def test_context_file_exported(self):
        """Test ContextFile is importable from package."""
        from pydantic_deep import ContextFile as exported

        assert exported is ContextFile

    def test_load_context_files_exported(self):
        """Test load_context_files is importable from package."""
        from pydantic_deep import load_context_files as exported

        assert exported is load_context_files

    def test_discover_context_files_exported(self):
        """Test discover_context_files is importable from package."""
        from pydantic_deep import discover_context_files as exported

        assert exported is discover_context_files

    def test_format_context_prompt_exported(self):
        """Test format_context_prompt is importable from package."""
        from pydantic_deep import format_context_prompt as exported

        assert exported is format_context_prompt

    def test_constants_exported(self):
        """Test all constants are importable."""
        from pydantic_deep import (
            DEFAULT_CONTEXT_FILENAMES,
            DEFAULT_MAX_CONTEXT_CHARS,
            SUBAGENT_CONTEXT_ALLOWLIST,
        )

        assert DEFAULT_CONTEXT_FILENAMES is not None
        assert DEFAULT_MAX_CONTEXT_CHARS is not None
        assert SUBAGENT_CONTEXT_ALLOWLIST is not None
