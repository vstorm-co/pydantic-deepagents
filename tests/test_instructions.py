"""Tests for the runtime instruction providers."""

from __future__ import annotations

from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import RunContext
from pydantic_ai.usage import RunUsage
from pydantic_ai_backends import StateBackend

from pydantic_deep.agent import _DepsTodoProxy
from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.instructions import (
    build_instruction_providers,
    lean_todo_section,
    make_lean_subagent_section,
    make_subagent_section,
    make_todo_section,
    render_instructions,
    uploads_section,
    web_tools_section,
)
from pydantic_deep.types import SubAgentConfig

TEST_MODEL = TestModel()


def _ctx(deps: DeepAgentDeps | None = None) -> RunContext[DeepAgentDeps]:
    return RunContext(
        deps=deps or DeepAgentDeps(backend=StateBackend()),
        model=TEST_MODEL,
        usage=RunUsage(),
    )


class TestSections:
    def test_uploads_empty_when_no_uploads(self) -> None:
        assert uploads_section(_ctx()) == ""

    def test_todo_section_binds_deps(self) -> None:
        proxy = _DepsTodoProxy()
        provider = make_todo_section(proxy)
        ctx = _ctx()
        provider(ctx)
        assert proxy._deps is ctx.deps

    def test_subagent_section_empty_without_configs(self) -> None:
        provider = make_subagent_section([])
        assert provider(_ctx()) == ""

    def test_subagent_section_lists_specialists(self) -> None:
        configs: list[SubAgentConfig] = [{"name": "researcher", "description": "Researches things"}]
        provider = make_subagent_section(configs)
        assert "researcher" in provider(_ctx())

    def test_web_section_both_tools(self) -> None:
        text = web_tools_section(web_search=True, web_fetch=True)
        assert "web search" in text
        assert "web fetch" in text

    def test_web_section_search_only(self) -> None:
        text = web_tools_section(web_search=True, web_fetch=False)
        assert "web search" in text
        assert "web fetch" not in text

    def test_web_section_fetch_only(self) -> None:
        text = web_tools_section(web_search=False, web_fetch=True)
        assert "web fetch" in text
        assert "web search" not in text

    def test_lean_todo_section_is_behavioral_not_an_inventory(self) -> None:
        text = lean_todo_section(_ctx())
        assert "Task Tracking" in text
        assert "in_progress" in text
        # No per-tool enumeration — the tools carry their own schemas.
        assert "read_todos" not in text
        assert "write_todos" not in text

    def test_lean_subagent_section_lists_roster_only(self) -> None:
        configs: list[SubAgentConfig] = [
            {"name": "planner", "description": "Plans things"},
            {"name": "research", "description": "Researches things"},
        ]
        text = make_lean_subagent_section(configs)(_ctx())
        assert "planner" in text and "research" in text
        assert "`task` tool" in text

    def test_lean_subagent_section_empty_without_configs(self) -> None:
        assert make_lean_subagent_section([])(_ctx()) == ""

    def test_builtins_include_general_purpose_implementer(self) -> None:
        """A general-purpose subagent must be available so the agent can delegate
        actual build/file work — not just research/planning."""
        from pydantic_deep.subagents import BUILTIN_SUBAGENTS

        gp = next((s for s in BUILTIN_SUBAGENTS if s["name"] == "general-purpose"), None)
        assert gp is not None
        desc = gp["description"].lower()
        assert "implement" in desc or "writing" in desc or "files" in desc


class TestBuildAndRender:
    def test_all_features_off_keeps_uploads_only(self) -> None:
        providers = build_instruction_providers(
            include_todo=False,
            todo_proxy=None,
            include_filesystem=False,
            edit_format="hashline",
            include_subagents=False,
            subagents=[],
            web_search=False,
            web_fetch=False,
        )
        assert len(providers) == 1  # uploads_section only

    def test_all_features_on(self) -> None:
        providers = build_instruction_providers(
            include_todo=True,
            todo_proxy=_DepsTodoProxy(),
            include_filesystem=True,
            edit_format="hashline",
            include_subagents=True,
            subagents=[],
            web_search=True,
            web_fetch=True,
        )
        # uploads + todo + console + subagent + web
        assert len(providers) == 5

    def test_tool_search_swaps_in_lean_sections(self) -> None:
        configs: list[SubAgentConfig] = [{"name": "planner", "description": "Plans"}]
        providers = build_instruction_providers(
            include_todo=True,
            todo_proxy=_DepsTodoProxy(),
            include_filesystem=True,
            edit_format="hashline",
            include_subagents=True,
            subagents=configs,
            web_search=False,
            web_fetch=False,
            tool_search=True,
        )
        rendered = render_instructions(_ctx(), providers)
        assert "Task Tracking" in rendered  # lean todo
        assert "`task` tool" in rendered  # lean subagent
        # The verbose per-tool enumeration is gone.
        assert "read_todos" not in rendered

    def test_todo_skipped_when_proxy_missing(self) -> None:
        providers = build_instruction_providers(
            include_todo=True,
            todo_proxy=None,
            include_filesystem=False,
            edit_format="hashline",
            include_subagents=False,
            subagents=[],
            web_search=False,
            web_fetch=False,
        )
        assert len(providers) == 1

    def test_render_joins_nonempty_sections(self) -> None:
        providers = build_instruction_providers(
            include_todo=False,
            todo_proxy=None,
            include_filesystem=True,
            edit_format="hashline",
            include_subagents=False,
            subagents=[],
            web_search=True,
            web_fetch=False,
        )
        rendered = render_instructions(_ctx(), providers)
        assert "web search" in rendered
        # uploads is empty and is filtered out, so the prompt never opens with a
        # blank separator from a missing leading section.
        assert not rendered.startswith("\n")
