"""Tests for the agent factory."""

import pytest
from pydantic_ai.models.test import TestModel

from pydantic_deep import (
    DeepAgentDeps,
    StateBackend,
    UploadedFile,
    create_deep_agent,
    create_default_deps,
    run_with_files,
)
from pydantic_deep.deps import _format_size
from pydantic_deep.types import SubAgentConfig

# Use TestModel to avoid requiring API keys
TEST_MODEL = TestModel()


class TestCreateDeepAgent:
    """Tests for create_deep_agent factory."""

    def test_create_default_agent(self):
        """Test creating an agent with default settings."""
        agent = create_deep_agent(model=TEST_MODEL)

        assert agent is not None

    def test_create_with_custom_model(self):
        """Test creating an agent with a custom model."""
        agent = create_deep_agent(model=TEST_MODEL)
        assert agent is not None

    def test_create_with_instructions(self):
        """Test creating an agent with custom instructions."""
        agent = create_deep_agent(model=TEST_MODEL, instructions="You are a test agent")
        assert agent is not None

    def test_create_without_todo(self):
        """Test creating an agent without todo toolset."""
        agent = create_deep_agent(model=TEST_MODEL, include_todo=False)
        assert agent is not None

    def test_create_without_filesystem(self):
        """Test creating an agent without filesystem toolset."""
        agent = create_deep_agent(model=TEST_MODEL, include_filesystem=False)
        assert agent is not None

    def test_create_without_subagents(self):
        """Test creating an agent without subagent toolset."""
        agent = create_deep_agent(model=TEST_MODEL, include_subagents=False)
        assert agent is not None

    def test_create_with_subagent_configs(self):
        """Test creating an agent with custom subagent configs."""
        subagents = [
            SubAgentConfig(
                name="researcher",
                description="A research agent",
                instructions="You research topics",
            ),
        ]
        agent = create_deep_agent(model=TEST_MODEL, subagents=subagents)
        assert agent is not None

    def test_create_with_interrupt_on(self):
        """Test creating an agent with interrupt_on config."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            interrupt_on={
                "execute": True,
                "write_file": True,
            },
        )
        assert agent is not None

    def test_create_with_interrupt_on_all_false(self):
        """Test creating an agent with interrupt_on all False (no DeferredToolRequests)."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            interrupt_on={
                "execute": False,
                "write_file": False,
            },
        )
        assert agent is not None


class TestCreateDefaultDeps:
    """Tests for create_default_deps."""

    def test_create_with_defaults(self):
        """Test creating deps with default settings."""
        deps = create_default_deps()

        assert deps is not None
        assert isinstance(deps.backend, StateBackend)
        assert deps.todos == []
        assert deps.subagents == {}

    def test_create_with_custom_backend(self):
        """Test creating deps with a custom backend."""
        backend = StateBackend()
        deps = create_default_deps(backend=backend)

        assert deps.backend is backend


