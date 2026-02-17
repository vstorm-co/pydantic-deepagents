"""Extended tests for skills — directory, toolset, and agent integration."""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai._run_context import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from pydantic_deep import create_deep_agent
from pydantic_deep.toolsets.skills import (
    Skill,
    SkillNotFoundError,
    SkillResource,
    SkillsDirectory,
    SkillsToolset,
    SkillValidationError,
)
from pydantic_deep.toolsets.skills.directory import (
    _discover_resources,
    _discover_scripts,
    _discover_skills,
    _find_skill_files,
    _parse_skill_md,
    _parse_skill_md_regex,
    _validate_skill_metadata,
)
from pydantic_deep.toolsets.skills.local import LocalSkillScriptExecutor

# ==========================================================================
# Directory — _parse_skill_md_regex (fallback parser)
# ==========================================================================


class TestParseSkillMdRegex:
    """Tests for the regex-based YAML parser."""

    def test_basic_frontmatter(self) -> None:
        content = "---\nname: test-skill\ndescription: A test\n---\n\n# Instructions\n"
        fm, instr = _parse_skill_md_regex(content)
        assert fm["name"] == "test-skill"
        assert fm["description"] == "A test"
        assert "# Instructions" in instr

    def test_no_frontmatter(self) -> None:
        content = "Just instructions."
        fm, instr = _parse_skill_md_regex(content)
        assert fm == {}
        assert instr == "Just instructions."

    def test_with_tags_list(self) -> None:
        content = "---\nname: test\ntags:\n  - a\n  - b\n---\n\nBody."
        fm, instr = _parse_skill_md_regex(content)
        assert fm["tags"] == ["a", "b"]

    def test_quoted_values(self) -> None:
        content = "---\nname: \"quoted\"\ndescription: 'single'\n---\n\nBody."
        fm, instr = _parse_skill_md_regex(content)
        assert fm["name"] == "quoted"
        assert fm["description"] == "single"

    def test_empty_lines_in_frontmatter(self) -> None:
        content = "---\nname: test\n\ndescription: desc\n---\n\nBody."
        fm, _ = _parse_skill_md_regex(content)
        assert fm["name"] == "test"
        assert fm["description"] == "desc"


# ==========================================================================
# Directory — _parse_skill_md (with yaml or fallback)
# ==========================================================================


class TestParseSkillMd:
    """Tests for the main parser."""

    def test_basic_parsing(self) -> None:
        content = "---\nname: test-skill\ndescription: A test\n---\n\nInstructions."
        fm, instr = _parse_skill_md(content)
        assert fm["name"] == "test-skill"
        assert "Instructions" in instr

    def test_no_frontmatter(self) -> None:
        fm, instr = _parse_skill_md("Just text.")
        assert fm == {}
        assert instr == "Just text."

    def test_empty_frontmatter(self) -> None:
        content = "---\n\n---\n\nInstructions."
        fm, instr = _parse_skill_md(content)
        assert fm == {}


# ==========================================================================
# Directory — _validate_skill_metadata
# ==========================================================================


class TestValidateSkillMetadata:
    """Tests for skill metadata validation."""

    def test_valid_metadata(self) -> None:
        fm = {"name": "test-skill", "description": "Short desc"}
        assert _validate_skill_metadata(fm, "Short instructions.") is True

    def test_name_too_long(self) -> None:
        fm = {"name": "a" * 65}
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = _validate_skill_metadata(fm, "")
            assert result is False
            assert any("exceeds 64" in str(x.message) for x in w)

    def test_name_invalid_format(self) -> None:
        fm = {"name": "UPPERCASE"}
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = _validate_skill_metadata(fm, "")
            assert result is False
            assert any("lowercase" in str(x.message) for x in w)

    def test_name_reserved_word(self) -> None:
        fm = {"name": "my-anthropic-skill"}
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = _validate_skill_metadata(fm, "")
            assert result is False
            assert any("reserved word" in str(x.message) for x in w)

    def test_description_too_long(self) -> None:
        fm = {"name": "test", "description": "x" * 1025}
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = _validate_skill_metadata(fm, "")
            assert result is False
            assert any("1024" in str(x.message) for x in w)

    def test_compatibility_too_long(self) -> None:
        fm = {"name": "test", "compatibility": "x" * 501}
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = _validate_skill_metadata(fm, "")
            assert result is False
            assert any("500" in str(x.message) for x in w)

    def test_instructions_too_many_lines(self) -> None:
        fm = {"name": "test"}
        instr = "\n".join(["line"] * 501)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = _validate_skill_metadata(fm, instr)
            assert result is False
            assert any("500 lines" in str(x.message) for x in w)


