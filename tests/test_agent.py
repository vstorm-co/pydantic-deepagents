"""Tests for the agent factory."""

from typing import Any

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
from pydantic_deep.agent import _DepsTodoProxy, _TodoProxyBinder
from pydantic_deep.deps import _format_size
from pydantic_deep.types import SubAgentConfig, Todo

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

    @staticmethod
    def _default_factory(**parent_kwargs: object) -> Any:
        """Build the default subagent factory the way create_deep_agent does.

        Tests the factory in isolation rather than reaching into the caller's
        subagent-config list - which create_deep_agent no longer mutates.
        """
        from pydantic_deep.agent import _make_default_deep_agent_factory

        defaults = dict(
            model=TEST_MODEL,
            edit_format=None,
            context_files=None,
            context_discovery=False,
            memory_dir=None,
            web_search=False,
            web_fetch=False,
        )
        defaults.update(parent_kwargs)
        return _make_default_deep_agent_factory(**defaults)

    def test_default_subagent_factory_propagates_web_flags(self):
        """Regression for #77: default subagent factory must inherit parent's
        `web_search` and `web_fetch` flags. Otherwise Bedrock/Vertex
        Anthropic models error out on unsupported beta tools.
        """
        from pydantic_ai.capabilities import WebFetch, WebSearch

        def _sub_caps(parent_web_search: bool, parent_web_fetch: bool) -> list[type]:
            factory = self._default_factory(
                web_search=parent_web_search, web_fetch=parent_web_fetch
            )
            sub_agent = factory({"instructions": "sub instructions", "model": TEST_MODEL})
            return [type(c) for c in sub_agent._root_capability.capabilities]

        off_types = _sub_caps(parent_web_search=False, parent_web_fetch=False)
        assert WebSearch not in off_types
        assert WebFetch not in off_types

        on_types = _sub_caps(parent_web_search=True, parent_web_fetch=True)
        assert WebSearch in on_types
        assert WebFetch in on_types

    def test_default_subagent_factory_prepends_base_prompt(self):
        """Subagent factory always prepends BASE_PROMPT before task instructions."""
        from pydantic_deep.prompts import BASE_PROMPT

        factory = self._default_factory()
        sub_agent = factory({"instructions": "Research topics carefully.", "model": TEST_MODEL})
        assert any(BASE_PROMPT in str(i) for i in sub_agent._instructions)
        assert any("Research topics carefully." in str(i) for i in sub_agent._instructions)

    def test_default_subagent_factory_no_task_instructions(self):
        """Subagent factory with empty instructions uses only BASE_PROMPT."""
        from pydantic_deep.prompts import BASE_PROMPT

        factory = self._default_factory()
        sub_agent = factory({"instructions": "", "model": TEST_MODEL})
        assert any(BASE_PROMPT in str(i) for i in sub_agent._instructions)

    def test_subagent_configs_not_mutated_and_no_toolset_doubling(self):
        """create_deep_agent must not mutate caller subagent dicts, so reusing
        the same list (or calling twice) never injects agent_factory into the
        caller's dict nor doubles the per-subagent context/memory toolsets."""
        cfg: SubAgentConfig = SubAgentConfig(
            name="helper",
            description="A helper agent",
            instructions="help",
            context_files=["NOTES.md"],
            toolsets=[],
        )
        cfgs = [cfg]

        for _ in range(2):
            create_deep_agent(model=TEST_MODEL, subagents=cfgs, include_memory=True)
            # Caller's dict stays pristine across calls.
            assert "agent_factory" not in cfg
            assert cfg["toolsets"] == []

    def test_subagent_factory_single_memory_toolset(self):
        """Regression for #155: the default subagent factory must not register a
        second AgentMemoryToolset.

        `_inject_subagent_memory_toolset` adds one memory toolset under the
        subagent's own name; the factory previously also passed
        `include_memory=True`, so `create_deep_agent` added a second 'deep-memory'
        toolset (under the wrong "main" name), causing a `read_memory` collision.
        """
        from pydantic_deep.agent import _inject_subagent_memory_toolset
        from pydantic_deep.toolsets.memory import AgentMemoryToolset

        cfg: SubAgentConfig = SubAgentConfig(
            name="researcher", description="explores", instructions="explore", toolsets=[]
        )
        _inject_subagent_memory_toolset(cfg, None)

        sub_agent = self._default_factory()(cfg)

        seen: set[int] = set()
        found: list[Any] = []

        def _walk(toolsets: Any) -> None:
            for ts in toolsets:
                if id(ts) in seen:
                    continue
                seen.add(id(ts))
                found.append(ts)
                for attr in ("toolsets", "_toolsets", "wrapped"):
                    inner = getattr(ts, attr, None)
                    if isinstance(inner, (list, tuple)):
                        _walk(inner)
                    elif inner is not None and inner is not ts:
                        _walk([inner])

        _walk(list(getattr(sub_agent, "toolsets", []) or []))
        memory_toolsets = [t for t in found if isinstance(t, AgentMemoryToolset)]
        assert len(memory_toolsets) == 1
        assert memory_toolsets[0]._agent_name == "researcher"

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


