"""Tests for pydantic-ai-middleware integration."""

from __future__ import annotations

from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from pydantic_ai_middleware import (
    AgentMiddleware,
    MiddlewareAgent,
    MiddlewareChain,
    MiddlewareContext,
    ToolDecision,
    ToolPermissionResult,
    before_run,
)

from pydantic_deep import DeepAgentDeps, StateBackend, create_deep_agent

TEST_MODEL = TestModel()


# --- Helper middleware ---


class LoggingMiddleware(AgentMiddleware[DeepAgentDeps]):  # type: ignore[misc]
    """Simple middleware that records calls."""

    def __init__(self) -> None:
        self.before_run_calls: list[str] = []
        self.after_run_calls: list[str] = []

    async def before_run(self, prompt, deps, ctx):
        self.before_run_calls.append(str(prompt))
        return prompt

    async def after_run(self, prompt, output, deps, ctx):
        self.after_run_calls.append(str(output))
        return output


class BlockingMiddleware(AgentMiddleware[DeepAgentDeps]):  # type: ignore[misc]
    """Middleware that blocks specific tools."""

    def __init__(self, blocked_tools: set[str]) -> None:
        self.blocked_tools = blocked_tools

    async def before_tool_call(self, tool_name, tool_args, deps, ctx):
        if tool_name in self.blocked_tools:
            return ToolPermissionResult(
                decision=ToolDecision.DENY,
                reason=f"Tool {tool_name} is blocked",
            )
        return tool_args


# --- Tests: Agent creation ---


class TestCreateWithMiddleware:
    """Tests for create_deep_agent with middleware params."""

    def test_create_without_middleware(self):
        """Without middleware and cost_tracking, returns plain Agent."""
        agent = create_deep_agent(model=TEST_MODEL, cost_tracking=False)
        assert isinstance(agent, Agent)

    def test_create_with_middleware(self):
        """With middleware, returns MiddlewareAgent."""
        mw = LoggingMiddleware()
        agent = create_deep_agent(model=TEST_MODEL, middleware=[mw])
        assert isinstance(agent, MiddlewareAgent)

    def test_create_with_empty_middleware_list(self):
        """Empty middleware list still wraps in MiddlewareAgent."""
        agent = create_deep_agent(model=TEST_MODEL, middleware=[])
        assert isinstance(agent, MiddlewareAgent)

    def test_create_with_permission_handler_only(self):
        """permission_handler alone triggers MiddlewareAgent wrapping."""

        async def handler(tool_name, tool_args, reason):
            return True

        agent = create_deep_agent(model=TEST_MODEL, permission_handler=handler)
        assert isinstance(agent, MiddlewareAgent)

    def test_create_with_middleware_context(self):
        """MiddlewareContext is passed through."""
        ctx = MiddlewareContext(config={"key": "value"})
        mw = LoggingMiddleware()
        agent = create_deep_agent(model=TEST_MODEL, middleware=[mw], middleware_context=ctx)
        assert isinstance(agent, MiddlewareAgent)
        assert agent.context is ctx

    def test_middleware_agent_has_run(self):
        """Wrapped agent has run() method."""
        mw = LoggingMiddleware()
        agent = create_deep_agent(model=TEST_MODEL, middleware=[mw])
        assert hasattr(agent, "run")
        assert callable(agent.run)

    def test_middleware_agent_wraps_original(self):
        """MiddlewareAgent wraps the original Agent."""
        mw = LoggingMiddleware()
        agent = create_deep_agent(model=TEST_MODEL, middleware=[mw])
        assert isinstance(agent, MiddlewareAgent)
        assert isinstance(agent.wrapped, Agent)

    def test_middleware_with_all_params(self):
        """All middleware params work together."""

        async def handler(tool_name, tool_args, reason):
            return True

        ctx = MiddlewareContext()
        mw = LoggingMiddleware()
        agent = create_deep_agent(
            model=TEST_MODEL,
            middleware=[mw],
            permission_handler=handler,
            middleware_context=ctx,
        )
        assert isinstance(agent, MiddlewareAgent)
        assert agent.context is ctx
        # 1 user middleware + 1 ContextManagerMiddleware + 1 CostTrackingMiddleware (defaults)
        assert len(agent.middleware) == 3

    def test_middleware_with_chain(self):
        """MiddlewareChain works with create_deep_agent."""
        mw1 = LoggingMiddleware()
        mw2 = LoggingMiddleware()
        chain = MiddlewareChain([mw1, mw2])
        agent = create_deep_agent(model=TEST_MODEL, middleware=[chain])
        assert isinstance(agent, MiddlewareAgent)

    def test_middleware_preserves_toolsets(self):
        """Middleware wrapping preserves all toolsets."""
        agent = create_deep_agent(
            model=TEST_MODEL,
            middleware=[LoggingMiddleware()],
            include_todo=True,
            include_filesystem=True,
        )
        assert isinstance(agent, MiddlewareAgent)
        # The wrapped agent should have toolsets
        assert agent.wrapped is not None


