"""Extended tests for agent factory to reach 100% coverage."""

from pydantic_ai.models.test import TestModel

from pydantic_deep import (
    DeepAgentDeps,
    StateBackend,
    create_deep_agent,
)
from pydantic_deep.toolsets.skills import Skill as SkillDataclass
from pydantic_deep.toolsets.skills import SkillsToolset

TEST_MODEL = TestModel()


class TestCreateDeepAgentExtended:
    """Extended tests for create_deep_agent factory."""

    def test_create_without_skills(self):
        """Test creating an agent without skills toolset."""
        agent = create_deep_agent(model=TEST_MODEL, include_skills=False)
        assert agent is not None

    def test_create_without_builtin_subagents(self):
        """Test creating without built-in subagents."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            include_builtin_subagents=False,
        )
        assert agent is not None

    def test_create_with_custom_toolsets(self):
        """Test creating with additional custom toolsets."""
        from pydantic_ai.toolsets import FunctionToolset

        custom_toolset = FunctionToolset(id="custom")

        @custom_toolset.tool
        async def custom_tool() -> str:
            """Custom tool."""
            return "custom"

        agent = create_deep_agent(
            model=TEST_MODEL,
            toolsets=[custom_toolset],
        )
        assert agent is not None

    def test_create_with_custom_tools(self):
        """Test creating with additional custom tools."""

        async def custom_function() -> str:
            """Custom function."""
            return "custom"

        agent = create_deep_agent(
            model=TEST_MODEL,
            tools=[custom_function],
        )
        assert agent is not None

    def test_create_with_skills_toolset(self):
        """Test creating with pre-loaded skills via SkillsToolset."""
        skill = SkillDataclass(
            name="test-skill",
            description="A test skill",
            content="Instructions",
        )
        agent = create_deep_agent(
            model=TEST_MODEL,
            toolsets=[SkillsToolset(skills=[skill])],
            include_skills=False,
        )
        assert agent is not None

    def test_create_with_skill_directories(self, tmp_path):
        """Test creating with skill directories."""
        # Create a test skill
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        skill_file = skill_dir / "SKILL.md"
        skill_file.write_text("""---
name: test-skill
description: A test skill
version: 1.0.0
---

# Test Skill Instructions