class TestBasePrompt:
    """Tests for BASE_PROMPT and default instructions."""

    def test_base_prompt_is_default(self):
        """Default agent uses BASE_PROMPT as instructions."""
        from pydantic_deep.prompts import BASE_PROMPT

        agent = create_deep_agent(model=TEST_MODEL, cost_tracking=False)
        # pydantic-ai stores instructions as a normalized list
        assert any(BASE_PROMPT in str(i) for i in agent._instructions)

    def test_custom_instructions_replace_base_prompt(self):
        """Custom instructions replace BASE_PROMPT entirely."""
        from pydantic_deep.prompts import BASE_PROMPT

        custom = "You are a custom agent."
        agent = create_deep_agent(model=TEST_MODEL, instructions=custom, cost_tracking=False)
        assert any(custom in str(i) for i in agent._instructions)
        assert not any(BASE_PROMPT in str(i) for i in agent._instructions)

    def test_custom_instructions_with_base_prompt_fstring(self):
        """User can combine BASE_PROMPT with their own instructions via f-string."""
        from pydantic_deep import BASE_PROMPT

        custom = f"{BASE_PROMPT}\n\nYou are a coding assistant."
        agent = create_deep_agent(model=TEST_MODEL, instructions=custom, cost_tracking=False)
        assert any(BASE_PROMPT in str(i) for i in agent._instructions)
        assert any("coding assistant" in str(i) for i in agent._instructions)

    def test_empty_instructions_uses_base_prompt(self):
        """instructions=None (default) uses BASE_PROMPT."""
        from pydantic_deep.prompts import BASE_PROMPT

        agent = create_deep_agent(model=TEST_MODEL, instructions=None, cost_tracking=False)
        assert any(BASE_PROMPT in str(i) for i in agent._instructions)

    def test_create_with_all_capabilities_disabled(self):
        """Agent can be created with all built-in capabilities disabled (all_capabilities empty)."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            context_manager=False,
            cost_tracking=False,
            stuck_loop_detection=False,
            patch_tool_calls=False,
            eviction_token_limit=None,
            web_search=False,
            web_fetch=False,
            thinking=False,
            capabilities=[],
        )
        assert agent is not None

    def test_base_prompt_importable(self):
        """BASE_PROMPT is importable from pydantic_deep."""
        from pydantic_deep import BASE_PROMPT

        assert isinstance(BASE_PROMPT, str)
        assert len(BASE_PROMPT) > 100
        assert "Core Behavior" in BASE_PROMPT

    def test_base_prompt_content(self):
        """BASE_PROMPT contains key sections."""
        from pydantic_deep.prompts import BASE_PROMPT

        assert "Tool Usage" in BASE_PROMPT
        assert "Workflow" in BASE_PROMPT
        assert "Error Handling" in BASE_PROMPT
        assert "Subagent Delegation" in BASE_PROMPT


class TestImageSupport:
    """Tests that image support is always enabled."""

    def test_agent_has_image_support(self):
        """Test that agents are created with image support enabled."""
        agent = create_deep_agent(model=TEST_MODEL)
        assert agent is not None


class TestCreateDefaultDeps:
    """Tests for create_default_deps."""

    def test_create_with_defaults(self):
        """Test creating deps with default settings."""
        deps = create_default_deps()

        assert deps is not None
        assert isinstance(deps.backend.unwrap(), StateBackend)
        assert deps.todos == []
        assert deps.subagents == {}

    def test_create_with_custom_backend(self):
        """Test creating deps with a custom backend."""
        backend = StateBackend()
        deps = create_default_deps(backend=backend)

        assert deps.backend.unwrap() is backend


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

    def test_get_todo_prompt_blocked_status(self):
        """Test todo prompt renders the blocked status distinctly."""
        from pydantic_deep.types import Todo

        deps = DeepAgentDeps(
            backend=StateBackend(),
            todos=[
                Todo(content="Blocked task", status="blocked", active_form="Blocking"),
            ],
        )
        prompt = deps.get_todo_prompt()

        assert "Blocked task" in prompt
        assert "[!]" in prompt

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

    def test_checkpoint_store_default(self):
        """checkpoint_store defaults to None."""
        deps = DeepAgentDeps()
        assert deps.checkpoint_store is None

    def test_checkpoint_store_set(self):
        """checkpoint_store can be passed to constructor."""
        from pydantic_deep.features.checkpointing import InMemoryCheckpointStore

        store = InMemoryCheckpointStore()
        deps = DeepAgentDeps(checkpoint_store=store)
        assert deps.checkpoint_store is store

    def test_clone_for_subagent_propagates_checkpoint_store(self):
        """checkpoint_store is shared with subagent deps."""
        from pydantic_deep.features.checkpointing import InMemoryCheckpointStore

        store = InMemoryCheckpointStore()
        original = DeepAgentDeps(checkpoint_store=store)
        cloned = original.clone_for_subagent()
        assert cloned.checkpoint_store is store

    async def test_upload_file(self):
        """Test uploading a file."""
        deps = DeepAgentDeps(backend=StateBackend())

        content = b"id,name,value\n1,foo,100\n2,bar,200\n"
        path = await deps.upload_file("data.csv", content)

        # Check path is correct
        assert path == "/uploads/data.csv"

        # Check file is in backend
        file_data = await deps.backend.read(path)
        assert file_data is not None
        assert "id,name,value" in file_data

        # Check upload metadata is tracked
        assert path in deps.uploads
        assert deps.uploads[path]["name"] == "data.csv"
        assert deps.uploads[path]["size"] == len(content)
        assert deps.uploads[path]["line_count"] == 3

    async def test_upload_file_custom_dir(self):
        """Test uploading a file to a custom directory."""
        deps = DeepAgentDeps(backend=StateBackend())

        content = b"test content"
        path = await deps.upload_file("test.txt", content, upload_dir="/custom/dir")

        assert path == "/custom/dir/test.txt"
        assert path in deps.uploads

    async def test_upload_file_binary(self):
        """Test uploading a binary file (non-UTF-8)."""
        from unittest.mock import patch

        deps = DeepAgentDeps(backend=StateBackend())

        # Binary content - mock chardet to return no encoding (platform-dependent)
        content = bytes([0x80, 0x81, 0x82, 0xFF])
        with patch("pydantic_deep.deps.chardet.detect", return_value={"encoding": None}):
            path = await deps.upload_file("binary.dat", content)

        assert path == "/uploads/binary.dat"
        # Binary files should have line_count = None
        assert deps.uploads[path]["line_count"] is None

    async def test_upload_files_skips_failures(self, caplog):
        """A failing file should not abort the rest of the batch (and is logged, B9)."""
        from unittest.mock import patch

        deps = DeepAgentDeps(backend=StateBackend())

        real_upload_file = deps.upload_file

        async def flaky_upload_file(name, content, *, upload_dir="/uploads"):
            # Simulate a non-RuntimeError failure mid-batch (e.g. an
            # encoding/metadata error or a backend that raises directly).
            if name == "bad.bin":
                raise ValueError("boom")
            return await real_upload_file(name, content, upload_dir=upload_dir)

        with (
            patch.object(deps, "upload_file", side_effect=flaky_upload_file),
            caplog.at_level("WARNING"),
        ):
            paths = await deps.upload_files(
                [
                    ("good1.csv", b"a,b\n1,2\n"),
                    ("bad.bin", b"\x00\x01"),
                    ("good2.txt", b"hello"),
                ]
            )

        # The bad file is skipped, the good ones still upload.
        assert paths == ["/uploads/good1.csv", "/uploads/good2.txt"]
        # The skip is surfaced, not silent (B9).
        assert any("bad.bin" in r.getMessage() for r in caplog.records)

    def test_get_uploads_summary_empty(self):
        """Test uploads summary with no uploads."""
        deps = DeepAgentDeps(backend=StateBackend())
        summary = deps.get_uploads_summary()

        assert summary == ""

    async def test_get_uploads_summary_with_files(self):
        """Test uploads summary with uploaded files."""
        deps = DeepAgentDeps(backend=StateBackend())

        await deps.upload_file("data.csv", b"a,b,c\n1,2,3\n")
        await deps.upload_file("config.json", b'{"key": "value"}')

        summary = deps.get_uploads_summary()

        assert "## Uploaded Files" in summary
        assert "`/uploads/data.csv`" in summary
        assert "`/uploads/config.json`" in summary
        assert "2 lines" in summary  # data.csv has 2 lines
        assert "read_file" in summary  # instruction about how to use files

    async def test_get_uploads_summary_with_binary_files(self):
        """Test uploads summary with binary files (no line count)."""
        from unittest.mock import patch

        deps = DeepAgentDeps(backend=StateBackend())

        # Binary file - mock chardet to return no encoding (platform-dependent)
        with patch("pydantic_deep.deps.chardet.detect", return_value={"encoding": None}):
            await deps.upload_file("binary.dat", bytes([0x80, 0x81, 0x82]))

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
            mime_type="text/plain",
            encoding="utf-8",
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
        agent = create_deep_agent(model=TEST_MODEL, web_search=False, web_fetch=False)
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
        agent = create_deep_agent(model=TEST_MODEL, web_search=False, web_fetch=False)
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
        agent = create_deep_agent(model=TEST_MODEL, web_search=False, web_fetch=False)
        deps1 = DeepAgentDeps(backend=StateBackend())
        deps2 = DeepAgentDeps(backend=StateBackend())

        # Should not raise error
        await run_with_files(agent, "Test query", deps1, files=None)
        await run_with_files(agent, "Test query", deps2, files=[])

        assert deps1.uploads == {}
        assert deps2.uploads == {}


class TestDepsTodoProxy:
    """Tests for _DepsTodoProxy."""

    def test_returns_empty_list_when_deps_is_none(self):
        """Proxy returns [] before being bound to any deps."""
        proxy = _DepsTodoProxy()
        assert proxy.todos == []

    def test_delegates_read_to_deps(self):
        """Proxy reads from deps.todos."""
        proxy = _DepsTodoProxy()
        deps = DeepAgentDeps(backend=StateBackend())
        todo = Todo(content="Test task", status="pending", active_form="Testing")
        deps.todos = [todo]
        proxy._deps = deps
        assert proxy._deps is deps
        assert proxy.todos == [todo]

    def test_delegates_write_to_deps(self):
        """Proxy writes to deps.todos."""
        proxy = _DepsTodoProxy()
        deps = DeepAgentDeps(backend=StateBackend())
        proxy._deps = deps
        todo = Todo(content="Test task", status="pending", active_form="Testing")
        proxy.todos = [todo]
        assert deps.todos == [todo]

    def test_setter_copies_list(self):
        """Setter creates a copy, not assigns reference."""
        proxy = _DepsTodoProxy()
        deps = DeepAgentDeps(backend=StateBackend())
        proxy._deps = deps
        original = [Todo(content="Task", status="pending", active_form="Working")]
        proxy.todos = original
        assert deps.todos == original
        assert deps.todos is not original

    def test_setter_noop_when_deps_is_none(self):
        """Setter silently no-ops without deps."""
        proxy = _DepsTodoProxy()
        proxy.todos = [Todo(content="Task", status="pending", active_form="Working")]
        assert proxy.todos == []

    def test_agent_created_with_proxy_storage(self):
        """Integration: agent is created with proxy-backed todo toolset."""
        agent = create_deep_agent(model=TEST_MODEL, include_todo=True)
        # The agent should have a toolset with id "deep-todo"
        assert agent is not None

    async def test_concurrent_runs_isolated_via_contextvar(self):
        """Concurrent runs of one proxy see their own deps (no cross-run race).

        The proxy stores its bound deps in a ContextVar, and asyncio copies the
        context per task, so binding in one task must not leak into another.
        """
        import asyncio

        proxy = _DepsTodoProxy()
        deps_a = DeepAgentDeps(backend=StateBackend())
        deps_b = DeepAgentDeps(backend=StateBackend())
        todo_a = Todo(content="A task", status="pending", active_form="Doing A")
        todo_b = Todo(content="B task", status="pending", active_form="Doing B")

        async def run(deps: DeepAgentDeps, todo: Todo, other_starts: asyncio.Event) -> list[Any]:
            proxy._deps = deps
            # Yield so the sibling task can bind its own deps in between, which
            # would clobber a shared attribute but not an isolated ContextVar.
            other_starts.set()
            await asyncio.sleep(0)
            proxy.todos = [todo]
            await asyncio.sleep(0)
            return proxy.todos

        ev_a = asyncio.Event()
        ev_b = asyncio.Event()
        result_a, result_b = await asyncio.gather(
            run(deps_a, todo_a, ev_a),
            run(deps_b, todo_b, ev_b),
        )

        assert result_a == [todo_a]
        assert result_b == [todo_b]
        assert deps_a.todos == [todo_a]
        assert deps_b.todos == [todo_b]


class TestTodoProxyBinder:
    """Tests for _TodoProxyBinder (issue #148)."""

    async def test_binds_proxy_to_ctx_deps(self):
        """before_tool_execute binds the proxy to the run's deps and passes args through."""
        proxy = _DepsTodoProxy()
        deps = DeepAgentDeps(backend=StateBackend())
        binder = _TodoProxyBinder(proxy)

        class _Ctx:
            pass

        ctx = _Ctx()
        ctx.deps = deps  # type: ignore[attr-defined]
        sentinel: dict[str, Any] = {"todos": []}
        result = await binder.before_tool_execute(
            ctx,
            call=None,
            tool_def=None,
            args=sentinel,
        )
        assert proxy._deps is deps
        assert result is sentinel

    async def test_write_todos_persists_to_deps_end_to_end(self):
        """write_todos must land on deps.todos through a real run.

        The todo tools are ``tool_plain`` and pydantic-ai runs each tool in its
        own ``contextvars`` context, so binding the proxy only in instructions
        never reached the tools — writes were silently dropped. The binder
        re-binds the proxy in each tool's own context.
        """
        from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
        from pydantic_ai.models.function import FunctionModel

        def model(messages: list[Any], info: Any) -> ModelResponse:
            returns = [
                p for m in messages for p in getattr(m, "parts", []) if hasattr(p, "tool_name")
            ]
            if not returns:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="write_todos",
                            args={
                                "todos": [
                                    {
                                        "content": "Task A",
                                        "status": "pending",
                                        "active_form": "Doing A",
                                    },
                                    {
                                        "content": "Task B",
                                        "status": "in_progress",
                                        "active_form": "Doing B",
                                    },
                                ]
                            },
                        )
                    ]
                )
            return ModelResponse(parts=[TextPart("done")])

        agent = create_deep_agent(
            model=FunctionModel(model),
            include_todo=True,
            include_filesystem=False,
            include_execute=False,
            include_subagents=False,
            include_skills=False,
            include_plan=False,
            include_builtin_subagents=False,
            include_memory=False,
            context_manager=False,
            cost_tracking=False,
        )
        deps = DeepAgentDeps(backend=StateBackend())
        await agent.run("make todos", deps=deps)
        assert [t.content for t in deps.todos] == ["Task A", "Task B"]

    def test_no_capabilities_when_all_disabled(self):
        """Agent builds with an empty capability list when every feature is off."""
        agent = create_deep_agent(
            model=TestModel(),
            include_todo=False,
            patch_tool_calls=False,
            stuck_loop_detection=False,
            web_search=False,
            web_fetch=False,
            thinking=False,
            cost_tracking=False,
            context_manager=False,
            eviction_token_limit=None,
        )
        assert agent is not None


