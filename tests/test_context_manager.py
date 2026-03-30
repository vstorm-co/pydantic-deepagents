"""Tests for context management integration in create_deep_agent."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from pydantic_ai.models.test import TestModel
from pydantic_ai_summarization import ContextManagerCapability

from pydantic_deep import create_deep_agent

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
    return create_deep_agent(**defaults)  # type: ignore[call-overload]


class TestContextManagerIntegration:
    """Tests for context_manager parameter in create_deep_agent."""

    def test_default_has_context_manager(self):
        """Default agent has ContextManagerCapability."""
        agent = _minimal_agent()
        # Context middleware is exposed on agent
        assert hasattr(agent, "_context_middleware")
        assert agent._context_middleware is not None

    def test_context_manager_disabled(self):
        """context_manager=False excludes context capability."""
        agent = _minimal_agent(context_manager=False)
        assert agent._context_middleware is None

    def test_custom_max_tokens(self):
        """context_manager_max_tokens is passed through."""
        agent = _minimal_agent(context_manager_max_tokens=128_000)
        cm = agent._context_middleware
        assert isinstance(cm, ContextManagerCapability)
        assert cm._resolved_max_tokens == 128_000

    def test_on_context_update_callback(self):
        """on_context_update callback is wired."""
        callback = MagicMock()
        agent = _minimal_agent(on_context_update=callback)
        cm = agent._context_middleware
        assert isinstance(cm, ContextManagerCapability)
        assert cm.on_usage_update is callback

    def test_no_callback_by_default(self):
        """No usage callback is set by default."""
        agent = _minimal_agent()
        cm = agent._context_middleware
        assert isinstance(cm, ContextManagerCapability)
        assert cm.on_usage_update is None

    def test_disabled_has_no_context_middleware(self):
        """Agent with context_manager=False has None context_middleware."""
        agent = _minimal_agent(context_manager=False)
        assert agent._context_middleware is None

    def test_on_before_compress_forwarded(self):
        """on_before_compress callback is wired to ContextManagerCapability."""
        callback = MagicMock()
        agent = _minimal_agent(on_before_compress=callback)
        cm = agent._context_middleware
        assert isinstance(cm, ContextManagerCapability)
        assert cm.on_before_compress is callback

    def test_on_after_compress_forwarded(self):
        """on_after_compress callback is wired to ContextManagerCapability."""
        callback = MagicMock()
        agent = _minimal_agent(on_after_compress=callback)
        cm = agent._context_middleware
        assert isinstance(cm, ContextManagerCapability)
        assert cm.on_after_compress is callback