class TestDeepAgentDeps:
    """Tests for DeepAgentDeps."""

    def test_get_todo_prompt_empty(self):
        """Test todo prompt with no todos."""
        deps = DeepAgentDeps(backend=StateBackend())
        prompt = deps.get_todo_prompt()

        assert prompt == ""

    def test_get_todo_prompt_with_todos(self):
        """Test todo prompt with todos."""
        from pydantic_deep.types import Todo

        deps = DeepAgentDeps(
            backend=StateBackend(),
            todos=[
                Todo(content="Test task", status="pending", active_form="Testing"),
            ],
        )
        prompt = deps.get_todo_prompt()

        assert "Test task" in prompt
        assert "[ ]" in prompt

    def test_clone_for_subagent(self):
        """Test cloning deps for a subagent."""
        from pydantic_deep.types import Todo

        original = DeepAgentDeps(
            backend=StateBackend(),
            todos=[Todo(content="Task", status="pending", active_form="Working")],
        )
        original.files["/test.txt"] = {
            "content": ["test"],
            "created_at": "2024-01-01",
            "modified_at": "2024-01-01",
        }

        cloned = original.clone_for_subagent()

        # Should share backend and files
        assert cloned.backend is original.backend
        assert cloned.files is original.files

        # Should have empty todos and subagents
        assert cloned.todos == []
        assert cloned.subagents == {}

    def test_upload_file(self):
        """Test uploading a file."""
        deps = DeepAgentDeps(backend=StateBackend())

        content = b"id,name,value\n1,foo,100\n2,bar,200\n"
        path = deps.upload_file("data.csv", content)

        # Check path is correct
        assert path == "/uploads/data.csv"

        # Check file is in backend
        file_data = deps.backend.read(path)
        assert file_data is not None
        assert "id,name,value" in file_data

        # Check upload metadata is tracked
        assert path in deps.uploads
        assert deps.uploads[path]["name"] == "data.csv"
        assert deps.uploads[path]["size"] == len(content)
        assert deps.uploads[path]["line_count"] == 3

    def test_upload_file_custom_dir(self):
        """Test uploading a file to a custom directory."""
        deps = DeepAgentDeps(backend=StateBackend())

        content = b"test content"
        path = deps.upload_file("test.txt", content, upload_dir="/custom/dir")

        assert path == "/custom/dir/test.txt"
        assert path in deps.uploads

    def test_upload_file_binary(self):
        """Test uploading a binary file (non-UTF-8)."""
        deps = DeepAgentDeps(backend=StateBackend())

        # Binary content that is not valid UTF-8
        content = bytes([0x80, 0x81, 0x82, 0xFF])
        path = deps.upload_file("binary.dat", content)

        assert path == "/uploads/binary.dat"
        # Binary files should have line_count = None
        assert deps.uploads[path]["line_count"] is None

    def test_get_uploads_summary_empty(self):
        """Test uploads summary with no uploads."""
        deps = DeepAgentDeps(backend=StateBackend())
        summary = deps.get_uploads_summary()

        assert summary == ""

    def test_get_uploads_summary_with_files(self):
        """Test uploads summary with uploaded files."""
        deps = DeepAgentDeps(backend=StateBackend())

        deps.upload_file("data.csv", b"a,b,c\n1,2,3\n")
        deps.upload_file("config.json", b'{"key": "value"}')

        summary = deps.get_uploads_summary()

        assert "## Uploaded Files" in summary
        assert "`/uploads/data.csv`" in summary
        assert "`/uploads/config.json`" in summary
        assert "2 lines" in summary  # data.csv has 2 lines
        assert "read_file" in summary  # instruction about how to use files

    def test_get_uploads_summary_with_binary_files(self):
        """Test uploads summary with binary files (no line count)."""
        deps = DeepAgentDeps(backend=StateBackend())

        # Binary file (non-UTF-8)
        deps.upload_file("binary.dat", bytes([0x80, 0x81, 0x82]))

        summary = deps.get_uploads_summary()

        assert "## Uploaded Files" in summary
        assert "`/uploads/binary.dat`" in summary
        # Binary files should not show line count
        assert "lines" not in summary.split("`/uploads/binary.dat`")[1].split("\n")[0]

    def test_clone_for_subagent_shares_uploads(self):
        """Test that cloned deps share uploads with original."""
        original = DeepAgentDeps(backend=StateBackend())
        original.uploads["/uploads/test.txt"] = UploadedFile(
            name="test.txt",
            path="/uploads/test.txt",
            size=100,
            line_count=5,
        )

        cloned = original.clone_for_subagent()

        # Should share uploads
        assert cloned.uploads is original.uploads
        assert "/uploads/test.txt" in cloned.uploads


class TestFormatSize:
    """Tests for _format_size helper."""

    def test_bytes(self):
        """Test formatting bytes."""
        assert _format_size(500) == "500 B"
        assert _format_size(0) == "0 B"
        assert _format_size(1023) == "1023 B"

    def test_kilobytes(self):
        """Test formatting kilobytes."""
        assert _format_size(1024) == "1.0 KB"
        assert _format_size(2048) == "2.0 KB"
        assert _format_size(1536) == "1.5 KB"

    def test_megabytes(self):
        """Test formatting megabytes."""
        assert _format_size(1024 * 1024) == "1.0 MB"
        assert _format_size(2 * 1024 * 1024) == "2.0 MB"
        assert _format_size(int(2.5 * 1024 * 1024)) == "2.5 MB"


class TestRunWithFiles:
    """Tests for run_with_files helper."""

    @pytest.mark.anyio
    async def test_run_with_files_uploads_files(self):
        """Test that run_with_files uploads files before running agent."""
        agent = create_deep_agent(model=TEST_MODEL)
        deps = DeepAgentDeps(backend=StateBackend())

        files = [
            ("data.csv", b"a,b\n1,2\n"),
            ("config.json", b"{}"),
        ]

        await run_with_files(
            agent,
            "Test query",
            deps,
            files=files,
        )

        # Files should be uploaded
        assert "/uploads/data.csv" in deps.uploads
        assert "/uploads/config.json" in deps.uploads

    @pytest.mark.anyio
    async def test_run_with_files_custom_upload_dir(self):
        """Test run_with_files with custom upload directory."""
        agent = create_deep_agent(model=TEST_MODEL)
        deps = DeepAgentDeps(backend=StateBackend())

        files = [("test.txt", b"content")]

        await run_with_files(
            agent,
            "Test query",
            deps,
            files=files,
            upload_dir="/custom",
        )

        assert "/custom/test.txt" in deps.uploads

    @pytest.mark.anyio
    async def test_run_with_files_no_files(self):
        """Test run_with_files with no files."""
        agent = create_deep_agent(model=TEST_MODEL)
        deps1 = DeepAgentDeps(backend=StateBackend())
        deps2 = DeepAgentDeps(backend=StateBackend())

        # Should not raise error
        await run_with_files(agent, "Test query", deps1, files=None)
        await run_with_files(agent, "Test query", deps2, files=[])

        assert deps1.uploads == {}
        assert deps2.uploads == {}
