"""Skills that live in the run's workspace: discovery, resources, scripts, the toolset."""

from __future__ import annotations

import sys
import warnings
from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.workspaces import LocalWorkspaceBackend, Workspace

from pydantic_deep import create_deep_agent
from pydantic_deep.features.skills import (
    Skill,
    SkillResourceLoadError,
    SkillScriptExecutionError,
    SkillsToolset,
    SkillValidationError,
    WorkspaceSkillResource,
    WorkspaceSkillScript,
    WorkspaceSkillsDirectory,
)
from pydantic_deep.features.skills import workspace as workspace_module
from tests.workspaces import run_context, state_workspace

SKILL = """---
name: {name}
description: {description}
---

Instructions for {name}.
"""


def _skill(name: str, description: str = "Does things") -> str:
    return SKILL.format(name=name, description=description)


def _local(tmp_path: Path) -> Workspace:
    return Workspace(LocalWorkspaceBackend(tmp_path))


class TestDiscovery:
    async def test_finds_skills_with_their_resources_and_scripts(self, tmp_path: Path) -> None:
        files = {
            "skills/pdf/SKILL.md": _skill("pdf", "Handles PDFs"),
            "skills/pdf/FORMS.md": "# Forms",
            "skills/pdf/data/fields.json": "{}",
            "skills/pdf/extract.py": "print('x')",
            "skills/pdf/scripts/fill.py": "print('y')",
            "skills/pdf/scripts/__init__.py": "",
            "skills/pdf/lib/helper.py": "",
            "skills/csv/SKILL.md": _skill("csv"),
        }
        for path, content in files.items():
            (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / path).write_text(content)
        skills = await WorkspaceSkillsDirectory(path="skills").discover(_local(tmp_path))

        assert sorted(skills) == ["csv", "pdf"]
        pdf = skills["pdf"]
        assert pdf.description == "Handles PDFs"
        assert pdf.uri is not None and pdf.uri.endswith("skills/pdf")
        assert sorted(r.name for r in pdf.resources) == ["FORMS.md", "data/fields.json"]
        assert sorted(s.name for s in pdf.scripts) == ["extract.py", "scripts/fill.py"]
        assert all(s.skill_name == "pdf" for s in pdf.scripts)

    async def test_a_workspace_without_commands_offers_no_scripts(self) -> None:
        """It cannot run them, and says so as misuse rather than a failed script."""
        workspace = state_workspace(
            {
                "/skills/pdf/SKILL.md": _skill("pdf"),
                "/skills/pdf/FORMS.md": "# Forms",
                "/skills/pdf/extract.py": "print('x')",
            }
        )
        skills = await WorkspaceSkillsDirectory(path="skills").discover(workspace)

        assert [r.name for r in skills["pdf"].resources] == ["FORMS.md"]
        assert skills["pdf"].scripts == []

    async def test_a_missing_folder_holds_no_skills(self) -> None:
        assert await WorkspaceSkillsDirectory(path="nowhere").discover(state_workspace()) == {}

    async def test_respects_max_depth(self) -> None:
        workspace = state_workspace(
            {"/skills/a/SKILL.md": _skill("a"), "/skills/x/y/z/b/SKILL.md": _skill("b")}
        )
        shallow = await WorkspaceSkillsDirectory(path="skills", max_depth=1).discover(workspace)
        deep = await WorkspaceSkillsDirectory(path="skills", max_depth=None).discover(workspace)
        assert sorted(shallow) == ["a"]
        assert sorted(deep) == ["a", "b"]

    async def test_an_invalid_skill_raises_when_validating(self) -> None:
        workspace = state_workspace({"/skills/bad/SKILL.md": b"\xff\xfe"})
        with pytest.raises(SkillValidationError, match="Failed to load skill"):
            await WorkspaceSkillsDirectory(path="skills").discover(workspace)

    async def test_an_invalid_skill_is_skipped_with_a_warning_otherwise(self) -> None:
        workspace = state_workspace(
            {"/skills/bad/SKILL.md": b"\xff\xfe", "/skills/ok/SKILL.md": _skill("ok")}
        )
        with pytest.warns(UserWarning, match="Skipping invalid skill"):
            skills = await WorkspaceSkillsDirectory(path="skills", validate=False).discover(
                workspace
            )
        assert list(skills) == ["ok"]

    async def test_a_skill_without_a_name_takes_its_folder_name_unvalidated(self) -> None:
        workspace = state_workspace({"/skills/my-skill/SKILL.md": "---\ndescription: d\n---\nx"})
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            skills = await WorkspaceSkillsDirectory(path="skills", validate=False).discover(
                workspace
            )
        assert list(skills) == ["my-skill"]

    async def test_a_skill_the_frontmatter_rejects_is_left_out(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(workspace_module, "_extract_skill_fields", lambda *a, **k: None)
        workspace = state_workspace({"/skills/a/SKILL.md": _skill("a")})
        assert await WorkspaceSkillsDirectory(path="skills").discover(workspace) == {}


class TestResource:
    async def test_text_json_and_yaml_are_loaded(self) -> None:
        workspace = state_workspace(
            {
                "/r/notes.md": "# Notes",
                "/r/data.json": '{"a": 1}',
                "/r/bad.json": "{nope",
                "/r/conf.yaml": "a: 1",
                "/r/bad.yml": "a: [",
            }
        )
        ctx = run_context(workspace=workspace)

        async def load(name: str) -> Any:
            return await WorkspaceSkillResource(name=name, uri=f"/r/{name}").load(ctx)

        assert await load("notes.md") == "# Notes"
        assert await load("data.json") == {"a": 1}
        assert await load("bad.json") == "{nope"
        assert await load("conf.yaml") == {"a": 1}
        assert await load("bad.yml") == "a: ["

    async def test_yaml_is_text_without_pyyaml(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(workspace_module, "_HAS_YAML", False)
        ctx = run_context(workspace=state_workspace({"/r/conf.yaml": "a: 1"}))
        resource = WorkspaceSkillResource(name="conf.yaml", uri="/r/conf.yaml")
        assert await resource.load(ctx) == "a: 1"

    async def test_a_missing_file_or_uri_raises(self) -> None:
        ctx = run_context(workspace=state_workspace())
        with pytest.raises(SkillResourceLoadError, match="Failed to read"):
            await WorkspaceSkillResource(name="x.md", uri="/x.md").load(ctx)
        resource = WorkspaceSkillResource(name="x.md", uri="/x.md")
        resource.uri = None
        with pytest.raises(SkillResourceLoadError, match="no URI"):
            await resource.load(ctx)


class TestScript:
    async def test_runs_with_arguments_in_the_workspace(self, tmp_path: Path) -> None:
        (tmp_path / "echo.py").write_text("import sys; print(' '.join(sys.argv[1:]))")
        ctx = run_context(workspace=_local(tmp_path))
        script = WorkspaceSkillScript(name="echo.py", uri="echo.py")
        out = await script.run(
            ctx,
            {
                "name": "a b; rm -rf /",
                "verbose": True,
                "quiet": False,
                "tag": ["x", "y"],
                "n": None,
            },
        )
        assert out == "--name a b; rm -rf / --verbose --tag x --tag y"

    async def test_reports_a_failing_exit_code_and_empty_output(self, tmp_path: Path) -> None:
        (tmp_path / "fail.py").write_text("import sys; sys.exit(3)")
        (tmp_path / "quiet.py").write_text("")
        ctx = run_context(workspace=_local(tmp_path))
        failed = await WorkspaceSkillScript(name="fail.py", uri="fail.py").run(ctx)
        quiet = await WorkspaceSkillScript(name="quiet.py", uri="quiet.py").run(ctx)
        assert failed == "Script exited with code 3"
        assert quiet == "(no output)"

    async def test_a_timeout_or_missing_uri_raises(self, tmp_path: Path) -> None:
        (tmp_path / "slow.py").write_text("import time; time.sleep(5)")
        ctx = run_context(workspace=_local(tmp_path))
        with pytest.raises(SkillScriptExecutionError, match="Failed to run"):
            await WorkspaceSkillScript(name="slow.py", uri="slow.py", timeout=1).run(ctx)
        script = WorkspaceSkillScript(name="x.py", uri="x.py")
        script.uri = None
        with pytest.raises(SkillScriptExecutionError, match="no URI"):
            await script.run(ctx)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell")
class TestToolset:
    async def test_workspace_skills_appear_alongside_loaded_ones(self) -> None:
        toolset = SkillsToolset(
            skills=[Skill(name="local", description="Local", content="L")],
            directories=[WorkspaceSkillsDirectory(path="skills")],
        )
        ctx = run_context(workspace=state_workspace({"/skills/pdf/SKILL.md": _skill("pdf")}))

        listed = await toolset.tools["list_skills"].function(ctx)
        loaded = await toolset.tools["load_skill"].function(ctx, skill_name="pdf")
        prompt = await toolset.get_instructions(ctx)

        assert listed == {"local": "Local", "pdf": "Does things"}
        assert "Instructions for pdf" in loaded
        assert prompt is not None and "pdf" in prompt[0].content
        assert toolset.skills.keys() == {"local"}  # discovered per workspace, not loaded

    async def test_each_workspace_is_discovered_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[Workspace] = []
        original = WorkspaceSkillsDirectory.discover

        async def counting(self: WorkspaceSkillsDirectory, workspace: Workspace) -> Any:
            calls.append(workspace)
            return await original(self, workspace)

        monkeypatch.setattr(WorkspaceSkillsDirectory, "discover", counting)
        toolset = SkillsToolset(directories=[WorkspaceSkillsDirectory(path="skills")])
        ctx = run_context(workspace=state_workspace({"/skills/pdf/SKILL.md": _skill("pdf")}))
        await toolset.tools["list_skills"].function(ctx)
        await toolset.tools["list_skills"].function(ctx)
        assert len(calls) == 1

    async def test_a_workspace_skill_replaces_a_loaded_one_with_a_warning(self) -> None:
        toolset = SkillsToolset(
            skills=[Skill(name="pdf", description="Old", content="old")],
            directories=[WorkspaceSkillsDirectory(path="skills")],
        )
        ctx = run_context(workspace=state_workspace({"/skills/pdf/SKILL.md": _skill("pdf")}))
        with pytest.warns(UserWarning, match="Duplicate skill 'pdf'"):
            listed = await toolset.tools["list_skills"].function(ctx)
        assert listed == {"pdf": "Does things"}

    async def test_resources_and_scripts_reach_the_workspace(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "skills" / "tool"
        (skill_dir / "scripts").mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(_skill("tool"))
        (skill_dir / "GUIDE.md").write_text("guide text")
        (skill_dir / "scripts" / "hi.py").write_text("print('hi')")
        toolset = SkillsToolset(directories=[WorkspaceSkillsDirectory(path="skills")])
        ctx = run_context(workspace=_local(tmp_path))

        guide = await toolset.tools["read_skill_resource"].function(
            ctx, skill_name="tool", resource_name="GUIDE.md"
        )
        ran = await toolset.tools["run_skill_script"].function(
            ctx, skill_name="tool", script_name="scripts/hi.py"
        )
        assert (guide, ran) == ("guide text", "hi")

    async def test_without_a_workspace_only_loaded_skills_are_offered(self) -> None:
        toolset = SkillsToolset(
            skills=[Skill(name="local", description="Local", content="L")],
            directories=[WorkspaceSkillsDirectory(path="skills")],
        )
        assert await toolset.tools["list_skills"].function(run_context()) == {"local": "Local"}


def test_create_deep_agent_accepts_workspace_skill_directories() -> None:
    agent = create_deep_agent(
        model="test", skill_directories=[WorkspaceSkillsDirectory(path="skills")]
    )
    assert agent is not None
