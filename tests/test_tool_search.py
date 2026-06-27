"""Tests for the tool_search feature (pydantic_deep/features/tool_search)."""

from __future__ import annotations

from pydantic_ai.capabilities import ToolSearch as PydanticAIToolSearch
from pydantic_ai.toolsets.deferred_loading import DeferredLoadingToolset
from pydantic_ai.toolsets.function import FunctionToolset

from pydantic_deep.features.tool_search import (
    DEFAULT_ALWAYS_LOADED_TOOLSET_IDS,
    ToolSearch,
    defer_situational_toolsets,
)


def test_reexports_pydantic_ai_tool_search() -> None:
    assert ToolSearch is PydanticAIToolSearch


def test_always_loaded_ids_kept_loaded() -> None:
    """Core-loop toolsets are returned untouched; everything else is deferred."""
    console = FunctionToolset(id="deep-console")
    todo = FunctionToolset(id="deep-todo")
    skills = FunctionToolset(id="deep-skills")

    result = defer_situational_toolsets([console, todo, skills])

    assert result[0] is console
    assert result[1] is todo
    assert isinstance(result[2], DeferredLoadingToolset)


def test_toolset_without_id_is_deferred() -> None:
    anonymous = FunctionToolset()
    (wrapped,) = defer_situational_toolsets([anonymous])
    assert isinstance(wrapped, DeferredLoadingToolset)


def test_custom_always_loaded_set() -> None:
    skills = FunctionToolset(id="deep-skills")
    (kept,) = defer_situational_toolsets([skills], always_loaded_ids=frozenset({"deep-skills"}))
    assert kept is skills


def test_default_always_loaded_contents() -> None:
    assert frozenset({"deep-console", "deep-todo"}) == DEFAULT_ALWAYS_LOADED_TOOLSET_IDS


def test_create_deep_agent_defers_situational_toolsets() -> None:
    """`tool_search=True` wraps the non-core toolsets and adds the capability."""
    from pydantic_ai_backends import StateBackend

    from pydantic_deep import create_deep_agent

    agent = create_deep_agent(
        model="test",
        backend=StateBackend(),
        output_type=str,
        tool_search=True,
        include_skills=False,  # avoid the missing-skills-dir warning
    )
    deferred = [t for t in agent.toolsets if isinstance(t, DeferredLoadingToolset)]
    assert deferred, "expected at least one deferred toolset"


def test_create_deep_agent_tool_search_off_by_default() -> None:
    from pydantic_ai_backends import StateBackend

    from pydantic_deep import create_deep_agent

    agent = create_deep_agent(
        model="test",
        backend=StateBackend(),
        output_type=str,
        include_skills=False,
    )
    deferred = [t for t in agent.toolsets if isinstance(t, DeferredLoadingToolset)]
    assert not deferred
