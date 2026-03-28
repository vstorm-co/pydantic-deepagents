"""Tests for capabilities support."""

from unittest.mock import MagicMock

import pytest
from pydantic_ai.capabilities import AbstractCapability
from pydantic_ai.models.test import TestModel

from pydantic_deep import create_deep_agent
from pydantic_deep.capabilities import ContextCapability, MemoryCapability, SkillsCapability
from pydantic_deep.toolsets.context import ContextToolset
from pydantic_deep.toolsets.memory import AgentMemoryToolset
from pydantic_deep.toolsets.skills import SkillsToolset

TEST_MODEL = TestModel()


class TestCapabilitiesPassthrough:
    """Test that capabilities parameter is forwarded to Agent."""

    def test_create_agent_with_no_capabilities(self):
        agent = create_deep_agent(model=TEST_MODEL)
        assert agent is not None

    def test_create_agent_with_empty_capabilities(self):
        agent = create_deep_agent(model=TEST_MODEL, capabilities=[])
        assert agent is not None

    def test_create_agent_with_user_capabilities(self):
        class DummyCapability(AbstractCapability[None]):
            pass

        cap = DummyCapability()
        agent = create_deep_agent(model=TEST_MODEL, capabilities=[cap])
        assert agent is not None


class TestSkillsCapability:
    """Test SkillsCapability wrapper."""

    def test_get_instructions_returns_callable(self):
        toolset = SkillsToolset(id="test-skills")
        cap = SkillsCapability(toolset=toolset)
        instructions = cap.get_instructions()
        assert callable(instructions)

    def test_get_instructions_delegates_to_toolset(self):
        toolset = SkillsToolset(id="test-skills")
        cap = SkillsCapability(toolset=toolset)
        instructions = cap.get_instructions()
        assert instructions == toolset.get_instructions

    def test_get_toolset_returns_toolset(self):
        toolset = SkillsToolset(id="test-skills")
        cap = SkillsCapability(toolset=toolset)
        assert cap.get_toolset() is toolset

    def test_default_toolset(self):
        cap = SkillsCapability()
        assert isinstance(cap.toolset, SkillsToolset)
        assert cap.get_toolset() is cap.toolset


class TestContextCapability:
    """Test ContextCapability wrapper."""

    def test_get_instructions_returns_callable(self):
        toolset = ContextToolset(context_files=["/test.md"])
        cap = ContextCapability(toolset=toolset)
        instructions = cap.get_instructions()
        assert callable(instructions)

    def test_get_instructions_delegates_to_toolset(self):
        toolset = ContextToolset(context_files=["/test.md"])
        cap = ContextCapability(toolset=toolset)
        instructions = cap.get_instructions()
        assert instructions == toolset.get_instructions

    def test_no_toolset_returned(self):
        """ContextCapability has no tools, so get_toolset returns None."""
        toolset = ContextToolset(context_files=["/test.md"])
        cap = ContextCapability(toolset=toolset)
        assert cap.get_toolset() is None


class TestMemoryCapability:
    """Test MemoryCapability wrapper."""

    def test_get_instructions_returns_callable(self):
        toolset = AgentMemoryToolset(agent_name="test")
        cap = MemoryCapability(toolset=toolset)
        instructions = cap.get_instructions()
        assert callable(instructions)

    def test_get_instructions_delegates_to_toolset(self):
        toolset = AgentMemoryToolset(agent_name="test")
        cap = MemoryCapability(toolset=toolset)
        instructions = cap.get_instructions()
        assert instructions == toolset.get_instructions

    def test_get_toolset_returns_toolset(self):
        toolset = AgentMemoryToolset(agent_name="test")
        cap = MemoryCapability(toolset=toolset)
        assert cap.get_toolset() is toolset


class TestInternalCapabilitiesIntegration:
    """Test that internal capabilities are created when features are enabled."""

    def test_skills_creates_capability(self):
        agent = create_deep_agent(model=TEST_MODEL, include_skills=True)
        assert agent is not None

    def test_context_creates_capability(self):
        agent = create_deep_agent(
            model=TEST_MODEL, context_files=["/test.md"]
        )
        assert agent is not None

    def test_memory_creates_capability(self):
        agent = create_deep_agent(model=TEST_MODEL, include_memory=True)
        assert agent is not None

    def test_all_features_together(self):
        agent = create_deep_agent(
            model=TEST_MODEL,
            include_skills=True,
            include_memory=True,
            context_files=["/test.md"],
        )
        assert agent is not None

    def test_user_capabilities_merged_with_internal(self):
        class DummyCapability(AbstractCapability[None]):
            pass

        agent = create_deep_agent(
            model=TEST_MODEL,
            include_skills=True,
            capabilities=[DummyCapability()],
        )
        assert agent is not None
