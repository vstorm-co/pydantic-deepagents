"""Tests for ContextManagerMiddleware integration in create_deep_agent."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from pydantic_ai.messages import ModelMessage
from pydantic_ai.models.test import TestModel
from pydantic_ai_middleware import AgentMiddleware, MiddlewareAgent
from pydantic_ai_summarization import ContextManagerMiddleware

from pydantic_deep import create_deep_agent
from pydantic_deep.deps import DeepAgentDeps

TEST_MODEL = TestModel()


def _minimal_agent(**kwargs: Any) -> Any:
    """Create agent with minimal toolsets for fast tests."""
    defaults = {
        "model": TEST_MODEL,
        "include_subagents": False,
        "include_skills": False,
        "cost_tracking": False,
    }
    defaults.update(kwargs)
    return create_deep_agent(**defaults)


class TestContextManagerIntegration:
    """Tests for context_manager parameter in create_deep_agent."""

    def test_default_has_context_manager(self):
        """Default agent has ContextManagerMiddleware in history_processors."""
        agent = _minimal_agent()
        processors = agent.history_processors  # type: ignore[union-attr]
        assert any(isinstance(p, ContextManagerMiddleware) for p in processors)

    def test_context_manager_disabled(self):
        """context_manager=False excludes ContextManagerMiddleware."""
        agent = _minimal_agent(context_manager=False)
        processors = agent.history_processors  # type: ignore[union-attr]
        assert all(not isinstance(p, ContextManagerMiddleware) for p in processors)

    def test_custom_max_tokens(self):
        """context_manager_max_tokens is passed through to the middleware."""
        agent = _minimal_agent(context_manager_max_tokens=128_000)
        processors = agent.history_processors  # type: ignore[union-attr]
        cm = next(p for p in processors if isinstance(p, ContextManagerMiddleware))
        assert cm.max_tokens == 128_000

    def test_default_max_tokens(self):
        """Default max_tokens is 200_000."""
        agent = _minimal_agent()
        processors = agent.history_processors  # type: ignore[union-attr]
        cm = next(p for p in processors if isinstance(p, ContextManagerMiddleware))
        assert cm.max_tokens == 200_000

    def test_on_context_update_callback(self):
        """on_context_update callback is wired to the middleware."""
        callback = MagicMock()
        agent = _minimal_agent(on_context_update=callback)
        processors = agent.history_processors  # type: ignore[union-attr]
        cm = next(p for p in processors if isinstance(p, ContextManagerMiddleware))
        assert cm.on_usage_update is callback

    def test_no_callback_by_default(self):
        """No usage callback is set by default."""
        agent = _minimal_agent()
        processors = agent.history_processors  # type: ignore[union-attr]
        cm = next(p for p in processors if isinstance(p, ContextManagerMiddleware))
        assert cm.on_usage_update is None

    def test_context_manager_with_eviction(self):
        """Context manager and eviction work together."""
        agent = _minimal_agent(eviction_token_limit=20000)
        processors = agent.history_processors  # type: ignore[union-attr]
        # Eviction should be first, context manager last
        from pydantic_deep.processors.eviction import EvictionProcessor

        assert isinstance(processors[0], EvictionProcessor)
        assert isinstance(processors[-1], ContextManagerMiddleware)

    def test_context_manager_with_user_processors(self):
        """Context manager is appended AFTER user-provided processors."""

        def custom_processor(messages: list[ModelMessage]) -> list[ModelMessage]:
            return messages

        agent = _minimal_agent(history_processors=[custom_processor])
        processors = agent.history_processors  # type: ignore[union-attr]
        # User processor should come before context manager
        cm_idx = next(
            i for i, p in enumerate(processors) if isinstance(p, ContextManagerMiddleware)
        )
        custom_idx = next(i for i, p in enumerate(processors) if p is custom_processor)
        assert custom_idx < cm_idx

    def test_context_manager_with_patch_tool_calls(self):
        """Context manager works with patch_tool_calls."""
        agent = _minimal_agent(patch_tool_calls=True)
        processors = agent.history_processors  # type: ignore[union-attr]
        # Patch processor should be first, context manager last
        from pydantic_deep.processors.patch import patch_tool_calls_processor

        assert processors[0] is patch_tool_calls_processor
        assert isinstance(processors[-1], ContextManagerMiddleware)

    def test_context_manager_with_middleware_wrapping(self):
        """When MiddlewareAgent wrapping is active, context_mw is in middleware list too."""

        class DummyMiddleware(AgentMiddleware[DeepAgentDeps]):
            pass

        agent = _minimal_agent(middleware=[DummyMiddleware()])
        assert isinstance(agent, MiddlewareAgent)

    def test_context_manager_disabled_with_middleware(self):
        """context_manager=False doesn't add to middleware list."""

        class DummyMiddleware(AgentMiddleware[DeepAgentDeps]):
            pass

        agent = _minimal_agent(context_manager=False, middleware=[DummyMiddleware()])
        assert isinstance(agent, MiddlewareAgent)

    def test_disabled_has_no_processors(self):
        """Agent with context_manager=False and no other processors has empty list."""
        agent = _minimal_agent(context_manager=False)
        processors = agent.history_processors  # type: ignore[union-attr]
        assert len(processors) == 0