# ==========================================================================
# Directory — discovery functions
# ==========================================================================


class TestDiscoveryFunctions:
    """Tests for resource, script, and skill discovery."""

    def test_discover_resources(self, tmp_path: Path) -> None:
        (tmp_path / "doc.md").write_text("# Doc")
        (tmp_path / "data.json").write_text("{}")
        (tmp_path / "SKILL.MD").write_text("skip me")  # Should be skipped

        resources = _discover_resources(tmp_path)
        names = {r.name for r in resources}
        assert "doc.md" in names
        assert "data.json" in names
        assert "SKILL.MD" not in names

    def test_discover_resources_with_subdirectory(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "nested.txt").write_text("nested content")

        resources = _discover_resources(tmp_path)
        names = {r.name for r in resources}
        assert "sub/nested.txt" in names

    def test_discover_scripts(self, tmp_path: Path) -> None:
        (tmp_path / "run.py").write_text("print('hi')")
        (tmp_path / "__init__.py").write_text("")  # Should be skipped

        executor = LocalSkillScriptExecutor(timeout=10)
        scripts = _discover_scripts(tmp_path, "test-skill", executor)
        names = {s.name for s in scripts}
        assert "run.py" in names
        assert "__init__.py" not in names

    def test_discover_scripts_in_scripts_dir(self, tmp_path: Path) -> None:
        scripts_dir = tmp_path / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "analyze.py").write_text("print('analyze')")
        (scripts_dir / "__init__.py").write_text("")

        executor = LocalSkillScriptExecutor(timeout=10)
        scripts = _discover_scripts(tmp_path, "test-skill", executor)
        names = {s.name for s in scripts}
        assert "scripts/analyze.py" in names
        assert "scripts/__init__.py" not in names

    def test_find_skill_files_unlimited(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        (nested / "SKILL.md").write_text("---\nname: deep\n---\n")

        files = _find_skill_files(tmp_path, max_depth=None)
        assert len(files) == 1

    def test_find_skill_files_depth_limited(self, tmp_path: Path) -> None:
        # Depth 0
        (tmp_path / "SKILL.md").write_text("root")
        # Depth 1
        d1 = tmp_path / "a"
        d1.mkdir()
        (d1 / "SKILL.md").write_text("depth1")
        # Depth 3 (should be excluded with max_depth=2)
        d3 = tmp_path / "a" / "b" / "c"
        d3.mkdir(parents=True)
        (d3 / "SKILL.md").write_text("depth3")

        files = _find_skill_files(tmp_path, max_depth=1)
        assert len(files) == 2  # root + depth1

    def test_discover_skills_basic(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: my-skill\ndescription: Test\n---\n\nInstructions."
        )

        skills = _discover_skills(tmp_path)
        assert len(skills) == 1
        assert skills[0].name == "my-skill"

    def test_discover_skills_nonexistent_dir(self) -> None:
        skills = _discover_skills("/nonexistent/path")
        assert skills == []

    def test_discover_skills_not_a_dir(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("not a dir")
        skills = _discover_skills(f)
        assert skills == []

    def test_discover_skills_missing_name_with_validate(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "unnamed"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\ndescription: No name\n---\n\nInstr.")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            skills = _discover_skills(tmp_path, validate=True)
            assert len(skills) == 0
            assert any("missing required" in str(x.message) for x in w)

    def test_discover_skills_missing_name_without_validate(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "unnamed"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\ndescription: No name\n---\n\nInstr.")

        skills = _discover_skills(tmp_path, validate=False)
        assert len(skills) == 1
        assert skills[0].name == "unnamed"

    def test_discover_skills_with_metadata(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "meta"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: meta\ndescription: desc\nlicense: MIT\n"
            "compatibility: py310\nversion: 2.0\n---\n\nBody."
        )

        skills = _discover_skills(tmp_path, validate=False)
        assert len(skills) == 1
        assert skills[0].license == "MIT"
        assert skills[0].compatibility == "py310"
        assert skills[0].metadata == {"version": 2.0}

    def test_discover_skills_oserror(self, tmp_path: Path) -> None:
        """OSError during read raises SkillValidationError."""
        skill_dir = tmp_path / "broken"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("---\nname: test\n---\nInstr.")
        # Make unreadable
        skill_file.chmod(0o000)

        try:
            with pytest.raises(SkillValidationError, match="Failed to load"):
                _discover_skills(tmp_path)
        finally:
            skill_file.chmod(0o644)


# ==========================================================================
# Directory — SkillsDirectory class
# ==========================================================================


class TestSkillsDirectory:
    """Tests for SkillsDirectory class."""

    def test_basic_directory(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test-skill\ndescription: Test\n---\n\nInstr."
        )

        sd = SkillsDirectory(path=tmp_path)
        assert len(sd.skills) == 1

    def test_load_skill(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test-skill\ndescription: Test\n---\n\nInstr."
        )

        sd = SkillsDirectory(path=tmp_path)
        uri = next(iter(sd.skills.keys()))
        skill = sd.load_skill(uri)
        assert skill.name == "test-skill"

    def test_load_skill_not_found(self, tmp_path: Path) -> None:
        sd = SkillsDirectory(path=tmp_path)
        with pytest.raises(SkillNotFoundError, match="not found"):
            sd.load_skill("nonexistent")

    def test_empty_directory(self, tmp_path: Path) -> None:
        sd = SkillsDirectory(path=tmp_path)
        assert len(sd.skills) == 0


# ==========================================================================
# Toolset — SkillsToolset
# ==========================================================================


class TestSkillsToolset:
    """Tests for SkillsToolset."""

    def test_create_with_skills(self) -> None:
        skill = Skill(name="test", description="desc", content="instr")
        toolset = SkillsToolset(skills=[skill])
        assert "test" in toolset.skills

    def test_create_with_directories(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test-skill\ndescription: Test\n---\n\nInstr."
        )

        toolset = SkillsToolset(directories=[str(tmp_path)])
        assert "test-skill" in toolset.skills

    def test_create_with_skills_directory_instance(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test-skill\ndescription: Test\n---\n\nInstr."
        )

        sd = SkillsDirectory(path=tmp_path)
        toolset = SkillsToolset(directories=[sd])
        assert "test-skill" in toolset.skills

    def test_get_skill(self) -> None:
        skill = Skill(name="test", description="desc", content="instr")
        toolset = SkillsToolset(skills=[skill])
        result = toolset.get_skill("test")
        assert result.name == "test"

    def test_get_skill_not_found(self) -> None:
        toolset = SkillsToolset(skills=[])
        with pytest.raises(SkillNotFoundError, match="not found"):
            toolset.get_skill("nonexistent")

    def test_exclude_tools(self) -> None:
        skill = Skill(name="test", description="desc", content="instr")
        toolset = SkillsToolset(
            skills=[skill],
            exclude_tools=["run_skill_script"],
        )
        tool_names = set(toolset.tools.keys())
        assert "run_skill_script" not in tool_names
        assert "list_skills" in tool_names

    def test_exclude_invalid_tool_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown tools"):
            SkillsToolset(skills=[], exclude_tools=["invalid_tool"])

    def test_exclude_load_skill_warns(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            SkillsToolset(skills=[], exclude_tools=["load_skill"])
            assert any("critical" in str(x.message).lower() for x in w)

    def test_default_directory_warns(self) -> None:
        """When no skills or dirs provided, warns about missing ./skills."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            SkillsToolset()
            assert any("does not exist" in str(x.message) for x in w)

    def test_duplicate_skill_warns(self) -> None:
        skill1 = Skill(name="dupe", description="first", content="a")
        skill2 = Skill(name="dupe", description="second", content="b")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            toolset = SkillsToolset(skills=[skill1, skill2])
            assert any("Duplicate" in str(x.message) for x in w)
        assert toolset.skills["dupe"].description == "second"

    def test_custom_id(self) -> None:
        toolset = SkillsToolset(skills=[], id="custom")
        assert toolset.id == "custom"

    def test_skill_decorator(self) -> None:
        toolset = SkillsToolset(skills=[])

        @toolset.skill
        def my_analyzer() -> str:
            """Analyze stuff."""
            return "Use this for analysis."

        assert "my-analyzer" in toolset.skills
        assert toolset.skills["my-analyzer"].content == "Use this for analysis."

    def test_skill_decorator_with_args(self) -> None:
        toolset = SkillsToolset(skills=[])

        @toolset.skill(name="custom-name", description="Custom desc")  # type: ignore[untyped-decorator]
        def my_skill() -> str:
            return "content"

        assert "custom-name" in toolset.skills
        assert toolset.skills["custom-name"].description == "Custom desc"

    def test_skill_decorator_invalid_name(self) -> None:
        toolset = SkillsToolset(skills=[])
        with pytest.raises(SkillValidationError, match="invalid"):

            @toolset.skill(name="INVALID!")  # type: ignore[untyped-decorator]
            def bad() -> str:
                return "x"

    def test_skill_decorator_name_too_long(self) -> None:
        toolset = SkillsToolset(skills=[])
        with pytest.raises(SkillValidationError, match="exceeds 64"):

            @toolset.skill(name="a" * 65)  # type: ignore[untyped-decorator]
            def bad() -> str:
                return "x"


# ==========================================================================
# Toolset — get_instructions
# ==========================================================================


class TestGetInstructions:
    """Tests for SkillsToolset.get_instructions."""

    async def test_no_skills_returns_none(self) -> None:
        toolset = SkillsToolset(skills=[])
        result = await toolset.get_instructions(ctx=None)
        assert result is None

    async def test_with_skills_returns_xml(self) -> None:
        skill = Skill(name="test", description="desc", content="instr")
        toolset = SkillsToolset(skills=[skill])
        result = await toolset.get_instructions(ctx=None)
        assert result is not None
        assert "<name>test</name>" in result
        assert "<description>desc</description>" in result

    async def test_custom_template(self) -> None:
        skill = Skill(name="test", description="desc", content="instr")
        toolset = SkillsToolset(
            skills=[skill],
            instruction_template="Custom: {skills_list}",
        )
        result = await toolset.get_instructions(ctx=None)
        assert result is not None
        assert result.startswith("Custom:")

    async def test_with_uri(self) -> None:
        skill = Skill(name="test", description="desc", content="instr", uri="/path/to/skill")
        toolset = SkillsToolset(skills=[skill])
        result = await toolset.get_instructions(ctx=None)
        assert result is not None
        assert "<uri>/path/to/skill</uri>" in result


# ==========================================================================
# Toolset — Tool functions (via TestModel)
# ==========================================================================


class TestToolFunctions:
    """Tests for the actual tool functions registered by SkillsToolset."""

    @staticmethod
    def _make_ctx() -> RunContext[Any]:
        return RunContext[Any](
            deps=None,
            model=TestModel(),
            usage=RunUsage(),
            retry=0,
            run_step=0,
            tool_name=None,
            tool_call_id=None,
        )

    async def _call(
        self,
        toolset: SkillsToolset,
        name: str,
        args: dict[str, Any] | None = None,
    ) -> Any:
        ctx = self._make_ctx()
        tools = await toolset.get_tools(ctx)
        return await toolset.call_tool(name, args or {}, ctx, tools[name])

    async def test_list_skills_tool(self) -> None:
        skill = Skill(name="test", description="desc", content="instr")
        toolset = SkillsToolset(skills=[skill], id="test-skills")

        result = await self._call(toolset, "list_skills")
        assert result == {"test": "desc"}

    async def test_load_skill_tool(self) -> None:
        skill = Skill(
            name="test",
            description="desc",
            content="Instructions here",
            resources=[SkillResource(name="doc.md", content="hello")],
        )
        toolset = SkillsToolset(skills=[skill], id="test-skills")

        result = await self._call(toolset, "load_skill", {"skill_name": "test"})
        assert "<name>test</name>" in result
        assert "Instructions here" in result
        assert 'name="doc.md"' in result

    async def test_load_skill_not_found(self) -> None:
        toolset = SkillsToolset(
            skills=[Skill(name="test", description="d", content="c")],
            id="test-skills",
        )

        result = await self._call(toolset, "load_skill", {"skill_name": "nonexistent"})
        assert "Error:" in result
        assert "nonexistent" in result

    async def test_read_skill_resource_tool(self) -> None:
        skill = Skill(
            name="test",
            description="desc",
            content="instr",
            resources=[SkillResource(name="doc.md", content="resource content")],
        )
        toolset = SkillsToolset(skills=[skill], id="test-skills")

        result = await self._call(
            toolset, "read_skill_resource", {"skill_name": "test", "resource_name": "doc.md"}
        )
        assert result == "resource content"

    async def test_read_skill_resource_not_found(self) -> None:
        skill = Skill(name="test", description="d", content="c")
        toolset = SkillsToolset(skills=[skill], id="test-skills")

        result = await self._call(
            toolset, "read_skill_resource", {"skill_name": "test", "resource_name": "missing.md"}
        )
        assert "Error:" in result
        assert "missing.md" in result

    async def test_read_skill_resource_skill_not_found(self) -> None:
        toolset = SkillsToolset(skills=[], id="test-skills")

        result = await self._call(
            toolset, "read_skill_resource", {"skill_name": "bad", "resource_name": "doc.md"}
        )
        assert "Error:" in result
        assert "bad" in result

    async def test_run_skill_script_not_found(self) -> None:
        skill = Skill(name="test", description="d", content="c")
        toolset = SkillsToolset(skills=[skill], id="test-skills")

        result = await self._call(
            toolset, "run_skill_script", {"skill_name": "test", "script_name": "missing.py"}
        )
        assert "Error:" in result
        assert "missing.py" in result

    async def test_run_skill_script_skill_not_found(self) -> None:
        toolset = SkillsToolset(skills=[], id="test-skills")

        result = await self._call(
            toolset, "run_skill_script", {"skill_name": "bad", "script_name": "run.py"}
        )
        assert "Error:" in result
        assert "bad" in result

    async def test_load_skill_with_no_resources_or_scripts(self) -> None:
        skill = Skill(name="test", description="desc", content="instr")
        toolset = SkillsToolset(skills=[skill], id="test-skills")

        result = await self._call(toolset, "load_skill", {"skill_name": "test"})
        assert "<!-- No resources -->" in result
        assert "<!-- No scripts -->" in result


# ==========================================================================
# Agent integration
# ==========================================================================


class TestAgentIntegration:
    """Tests for skills integration with create_deep_agent."""

    def test_create_agent_with_skills(self) -> None:
        skill = Skill(name="test-skill", description="Test", content="Instructions")
        agent = create_deep_agent(
            model=TestModel(),
            skills=[skill],
            include_skills=True,
        )
        assert agent is not None

    def test_create_agent_with_skill_directories(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test-skill\ndescription: Test\n---\n\nInstr."
        )

        agent = create_deep_agent(
            model=TestModel(),
            skill_directories=[str(tmp_path)],
            include_skills=True,
        )
        assert agent is not None

    def test_create_agent_with_legacy_skill_directories(self, tmp_path: Path) -> None:
        """Test backward compat with SkillDirectory TypedDict."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test-skill\ndescription: Test\n---\n\nInstr."
        )

        agent = create_deep_agent(
            model=TestModel(),
            skill_directories=[{"path": str(tmp_path)}],
            include_skills=True,
        )
        assert agent is not None

    def test_create_agent_without_skills(self) -> None:
        agent = create_deep_agent(
            model=TestModel(),
            include_skills=False,
        )
        assert agent is not None

    def test_create_agent_skills_none(self) -> None:
        """When skills=None and no directories, default ./skills is used."""
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            agent = create_deep_agent(
                model=TestModel(),
                include_skills=True,
            )
        assert agent is not None


# ==========================================================================
# Coverage — directory edge cases
# ==========================================================================


class TestDirectoryCoverageEdgeCases:
    """Tests for uncovered branches in directory.py."""

    def test_validate_metadata_no_name(self) -> None:
        """_validate_skill_metadata with empty name skips name checks."""
        # Covers branch 64->92 (name is falsy, skip to description check)
        result = _validate_skill_metadata({"description": "test"}, "Body.")
        assert result is True

    def test_parse_skill_md_regex_line_without_colon(self) -> None:
        """Regex parser handles lines without colon in frontmatter."""
        import pydantic_deep.toolsets.skills.directory as dir_module

        original = dir_module._HAS_YAML
        try:
            dir_module._HAS_YAML = False
            # Include a line without ":" to hit the else branch
            content = "---\nname: test\nno-colon-line\ndescription: desc\n---\n\nBody."
            frontmatter, instructions = _parse_skill_md(content)
            assert frontmatter["name"] == "test"
            assert frontmatter["description"] == "desc"
        finally:
            dir_module._HAS_YAML = original

    def test_parse_skill_md_yaml_error(self) -> None:
        """Malformed YAML raises SkillValidationError."""
        content = "---\ninvalid: yaml: [\n---\n\nBody."
        with pytest.raises(SkillValidationError, match="Failed to parse YAML"):
            _parse_skill_md(content)

    def test_parse_skill_md_no_yaml(self) -> None:
        """Test fallback to regex parser when pyyaml unavailable."""
        import pydantic_deep.toolsets.skills.directory as dir_module

        original = dir_module._HAS_YAML
        try:
            dir_module._HAS_YAML = False
            frontmatter, instructions = _parse_skill_md(
                "---\nname: test\ndescription: desc\n---\n\nBody text."
            )
            assert frontmatter["name"] == "test"
            assert frontmatter["description"] == "desc"
            assert "Body text" in instructions
        finally:
            dir_module._HAS_YAML = original

    def test_discover_resources_symlink_escape(self, tmp_path: Path) -> None:
        """Symlink escaping skill directory emits warning."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        outside = tmp_path / "outside.md"
        outside.write_text("evil content")
        symlink = skill_dir / "escaped.md"
        symlink.symlink_to(outside)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            resources = _discover_resources(skill_dir)

        # Symlinked file should be skipped
        resource_names = [r.name for r in resources]
        assert "escaped.md" not in resource_names
        assert any("symlink escape" in str(warning.message) for warning in w)

    def test_discover_scripts_symlink_escape(self, tmp_path: Path) -> None:
        """Symlinked script escaping skill directory emits warning."""
        skill_dir = tmp_path / "my-skill"
        skill_dir.mkdir()
        outside = tmp_path / "evil.py"
        outside.write_text("print('evil')")
        symlink = skill_dir / "evil.py"
        symlink.symlink_to(outside)

        from pydantic_deep.toolsets.skills.local import LocalSkillScriptExecutor

        executor = LocalSkillScriptExecutor(timeout=10)

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            scripts = _discover_scripts(skill_dir, "my-skill", executor)

        script_names = [s.name for s in scripts]
        assert "evil.py" not in script_names
        assert any("symlink escape" in str(warning.message) for warning in w)

    def test_discover_skills_validation_error_suppressed(self, tmp_path: Path) -> None:
        """With validate=False, SkillValidationError emits warning instead of raising."""
        # Malformed YAML triggers SkillValidationError from _parse_skill_md
        skill_dir = tmp_path / "bad-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\ninvalid: yaml: [\n---\n\nBody.")

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            skills = _discover_skills(tmp_path, validate=False)

        assert len(skills) == 0
        assert any("Skipping invalid skill" in str(warning.message) for warning in w)

    def test_discover_skills_validation_error_raised(self, tmp_path: Path) -> None:
        """With validate=True (default), SkillValidationError re-raises."""
        skill_dir = tmp_path / "bad-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\ninvalid: yaml: [\n---\n\nBody.")

        with pytest.raises(SkillValidationError):
            _discover_skills(tmp_path, validate=True)


# ==========================================================================
# Coverage — toolset XML building and tool integration
# ==========================================================================


class TestToolsetCoverageEdgeCases:
    """Tests for uncovered branches in toolset.py."""

    def test_build_resource_xml_with_description(self) -> None:
        resource = SkillResource(
            name="doc.md",
            description="API docs",
            content="stuff",
        )
        toolset = SkillsToolset(skills=[], id="test")
        xml = toolset._build_resource_xml(resource)
        assert 'description="API docs"' in xml

    def test_build_resource_xml_with_function_schema(self) -> None:
        from unittest.mock import MagicMock

        mock_schema = MagicMock()
        mock_schema.json_schema = {"type": "object", "properties": {"x": {"type": "string"}}}

        resource = SkillResource(
            name="dynamic",
            function=lambda: "unused",
            function_schema=mock_schema,
        )
        toolset = SkillsToolset(skills=[], id="test")
        xml = toolset._build_resource_xml(resource)
        assert "parameters=" in xml
        assert "dynamic" in xml

    def test_build_script_xml_with_description(self) -> None:
        from pydantic_deep.toolsets.skills import SkillScript

        script = SkillScript(name="run.py", uri="file:///run.py", description="Runs tests")
        toolset = SkillsToolset(skills=[], id="test")
        xml = toolset._build_script_xml(script)
        assert 'description="Runs tests"' in xml

    def test_build_script_xml_with_function_schema(self) -> None:
        from unittest.mock import MagicMock

        from pydantic_deep.toolsets.skills import SkillScript

        mock_schema = MagicMock()
        mock_schema.json_schema = {"type": "object", "properties": {}}

        script = SkillScript(
            name="run.py",
            function=lambda: "unused",
            function_schema=mock_schema,
        )
        toolset = SkillsToolset(skills=[], id="test")
        xml = toolset._build_script_xml(script)
        assert "parameters=" in xml

    def test_exclude_read_skill_resource(self) -> None:
        """Excluding read_skill_resource removes it from tool list."""
        skill = Skill(name="test", description="d", content="c")
        toolset = SkillsToolset(
            skills=[skill],
            id="test",
            exclude_tools=["read_skill_resource"],
        )
        assert "read_skill_resource" not in toolset.tools
        assert "list_skills" in toolset.tools
        assert "load_skill" in toolset.tools
        assert "run_skill_script" in toolset.tools

    async def test_find_resource_with_multiple_resources(self) -> None:
        """Find a resource when skill has multiple resources (loop iterates)."""
        skill = Skill(
            name="test",
            description="desc",
            content="instr",
            resources=[
                SkillResource(name="first.md", content="first"),
                SkillResource(name="second.md", content="second"),
            ],
        )
        toolset = SkillsToolset(skills=[skill], id="test-skills")

        ctx = RunContext[Any](
            deps=None,
            model=TestModel(),
            usage=RunUsage(),
            retry=0,
            run_step=0,
            tool_name=None,
            tool_call_id=None,
        )
        tools = await toolset.get_tools(ctx)

        # Read second resource (loop must skip first)
        result = await toolset.call_tool(
            "read_skill_resource",
            {"skill_name": "test", "resource_name": "second.md"},
            ctx,
            tools["read_skill_resource"],
        )
        assert result == "second"

        # Read non-existent (loop exhausts all, returns None -> error string)
        result = await toolset.call_tool(
            "read_skill_resource",
            {"skill_name": "test", "resource_name": "missing.md"},
            ctx,
            tools["read_skill_resource"],
        )
        assert "Error:" in result

    async def test_find_script_with_multiple_scripts(self) -> None:
        """Find a script when skill has multiple scripts (loop iterates)."""
        from pydantic_deep.toolsets.skills import SkillScript

        skill = Skill(
            name="test",
            description="desc",
            content="instr",
            scripts=[
                SkillScript(name="first.py", uri="file:///first.py"),
                SkillScript(name="second.py", uri="file:///second.py"),
            ],
        )
        toolset = SkillsToolset(skills=[skill], id="test-skills")

        ctx = RunContext[Any](
            deps=None,
            model=TestModel(),
            usage=RunUsage(),
            retry=0,
            run_step=0,
            tool_name=None,
            tool_call_id=None,
        )
        tools = await toolset.get_tools(ctx)

        # Try non-existent script (loop exhausts both, returns None -> error string)
        result = await toolset.call_tool(
            "run_skill_script",
            {"skill_name": "test", "script_name": "missing.py"},
            ctx,
            tools["run_skill_script"],
        )
        assert "Error:" in result

    def test_duplicate_skill_from_directories(self, tmp_path: Path) -> None:
        """Duplicate skills from directories emit warning."""
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        for d in [dir1, dir2]:
            skill_dir = d / "dupe-skill"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: dupe-skill\ndescription: desc\n---\n\nBody."
            )

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            SkillsToolset(directories=[str(dir1), str(dir2)], id="test")

        assert any("Duplicate skill" in str(warning.message) for warning in w)

    async def test_load_skill_with_scripts(self) -> None:
        """Load skill tool includes script XML."""
        from pydantic_deep.toolsets.skills import SkillScript

        skill = Skill(
            name="test",
            description="desc",
            content="instr",
            scripts=[SkillScript(name="run.py", uri="file:///run.py")],
        )
        toolset = SkillsToolset(skills=[skill], id="test-skills")

        ctx = RunContext[Any](
            deps=None,
            model=TestModel(),
            usage=RunUsage(),
            retry=0,
            run_step=0,
            tool_name=None,
            tool_call_id=None,
        )
        tools = await toolset.get_tools(ctx)
        result = await toolset.call_tool(
            "load_skill", {"skill_name": "test"}, ctx, tools["load_skill"]
        )
        assert 'name="run.py"' in result
        assert "<!-- No scripts -->" not in result

    async def test_read_skill_resource_via_tool(self) -> None:
        """read_skill_resource tool returns static content."""
        skill = Skill(
            name="test",
            description="desc",
            content="instr",
            resources=[SkillResource(name="data.txt", content="hello world")],
        )
        toolset = SkillsToolset(skills=[skill], id="test-skills")

        ctx = RunContext[Any](
            deps=None,
            model=TestModel(),
            usage=RunUsage(),
            retry=0,
            run_step=0,
            tool_name=None,
            tool_call_id=None,
        )
        tools = await toolset.get_tools(ctx)
        result = await toolset.call_tool(
            "read_skill_resource",
            {"skill_name": "test", "resource_name": "data.txt"},
            ctx,
            tools["read_skill_resource"],
        )
        assert result == "hello world"

    async def test_run_skill_script_via_tool(self, tmp_path: Path) -> None:
        """run_skill_script tool executes script and returns output."""
        from pydantic_deep.toolsets.skills.local import (
            FileBasedSkillScript,
            LocalSkillScriptExecutor,
        )

        # Create actual script file
        script_file = tmp_path / "run.py"
        script_file.write_text("print('hello from script')")

        executor = LocalSkillScriptExecutor(timeout=10)
        script = FileBasedSkillScript(
            name="run.py",
            uri=str(script_file),
            executor=executor,
        )

        skill = Skill(
            name="test",
            description="desc",
            content="instr",
            scripts=[script],
        )
        toolset = SkillsToolset(skills=[skill], id="test-skills")

        ctx = RunContext[Any](
            deps=None,
            model=TestModel(),
            usage=RunUsage(),
            retry=0,
            run_step=0,
            tool_name=None,
            tool_call_id=None,
        )
        tools = await toolset.get_tools(ctx)
        result = await toolset.call_tool(
            "run_skill_script",
            {"skill_name": "test", "script_name": "run.py"},
            ctx,
            tools["run_skill_script"],
        )
        assert "hello from script" in result
