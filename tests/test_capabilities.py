"""Tests for pydantic_deep.capabilities module."""

from __future__ import annotations

import pytest
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from pydantic_deep.capabilities import (
    ContextFilesCapability,
    MemoryCapability,
    PlanCapability,
    SkillsCapability,
    TeamCapability,
)
from pydantic_deep.toolsets.skills import Skill

_MODEL = TestModel()


class TestSkillsCapability:
    def test_default_construction(self):
        cap = SkillsCapability()
        assert cap._toolset is not None

    def test_with_programmatic_skills(self):
        skill = Skill(name="test", description="desc", content="content")
        cap = SkillsCapability(skills=[skill])
        assert cap.get_toolset() is not None

    def test_get_instructions_returns_callable(self):
        skill = Skill(name="test", description="desc", content="content")
        cap = SkillsCapability(skills=[skill])
        instr = cap.get_instructions()
        assert callable(instr)

    @pytest.mark.anyio
    async def test_instructions_contain_skill_names(self):
        skill = Skill(name="my-skill", description="does stuff", content="content")
        cap = SkillsCapability(skills=[skill])
        instr_fn = cap.get_instructions()
        ctx = type("FakeCtx", (), {"deps": None})()
        result = await instr_fn(ctx)
        assert result is not None
        assert "my-skill" in result

    @pytest.mark.anyio
    async def test_agent_integration(self):
        cap = SkillsCapability(
            skills=[
                Skill(name="test", description="test skill", content="test"),
            ]
        )
        agent = Agent(_MODEL, capabilities=[cap])
        result = await agent.run("Hello")
        assert result.output is not None


class TestContextFilesCapability:
    @pytest.mark.anyio
    async def test_no_files_no_toolset(self):
        cap = ContextFilesCapability()
        instr_fn = cap.get_instructions()
        ctx = type("FakeCtx", (), {"deps": None})()
        assert await instr_fn(ctx) is None

    def test_with_files(self):
        cap = ContextFilesCapability(context_files=["/DEEP.md"])
        assert cap._toolset is not None

    def test_with_discovery(self):
        cap = ContextFilesCapability(context_discovery=True)
        assert cap._toolset is not None

    def test_get_instructions_callable(self):
        cap = ContextFilesCapability(context_files=["/DEEP.md"])
        assert callable(cap.get_instructions())


class TestMemoryCapability:
    def test_default_construction(self):
        cap = MemoryCapability()
        assert cap._toolset is not None
        assert cap.agent_name == "main"

    def test_custom_name(self):
        cap = MemoryCapability(agent_name="worker")
        assert cap.agent_name == "worker"

    def test_get_toolset(self):
        cap = MemoryCapability()
        assert cap.get_toolset() is not None

    def test_get_instructions_callable(self):
        cap = MemoryCapability()
        assert callable(cap.get_instructions())


class TestPlanCapability:
    def test_default_construction(self):
        cap = PlanCapability()
        assert cap._toolset is not None
        assert cap.plans_dir == "/plans"

    def test_custom_dir(self):
        cap = PlanCapability(plans_dir="/custom/plans")
        assert cap.plans_dir == "/custom/plans"

    def test_get_toolset(self):
        cap = PlanCapability()
        assert cap.get_toolset() is not None


class TestTeamCapability:
    def test_default_construction(self):
        cap = TeamCapability()
        assert cap._toolset is not None

    def test_get_toolset(self):
        cap = TeamCapability()
        assert cap.get_toolset() is not None


class TestCapabilityComposition:
    @pytest.mark.anyio
    async def test_multiple_capabilities(self):
        """Multiple capabilities compose without errors."""
        agent = Agent(
            _MODEL,
            capabilities=[
                SkillsCapability(
                    skills=[
                        Skill(name="test", description="test", content="test"),
                    ]
                ),
            ],
        )
        result = await agent.run("Hello")
        assert result.output is not None


class TestInstructionCallables:
    """Test the get_instructions() callables execute properly."""

    @pytest.mark.anyio
    async def test_skills_instructions_with_no_skills(self):
        cap = SkillsCapability()
        fn = cap.get_instructions()
        ctx = type("Ctx", (), {"deps": None})()
        result = await fn(ctx)
        # Empty skills → None or empty
        assert result is None or result == ""

    @pytest.mark.anyio
    async def test_context_instructions_no_backend(self):
        cap = ContextFilesCapability(context_files=["/test.md"])
        fn = cap.get_instructions()
        ctx = type("Ctx", (), {"deps": None})()
        result = await fn(ctx)
        assert result is None

    @pytest.mark.anyio
    async def test_memory_instructions_no_backend(self):
        cap = MemoryCapability()
        fn = cap.get_instructions()
        ctx = type("Ctx", (), {"deps": None})()
        result = await fn(ctx)
        assert result is None
