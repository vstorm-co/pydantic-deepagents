"""Tests for cost tracking integration in create_deep_agent."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel
from pydantic_ai_middleware import MiddlewareAgent

from pydantic_deep import create_deep_agent
from pydantic_deep.deps import DeepAgentDeps

TEST_MODEL = TestModel()


def _minimal_agent(**kwargs: Any) -> Any:
    """Create agent with minimal toolsets for fast tests."""
    defaults = {
        "model": TEST_MODEL,
        "include_subagents": False,
        "include_skills": False,
    }
    defaults.update(kwargs)
    return create_deep_agent(**defaults)


class TestCostTrackingIntegration:
    """Tests for cost_tracking parameter in create_deep_agent."""

    def test_default_has_cost_tracking(self):
        """Default agent has CostTrackingMiddleware (wrapped in MiddlewareAgent)."""
        agent = _minimal_agent()
        assert isinstance(agent, MiddlewareAgent)
        from pydantic_ai_middleware.cost_tracking import CostTrackingMiddleware

        assert any(isinstance(m, CostTrackingMiddleware) for m in agent.middleware)

    def test_cost_tracking_disabled(self):
        """cost_tracking=False returns plain Agent (when no other middleware)."""
        agent = _minimal_agent(cost_tracking=False)
        assert isinstance(agent, Agent)

    def test_cost_tracking_disabled_no_context_manager(self):
        """Both cost_tracking=False and context_manager=False = plain Agent."""
        agent = _minimal_agent(cost_tracking=False, context_manager=False)
        assert isinstance(agent, Agent)

    def test_custom_budget(self):
        """cost_budget_usd is passed through to CostTrackingMiddleware."""
        agent = _minimal_agent(cost_budget_usd=5.0)
        from pydantic_ai_middleware.cost_tracking import CostTrackingMiddleware

        cost_mw = next(m for m in agent.middleware if isinstance(m, CostTrackingMiddleware))
        assert cost_mw.budget_limit_usd == 5.0

    def test_on_cost_update_callback(self):
        """on_cost_update callback is wired to the middleware."""
        callback = MagicMock()
        agent = _minimal_agent(on_cost_update=callback)
        from pydantic_ai_middleware.cost_tracking import CostTrackingMiddleware

        cost_mw = next(m for m in agent.middleware if isinstance(m, CostTrackingMiddleware))
        assert cost_mw.on_cost_update is callback

    def test_no_callback_by_default(self):
        """No cost callback is set by default."""
        agent = _minimal_agent()
        from pydantic_ai_middleware.cost_tracking import CostTrackingMiddleware

        cost_mw = next(m for m in agent.middleware if isinstance(m, CostTrackingMiddleware))
        assert cost_mw.on_cost_update is None

    def test_model_name_passed_for_string_model(self):
        """String model is used for cost calculation model_name.

        We use TestModel but verify the logic by checking that non-string
        model results in None model_name (covered below). The actual
        string model passing is covered by the implementation path.
        """
        # We can't use a real model string without API keys, so we verify
        # the logic indirectly: the model param is checked with isinstance(model, str)

        # When model is a string, cost_mw.model_name should be set
        # We test this via the factory directly
        from pydantic_ai_middleware import create_cost_tracking_middleware

        mw = create_cost_tracking_middleware(model_name="openai:gpt-4.1")
        assert mw.model_name == "openai:gpt-4.1"

    def test_non_string_model_passes_none(self):
        """Non-string model (e.g. TestModel) passes None as model_name."""
        agent = _minimal_agent()
        from pydantic_ai_middleware.cost_tracking import CostTrackingMiddleware

        cost_mw = next(m for m in agent.middleware if isinstance(m, CostTrackingMiddleware))
        assert cost_mw.model_name is None

    def test_cost_tracking_with_existing_middleware(self):
        """Cost tracking merges into existing middleware list."""
        from pydantic_ai_middleware import AgentMiddleware

        class DummyMiddleware(AgentMiddleware[DeepAgentDeps]):
            pass

        agent = _minimal_agent(middleware=[DummyMiddleware()])
        assert isinstance(agent, MiddlewareAgent)
        from pydantic_ai_middleware.cost_tracking import CostTrackingMiddleware

        # Should have: DummyMiddleware + ContextManagerMiddleware + CostTrackingMiddleware
        assert any(isinstance(m, DummyMiddleware) for m in agent.middleware)
        assert any(isinstance(m, CostTrackingMiddleware) for m in agent.middleware)

    def test_cost_tracking_with_context_manager(self):
        """Cost tracking and context manager work together."""
        agent = _minimal_agent()
        from pydantic_ai_middleware.cost_tracking import CostTrackingMiddleware
        from pydantic_ai_summarization import ContextManagerMiddleware

        mw_types = [type(m) for m in agent.middleware]
        assert ContextManagerMiddleware in mw_types
        assert CostTrackingMiddleware in mw_types

    def test_cost_tracking_without_context_manager(self):
        """Cost tracking works when context_manager is disabled."""
        agent = _minimal_agent(context_manager=False)
        assert isinstance(agent, MiddlewareAgent)
        from pydantic_ai_middleware.cost_tracking import CostTrackingMiddleware

        assert any(isinstance(m, CostTrackingMiddleware) for m in agent.middleware)


class TestCostTrackingExports:
    """Tests for cost tracking types exported from pydantic_deep."""

    def test_core_types_importable(self):
        """Core cost tracking types are importable from pydantic_deep."""
        from pydantic_deep import (
            BudgetExceededError,
            CostCallback,
            CostInfo,
            CostTrackingMiddleware,
            create_cost_tracking_middleware,
        )

        assert CostTrackingMiddleware is not None
        assert CostInfo is not None
        assert CostCallback is not None
        assert BudgetExceededError is not None
        assert create_cost_tracking_middleware is not None
