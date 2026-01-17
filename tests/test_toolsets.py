"""Tests for toolset implementations."""

from pydantic_ai_backends import StateBackend, create_console_toolset, get_console_system_prompt
from pydantic_ai_todo import create_todo_toolset, get_todo_system_prompt

from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.types import Todo


class TestTodoToolset:
    """Tests for TodoToolset."""

    def test_create_toolset(self):
        """Test creating a todo toolset."""
        toolset = create_todo_toolset(id="test-todo")
        assert toolset.id == "test-todo"

    def test_toolset_has_read_and_write_tools(self):
        """Test that toolset has both read_todos and write_todos."""
        toolset = create_todo_toolset()
        tool_names = list(toolset.tools.keys())
        assert "read_todos" in tool_names
        assert "write_todos" in tool_names

    def test_get_todo_system_prompt_empty(self):
        """Test system prompt with no todos."""
        deps = DeepAgentDeps(backend=StateBackend())
        prompt = get_todo_system_prompt(deps)

        assert "Task Management" in prompt
        assert "write_todos" in prompt

    def test_get_todo_system_prompt_with_todos(self):
        """Test system prompt with todos."""
        deps = DeepAgentDeps(
            backend=StateBackend(),
            todos=[
                Todo(content="Task 1", status="completed", active_form="Completing task 1"),
                Todo(content="Task 2", status="in_progress", active_form="Working on task 2"),
                Todo(content="Task 3", status="pending", active_form="Starting task 3"),
            ],
        )
        prompt = get_todo_system_prompt(deps)

        assert "Current Todos" in prompt
        assert "[x]" in prompt  # completed
        assert "[*]" in prompt  # in_progress
        assert "[ ]" in prompt  # pending


class TestConsoleToolset:
    """Tests for Console Toolset (from pydantic-ai-backend)."""

    def test_create_toolset(self):
        """Test creating a console toolset."""
        toolset = create_console_toolset(id="test-console")
        assert toolset.id == "test-console"

    def test_create_without_execute(self):
        """Test creating toolset without execute."""
        toolset = create_console_toolset(include_execute=False)
        assert toolset is not None

    def test_get_console_system_prompt_basic(self):
        """Test basic console system prompt."""
        prompt = get_console_system_prompt()
        assert "File Tools" in prompt or "Console" in prompt or "ls" in prompt
