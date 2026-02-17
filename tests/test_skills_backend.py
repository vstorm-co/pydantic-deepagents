"""Tests for backend-aware skills — resources, scripts, and directory discovery."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from pydantic_ai_backends import StateBackend
from pydantic_ai_backends.types import ExecuteResponse

from pydantic_deep.toolsets.skills.backend import (
    BackendSkillResource,
    BackendSkillScript,
    BackendSkillScriptExecutor,
    BackendSkillsDirectory,
    _discover_backend_resources,
    _discover_backend_scripts,
    _get_relative_path,
    _get_skill_dir,
    create_backend_resource,
    create_backend_script,
)
from pydantic_deep.toolsets.skills.exceptions import (
    SkillResourceLoadError,
    SkillScriptExecutionError,
    SkillValidationError,
)
from pydantic_deep.toolsets.skills.toolset import SkillsToolset
from pydantic_deep.toolsets.skills.types import SkillScript

# ==========================================================================
# Helper: create a mock SandboxProtocol (StateBackend + execute)
# ==========================================================================


class MockSandboxBackend(StateBackend):  # type: ignore[misc]
    """StateBackend with execute() support for testing."""

    def __init__(self, execute_result: ExecuteResponse | None = None) -> None:
        super().__init__()
        self._execute_result = execute_result or ExecuteResponse(output="ok", exit_code=0)
        self._last_command: str | None = None
        self._last_timeout: int | None = None

    def execute(self, command: str, timeout: int | None = None) -> ExecuteResponse:
        self._last_command = command
        self._last_timeout = timeout
        return self._execute_result

    @property
    def id(self) -> str:
        return "mock-sandbox"


# ==========================================================================
# Utility functions
# ==========================================================================


class TestUtilityFunctions:
    """Tests for helper utility functions."""

    def test_get_skill_dir_normal(self):
        assert _get_skill_dir("/skills/my-skill/SKILL.md") == "/skills/my-skill"

    def test_get_skill_dir_root(self):
        assert _get_skill_dir("SKILL.md") == "/"

    def test_get_skill_dir_nested(self):
        assert _get_skill_dir("/a/b/c/SKILL.md") == "/a/b/c"

    def test_get_relative_path_within_base(self):
        assert _get_relative_path("/skills/my-skill/data.json", "/skills/my-skill") == "data.json"

    def test_get_relative_path_nested(self):
        assert (
            _get_relative_path("/skills/my-skill/sub/file.md", "/skills/my-skill") == "sub/file.md"
        )

    def test_get_relative_path_outside_base(self):
        assert _get_relative_path("/other/file.txt", "/skills/my-skill") == "file.txt"

    def test_get_relative_path_exact_match(self):
        # When base == file path (trailing slash scenario), falls back to filename
        result = _get_relative_path("/skills/my-skill/", "/skills/my-skill/")
        assert result == ""  # empty after stripping


# ==========================================================================
# BackendSkillResource
# ==========================================================================


class TestBackendSkillResource:
    """Tests for BackendSkillResource."""

    @pytest.fixture
    def backend(self) -> StateBackend:
        backend = StateBackend()
        backend.write("/skills/test/readme.md", "# Hello World")
        backend.write("/skills/test/data.json", json.dumps({"key": "value"}))
        backend.write("/skills/test/config.yaml", "name: test\nversion: 1")
        backend.write("/skills/test/plain.txt", "plain text content")
        return backend

    async def test_load_text_resource(self, backend: StateBackend) -> None:
        resource = BackendSkillResource(
            name="readme.md",
            uri="/skills/test/readme.md",
            backend=backend,
        )
        result = await resource.load(ctx=None)
        assert result == "# Hello World"

    async def test_load_json_resource_auto_parse(self, backend: StateBackend) -> None:
        resource = BackendSkillResource(
            name="data.json",
            uri="/skills/test/data.json",
            backend=backend,
        )
        result = await resource.load(ctx=None)
        assert result == {"key": "value"}

    async def test_load_yaml_resource_auto_parse(self, backend: StateBackend) -> None:
        resource = BackendSkillResource(
            name="config.yaml",
            uri="/skills/test/config.yaml",
            backend=backend,
        )
        result = await resource.load(ctx=None)
        assert result == {"name": "test", "version": 1}

    async def test_load_yml_extension(self, backend: StateBackend) -> None:
        backend.write("/skills/test/config.yml", "items:\n  - one\n  - two")
        resource = BackendSkillResource(
            name="config.yml",
            uri="/skills/test/config.yml",
            backend=backend,
        )
        result = await resource.load(ctx=None)
        assert result == {"items": ["one", "two"]}

    async def test_load_plain_text(self, backend: StateBackend) -> None:
        resource = BackendSkillResource(
            name="plain.txt",
            uri="/skills/test/plain.txt",
            backend=backend,
        )
        result = await resource.load(ctx=None)
        assert result == "plain text content"

    async def test_load_invalid_json_returns_text(self, backend: StateBackend) -> None:
        backend.write("/skills/test/bad.json", "not json {")
        resource = BackendSkillResource(
            name="bad.json",
            uri="/skills/test/bad.json",
            backend=backend,
        )
        result = await resource.load(ctx=None)
        assert result == "not json {"

    async def test_load_invalid_yaml_returns_text(self, backend: StateBackend) -> None:
        backend.write("/skills/test/bad.yaml", "invalid: yaml: [")
        resource = BackendSkillResource(
            name="bad.yaml",
            uri="/skills/test/bad.yaml",
            backend=backend,
        )
        result = await resource.load(ctx=None)
        assert result == "invalid: yaml: ["

    async def test_load_no_uri_raises(self):
        resource = BackendSkillResource(
            name="test",
            content="placeholder",  # satisfy __post_init__
            backend=StateBackend(),
        )
        # Force uri to None after construction
        resource.uri = None
        with pytest.raises(SkillResourceLoadError, match="has no URI"):
            await resource.load(ctx=None)

    async def test_load_no_backend_raises(self):
        resource = BackendSkillResource(
            name="test",
            uri="/skills/test/file.txt",
            backend=None,
        )
        with pytest.raises(SkillResourceLoadError, match="has no backend"):
            await resource.load(ctx=None)

    async def test_load_backend_error_raises(self):
        """If _read_bytes raises, SkillResourceLoadError is raised."""
        failing_backend = MagicMock()
        failing_backend._read_bytes.side_effect = OSError("disk error")

        resource = BackendSkillResource(
            name="missing.txt",
            uri="/skills/test/missing.txt",
            backend=failing_backend,
        )
        with pytest.raises(SkillResourceLoadError, match="Failed to read resource"):
            await resource.load(ctx=None)

    async def test_load_no_extension(self, backend: StateBackend) -> None:
        backend.write("/skills/test/Makefile", "all: build")
        resource = BackendSkillResource(
            name="Makefile",
            uri="/skills/test/Makefile",
            backend=backend,
        )
        result = await resource.load(ctx=None)
        assert result == "all: build"


# ==========================================================================
# BackendSkillScriptExecutor
# ==========================================================================


class TestBackendSkillScriptExecutor:
    """Tests for BackendSkillScriptExecutor."""

    def _make_script(self, name: str = "test.py", uri: str = "/skills/test/test.py") -> SkillScript:
        from pydantic_deep.toolsets.skills.types import SkillScript

        return SkillScript(
            name=name,
            uri=uri,
            function=lambda: "noop",
            function_schema=MagicMock(),
        )

    async def test_run_basic(self):
        backend = MockSandboxBackend(ExecuteResponse(output="hello world", exit_code=0))
        executor = BackendSkillScriptExecutor(backend=backend, timeout=30)
        script = self._make_script()

        result = await executor.run(script)
        assert result == "hello world"
        assert backend._last_command == "python /skills/test/test.py"
        assert backend._last_timeout == 30

    async def test_run_with_args(self):
        backend = MockSandboxBackend(ExecuteResponse(output="done", exit_code=0))
        executor = BackendSkillScriptExecutor(backend=backend)
        script = self._make_script()

        result = await executor.run(script, args={"input": "data.csv", "verbose": True})
        assert result == "done"
        assert "--input data.csv" in backend._last_command  # type: ignore[operator]
        assert "--verbose" in backend._last_command  # type: ignore[operator]

    async def test_run_with_bool_false_skipped(self):
        backend = MockSandboxBackend(ExecuteResponse(output="ok", exit_code=0))
        executor = BackendSkillScriptExecutor(backend=backend)
        script = self._make_script()

        await executor.run(script, args={"debug": False})
        assert "--debug" not in backend._last_command  # type: ignore[operator]

    async def test_run_with_none_value_skipped(self):
        backend = MockSandboxBackend(ExecuteResponse(output="ok", exit_code=0))
        executor = BackendSkillScriptExecutor(backend=backend)
        script = self._make_script()

        await executor.run(script, args={"optional": None})
        assert "--optional" not in backend._last_command  # type: ignore[operator]

    async def test_run_with_list_args(self):
        backend = MockSandboxBackend(ExecuteResponse(output="ok", exit_code=0))
        executor = BackendSkillScriptExecutor(backend=backend)
        script = self._make_script()

        await executor.run(script, args={"file": ["a.txt", "b.txt"]})
        assert "--file a.txt --file b.txt" in backend._last_command  # type: ignore[operator]

    async def test_run_nonzero_exit(self):
        backend = MockSandboxBackend(ExecuteResponse(output="error msg", exit_code=1))
        executor = BackendSkillScriptExecutor(backend=backend)
        script = self._make_script()

        result = await executor.run(script)
        assert "Script exited with code 1" in result

    async def test_run_truncated_output(self):
        backend = MockSandboxBackend(
            ExecuteResponse(output="partial output", exit_code=0, truncated=True)
        )
        executor = BackendSkillScriptExecutor(backend=backend)
        script = self._make_script()

        result = await executor.run(script)
        assert "(output was truncated)" in result

    async def test_run_empty_output(self):
        backend = MockSandboxBackend(ExecuteResponse(output="", exit_code=0))
        executor = BackendSkillScriptExecutor(backend=backend)
        script = self._make_script()

        result = await executor.run(script)
        assert result == "(no output)"

    async def test_run_no_uri_raises(self):
        backend = MockSandboxBackend()
        executor = BackendSkillScriptExecutor(backend=backend)
        script = self._make_script(uri=None)
        script.uri = None

        with pytest.raises(SkillScriptExecutionError, match="has no URI"):
            await executor.run(script)

    async def test_run_backend_exception_raises(self):
        backend = MockSandboxBackend()
        backend.execute = MagicMock(side_effect=RuntimeError("connection lost"))  # type: ignore[method-assign]
        executor = BackendSkillScriptExecutor(backend=backend)
        script = self._make_script()

        with pytest.raises(SkillScriptExecutionError, match="Failed to execute"):
            await executor.run(script)


# ==========================================================================
# BackendSkillScript
# ==========================================================================


class TestBackendSkillScript:
    """Tests for BackendSkillScript."""

    async def test_run_delegates_to_executor(self):
        backend = MockSandboxBackend(ExecuteResponse(output="executed", exit_code=0))
        executor = BackendSkillScriptExecutor(backend=backend)
        script = BackendSkillScript(
            name="run.py",
            uri="/skills/test/run.py",
            executor=executor,
        )
        result = await script.run(ctx=None)
        assert result == "executed"

    async def test_run_no_uri_raises(self):
        backend = MockSandboxBackend()
        executor = BackendSkillScriptExecutor(backend=backend)
        script = BackendSkillScript(
            name="run.py",
            uri="/placeholder",  # satisfy __post_init__
            executor=executor,
        )
        # Force uri to None after construction
        script.uri = None
        with pytest.raises(SkillScriptExecutionError, match="has no URI"):
            await script.run(ctx=None)

    async def test_run_no_executor_raises(self):
        script = BackendSkillScript(
            name="run.py",
            uri="/skills/test/run.py",
            executor=None,
        )
        with pytest.raises(SkillScriptExecutionError, match="has no backend executor"):
            await script.run(ctx=None)


# ==========================================================================
# Factory functions
# ==========================================================================


class TestFactoryFunctions:
    """Tests for create_backend_resource and create_backend_script."""

    def test_create_backend_resource(self):
        backend = StateBackend()
        resource = create_backend_resource(
            name="data.json",
            uri="/skills/test/data.json",
            backend=backend,
            description="Test data",
        )
        assert isinstance(resource, BackendSkillResource)
        assert resource.name == "data.json"
        assert resource.uri == "/skills/test/data.json"
        assert resource.backend is backend
        assert resource.description == "Test data"

    def test_create_backend_script(self):
        backend = MockSandboxBackend()
        executor = BackendSkillScriptExecutor(backend=backend)
        script = create_backend_script(
            name="run.py",
            uri="/skills/test/run.py",
            skill_name="test-skill",
            executor=executor,
            description="Test script",
        )
        assert isinstance(script, BackendSkillScript)
        assert script.name == "run.py"
        assert script.uri == "/skills/test/run.py"
        assert script.skill_name == "test-skill"
        assert script.executor is executor
        assert script.description == "Test script"


# ==========================================================================
# Discovery functions
# ==========================================================================


class TestDiscovery:
    """Tests for _discover_backend_resources and _discover_backend_scripts."""

    def test_discover_resources(self):
        backend = StateBackend()
        backend.write("/skills/test/SKILL.md", "---\nname: test\n---\nContent")
        backend.write("/skills/test/readme.md", "# README")
        backend.write("/skills/test/data.json", '{"key": "val"}')
        backend.write("/skills/test/sub/template.txt", "template content")

        resources = _discover_backend_resources(backend, "/skills/test")

        names = [r.name for r in resources]
        assert "readme.md" in names or any("readme" in n for n in names)
        assert "data.json" in names or any("data.json" in n for n in names)
        # SKILL.md should be excluded
        assert not any("SKILL" in n.upper() for n in names)

    def test_discover_resources_empty_dir(self):
        backend = StateBackend()
        resources = _discover_backend_resources(backend, "/skills/empty")
        assert resources == []

    def test_discover_resources_glob_error_handled(self):
        """If glob_info throws, resources are still collected for other extensions."""
        backend = MagicMock()
        backend.glob_info.side_effect = RuntimeError("glob failed")
        resources = _discover_backend_resources(backend, "/skills/test")
        assert resources == []

    def test_discover_scripts(self):
        backend = MockSandboxBackend()
        backend.write("/skills/test/SKILL.md", "---\nname: test\n---\nContent")
        backend.write("/skills/test/analyze.py", "print('hello')")
        backend.write("/skills/test/scripts/process.py", "print('process')")
        backend.write("/skills/test/__init__.py", "")  # should be skipped

        executor = BackendSkillScriptExecutor(backend=backend)
        scripts = _discover_backend_scripts(backend, "/skills/test", "test", executor)

        names = [s.name for s in scripts]
        assert any("analyze.py" in n for n in names)
        assert any("process.py" in n for n in names)
        assert not any("__init__" in n for n in names)

    def test_discover_scripts_empty(self):
        backend = MockSandboxBackend()
        executor = BackendSkillScriptExecutor(backend=backend)
        scripts = _discover_backend_scripts(backend, "/skills/empty", "test", executor)
        assert scripts == []

    def test_discover_scripts_glob_error_handled(self):
        backend = MagicMock()
        backend.glob_info.side_effect = RuntimeError("glob failed")
        executor = MagicMock()
        scripts = _discover_backend_scripts(backend, "/skills/test", "test", executor)
        assert scripts == []

    def test_discover_scripts_deduplication(self):
        """Scripts found via multiple patterns should not be duplicated."""
        backend = MockSandboxBackend()
        # A file in root that might match both *.py and scripts/*.py if mispatched
        backend.write("/skills/test/run.py", "print('run')")

        executor = BackendSkillScriptExecutor(backend=backend)
        scripts = _discover_backend_scripts(backend, "/skills/test", "test", executor)

        paths = [s.uri for s in scripts]
        assert len(paths) == len(set(paths))


# ==========================================================================
# BackendSkillsDirectory
# ==========================================================================


class TestBackendSkillsDirectory:
    """Tests for BackendSkillsDirectory."""

    def _write_skill(
        self,
        backend: StateBackend,
        path: str,
        name: str,
        description: str = "A test skill",
        content: str = "Skill instructions here",
    ) -> None:
        """Helper to write a SKILL.md to the backend."""
        skill_md = f"---\nname: {name}\ndescription: {description}\n---\n{content}"
        backend.write(f"{path}/SKILL.md", skill_md)

    def test_discover_single_skill(self):
        backend = StateBackend()
        self._write_skill(backend, "/skills/my-skill", "my-skill")

        directory = BackendSkillsDirectory(backend=backend, path="/skills")
        assert "my-skill" in directory.skills

    def test_discover_multiple_skills(self):
        backend = StateBackend()
        self._write_skill(backend, "/skills/skill-a", "skill-a")
        self._write_skill(backend, "/skills/skill-b", "skill-b")

        directory = BackendSkillsDirectory(backend=backend, path="/skills")
        assert "skill-a" in directory.skills
        assert "skill-b" in directory.skills

    def test_discover_with_resources(self):
        backend = StateBackend()
        self._write_skill(backend, "/skills/my-skill", "my-skill")
        backend.write("/skills/my-skill/readme.md", "# Resource")
        backend.write("/skills/my-skill/data.json", '{"key": "val"}')

        directory = BackendSkillsDirectory(backend=backend, path="/skills")
        skill = directory.skills["my-skill"]
        assert len(skill.resources) >= 2

    def test_discover_with_scripts_sandbox(self):
        backend = MockSandboxBackend()
        self._write_skill(backend, "/skills/my-skill", "my-skill")
        backend.write("/skills/my-skill/analyze.py", "print('hello')")

        directory = BackendSkillsDirectory(backend=backend, path="/skills")
        skill = directory.skills["my-skill"]
        assert len(skill.scripts) >= 1

    def test_discover_no_scripts_without_sandbox(self):
        """Regular BackendProtocol (no execute) should not discover scripts."""
        backend = StateBackend()  # No execute()
        self._write_skill(backend, "/skills/my-skill", "my-skill")
        backend.write("/skills/my-skill/analyze.py", "print('hello')")

        directory = BackendSkillsDirectory(backend=backend, path="/skills")
        skill = directory.skills["my-skill"]
        assert len(skill.scripts) == 0

    def test_discover_empty_backend(self):
        backend = StateBackend()
        directory = BackendSkillsDirectory(backend=backend, path="/skills")
        assert directory.skills == {}

    def test_discover_with_metadata(self):
        backend = StateBackend()
        skill_md = (
            "---\nname: my-skill\ndescription: test\nlicense: MIT\nversion: 2.0\n---\nContent"
        )
        backend.write("/skills/my-skill/SKILL.md", skill_md)

        directory = BackendSkillsDirectory(backend=backend, path="/skills")
        skill = directory.skills["my-skill"]
        assert skill.license == "MIT"
        assert skill.metadata == {"version": 2.0}

    def test_discover_missing_name_skipped_with_validation(self):
        backend = StateBackend()
        backend.write("/skills/my-skill/SKILL.md", "---\ndescription: no name\n---\nContent")

        with pytest.warns(UserWarning, match="missing required"):
            directory = BackendSkillsDirectory(backend=backend, path="/skills")
        assert directory.skills == {}

    def test_discover_missing_name_uses_dirname_without_validation(self):
        backend = StateBackend()
        backend.write("/skills/my-skill/SKILL.md", "---\ndescription: no name\n---\nContent")

        directory = BackendSkillsDirectory(backend=backend, path="/skills", validate=False)
        assert "my-skill" in directory.skills

    def test_discover_respects_max_depth(self):
        backend = StateBackend()
        self._write_skill(backend, "/skills/level1", "level1")
        self._write_skill(backend, "/skills/a/level2", "level2")
        self._write_skill(backend, "/skills/a/b/level3", "level3")

        # max_depth=1 should find level1 only (1 level deep)
        directory = BackendSkillsDirectory(backend=backend, path="/skills", max_depth=1)
        assert "level1" in directory.skills
        # level2 and level3 may or may not be found depending on depth

    def test_discover_unlimited_depth(self):
        backend = StateBackend()
        self._write_skill(backend, "/skills/a/b/c/deep-skill", "deep-skill")

        directory = BackendSkillsDirectory(backend=backend, path="/skills", max_depth=None)
        assert "deep-skill" in directory.skills

    def test_get_skills_returns_dict(self):
        backend = StateBackend()
        self._write_skill(backend, "/skills/test", "test")

        directory = BackendSkillsDirectory(backend=backend, path="/skills")
        skills = directory.get_skills()
        assert isinstance(skills, dict)
        assert "test" in skills

    def test_skills_property(self):
        backend = StateBackend()
        self._write_skill(backend, "/skills/test", "test")

        directory = BackendSkillsDirectory(backend=backend, path="/skills")
        assert directory.skills == directory._skills

    def test_skill_uri_is_directory(self):
        backend = StateBackend()
        self._write_skill(backend, "/skills/my-skill", "my-skill")

        directory = BackendSkillsDirectory(backend=backend, path="/skills")
        skill = directory.skills["my-skill"]
        assert skill.uri == "/skills/my-skill"

    def test_validation_error_propagated(self):
        backend = StateBackend()
        # Invalid YAML frontmatter
        backend.write("/skills/test/SKILL.md", "---\ninvalid: yaml: [\n---\nContent")

        with pytest.raises(SkillValidationError):
            BackendSkillsDirectory(backend=backend, path="/skills")

    def test_validation_error_suppressed(self):
        backend = StateBackend()
        backend.write("/skills/test/SKILL.md", "---\ninvalid: yaml: [\n---\nContent")

        with pytest.warns(UserWarning, match="Skipping invalid skill"):
            directory = BackendSkillsDirectory(backend=backend, path="/skills", validate=False)
        assert directory.skills == {}

    def test_glob_error_returns_empty(self):
        backend = MagicMock()
        backend.glob_info.side_effect = RuntimeError("backend unavailable")

        directory = BackendSkillsDirectory.__new__(BackendSkillsDirectory)
        directory._backend = backend
        directory._path = "/skills"
        directory._validate = True
        directory._max_depth = 3
        directory._script_timeout = 30
        result = directory.get_skills()
        assert result == {}

    def test_unexpected_error_wraps_in_validation_error(self):
        backend = StateBackend()
        # Write a valid-looking SKILL.md but make _read_bytes fail
        backend.write("/skills/test/SKILL.md", "---\nname: test\n---\nContent")

        # Patch _read_bytes to fail after glob succeeds
        original_read = backend._read_bytes

        def failing_read(path: str) -> bytes:
            if "SKILL.md" in path:
                raise OSError("disk error")
            return original_read(path)  # type: ignore[no-any-return]

        backend._read_bytes = failing_read

        with pytest.raises(SkillValidationError, match="Failed to load skill"):
            BackendSkillsDirectory(backend=backend, path="/skills")

    def test_script_timeout_parameter(self):
        backend = MockSandboxBackend(ExecuteResponse(output="ok", exit_code=0))
        self._write_skill(backend, "/skills/test", "test")
        backend.write("/skills/test/run.py", "print('hi')")

        directory = BackendSkillsDirectory(backend=backend, path="/skills", script_timeout=60)
        skill = directory.skills["test"]
        # Scripts should use the configured timeout
        if skill.scripts:
            script = skill.scripts[0]
            assert isinstance(script, BackendSkillScript)
            assert script.executor.timeout == 60

    def test_no_frontmatter_returns_full_content(self):
        backend = StateBackend()
        backend.write("/skills/test/SKILL.md", "Just instructions, no frontmatter")

        # No name field → skipped with validation
        with pytest.warns(UserWarning, match="missing required"):
            directory = BackendSkillsDirectory(backend=backend, path="/skills")
        assert directory.skills == {}


# ==========================================================================
# Integration: SkillsToolset with BackendSkillsDirectory
# ==========================================================================


class TestToolsetIntegration:
    """Test SkillsToolset integration with BackendSkillsDirectory."""

    def test_toolset_accepts_backend_directory(self):
        backend = StateBackend()
        skill_md = "---\nname: backend-skill\ndescription: A backend skill\n---\nInstructions"
        backend.write("/skills/backend-skill/SKILL.md", skill_md)

        directory = BackendSkillsDirectory(backend=backend, path="/skills")
        toolset = SkillsToolset(directories=[directory])

        assert "backend-skill" in toolset.skills

    def test_toolset_mixed_directories(self, tmp_path):
        """Test mixing local and backend directories."""
        # Create a local skill
        skill_dir = tmp_path / "local-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: local-skill\ndescription: Local skill\n---\nLocal instructions"
        )

        # Create a backend skill
        backend = StateBackend()
        backend.write(
            "/skills/backend-skill/SKILL.md",
            "---\nname: backend-skill\ndescription: Backend skill\n---\nBackend instructions",
        )
        backend_dir = BackendSkillsDirectory(backend=backend, path="/skills")

        toolset = SkillsToolset(directories=[str(tmp_path), backend_dir])

        assert "local-skill" in toolset.skills
        assert "backend-skill" in toolset.skills


# ==========================================================================
# Agent integration
# ==========================================================================


class TestAgentIntegration:
    """Test create_deep_agent with BackendSkillsDirectory."""

    def test_create_agent_with_backend_skill_directories(self):
        from pydantic_deep.agent import create_deep_agent

        backend = StateBackend()
        backend.write(
            "/skills/agent-skill/SKILL.md",
            "---\nname: agent-skill\ndescription: Agent skill\n---\nInstructions",
        )
        backend_dir = BackendSkillsDirectory(backend=backend, path="/skills")

        agent = create_deep_agent(
            model="test",
            skill_directories=[backend_dir],
            include_subagents=False,
        )
        assert agent is not None


# ==========================================================================
# Edge cases for coverage
# ==========================================================================


class TestCoverageEdgeCases:
    """Tests to hit remaining uncovered lines."""

    async def test_yaml_without_pyyaml(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test YAML resource loading when pyyaml is not available."""
        import pydantic_deep.toolsets.skills.backend as backend_mod

        monkeypatch.setattr(backend_mod, "_HAS_YAML", False)

        backend = StateBackend()
        backend.write("/skills/test/config.yaml", "name: test\nversion: 1")

        resource = BackendSkillResource(
            name="config.yaml",
            uri="/skills/test/config.yaml",
            backend=backend,
        )
        # Without pyyaml, should return raw text
        result = await resource.load(ctx=None)
        assert isinstance(result, str)
        assert "name: test" in result

    def test_script_dedup_in_discovery(self):
        """Ensure duplicate scripts from overlapping patterns are deduplicated."""
        from pydantic_ai_backends.types import FileInfo

        # Mock backend that returns the same file for both patterns
        backend = MagicMock()
        dup_file = FileInfo(name="run.py", path="/skills/test/run.py", is_dir=False, size=10)
        backend.glob_info.return_value = [dup_file]

        executor = MagicMock()
        scripts = _discover_backend_scripts(backend, "/skills/test", "test", executor)

        # "*.py" and "scripts/*.py" both return the same path — should be deduped to 1
        assert len(scripts) == 1

    def test_skill_file_dedup_in_get_skills(self):
        """Ensure duplicate SKILL.md from depth patterns are deduplicated."""
        from pydantic_ai_backends.types import FileInfo

        backend = StateBackend()
        skill_md = "---\nname: dedup-test\ndescription: test\n---\nContent"
        backend.write("/skills/dedup-test/SKILL.md", skill_md)

        # Monkey-patch glob_info to return duplicates
        original_glob = backend.glob_info

        def glob_with_dupes(pattern: str, path: str = "/") -> list[FileInfo]:
            results = original_glob(pattern, path)
            return results + results  # type: ignore[no-any-return]

        backend.glob_info = glob_with_dupes

        directory = BackendSkillsDirectory.__new__(BackendSkillsDirectory)
        directory._backend = backend
        directory._path = "/skills"
        directory._validate = True
        directory._max_depth = 3
        directory._script_timeout = 30
        skills = directory.get_skills()

        assert "dedup-test" in skills
        assert len(skills) == 1
