"""Tests for the runtime instruction providers."""

from __future__ import annotations

from pydantic_ai.models.test import TestModel
from pydantic_ai.tools import RunContext
from pydantic_ai.usage import RunUsage
from pydantic_ai_backends import StateBackend
from pydantic_ai_todo import Todo

from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.instructions import (
    build_instruction_providers,
    current_todos_section,
    lean_todo_section,
    make_lean_subagent_section,
    make_subagent_section,
    render_instructions,
    todo_section,
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


def _todo(content: str, status: str = "in_progress") -> Todo:
    return Todo(content=content, active_form=f"{content}ing", status=status)


class TestSections:
    def test_uploads_empty_when_no_uploads(self) -> None:
        assert uploads_section(_ctx()) == ""

    def test_todo_section_is_static_across_mutations(self) -> None:
        """The todo section opens the prompt-cache prefix, so it must not change
        when a todo does (issue #182)."""
        ctx = _ctx()
        before = todo_section(ctx)
        ctx.deps.todos = [_todo("Write docs")]
        assert todo_section(ctx) == before
        assert "## Current Todos" not in before

    def test_current_todos_section_renders_the_live_list(self) -> None:
        ctx = _ctx()
        assert current_todos_section(ctx) == ""
        todo = _todo("Write docs")
        ctx.deps.todos = [todo]
        rendered = current_todos_section(ctx)
        assert "## Current Todos" in rendered
        assert "Write docs" in rendered
        assert todo.id in rendered

    def test_subagent_section_empty_without_configs(self) -> None:
        provider = make_subagent_section([])
        assert provider(_ctx()) == ""

    def test_subagent_section_lists_specialists(self) -> None:
        configs: list[SubAgentConfig] = [
            {
                "name": "researcher",
                "description": "Researches things",
                "instructions": "Research.",
            }
        ]
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
            {"name": "planner", "description": "Plans things", "instructions": "Plan."},
            {
                "name": "research",
                "description": "Researches things",
                "instructions": "Research.",
            },
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
        configs: list[SubAgentConfig] = [
            {"name": "planner", "description": "Plans", "instructions": "Plan."}
        ]
        providers = build_instruction_providers(
            include_todo=True,
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

    def test_todo_prompt_is_stable_across_mutations_by_default(self) -> None:
        """A todo mutation must not rewrite the instructions, or the provider's
        prompt-cache prefix is invalidated on every mutating tool call (#182)."""
        providers = build_instruction_providers(
            include_todo=True,
            include_filesystem=False,
            edit_format="hashline",
            include_subagents=False,
            subagents=[],
            web_search=False,
            web_fetch=False,
        )
        ctx = _ctx()
        before = render_instructions(ctx, providers)
        ctx.deps.todos = [_todo("Write docs")]
        assert render_instructions(ctx, providers) == before
        assert "## Current Todos" not in before

    def test_current_todos_opt_in_appends_the_live_list(self) -> None:
        providers = build_instruction_providers(
            include_todo=True,
            include_filesystem=False,
            edit_format="hashline",
            include_subagents=False,
            subagents=[],
            web_search=False,
            web_fetch=False,
            include_current_todos=True,
        )
        ctx = _ctx()
        ctx.deps.todos = [_todo("Write docs")]
        rendered = render_instructions(ctx, providers)
        assert "## Current Todos" in rendered
        assert "Write docs" in rendered

    def test_current_todos_opt_in_composes_with_tool_search(self) -> None:
        """The lean section replaces the tool inventory, not the explicit
        opt-in to the live list."""
        providers = build_instruction_providers(
            include_todo=True,
            include_filesystem=False,
            edit_format="hashline",
            include_subagents=False,
            subagents=[],
            web_search=False,
            web_fetch=False,
            tool_search=True,
            include_current_todos=True,
        )
        ctx = _ctx()
        ctx.deps.todos = [_todo("Write docs")]
        rendered = render_instructions(ctx, providers)
        assert "Task Tracking" in rendered  # lean base
        assert "Write docs" in rendered  # live list

    def test_render_joins_nonempty_sections(self) -> None:
        providers = build_instruction_providers(
            include_todo=False,
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
