"""Extended tests for agent factory to reach 100% coverage."""

from collections.abc import Awaitable
from typing import Any, cast

from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.test import TestModel

from pydantic_deep import (
    DeepAgentDeps,
    StateBackend,
    create_deep_agent,
)
from pydantic_deep.features.skills import Skill as SkillDataclass
from pydantic_deep.features.skills import SkillsToolset

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
        """Return the resolved `requires_approval` flag of the console `execute` tool.

        Returns `None` if the console toolset / execute tool is not present.
        """
        seen: set[int] = set()

        def find_console(obj: object) -> object | None:
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

        Regression: the default must follow `any(interrupt_on.values())` so a caller
        enabling edit/write interrupts keeps shell `execute` behind human approval.
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
        assert deps.backend.unwrap() is local_backend
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

    def test_builtin_planner_skipped_if_already_defined(self):
        """Test that built-in planner subagent does not overwrite a user-defined one."""
        from pydantic_deep.types import SubAgentConfig

        custom_planner = SubAgentConfig(
            name="planner",
            description="My custom planner",
            instructions="Custom planner instructions",
        )
        agent = create_deep_agent(
            model=TEST_MODEL,
            subagents=[custom_planner],
            include_plan=True,
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


FALLBACK_MODEL = TestModel()
FALLBACK_MODEL_2 = TestModel()


class TestFallbackModel:
    def test_fallback_model_instance_wraps_in_fallback_model(self) -> None:
        agent = create_deep_agent(
            model=TEST_MODEL,
            fallback_model=FALLBACK_MODEL,
            web_search=False,
            web_fetch=False,
            thinking=False,
        )
        assert isinstance(agent.model, FallbackModel)
        assert len(agent.model.models) == 2

    def test_fallback_model_list_wraps_chain(self) -> None:
        agent = create_deep_agent(
            model=TEST_MODEL,
            fallback_model=[FALLBACK_MODEL, FALLBACK_MODEL_2],
            web_search=False,
            web_fetch=False,
            thinking=False,
        )
        assert isinstance(agent.model, FallbackModel)
        assert len(agent.model.models) == 3

    def test_fallback_model_none_does_not_wrap(self) -> None:
        agent = create_deep_agent(
            model=TEST_MODEL,
            fallback_model=None,
            web_search=False,
            web_fetch=False,
            thinking=False,
        )
        assert not isinstance(agent.model, FallbackModel)

    async def test_fallback_hook_dispatched_on_model_api_error(self) -> None:
        from pydantic_deep.features.hooks import Hook, HookEvent, HookInput, HookResult

        received: list[HookInput] = []

        async def handler(inp: HookInput) -> HookResult:
            received.append(inp)
            return HookResult()

        agent = create_deep_agent(
            model=TEST_MODEL,
            fallback_model=FALLBACK_MODEL,
            hooks=[Hook(event=HookEvent.MODEL_FALLBACK_TRIGGERED, handler=handler)],
            web_search=False,
            web_fetch=False,
            thinking=False,
        )
        assert isinstance(agent.model, FallbackModel)
        # _exception_handlers is a private pydantic-ai FallbackModel attribute; there is
        # no public equivalent that lets us unit-test the fallback_on callable directly.
        _fallback_on = cast(
            "Awaitable[bool]",
            agent.model._exception_handlers[0](ModelAPIError("test-model", "rate limit")),
        )
        result = await _fallback_on
        assert result is True
        assert len(received) == 1
        assert received[0].tool_input["primary"] is not None

    async def test_fallback_hook_not_triggered_for_non_api_error(self) -> None:
        from pydantic_deep.features.hooks import Hook, HookEvent, HookInput, HookResult

        received: list[HookInput] = []

        async def handler(inp: HookInput) -> HookResult:
            received.append(inp)
            return HookResult()

        agent = create_deep_agent(
            model=TEST_MODEL,
            fallback_model=FALLBACK_MODEL,
            hooks=[Hook(event=HookEvent.MODEL_FALLBACK_TRIGGERED, handler=handler)],
            web_search=False,
            web_fetch=False,
            thinking=False,
        )
        assert isinstance(agent.model, FallbackModel)
        # _exception_handlers is a private pydantic-ai FallbackModel attribute; there is
        # no public equivalent that lets us unit-test the fallback_on callable directly.
        _fallback_on = cast(
            "Awaitable[bool]",
            agent.model._exception_handlers[0](ValueError("not an api error")),
        )
        result = await _fallback_on
        assert result is False
        assert received == []

    async def test_fallback_hook_not_triggered_for_auth_error(self) -> None:
        from pydantic_deep.features.hooks import Hook, HookEvent, HookInput, HookResult

        received: list[HookInput] = []

        async def handler(inp: HookInput) -> HookResult:
            received.append(inp)
            return HookResult()

        agent = create_deep_agent(
            model=TEST_MODEL,
            fallback_model=FALLBACK_MODEL,
            hooks=[Hook(event=HookEvent.MODEL_FALLBACK_TRIGGERED, handler=handler)],
            web_search=False,
            web_fetch=False,
            thinking=False,
        )
        assert isinstance(agent.model, FallbackModel)
        # Auth errors must not be forwarded to the next model - they are permanent.
        for auth_msg in ("401 unauthorized", "403 forbidden", "unauthorized access"):
            _fallback_on = cast(
                "Awaitable[bool]",
                agent.model._exception_handlers[0](ModelAPIError("test-model", auth_msg)),
            )
            result = await _fallback_on
            assert result is False, f"Expected False for auth error: {auth_msg!r}"
        assert received == []

    def test_fallback_model_always_uses_auth_filtering_without_hooks(self) -> None:
        """FallbackModel is always wrapped with auth-filtering fallback_on, even when
        no MODEL_FALLBACK_TRIGGERED hook is registered."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            fallback_model=FALLBACK_MODEL,
            web_search=False,
            web_fetch=False,
            thinking=False,
        )
        assert isinstance(agent.model, FallbackModel)
        # A custom fallback_on must be installed regardless of hooks.
        assert agent.model._exception_handlers, "expected a custom fallback_on handler"

    async def test_auth_error_not_forwarded_without_hooks(self) -> None:
        """Auth errors (401/403) must not trigger fallback even with no hooks registered."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            fallback_model=FALLBACK_MODEL,
            web_search=False,
            web_fetch=False,
            thinking=False,
        )
        assert isinstance(agent.model, FallbackModel)
        _fallback_on = cast(
            "Awaitable[bool]",
            agent.model._exception_handlers[0](ModelAPIError("m", "401 unauthorized")),
        )
        result = await _fallback_on
        assert result is False, "auth error must not trigger fallback (no hooks case)"

    async def test_hook_not_fired_for_last_model_in_exhausted_chain(self) -> None:
        """When the last model in the chain fails, no MODEL_FALLBACK_TRIGGERED hook fires."""
        from pydantic_deep.features.hooks import Hook, HookEvent, HookInput, HookResult

        received: list[HookInput] = []

        async def handler(inp: HookInput) -> HookResult:
            received.append(inp)
            return HookResult()

        agent = create_deep_agent(
            model=TEST_MODEL,
            fallback_model=FALLBACK_MODEL,
            hooks=[Hook(event=HookEvent.MODEL_FALLBACK_TRIGGERED, handler=handler)],
            web_search=False,
            web_fetch=False,
            thinking=False,
        )
        assert isinstance(agent.model, FallbackModel)
        _fallback_on_raw = agent.model._exception_handlers[0]
        api_error = ModelAPIError("test-model", "rate limit exceeded")

        # First call: primary fails → hook fires (there is a fallback to try).
        result1 = await cast("Awaitable[bool]", _fallback_on_raw(api_error))
        assert result1 is True
        assert len(received) == 1

        # Second call: last fallback fails (chain exhausted) → hook must NOT fire.
        result2 = await cast("Awaitable[bool]", _fallback_on_raw(api_error))
        assert result2 is True
        assert len(received) == 1, "hook fired for exhausted chain - should be silent"

    async def test_hop_counter_auto_resets_after_chain_exhausted(self) -> None:
        """A fresh request after the chain was exhausted resets the hop counter.

        With a two-model chain the counter reaches `total_models` after the
        primary + fallback both fail in one request. The next failure (a new
        request, same coroutine context) must reset hop to 0 and fire the hook
        for the primary again - covering the auto-reset branch.
        """
        from pydantic_deep.features.hooks import Hook, HookEvent, HookInput, HookResult

        received: list[HookInput] = []

        async def handler(inp: HookInput) -> HookResult:
            received.append(inp)
            return HookResult()

        agent = create_deep_agent(
            model=TEST_MODEL,
            fallback_model=FALLBACK_MODEL,
            hooks=[Hook(event=HookEvent.MODEL_FALLBACK_TRIGGERED, handler=handler)],
            web_search=False,
            web_fetch=False,
            thinking=False,
        )
        assert isinstance(agent.model, FallbackModel)
        _fallback_on_raw = agent.model._exception_handlers[0]
        api_error = ModelAPIError("test-model", "rate limit exceeded")

        # First request: primary → fallback exhausts the two-model chain (hop = 2).
        await cast("Awaitable[bool]", _fallback_on_raw(api_error))
        await cast("Awaitable[bool]", _fallback_on_raw(api_error))
        assert len(received) == 1

        # New request, same context: hop (2) >= total_models (2) → reset to 0 and
        # the primary's failure fires the hook again.
        result = await cast("Awaitable[bool]", _fallback_on_raw(api_error))
        assert result is True
        assert len(received) == 2, "hop counter did not reset after exhaustion"

    async def test_partial_recovery_does_not_leak_hop_counter(self) -> None:
        """Regression: primary fails, a fallback succeeds (partial recovery). The
        request-boundary reset must zero the hop counter so the NEXT request in
        the same coroutine context re-attributes primary→fallback correctly
        instead of shifting (or skipping) the pair from a stale counter."""
        from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, UserPromptPart
        from pydantic_ai.models import Model, ModelRequestParameters
        from pydantic_ai_backends import StateBackend

        from pydantic_deep.agent import _fallback_hop_cv, _wrap_with_fallback_and_hooks
        from pydantic_deep.features.hooks import Hook, HookEvent, HookInput, HookResult

        seen_hops: list[int] = []

        class _FailModel(Model):
            @property
            def model_name(self) -> str:
                return "failing-primary"

            @property
            def system(self) -> str:
                return "test"

            async def request(self, *args: object, **kwargs: object) -> ModelResponse:
                seen_hops.append(_fallback_hop_cv.get())
                raise ModelAPIError("failing-primary", "rate limit exceeded")

        class _OkModel(Model):
            @property
            def model_name(self) -> str:
                return "ok-fallback"

            @property
            def system(self) -> str:
                return "test"

            async def request(self, *args: object, **kwargs: object) -> ModelResponse:
                return ModelResponse(parts=[TextPart(content="done")])

        received: list[HookInput] = []

        async def handler(inp: HookInput) -> HookResult:
            received.append(inp)
            return HookResult()

        model = _wrap_with_fallback_and_hooks(
            _FailModel(),
            [_OkModel()],
            [Hook(event=HookEvent.MODEL_FALLBACK_TRIGGERED, handler=handler)],
            StateBackend(),
        )
        msgs = [ModelRequest(parts=[UserPromptPart(content="hi")])]
        params = ModelRequestParameters()

        # Simulate a stale counter leaked from a prior partial recovery.
        _fallback_hop_cv.set(7)

        await model.request(msgs, None, params)
        await model.request(msgs, None, params)

        # Each request reset the counter to 0 before running the chain.
        assert seen_hops == [0, 0]
        # The hook fired on BOTH requests with the same correct primary→fallback
        # pair - not shifted or skipped by a stale counter.
        assert len(received) == 2
        pairs = {(r.tool_input["primary"], r.tool_input["fallback"]) for r in received}
        assert len(pairs) == 1, f"primary→fallback pair drifted across requests: {pairs}"

    async def test_model_fallback_command_hook_wraps_sync_sandbox_backend(self) -> None:
        """Regression: fallback command hooks receive the factory's sync backend.

        The async migration made command hook dispatch require an async sandbox;
        the fallback wrapper must normalize the sync sandbox before dispatching.
        """
        from pydantic_ai_backends import ExecuteResponse

        from pydantic_deep.agent import _wrap_with_fallback_and_hooks
        from pydantic_deep.features.hooks import Hook, HookEvent

        class _CommandBackend(StateBackend):  # type: ignore[misc]
            id = "command-backend"

            def __init__(self) -> None:
                super().__init__()
                self.executed: list[str] = []

            def execute(self, command: str, timeout: int | None = None) -> ExecuteResponse:
                self.executed.append(command)
                return ExecuteResponse(output="", exit_code=0)

        backend = _CommandBackend()
        model = _wrap_with_fallback_and_hooks(
            TestModel(),
            [TestModel()],
            [Hook(event=HookEvent.MODEL_FALLBACK_TRIGGERED, command="cat")],
            backend,
        )

        _fallback_on = cast(
            "Awaitable[bool]",
            model._exception_handlers[0](ModelAPIError("primary-model", "rate limit exceeded")),
        )
        assert await _fallback_on is True
        assert len(backend.executed) == 1
        assert "model_fallback_triggered" in backend.executed[0]

    async def test_request_stream_resets_hop_counter(self) -> None:
        """`request_stream` must also zero the per-context hop counter."""
        from pydantic_ai.messages import ModelRequest, UserPromptPart
        from pydantic_ai.models import ModelRequestParameters
        from pydantic_ai_backends import StateBackend

        from pydantic_deep.agent import _fallback_hop_cv, _wrap_with_fallback_and_hooks

        model = _wrap_with_fallback_and_hooks(TestModel(), [TestModel()], [], StateBackend())
        msgs = [ModelRequest(parts=[UserPromptPart(content="hi")])]
        params = ModelRequestParameters()

        _fallback_hop_cv.set(9)
        async with model.request_stream(msgs, None, params) as stream:
            async for _ in stream:
                pass
        assert _fallback_hop_cv.get() == 0