# --- Tests: Middleware hooks ---


class TestMiddlewareHooks:
    """Tests for middleware hooks working with deep agent."""

    async def test_before_run_hook(self):
        """before_run hook is called during agent.run()."""
        mw = LoggingMiddleware()
        agent = create_deep_agent(
            model=TEST_MODEL,
            middleware=[mw],
            include_todo=False,
            include_filesystem=False,
            include_subagents=False,
            include_skills=False,
        )
        deps = DeepAgentDeps(backend=StateBackend())
        await agent.run("Hello world", deps=deps)
        assert len(mw.before_run_calls) == 1
        assert mw.before_run_calls[0] == "Hello world"

    async def test_after_run_hook(self):
        """after_run hook is called after agent.run()."""
        mw = LoggingMiddleware()
        agent = create_deep_agent(
            model=TEST_MODEL,
            middleware=[mw],
            include_todo=False,
            include_filesystem=False,
            include_subagents=False,
            include_skills=False,
        )
        deps = DeepAgentDeps(backend=StateBackend())
        await agent.run("Hello", deps=deps)
        assert len(mw.after_run_calls) == 1

    async def test_decorator_based_middleware(self):
        """@before_run decorator creates working middleware."""
        calls: list[str] = []

        @before_run
        async def log_input(prompt, deps, ctx):
            calls.append(str(prompt))
            return prompt

        agent = create_deep_agent(
            model=TEST_MODEL,
            middleware=[log_input],
            include_todo=False,
            include_filesystem=False,
            include_subagents=False,
            include_skills=False,
        )
        deps = DeepAgentDeps(backend=StateBackend())
        await agent.run("Test prompt", deps=deps)
        assert len(calls) == 1
        assert calls[0] == "Test prompt"

    async def test_multiple_middleware(self):
        """Multiple middleware are applied in order."""
        mw1 = LoggingMiddleware()
        mw2 = LoggingMiddleware()
        agent = create_deep_agent(
            model=TEST_MODEL,
            middleware=[mw1, mw2],
            include_todo=False,
            include_filesystem=False,
            include_subagents=False,
            include_skills=False,
        )
        deps = DeepAgentDeps(backend=StateBackend())
        await agent.run("Hello", deps=deps)
        assert len(mw1.before_run_calls) == 1
        assert len(mw2.before_run_calls) == 1


# --- Tests: Exports ---


class TestMiddlewareExports:
    """Tests for middleware types exported from pydantic_deep."""

    def test_core_types_importable(self):
        """Core middleware types are importable from pydantic_deep."""
        from pydantic_deep import (
            AgentMiddleware,
            MiddlewareAgent,
            MiddlewareChain,
            MiddlewareContext,
        )

        assert AgentMiddleware is not None
        assert MiddlewareAgent is not None
        assert MiddlewareChain is not None
        assert MiddlewareContext is not None

    def test_permission_types_importable(self):
        """Permission types are importable from pydantic_deep."""
        from pydantic_deep import PermissionHandler, ToolDecision, ToolPermissionResult

        assert PermissionHandler is not None
        assert ToolDecision is not None
        assert ToolPermissionResult is not None

    def test_decorators_importable(self):
        """Middleware decorators are importable from pydantic_deep."""
        from pydantic_deep import (
            after_run,
            after_tool_call,
            before_model_request,
            before_run,
            before_tool_call,
            on_error,
            on_tool_error,
        )

        assert before_run is not None
        assert after_run is not None
        assert before_model_request is not None
        assert before_tool_call is not None
        assert after_tool_call is not None
        assert on_tool_error is not None
        assert on_error is not None

    def test_exception_types_importable(self):
        """Middleware exception types are importable from pydantic_deep."""
        from pydantic_deep import InputBlocked, OutputBlocked, ToolBlocked

        assert InputBlocked is not None
        assert OutputBlocked is not None
        assert ToolBlocked is not None
