"""Memory as the harness `Memory` capability, in the run's workspace."""

from __future__ import annotations

import warnings
from typing import Any, cast

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

    async def test_tool_search_leaves_memory_loaded(self) -> None:
        """A deferred capability's hooks wait for `load_capability`, so deferring
        memory with the rest stopped the notebook being injected at all."""
        seen: list[str] = []
        workspace = state_workspace({".deep/memory/main/MEMORY.md": "The user prefers tabs."})
        agent = _agent(_requests_seen(seen), tool_search=True)
        [memory] = [c for c in agent._root_capability.capabilities if isinstance(c, Memory)]

        await agent.run("hi", deps=DeepAgentDeps(), workspace=workspace)

        assert memory.defer_loading is False
        assert any("The user prefers tabs." in text for text in seen)

    def test_memory_comes_after_the_caller_s_capabilities(self) -> None:
        """A history processor or capability listed after it would rewrite - or
        summarize - the history the notebook is injected into."""
        from pydantic_ai.capabilities import ProcessHistory

        agent = _agent(_requests_seen([]), history_processors=[lambda messages: messages])
        kinds = [type(c) for c in agent._root_capability.capabilities]

        assert kinds.index(Memory) > kinds.index(ProcessHistory)

    def test_the_agent_and_its_subagents_share_one_store(self) -> None:
        """Separate stores over one directory each lock on their own, and their
        receipts overwrite each other's."""
        from pydantic_deep.types import SubAgentConfig

        agent = create_deep_agent(
            model=_requests_seen([]),
            subagents=[SubAgentConfig(name="researcher", description="d", instructions="i")],
            include_builtin_subagents=False,
            web_search=False,
            web_fetch=False,
        )
        [main] = [c for c in agent._root_capability.capabilities if isinstance(c, Memory)]
        [subagents] = [t for t in agent.toolsets if t.id == "deep-subagents"]
        researcher = cast(Any, subagents)._compiled["researcher"].agent
        [sub] = [c for c in researcher._root_capability.capabilities if isinstance(c, Memory)]

        assert sub.store is main.store
        assert (main.agent_name, sub.agent_name) == ("main", "researcher")

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
            memory_dir=".deep/memory",
            agent_name="main",
            max_lines=50,
            max_tokens=500,
            max_memory_size=1_000_000,
        )

        assert (memory.max_lines, memory.max_tokens, memory.max_memory_size) == (50, 500, 1_000_000)

    def test_a_fixed_namespace_the_harness_would_refuse_fails_at_build(self) -> None:
        """Rather than at every run - and rather than being renamed, which could
        put two tenants in one notebook."""
        with pytest.raises(ValueError, match="memory_namespace='user@example.com'"):
            build_memory_capability(agent_name="main", namespace="user@example.com")

    @pytest.mark.parametrize("namespace", ["tenant-1", "org.a/team_b"])
    def test_a_usable_namespace_is_kept_as_it_is(self, namespace: str) -> None:
        assert (
            build_memory_capability(agent_name="main", namespace=namespace).namespace == namespace
        )

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
            ("a..b", "a.b"),
            ("..", "agent"),
            (".", "agent"),
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
            missing = "no_such_name"
            with pytest.raises(AttributeError, match=missing):
                getattr(pydantic_deep, missing)


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


class TestSubagents:
    @staticmethod
    def _build(**subagent: Any) -> None:
        from pydantic_deep.types import SubAgentConfig

        config = cast(
            SubAgentConfig, {"name": "critic", "description": "d", "instructions": "i", **subagent}
        )
        create_deep_agent(
            model=_requests_seen([]),
            subagents=[config],
            include_builtin_subagents=False,
            web_search=False,
            web_fetch=False,
        )

    def test_a_subagent_with_its_own_factory_is_handed_the_memory_tools(self) -> None:
        """They arrive in `cfg["toolsets"]`, and a factory that passes those on
        gives its agent the tools under the subagent's own name."""
        from pydantic_ai import Agent
        from pydantic_ai.models.test import TestModel
        from pydantic_ai_harness.memory import MemoryToolset

        built: list[Agent[Any, str]] = []

        def factory(config: Any) -> Agent[Any, str]:
            agent = Agent(TestModel(), toolsets=config.get("toolsets", []))
            built.append(agent)
            return agent

        self._build(agent_factory=factory)

        [agent] = built
        memory = [t for t in agent.toolsets if isinstance(t, MemoryToolset)]
        assert [t._capability.agent_name for t in memory] == ["critic"]

    def test_a_prebuilt_subagent_is_left_as_it_is(self) -> None:
        """It is used as given, so there is nothing to hand the tools to."""
        from pydantic_ai import Agent
        from pydantic_ai.models.test import TestModel

        prebuilt = Agent(TestModel())
        before = list(prebuilt.toolsets)

        self._build(agent=prebuilt)

        assert list(prebuilt.toolsets) == before


class TestTeamMembers:
    async def test_a_member_remembers_under_the_lead_s_namespace_and_its_own_name(self) -> None:
        """Members are built by the subagent factory, so the per-tenant namespace
        reaches them: a member with the lead's un-namespaced "main" notebook would
        share it across every tenant of a shared workspace."""
        from pydantic_deep.features.teams import TeamMemberSpec
        from tests.workspaces import run_context

        def tenant(ctx: RunContext[Any]) -> str:
            return "tenant-a"

        agent = create_deep_agent(
            model=_requests_seen([]),
            include_teams=True,
            include_builtin_subagents=False,
            web_search=False,
            web_fetch=False,
            memory_namespace=tenant,
        )
        toolsets = {t.id: cast(Any, t) for t in agent.toolsets if t.id is not None}
        [main] = [c for c in agent._root_capability.capabilities if isinstance(c, Memory)]

        await (
            toolsets["deep-team"]
            .tools["spawn_team"]
            .function(run_context(DeepAgentDeps()), "build", [TeamMemberSpec(name="coder")])
        )

        member = toolsets["deep-subagents"].registry.get_compiled("coder").agent
        [memory] = [c for c in member._root_capability.capabilities if isinstance(c, Memory)]
        assert (memory.agent_name, memory.namespace, memory.store) == ("coder", tenant, main.store)
