"""Tests for toolset implementations."""

from pydantic_deep.backends.state import StateBackend
from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.toolsets.filesystem import (
    _get_runtime_system_prompt,
    create_filesystem_toolset,
    get_filesystem_system_prompt,
)
from pydantic_deep.toolsets.todo import create_todo_toolset, get_todo_system_prompt
from pydantic_deep.types import RuntimeConfig, Todo


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


class TestFilesystemToolset:
    """Tests for FilesystemToolset."""

    def test_create_toolset(self):
        """Test creating a filesystem toolset."""
        toolset = create_filesystem_toolset(id="test-fs")
        assert toolset.id == "test-fs"

    def test_create_without_execute(self):
        """Test creating toolset without execute."""
        toolset = create_filesystem_toolset(include_execute=False)
        # The toolset should be created successfully
        assert toolset is not None

    def test_create_with_approval(self):
        """Test creating toolset with approval requirements."""
        toolset = create_filesystem_toolset(
            require_write_approval=True,
            require_execute_approval=True,
        )
        assert toolset is not None

    def test_get_filesystem_system_prompt_basic(self):
        """Test basic filesystem system prompt."""
        deps = DeepAgentDeps(backend=StateBackend())
        prompt = get_filesystem_system_prompt(deps)

        assert "Filesystem Tools" in prompt
        assert "ls" in prompt
        assert "read_file" in prompt

    def test_get_filesystem_system_prompt_with_runtime(self):
        """Test filesystem system prompt includes runtime info."""

        class MockBackendWithRuntime:
            """Mock backend with runtime attribute."""

            _runtime = RuntimeConfig(
                name="test-runtime",
                description="Test runtime description",
                base_image="python:3.12",
                packages=["pandas", "numpy"],
                work_dir="/workspace",
            )

            def ls_info(self, path: str):
                return []

            def read(self, path: str, offset: int = 0, limit: int = 2000):
                return ""

            def write(self, path: str, content: str):
                pass

            def edit(self, path: str, old: str, new: str, replace_all: bool = False):
                pass

            def glob_info(self, pattern: str, path: str = "/"):
                return []

            def grep_raw(self, pattern: str, path: str | None = None, glob: str | None = None):
                return []

        deps = DeepAgentDeps(backend=MockBackendWithRuntime())
        prompt = get_filesystem_system_prompt(deps)

        # Should include both filesystem tools and runtime info
        assert "Filesystem Tools" in prompt
        assert "Runtime Environment" in prompt
        assert "test-runtime" in prompt

    def test_get_runtime_system_prompt_no_runtime(self):
        """Test runtime system prompt with no runtime configured."""
        deps = DeepAgentDeps(backend=StateBackend())
        prompt = _get_runtime_system_prompt(deps)
        assert prompt is None

    def test_get_runtime_system_prompt_with_runtime(self):
        """Test runtime system prompt with runtime configured."""

        class MockBackendWithRuntime:
            """Mock backend with runtime attribute."""

            _runtime = RuntimeConfig(
                name="test-runtime",
                description="Test runtime description",
                base_image="python:3.12",
                packages=["pandas", "numpy"],
                work_dir="/workspace",
            )

            def ls_info(self, path: str):
                return []

            def read(self, path: str, offset: int = 0, limit: int = 2000):
                return ""

            def write(self, path: str, content: str):
                pass

            def edit(self, path: str, old: str, new: str, replace_all: bool = False):
                pass

            def glob_info(self, pattern: str, path: str = "/"):
                return []

            def grep_raw(self, pattern: str, path: str | None = None, glob: str | None = None):
                return []

        deps = DeepAgentDeps(backend=MockBackendWithRuntime())
        prompt = _get_runtime_system_prompt(deps)

        assert prompt is not None
        assert "Runtime Environment" in prompt
        assert "test-runtime" in prompt
        assert "Test runtime description" in prompt
        assert "/workspace" in prompt
        assert "pandas" in prompt
        assert "numpy" in prompt

    def test_get_runtime_system_prompt_with_env_vars(self):
        """Test runtime system prompt with environment variables."""

        class MockBackendWithEnvVars:
            """Mock backend with runtime that has env vars."""

            _runtime = RuntimeConfig(
                name="env-runtime",
                base_image="python:3.12",
                env_vars={"DEBUG": "true", "API_KEY": "secret"},
                work_dir="/app",
            )

            def ls_info(self, path: str):
                return []

            def read(self, path: str, offset: int = 0, limit: int = 2000):
                return ""

            def write(self, path: str, content: str):
                pass

            def edit(self, path: str, old: str, new: str, replace_all: bool = False):
                pass

            def glob_info(self, pattern: str, path: str = "/"):
                return []

            def grep_raw(self, pattern: str, path: str | None = None, glob: str | None = None):
                return []

        deps = DeepAgentDeps(backend=MockBackendWithEnvVars())
        prompt = _get_runtime_system_prompt(deps)

        assert prompt is not None
        assert "Environment variables" in prompt
        assert "DEBUG=true" in prompt
        assert "API_KEY=secret" in prompt

    def test_get_runtime_system_prompt_no_packages(self):
        """Test runtime system prompt without packages."""

        class MockBackendNoPackages:
            """Mock backend with runtime but no packages."""

            _runtime = RuntimeConfig(
                name="minimal-runtime",
                image="python:3.12-slim",
                work_dir="/workspace",
            )

            def ls_info(self, path: str):
                return []

            def read(self, path: str, offset: int = 0, limit: int = 2000):
                return ""

            def write(self, path: str, content: str):
                pass

            def edit(self, path: str, old: str, new: str, replace_all: bool = False):
                pass

            def glob_info(self, pattern: str, path: str = "/"):
                return []

            def grep_raw(self, pattern: str, path: str | None = None, glob: str | None = None):
                return []

        deps = DeepAgentDeps(backend=MockBackendNoPackages())
        prompt = _get_runtime_system_prompt(deps)

        assert prompt is not None
        assert "minimal-runtime" in prompt
        assert "Pre-installed packages" not in prompt

    def test_get_runtime_system_prompt_no_description(self):
        """Test runtime system prompt without description."""

        class MockBackendNoDesc:
            """Mock backend with runtime but no description."""

            _runtime = RuntimeConfig(
                name="no-desc-runtime",
                image="python:3.12-slim",
                work_dir="/workspace",
            )

            def ls_info(self, path: str):
                return []

            def read(self, path: str, offset: int = 0, limit: int = 2000):
                return ""

            def write(self, path: str, content: str):
                pass

            def edit(self, path: str, old: str, new: str, replace_all: bool = False):
                pass

            def glob_info(self, pattern: str, path: str = "/"):
                return []

            def grep_raw(self, pattern: str, path: str | None = None, glob: str | None = None):
                return []

        deps = DeepAgentDeps(backend=MockBackendNoDesc())
        prompt = _get_runtime_system_prompt(deps)

        assert prompt is not None
        assert "no-desc-runtime" in prompt
        # No description line since it's empty
        assert "Description" not in prompt