This is a test skill.
""")

        agent = create_deep_agent(
            model=TEST_MODEL,
            skill_directories=[str(tmp_path)],
        )
        assert agent is not None

    def test_create_with_interrupt_on_edit_file(self):
        """Test creating with edit_file in interrupt_on."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            interrupt_on={"edit_file": True},
        )
        assert agent is not None

    def test_create_with_output_type_and_interrupt_on(self):
        """Test creating with both output_type and interrupt_on."""
        from pydantic import BaseModel

        class TestOutput(BaseModel):
            result: str

        agent = create_deep_agent(
            model=TEST_MODEL,
            output_type=TestOutput,
            interrupt_on={"write_file": True},
        )
        assert agent is not None

    @staticmethod
    def _execute_requires_approval(agent: object) -> bool | None:
        """Return the resolved ``requires_approval`` flag of the console ``execute`` tool.

        Returns ``None`` if the console toolset / execute tool is not present.
        """
        seen: set[int] = set()

        def find_console(obj: object):
            if id(obj) in seen:
                return None
            seen.add(id(obj))
            if getattr(obj, "id", None) == "deep-console":
                return obj
            for attr in ("toolsets", "toolset", "wrapped", "_toolset", "tools", "_toolsets"):
                child = getattr(obj, attr, None)
                if child is None:
                    continue
                if isinstance(child, dict):
                    items = list(child.values())
                elif isinstance(child, (list, tuple, set)):
                    items = list(child)
                else:
                    items = [child]
                for item in items:
                    found = find_console(item)
                    if found is not None:
                        return found
            return None

        console = find_console(agent)
        if console is None:
            return None
        execute = getattr(console, "tools", {}).get("execute")
        if execute is None:
            return None
        return getattr(execute, "requires_approval", None)

    def test_execute_gated_when_other_interrupt_enabled(self):
        """A non-empty interrupt_on that omits execute still gates shell execute.

        Regression: the default must follow ``any(interrupt_on.values())`` so a caller
        enabling edit/write interrupts keeps shell ``execute`` behind human approval.
        """
        agent = create_deep_agent(
            model=TEST_MODEL,
            interrupt_on={"edit_file": True},
            include_execute=True,
        )
        assert self._execute_requires_approval(agent) is True

    def test_execute_not_gated_when_interrupt_on_empty(self):
        """An empty interrupt_on wires no interrupt tools, so execute defaults ungated."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            interrupt_on={},
            include_execute=True,
        )
        assert self._execute_requires_approval(agent) is False

    def test_explicit_execute_false_overrides_default(self):
        """An explicit {"execute": False} wins even when other interrupts are enabled."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            interrupt_on={"execute": False, "edit_file": True},
            include_execute=True,
        )
        assert self._execute_requires_approval(agent) is False

    def test_explicit_execute_true_gates(self):
        """An explicit {"execute": True} gates execute."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            interrupt_on={"execute": True},
            include_execute=True,
        )
        assert self._execute_requires_approval(agent) is True

    def test_create_with_user_capabilities(self):
        """Test creating with user-provided capabilities."""
        from pydantic_ai.capabilities import Thinking

        agent = create_deep_agent(
            model=TEST_MODEL,
            capabilities=[Thinking(effort="low")],
        )
        assert agent is not None

    def test_create_with_custom_retries(self):
        """Test creating an agent with custom retries value."""
        agent = create_deep_agent(model=TEST_MODEL, retries=5)
        assert agent is not None

    def test_default_retries_is_three(self):
        """Test that the default retries value is 3."""
        from pydantic_ai.toolsets.function import FunctionToolset

        agent = create_deep_agent(model=TEST_MODEL, cost_tracking=False)

        # Find the console toolset and verify retries
        for toolset in agent._user_toolsets:
            if isinstance(toolset, FunctionToolset) and toolset._id == "deep-console":
                assert toolset.max_retries == 3
                for tool in toolset.tools.values():
                    assert tool.max_retries == 3
                break

    def test_retries_propagated_to_console_toolset(self):
        """Test that retries value is propagated to console toolset tools."""
        from pydantic_ai.toolsets.function import FunctionToolset

        agent = create_deep_agent(model=TEST_MODEL, retries=5, cost_tracking=False)

        # Find the console toolset and verify retries
        for toolset in agent._user_toolsets:
            if isinstance(toolset, FunctionToolset) and toolset._id == "deep-console":
                assert toolset.max_retries == 5
                # write_file specifically should have the custom retries
                assert toolset.tools["write_file"].max_retries == 5
                break


class TestDeepAgentDepsExtended:
    """Extended tests for DeepAgentDeps."""

    def test_post_init_syncs_files(self):
        """Test that __post_init__ syncs files to StateBackend."""
        backend = StateBackend()
        files = {
            "/test.txt": {
                "content": ["test content"],
                "created_at": "2024-01-01",
                "modified_at": "2024-01-01",
            }
        }
        _ = DeepAgentDeps(backend=backend, files=files)

        # Files should be synced to backend
        assert "/test.txt" in backend.files

    def test_post_init_with_non_state_backend(self, local_backend):
        """Test that __post_init__ works with non-StateBackend."""
        # This covers the branch where backend is NOT a StateBackend
        deps = DeepAgentDeps(backend=local_backend)
        assert deps.backend is local_backend
        # files dict should remain empty (not synced from backend)
        assert deps.files == {}

    def test_get_files_summary_empty(self):
        """Test get_files_summary with empty files."""
        deps = DeepAgentDeps(backend=StateBackend())
        # Ensure files is empty
        deps.files.clear()
        summary = deps.get_files_summary()
        assert summary == ""

    def test_get_files_summary_with_files(self):
        """Test get_files_summary with files."""
        deps = DeepAgentDeps(backend=StateBackend())
        deps.files["/test.txt"] = {
            "content": ["line1", "line2"],
            "created_at": "2024-01-01",
            "modified_at": "2024-01-01",
        }

        summary = deps.get_files_summary()
        assert "Files in Memory" in summary
        assert "/test.txt" in summary
        assert "2 lines" in summary

    def test_get_subagents_summary_empty(self):
        """Test get_subagents_summary with no subagents."""
        deps = DeepAgentDeps(backend=StateBackend())
        summary = deps.get_subagents_summary()
        assert summary == ""

    def test_get_subagents_summary_with_subagents(self):
        """Test get_subagents_summary with subagents."""
        deps = DeepAgentDeps(backend=StateBackend())
        deps.subagents = {"researcher": object(), "writer": object()}

        summary = deps.get_subagents_summary()
        assert "Available Subagents" in summary
        assert "researcher" in summary
        assert "writer" in summary

    def test_builtin_research_skipped_if_already_defined(self):
        """Test that built-in research subagent is not added if user defines one."""
        from pydantic_deep.types import SubAgentConfig

        custom_research = SubAgentConfig(
            name="research",
            description="My custom research",
            instructions="Custom instructions",
        )
        agent = create_deep_agent(
            model=TEST_MODEL,
            subagents=[custom_research],
            include_builtin_subagents=True,
        )
        assert agent is not None

    def test_create_with_context_manager_disabled(self):
        """Test creating with context_manager=False."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            context_manager=False,
        )
        assert agent is not None

    def test_create_with_thinking_disabled(self):
        """Test creating with thinking=False."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            thinking=False,
            web_search=False,
            web_fetch=False,
        )
        assert agent is not None

    def test_create_with_eviction_disabled(self):
        """Test creating with eviction disabled."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            eviction_token_limit=None,
            web_search=False,
            web_fetch=False,
            thinking=False,
        )
        assert agent is not None

    def test_create_with_no_processors(self):
        """Test creating with all processors disabled."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            eviction_token_limit=None,
            patch_tool_calls=False,
            web_search=False,
            web_fetch=False,
            thinking=False,
        )
        assert agent is not None

    def test_create_with_no_capabilities(self):
        """Test creating with all capabilities disabled."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            web_search=False,
            web_fetch=False,
            thinking=False,
            cost_tracking=False,
            context_manager=False,
        )
        assert agent is not None

    def test_create_with_model_settings(self):
        """Test creating with custom model_settings."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            model_settings={"temperature": 0.5},
            web_search=False,
            web_fetch=False,
            thinking=False,
        )
        assert agent is not None
