"""Tests for skills toolset — exceptions, types, and local modules."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from pydantic_deep.toolsets.skills.exceptions import (
    SkillException,
    SkillNotFoundError,
    SkillResourceLoadError,
    SkillResourceNotFoundError,
    SkillScriptExecutionError,
    SkillValidationError,
)
from pydantic_deep.toolsets.skills.local import (
    CallableSkillScriptExecutor,
    FileBasedSkillResource,
    FileBasedSkillScript,
    LocalSkillScriptExecutor,
    create_file_based_resource,
    create_file_based_script,
)
from pydantic_deep.toolsets.skills.types import (
    SKILL_NAME_PATTERN,
    Skill,
    SkillResource,
    SkillScript,
    SkillWrapper,
    normalize_skill_name,
)

# ==========================================================================
# Exceptions
# ==========================================================================


class TestExceptions:
    """Tests for skills exception hierarchy."""

    def test_skill_exception_is_base(self):
        """All skill exceptions inherit from SkillException."""
        assert issubclass(SkillNotFoundError, SkillException)
        assert issubclass(SkillValidationError, SkillException)
        assert issubclass(SkillResourceNotFoundError, SkillException)
        assert issubclass(SkillResourceLoadError, SkillException)
        assert issubclass(SkillScriptExecutionError, SkillException)

    def test_exceptions_carry_message(self):
        """Exceptions carry the provided message."""
        err = SkillNotFoundError("test-skill not found")
        assert "test-skill not found" in str(err)


# ==========================================================================
# Types — normalize_skill_name
# ==========================================================================


class TestNormalizeSkillName:
    """Tests for normalize_skill_name."""

    def test_basic_normalization(self):
        assert normalize_skill_name("data_analyzer") == "data-analyzer"

    def test_lowercase(self):
        assert normalize_skill_name("my_cool_skill") == "my-cool-skill"

    def test_already_valid(self):
        assert normalize_skill_name("valid-name") == "valid-name"

    def test_invalid_characters_raises(self):
        with pytest.raises(SkillValidationError, match="invalid"):
            normalize_skill_name("bad.name")

    def test_too_long_raises(self):
        with pytest.raises(SkillValidationError, match="exceeds 64"):
            normalize_skill_name("a" * 65)

    def test_consecutive_hyphens_raises(self):
        with pytest.raises(SkillValidationError, match="invalid"):
            normalize_skill_name("bad--name")


class TestSkillNamePattern:
    """Tests for SKILL_NAME_PATTERN regex."""

    def test_valid_patterns(self):
        for name in ["a", "abc", "a-b", "my-skill-2", "abc123"]:
            assert SKILL_NAME_PATTERN.match(name), f"Should match: {name}"

    def test_invalid_patterns(self):
        for name in ["", "-a", "a-", "A", "a--b", "a_b", "a b"]:
            assert not SKILL_NAME_PATTERN.match(name), f"Should not match: {name}"


# ==========================================================================
# Types — SkillResource
# ==========================================================================


class TestSkillResource:
    """Tests for SkillResource dataclass."""

    def test_static_content_resource(self):
        res = SkillResource(name="doc", content="hello")
        assert res.name == "doc"
        assert res.content == "hello"
        assert res.function is None

    def test_uri_resource(self):
        res = SkillResource(name="data.json", uri="/path/to/data.json")
        assert res.uri == "/path/to/data.json"

    def test_no_content_no_function_no_uri_raises(self):
        with pytest.raises(ValueError, match="must have either"):
            SkillResource(name="bad")

    def test_function_without_schema_raises(self):
        with pytest.raises(ValueError, match="must have function_schema"):
            SkillResource(name="bad", function=lambda: "x")

    async def test_load_static_content(self):
        res = SkillResource(name="doc", content="hello world")
        result = await res.load(ctx=None)
        assert result == "hello world"

    async def test_load_no_content_raises(self):
        res = SkillResource(name="empty", uri="/tmp/x")
        with pytest.raises(ValueError, match="has no content or function"):
            await res.load(ctx=None)


# ==========================================================================
# Types — SkillScript
# ==========================================================================


class TestSkillScript:
    """Tests for SkillScript dataclass."""

    def test_uri_script(self):
        script = SkillScript(name="run.py", uri="/path/run.py")
        assert script.uri == "/path/run.py"

    def test_no_function_no_uri_raises(self):
        with pytest.raises(ValueError, match="must have either"):
            SkillScript(name="bad")

    def test_function_without_schema_raises(self):
        with pytest.raises(ValueError, match="must have function_schema"):
            SkillScript(name="bad", function=lambda: "x")

    async def test_run_no_function_raises(self):
        script = SkillScript(name="file.py", uri="/tmp/x.py")
        with pytest.raises(ValueError, match="has no function"):
            await script.run(ctx=None)


# ==========================================================================
# Types — Skill dataclass
# ==========================================================================


class TestSkill:
    """Tests for Skill dataclass."""

    def test_basic_creation(self):
        s = Skill(name="test", description="desc", content="instructions")
        assert s.name == "test"
        assert s.description == "desc"
        assert s.content == "instructions"
        assert s.resources == []
        assert s.scripts == []

    def test_with_resources(self):
        res = SkillResource(name="doc", content="hello")
        s = Skill(name="test", description="desc", content="instr", resources=[res])
        assert len(s.resources) == 1

    def test_resource_decorator(self):
        s = Skill(name="test", description="desc", content="instr")

        @s.resource
        def get_data() -> str:
            """Get data."""
            return "data"

        assert len(s.resources) == 1
        assert s.resources[0].name == "get_data"

    def test_resource_decorator_with_args(self):
        s = Skill(name="test", description="desc", content="instr")

        @s.resource(name="custom-name", description="Custom desc")  # type: ignore[untyped-decorator]
        def get_data() -> str:
            return "data"

        assert len(s.resources) == 1
        assert s.resources[0].name == "custom-name"
        assert s.resources[0].description == "Custom desc"

    def test_script_decorator(self):
        s = Skill(name="test", description="desc", content="instr")

        @s.script
        def run_analysis() -> str:
            """Run analysis."""
            return "done"

        assert len(s.scripts) == 1
        assert s.scripts[0].name == "run_analysis"

    def test_script_decorator_with_args(self):
        s = Skill(name="test", description="desc", content="instr")

        @s.script(name="custom-script")
        def run_it() -> str:
            return "done"

        assert len(s.scripts) == 1
        assert s.scripts[0].name == "custom-script"


# ==========================================================================
# Types — SkillWrapper
# ==========================================================================


class TestSkillWrapper:
    """Tests for SkillWrapper class."""

    def test_basic_wrapper(self) -> None:
        wrapper: SkillWrapper[Any] = SkillWrapper(
            function=lambda: "content",
            name="test-skill",
            description="desc",
            license=None,
            compatibility=None,
            metadata=None,
            resources=[],
            scripts=[],
        )
        assert wrapper.name == "test-skill"
        assert wrapper.description == "desc"

    def test_to_skill(self) -> None:
        wrapper: SkillWrapper[Any] = SkillWrapper(
            function=lambda: "content here",
            name="test-skill",
            description="desc",
            license="MIT",
            compatibility=None,
            metadata={"version": "1.0"},
            resources=[],
            scripts=[],
        )
        skill = wrapper.to_skill()
        assert isinstance(skill, Skill)
        assert skill.name == "test-skill"
        assert skill.content == "content here"
        assert skill.license == "MIT"
        assert skill.metadata == {"version": "1.0"}

    def test_resource_decorator(self) -> None:
        wrapper: SkillWrapper[Any] = SkillWrapper(
            function=lambda: "content",
            name="test",
            description="desc",
            license=None,
            compatibility=None,
            metadata=None,
            resources=[],
            scripts=[],
        )

        @wrapper.resource
        def get_data() -> str:
            """Get data."""
            return "data"

        assert len(wrapper.resources) == 1
        assert wrapper.resources[0].name == "get_data"

    def test_resource_decorator_with_args(self) -> None:
        wrapper: SkillWrapper[Any] = SkillWrapper(
            function=lambda: "content",
            name="test",
            description="desc",
            license=None,
            compatibility=None,
            metadata=None,
            resources=[],
            scripts=[],
        )

        @wrapper.resource(name="custom")  # type: ignore[untyped-decorator]
        def get_data() -> str:
            return "data"

        assert wrapper.resources[0].name == "custom"

    def test_script_decorator(self) -> None:
        wrapper: SkillWrapper[Any] = SkillWrapper(
            function=lambda: "content",
            name="test",
            description="desc",
            license=None,
            compatibility=None,
            metadata=None,
            resources=[],
            scripts=[],
        )

        @wrapper.script
        def do_thing() -> str:
            """Do a thing."""
            return "done"

        assert len(wrapper.scripts) == 1
        assert wrapper.scripts[0].name == "do_thing"

    def test_script_decorator_with_args(self) -> None:
        wrapper: SkillWrapper[Any] = SkillWrapper(
            function=lambda: "content",
            name="test",
            description="desc",
            license=None,
            compatibility=None,
            metadata=None,
            resources=[],
            scripts=[],
        )

        @wrapper.script(name="custom-script")  # type: ignore[untyped-decorator]
        def do_thing() -> str:
            return "done"

        assert wrapper.scripts[0].name == "custom-script"

    def test_to_skill_with_no_description(self) -> None:
        wrapper: SkillWrapper[Any] = SkillWrapper(
            function=lambda: "content",
            name="test",
            description=None,
            license=None,
            compatibility=None,
            metadata=None,
            resources=[],
            scripts=[],
        )
        skill = wrapper.to_skill()
        assert skill.description == ""


# ==========================================================================
# Local — FileBasedSkillResource
# ==========================================================================


class TestFileBasedSkillResource:
    """Tests for FileBasedSkillResource."""

    async def test_load_text_file(self, tmp_path: Path) -> None:
        f = tmp_path / "doc.md"
        f.write_text("# Hello")
        res = create_file_based_resource(name="doc.md", uri=str(f))
        result = await res.load(ctx=None)
        assert result == "# Hello"

    async def test_load_json_file(self, tmp_path: Path) -> None:
        f = tmp_path / "data.json"
        f.write_text(json.dumps({"key": "value"}))
        res = create_file_based_resource(name="data.json", uri=str(f))
        result = await res.load(ctx=None)
        assert result == {"key": "value"}

    async def test_load_json_invalid_fallback(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text("not json {{{")
        res = create_file_based_resource(name="bad.json", uri=str(f))
        result = await res.load(ctx=None)
        assert result == "not json {{{"

    async def test_load_yaml_file(self, tmp_path: Path) -> None:
        pytest.importorskip("yaml")
        f = tmp_path / "config.yaml"
        f.write_text("key: value\nlist:\n  - a\n  - b")
        res = create_file_based_resource(name="config.yaml", uri=str(f))
        result = await res.load(ctx=None)
        assert isinstance(result, dict)
        assert result["key"] == "value"

    async def test_load_no_uri_raises(self):
        res = FileBasedSkillResource(name="doc.md", uri=None, content="fallback")
        # Override uri to None after creation
        object.__setattr__(res, "uri", None)
        res.uri = None
        with pytest.raises(SkillResourceLoadError, match="has no URI"):
            await res.load(ctx=None)

    async def test_load_missing_file_raises(self):
        res = create_file_based_resource(name="gone.md", uri="/nonexistent/gone.md")
        with pytest.raises(SkillResourceLoadError, match="Failed to read"):
            await res.load(ctx=None)

    async def test_load_csv_file(self, tmp_path: Path) -> None:
        f = tmp_path / "data.csv"
        f.write_text("a,b,c\n1,2,3")
        res = create_file_based_resource(name="data.csv", uri=str(f))
        result = await res.load(ctx=None)
        assert "a,b,c" in result

    async def test_load_yml_extension(self, tmp_path: Path) -> None:
        pytest.importorskip("yaml")
        f = tmp_path / "config.yml"
        f.write_text("x: 1")
        res = create_file_based_resource(name="config.yml", uri=str(f))
        result = await res.load(ctx=None)
        assert result == {"x": 1}

    def test_create_with_description(self):
        res = create_file_based_resource(name="doc.md", uri="/path/doc.md", description="A doc")
        assert res.description == "A doc"


# ==========================================================================
# Local — LocalSkillScriptExecutor
# ==========================================================================


class TestLocalSkillScriptExecutor:
    """Tests for LocalSkillScriptExecutor."""

    async def test_run_basic_script(self, tmp_path: Path) -> None:
        script_file = tmp_path / "hello.py"
        script_file.write_text('print("hello world")')

        script = SkillScript(name="hello.py", uri=str(script_file))
        executor = LocalSkillScriptExecutor(timeout=10)
        result = await executor.run(script)
        assert "hello world" in result

    async def test_run_script_with_args(self, tmp_path: Path) -> None:
        script_file = tmp_path / "greet.py"
        script_file.write_text(
            "import argparse\np = argparse.ArgumentParser()\n"
            'p.add_argument("--name")\nargs = p.parse_args()\n'
            'print(f"Hi {args.name}")'
        )

        script = SkillScript(name="greet.py", uri=str(script_file))
        executor = LocalSkillScriptExecutor(timeout=10)
        result = await executor.run(script, args={"name": "Alice"})
        assert "Hi Alice" in result

    async def test_run_script_with_bool_arg(self, tmp_path: Path) -> None:
        script_file = tmp_path / "flags.py"
        script_file.write_text('import sys\nprint(" ".join(sys.argv[1:]))')

        script = SkillScript(name="flags.py", uri=str(script_file))
        executor = LocalSkillScriptExecutor(timeout=10)
        result = await executor.run(script, args={"verbose": True, "quiet": False})
        assert "--verbose" in result
        assert "--quiet" not in result

    async def test_run_script_with_list_arg(self, tmp_path: Path) -> None:
        script_file = tmp_path / "multi.py"
        script_file.write_text('import sys\nprint(" ".join(sys.argv[1:]))')

        script = SkillScript(name="multi.py", uri=str(script_file))
        executor = LocalSkillScriptExecutor(timeout=10)
        result = await executor.run(script, args={"item": ["a", "b"]})
        assert "--item a --item b" in result

    async def test_run_script_with_none_arg(self, tmp_path: Path) -> None:
        script_file = tmp_path / "none.py"
        script_file.write_text('import sys\nprint(" ".join(sys.argv[1:]))')

        script = SkillScript(name="none.py", uri=str(script_file))
        executor = LocalSkillScriptExecutor(timeout=10)
        result = await executor.run(script, args={"skip": None})
        # None args should be omitted
        assert "--skip" not in result

    async def test_run_script_no_uri_raises(self):
        script = SkillScript(name="nofile.py", uri="/tmp/nofile.py")
        object.__setattr__(script, "uri", None)
        script.uri = None
        executor = LocalSkillScriptExecutor(timeout=10)
        with pytest.raises(SkillScriptExecutionError, match="has no URI"):
            await executor.run(script)

    async def test_run_script_nonexistent_raises(self):
        script = SkillScript(name="missing.py", uri="/nonexistent/missing.py")
        executor = LocalSkillScriptExecutor(timeout=10)
        with pytest.raises(SkillScriptExecutionError, match="Failed to execute"):
            await executor.run(script)

    async def test_run_script_with_stderr(self, tmp_path: Path) -> None:
        script_file = tmp_path / "warn.py"
        script_file.write_text('import sys\nsys.stderr.write("warning\\n")\nprint("ok")')

        script = SkillScript(name="warn.py", uri=str(script_file))
        executor = LocalSkillScriptExecutor(timeout=10)
        result = await executor.run(script)
        assert "ok" in result
        assert "warning" in result

    async def test_run_script_nonzero_exit(self, tmp_path: Path) -> None:
        script_file = tmp_path / "fail.py"
        script_file.write_text("import sys\nsys.exit(1)")

        script = SkillScript(name="fail.py", uri=str(script_file))
        executor = LocalSkillScriptExecutor(timeout=10)
        result = await executor.run(script)
        assert "exited with code 1" in result

    async def test_run_script_no_output(self, tmp_path: Path) -> None:
        script_file = tmp_path / "silent.py"
        script_file.write_text("pass")

        script = SkillScript(name="silent.py", uri=str(script_file))
        executor = LocalSkillScriptExecutor(timeout=10)
        result = await executor.run(script)
        assert result == "(no output)"

    async def test_timeout(self, tmp_path: Path) -> None:
        script_file = tmp_path / "slow.py"
        script_file.write_text("import time\ntime.sleep(10)")

        script = SkillScript(name="slow.py", uri=str(script_file))
        executor = LocalSkillScriptExecutor(timeout=1)
        with pytest.raises(SkillScriptExecutionError, match="timed out"):
            await executor.run(script)

    def test_custom_python_executable(self):
        executor = LocalSkillScriptExecutor(python_executable="/usr/bin/python3")
        assert executor._python_executable == "/usr/bin/python3"


# ==========================================================================
# Local — CallableSkillScriptExecutor
# ==========================================================================


class TestCallableSkillScriptExecutor:
    """Tests for CallableSkillScriptExecutor."""

    async def test_sync_callable(self):
        def my_executor(script: SkillScript, args: dict[str, Any] | None = None) -> str:
            return f"Executed {script.name}"

        executor = CallableSkillScriptExecutor(func=my_executor)
        script = SkillScript(name="test.py", uri="/tmp/test.py")
        result = await executor.run(script)
        assert result == "Executed test.py"

    async def test_async_callable(self):
        async def my_executor(script: SkillScript, args: dict[str, Any] | None = None) -> str:
            return f"Async {script.name}"

        executor = CallableSkillScriptExecutor(func=my_executor)
        script = SkillScript(name="test.py", uri="/tmp/test.py")
        result = await executor.run(script)
        assert result == "Async test.py"


# ==========================================================================
# Local — FileBasedSkillScript
# ==========================================================================


class TestFileBasedSkillScript:
    """Tests for FileBasedSkillScript."""

    async def test_run_delegates_to_executor(self, tmp_path: Path) -> None:
        script_file = tmp_path / "hello.py"
        script_file.write_text('print("hi")')

        executor = LocalSkillScriptExecutor(timeout=10)
        script = create_file_based_script(
            name="hello.py",
            uri=str(script_file),
            skill_name="test",
            executor=executor,
        )
        result = await script.run(ctx=None)
        assert "hi" in result

    async def test_run_no_uri_raises(self):
        executor = LocalSkillScriptExecutor(timeout=10)
        script = FileBasedSkillScript(name="test.py", uri="/tmp/test.py", executor=executor)
        script.uri = None
        with pytest.raises(SkillScriptExecutionError, match="has no URI"):
            await script.run(ctx=None)

    def test_create_file_based_script(self, tmp_path: Path) -> None:
        executor = LocalSkillScriptExecutor(timeout=10)
        script = create_file_based_script(
            name="run.py",
            uri=str(tmp_path / "run.py"),
            skill_name="my-skill",
            executor=executor,
            description="Runs something",
        )
        assert script.name == "run.py"
        assert script.skill_name == "my-skill"
        assert script.description == "Runs something"


# ==========================================================================
# Callable resource/script (function_schema.call)
# ==========================================================================


class TestCallableResourceLoad:
    """Tests for SkillResource.load() with callable function."""

    async def test_load_callable_resource(self):
        """Test loading a resource with a function via function_schema."""
        mock_schema = MagicMock()
        mock_schema.call = AsyncMock(return_value="dynamic content")

        resource = SkillResource(
            name="dynamic",
            function=lambda: "unused",
            function_schema=mock_schema,
        )
        result = await resource.load(ctx=None, args={"key": "val"})
        assert result == "dynamic content"
        mock_schema.call.assert_awaited_once_with({"key": "val"}, None)

    async def test_load_callable_resource_no_args(self):
        """Test callable resource defaults args to {}."""
        mock_schema = MagicMock()
        mock_schema.call = AsyncMock(return_value="ok")

        resource = SkillResource(
            name="dynamic",
            function=lambda: "unused",
            function_schema=mock_schema,
        )
        result = await resource.load(ctx=None)
        assert result == "ok"
        mock_schema.call.assert_awaited_once_with({}, None)


class TestCallableScriptRun:
    """Tests for SkillScript.run() with callable function."""

    async def test_run_callable_script(self):
        """Test running a script with a function via function_schema."""
        mock_schema = MagicMock()
        mock_schema.call = AsyncMock(return_value="script output")

        script = SkillScript(
            name="run.py",
            function=lambda: "unused",
            function_schema=mock_schema,
        )
        result = await script.run(ctx=None, args={"x": 1})
        assert result == "script output"
        mock_schema.call.assert_awaited_once_with({"x": 1}, None)

    async def test_run_callable_script_no_args(self):
        """Test callable script defaults args to {}."""
        mock_schema = MagicMock()
        mock_schema.call = AsyncMock(return_value="done")

        script = SkillScript(
            name="run.py",
            function=lambda: "unused",
            function_schema=mock_schema,
        )
        result = await script.run(ctx=None)
        assert result == "done"
        mock_schema.call.assert_awaited_once_with({}, None)


# ==========================================================================
# FileBasedSkillResource YAML error fallback
# ==========================================================================


class TestFileBasedSkillResourceYamlError:
    """Tests for YAML parsing error fallback in FileBasedSkillResource."""

    async def test_load_yaml_parse_error_returns_raw(self, tmp_path: Path) -> None:
        """Invalid YAML falls back to raw content."""
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("invalid: yaml: [unterminated")

        resource = FileBasedSkillResource(
            name="bad.yaml",
            uri=str(yaml_file),
        )
        result = await resource.load(ctx=None)
        assert result == "invalid: yaml: [unterminated"

    async def test_load_yaml_without_pyyaml(self, tmp_path: Path) -> None:
        """YAML file loaded without pyyaml returns raw content."""
        import pydantic_deep.toolsets.skills.local as local_mod

        yaml_file = tmp_path / "data.yaml"
        yaml_file.write_text("key: value")

        resource = FileBasedSkillResource(
            name="data.yaml",
            uri=str(yaml_file),
        )

        original = local_mod._HAS_YAML
        try:
            local_mod._HAS_YAML = False
            result = await resource.load(ctx=None)
            assert result == "key: value"
        finally:
            local_mod._HAS_YAML = original
