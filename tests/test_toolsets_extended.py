"""Extended tests for toolset implementations to reach 100% coverage."""

from pydantic_ai_backends import StateBackend
from pydantic_ai_todo import TodoItem

from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.toolsets.subagents import (
    create_subagent_toolset,
    get_subagent_system_prompt,
)
from pydantic_deep.types import SubAgentConfig


class TestTodoToolsetExtended:
    """Extended tests for TodoToolset."""

    def test_todo_item_model(self):
        """Test TodoItem pydantic model."""
        item = TodoItem(
            content="Test task",
            status="pending",
            active_form="Testing",
        )
        assert item.content == "Test task"
        assert item.status == "pending"
        assert item.active_form == "Testing"


class TestSubagentToolsetExtended:
    """Extended tests for SubAgentToolset."""

    def test_create_with_custom_subagents(self):
        """Test creating with custom subagent configs."""
        subagents = [
            SubAgentConfig(
                name="researcher",
                description="Research topics",
                instructions="You research topics thoroughly.",
            ),
        ]
        toolset = create_subagent_toolset(subagents=subagents)
        assert toolset is not None

    def test_create_without_general_purpose(self):
        """Test creating without general-purpose subagent."""
        toolset = create_subagent_toolset(include_general_purpose=False)
        assert toolset is not None

    def test_create_with_no_subagents(self):
        """Test creating with no subagents at all."""
        toolset = create_subagent_toolset(
            subagents=[],
            include_general_purpose=False,
        )
        assert toolset is not None

    def test_get_subagent_system_prompt_basic(self):
        """Test basic subagent system prompt."""
        deps = DeepAgentDeps(backend=StateBackend())
        prompt = get_subagent_system_prompt(deps)
        assert "Task Delegation" in prompt

    def test_get_subagent_system_prompt_with_configs(self):
        """Test subagent system prompt with configs."""
        deps = DeepAgentDeps(backend=StateBackend())
        configs = [
            SubAgentConfig(
                name="researcher",
                description="Research topics",
                instructions="Research thoroughly.",
            ),
        ]
        prompt = get_subagent_system_prompt(deps, configs)
        assert "Available Subagents" in prompt
        assert "researcher" in prompt

    def test_get_subagent_system_prompt_with_cached_subagents(self):
        """Test subagent system prompt with cached subagents."""
        deps = DeepAgentDeps(backend=StateBackend())
        deps.subagents = {"researcher": object()}

        prompt = get_subagent_system_prompt(deps)
        assert "Cached Subagents" in prompt
        assert "researcher" in prompt
