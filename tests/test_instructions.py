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