class TestSubagentUsageLimits:
    """subagents#43 — create_deep_agent forwards delegated usage limits."""

    def _spy_toolset(self, monkeypatch: Any) -> dict[str, Any]:
        """Patch create_subagent_toolset to capture its kwargs, still building it."""
        from subagents_pydantic_ai import create_subagent_toolset as real

        captured: dict[str, Any] = {}

        def _spy(*args: Any, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return real(*args, **kwargs)

        monkeypatch.setattr("pydantic_deep.agent.create_subagent_toolset", _spy)
        return captured

    def test_static_usage_limits_forwarded(self, monkeypatch: Any) -> None:
        """A static UsageLimits reaches create_subagent_toolset unchanged."""
        from pydantic_ai import UsageLimits

        captured = self._spy_toolset(monkeypatch)
        limits = UsageLimits(request_limit=123)
        create_deep_agent(
            model=TEST_MODEL,
            include_subagents=True,
            subagent_usage_limits=limits,
        )
        assert captured["usage_limits"] is limits

    def test_factory_usage_limits_forwarded(self, monkeypatch: Any) -> None:
        """A UsageLimitsFactory is forwarded as-is for per-config resolution."""
        from pydantic_ai import UsageLimits

        captured = self._spy_toolset(monkeypatch)

        def _factory(ctx: Any, config: Any) -> UsageLimits:  # pragma: no cover
            return UsageLimits(request_limit=config.get("extra", {}).get("limit", 50))

        create_deep_agent(
            model=TEST_MODEL,
            include_subagents=True,
            subagent_usage_limits=_factory,
        )
        assert captured["usage_limits"] is _factory

    def test_usage_limits_default_none(self, monkeypatch: Any) -> None:
        """Omitting the param forwards None (pydantic-ai default stays in place)."""
        captured = self._spy_toolset(monkeypatch)
        create_deep_agent(model=TEST_MODEL, include_subagents=True)
        assert captured["usage_limits"] is None