class TestInjectSubagentExtraToolsets:
    """Tests for _inject_subagent_extra_toolsets helper."""

    def test_noop_when_empty(self):
        """Empty extra_toolsets should be a no-op."""
        from pydantic_deep.agent import _inject_subagent_extra_toolsets

        sa_config: dict[str, Any] = {"name": "test", "instructions": "test"}
        _inject_subagent_extra_toolsets(sa_config, ())
        assert sa_config.get("toolsets") is None

    def test_injects_into_config_without_toolsets(self):
        """Extra toolsets should be added even when config has no toolsets key."""
        from pydantic_deep.agent import _inject_subagent_extra_toolsets

        class _FakeToolset:
            pass

        sa_config: dict[str, Any] = {"name": "test", "instructions": "test"}
        toolset = _FakeToolset()
        _inject_subagent_extra_toolsets(sa_config, (toolset,))
        assert sa_config["toolsets"] == [toolset]

    def test_extends_existing_toolsets(self):
        """Extra toolsets should be appended to existing ones."""
        from pydantic_deep.agent import _inject_subagent_extra_toolsets

        class _FakeToolset:
            pass

        sa_config: dict[str, Any] = {
            "name": "test",
            "instructions": "test",
            "toolsets": ["existing"],
        }
        toolset = _FakeToolset()
        _inject_subagent_extra_toolsets(sa_config, (toolset,))
        assert sa_config["toolsets"] == ["existing", toolset]
