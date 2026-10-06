"""Memory as the harness `Memory` capability, in the run's workspace."""

from __future__ import annotations

import warnings
from typing import Any

import pytest
from pydantic_ai import RunContext
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai_harness import Memory
from pydantic_ai_summarization import ContextManagerCapability

from pydantic_deep import DeepAgentDeps, create_deep_agent
from pydantic_deep.features.memory import build_memory_capability
from pydantic_deep.features.memory.store import sanitize_agent_name
from tests.workspaces import state_workspace


def _agent(model: FunctionModel, **kwargs: Any) -> Any:
    return create_deep_agent(
        model=model,
        include_todo=False,
        include_subagents=False,
        include_skills=False,
        include_plan=False,
        include_teams=False,
        include_monitoring=False,
        web_search=False,
        web_fetch=False,
        cost_tracking=False,
        context_discovery=False,
        **kwargs,
    )


def _requests_seen(seen: list[str]) -> FunctionModel:
    """A model that records every user-role text it is sent, and answers."""

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        for message in messages:
            if isinstance(message, ModelRequest):
                seen.extend(
                    str(part.content) for part in message.parts if isinstance(part, UserPromptPart)
                )
        return ModelResponse(parts=[TextPart("done")])

    return FunctionModel(answer)


def _writes(content: str) -> FunctionModel:
    """A model that writes `content` to its notebook once, then answers."""

    def answer(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if any(isinstance(p, ToolReturnPart) for p in messages[-1].parts):
            return ModelResponse(parts=[TextPart("noted")])
        return ModelResponse(parts=[ToolCallPart("write_memory", {"content": content})])

    return FunctionModel(answer)


class TestTheNotebook:
    async def test_an_existing_notebook_is_read_where_it_always_was(self) -> None:
        """`{memory_dir}/{agent_name}/MEMORY.md` is the layout pydantic-deep's own
        memory wrote, so a notebook kept before the move is injected unchanged."""
        seen: list[str] = []
        workspace = state_workspace({".deep/memory/main/MEMORY.md": "The user prefers tabs."})

        await _agent(_requests_seen(seen)).run("hi", deps=DeepAgentDeps(), workspace=workspace)

        assert any("The user prefers tabs." in text for text in seen)

    async def test_what_the_agent_writes_lands_in_the_workspace(self) -> None:
        workspace = state_workspace()

        await _agent(_writes("Deploys go out on Fridays.")).run(
            "remember", deps=DeepAgentDeps(), workspace=workspace
        )

        notebook = await workspace.read_text(".deep/memory/main/MEMORY.md")
        assert "Deploys go out on Fridays." in notebook

    async def test_a_namespace_keeps_each_user_s_notebook_apart(self) -> None:
        """Several users sharing one workspace: the namespace is resolved per run
        from the app's own context, and the model never chooses it."""
        workspace = state_workspace()

        def user(ctx: RunContext[Any]) -> str:
            return "user-42"

        await _agent(_writes("Likes dark mode."), memory_namespace=user).run(
            "remember", deps=DeepAgentDeps(), workspace=workspace
        )

        assert "Likes dark mode." in await workspace.read_text(
            ".deep/memory/user-42/main/MEMORY.md"
        )
        assert not await workspace.exists(".deep/memory/main/MEMORY.md")


class TestWiring:
    def test_memory_comes_after_compaction(self) -> None:
        """The notebook is injected into each request only; a compaction listed
        after it would rewrite the history the block sits in."""
        capabilities = _agent(_requests_seen([]))._root_capability.capabilities
        kinds = [type(c) for c in capabilities]

        assert kinds.index(Memory) > kinds.index(ContextManagerCapability)

    @pytest.mark.parametrize("tool_search", [True, False])
    def test_tool_search_defers_the_memory_tools(self, tool_search: bool) -> None:
        capabilities = _agent(
            _requests_seen([]), tool_search=tool_search
        )._root_capability.capabilities
        [memory] = [c for c in capabilities if isinstance(c, Memory)]

        assert memory.defer_loading is tool_search

    def test_no_memory_when_turned_off(self) -> None:
        capabilities = _agent(
            _requests_seen([]), include_memory=False
        )._root_capability.capabilities

        assert not [c for c in capabilities if isinstance(c, Memory)]


class TestBuildingIt:
    def test_unset_limits_keep_the_harness_defaults(self) -> None:
        memory = build_memory_capability(memory_dir=".deep/memory", agent_name="main")

        assert (memory.max_lines, memory.max_tokens) == (Memory.max_lines, Memory.max_tokens)

    def test_set_limits_are_passed_on(self) -> None:
        memory = build_memory_capability(
            memory_dir=".deep/memory", agent_name="main", max_lines=50, max_tokens=500
        )

        assert (memory.max_lines, memory.max_tokens) == (50, 500)

    def test_a_pin_marker_warns_that_it_no_longer_pins(self) -> None:
        with pytest.warns(DeprecationWarning, match="memory_pin_marker"):
            build_memory_capability(
                memory_dir=".deep/memory", agent_name="main", pin_marker="<!-- end -->"
            )

    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("researcher", "researcher"),
            ("code reviewer", "code-reviewer"),
            ("a/b\\c", "a-b-c"),
            ("!!!", "agent"),
        ],
    )
    def test_an_agent_name_becomes_a_segment_the_harness_accepts(
        self, name: str, expected: str
    ) -> None:
        """The harness checks the segment when a run starts, so "code reviewer"
        built cleanly and failed at its first delegation."""
        assert sanitize_agent_name(name) == expected


class TestTheOldApi:
    @pytest.mark.parametrize("module", ["pydantic_deep", "pydantic_deep.features.memory"])
    def test_it_still_imports_with_a_warning(self, module: str) -> None:
        import importlib

        mod = importlib.import_module(module)
        mod.__dict__.pop("AgentMemoryToolset", None)

        with pytest.warns(DeprecationWarning, match="harness `Memory`"):
            toolset = mod.AgentMemoryToolset

        assert toolset.__name__ == "AgentMemoryToolset"

    def test_an_unknown_name_is_still_an_attribute_error(self) -> None:
        import pydantic_deep

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            with pytest.raises(AttributeError, match="no_such_name"):
                pydantic_deep.no_such_name  # noqa: B018


class TestForkedBranches:
    async def test_a_branch_remembers_in_its_overlay_until_it_is_merged(self) -> None:
        """Memory lives in the workspace, so a branch's notes are staged in its
        `BranchOverlay` like its files: a discarded branch leaves the parent's
        notebook as it was, and a merged one carries the notes over."""
        from pydantic_ai.workspaces import Workspace

        from pydantic_deep.features.forking.isolation import BranchOverlay

        parent = state_workspace({".deep/memory/main/MEMORY.md": "Shared fact.\n"})
        overlay = BranchOverlay(parent)

        await _agent(_writes("Branch-only fact.")).run(
            "remember", deps=DeepAgentDeps(), workspace=Workspace(overlay)
        )

        assert "Branch-only fact." not in await parent.read_text(".deep/memory/main/MEMORY.md")
        await overlay.flush_to(parent)
        merged = await parent.read_text(".deep/memory/main/MEMORY.md")
        assert "Shared fact." in merged
        assert "Branch-only fact." in merged
