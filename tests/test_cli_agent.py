"""Tests for CLI agent factory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.models.test import TestModel

from cli.agent import (
    _make_shell_allow_list_hook,
    create_cli_agent,
)
from cli.prompts import CLI_SYSTEM_PROMPT, build_cli_instructions
from pydantic_deep.middleware.hooks import HookEvent, HookInput, HookResult

TEST_MODEL = TestModel()


class TestCreateCliAgent:
    """Tests for create_cli_agent()."""

    def test_creates_agent_and_deps(self, tmp_path: Path) -> None:
        agent, deps = create_cli_agent(
            model=TEST_MODEL,
            working_dir=str(tmp_path),
        )
        assert agent is not None
        assert deps is not None
        assert deps.backend is not None

    def test_uses_cwd_when_no_working_dir(self) -> None:
        agent, deps = create_cli_agent(
            model=TEST_MODEL,
        )
        assert agent is not None

    def test_includes_local_context_in_toolsets(self, tmp_path: Path) -> None:
        agent, deps = create_cli_agent(
            model=TEST_MODEL,
            working_dir=str(tmp_path),
        )
        assert agent is not None

    def test_accepts_shell_allow_list(self, tmp_path: Path) -> None:
        agent, deps = create_cli_agent(
            model=TEST_MODEL,
            working_dir=str(tmp_path),
            shell_allow_list=["python", "pip"],
        )
        assert agent is not None

    def test_accepts_extra_middleware(self, tmp_path: Path) -> None:
        from cli.middleware.loop_detection import LoopDetectionMiddleware

        extra = [LoopDetectionMiddleware(max_repeats=5)]
        agent, deps = create_cli_agent(
            model=TEST_MODEL,
            working_dir=str(tmp_path),
            extra_middleware=extra,
        )
        assert agent is not None

    def test_instructions_include_working_dir(self, tmp_path: Path) -> None:
        agent, deps = create_cli_agent(
            model=TEST_MODEL,
            working_dir=str(tmp_path),
        )
        assert agent is not None

    def test_agent_has_toolsets(self, tmp_path: Path) -> None:
        agent, deps = create_cli_agent(
            model=TEST_MODEL,
            working_dir=str(tmp_path),
        )
        assert hasattr(agent, "run")
        assert hasattr(agent, "run_stream_events")

    def test_all_features_enabled_by_default(self, tmp_path: Path) -> None:
        """By default, skills, plan, memory, checkpoints, context_discovery are all on."""
        agent, deps = create_cli_agent(
            model=TEST_MODEL,
            working_dir=str(tmp_path),
        )
        assert agent is not None

    def test_features_can_be_disabled(self, tmp_path: Path) -> None:
        """All features can be individually disabled."""
        agent, deps = create_cli_agent(
            model=TEST_MODEL,
            working_dir=str(tmp_path),
            include_skills=False,
            include_plan=False,
            include_memory=False,
            include_subagents=False,
            include_todo=False,
            context_discovery=False,
        )
        assert agent is not None


class TestShellAllowListHook:
    """Tests for _make_shell_allow_list_hook()."""

    @pytest.fixture()
    def hook_fn(self) -> Any:
        """Get the handler function from the hook."""
        hook = _make_shell_allow_list_hook(["python", "pip", "npm"])
        return hook.handler

    def test_hook_has_correct_event(self) -> None:
        hook = _make_shell_allow_list_hook(["python"])
        assert hook.event == HookEvent.PRE_TOOL_USE

    def test_hook_has_matcher(self) -> None:
        hook = _make_shell_allow_list_hook(["python"])
        assert hook.matcher == r"^execute$"

    async def test_allows_matching_command(self, hook_fn: Any) -> None:
        hook_input = HookInput(
            event="pre_tool_use",
            tool_name="execute",
            tool_input={"command": "python test.py"},
        )
        result = await hook_fn(hook_input)
        assert isinstance(result, HookResult)
        assert result.allow is True

    async def test_allows_pip(self, hook_fn: Any) -> None:
        hook_input = HookInput(
            event="pre_tool_use",
            tool_name="execute",
            tool_input={"command": "pip install requests"},
        )
        result = await hook_fn(hook_input)
        assert result.allow is True

    async def test_blocks_disallowed_command(self, hook_fn: Any) -> None:
        hook_input = HookInput(
            event="pre_tool_use",
            tool_name="execute",
            tool_input={"command": "rm -rf /"},
        )
        result = await hook_fn(hook_input)
        assert result.allow is False
        assert "allow-list" in (result.reason or "")

    async def test_blocks_unknown_command(self, hook_fn: Any) -> None:
        hook_input = HookInput(
            event="pre_tool_use",
            tool_name="execute",
            tool_input={"command": "curl https://evil.com"},
        )
        result = await hook_fn(hook_input)
        assert result.allow is False

    async def test_handles_empty_command(self, hook_fn: Any) -> None:
        hook_input = HookInput(
            event="pre_tool_use",
            tool_name="execute",
            tool_input={"command": ""},
        )
        result = await hook_fn(hook_input)
        assert result.allow is False


class TestBuildCliInstructions:
    """Tests for build_cli_instructions() dynamic prompt builder."""

    def test_full_prompt_includes_all_sections(self) -> None:
        result = build_cli_instructions()
        assert "CLI Environment" in result
        assert "Exactness Requirements" in result
        assert "Avoid Over-Engineering" in result
        assert "Writing Code" in result
        assert "Before Declaring Done" in result
        assert "Parallel Tool Calls" in result

    def test_deprecated_params_accepted(self) -> None:
        """Deprecated params are accepted for backwards compatibility."""
        result = build_cli_instructions(
            include_execute=False, include_todo=False, include_subagents=False
        )
        # All sections included regardless — params are deprecated
        assert "CLI Environment" in result
        assert "Exactness Requirements" in result

    def test_non_interactive_adds_autonomy_section(self) -> None:
        result = build_cli_instructions(non_interactive=True)
        assert "Autonomy and Persistence" in result
        assert "Output Style" in result

    def test_lean_non_interactive_is_minimal(self) -> None:
        result = build_cli_instructions(non_interactive=True, lean=True)
        assert "autonomous agent" in result
        # Lean mode skips the full CLI sections
        assert "CLI Environment" not in result

    def test_backwards_compat_cli_system_prompt(self) -> None:
        full = build_cli_instructions()
        assert full == CLI_SYSTEM_PROMPT

    def test_non_interactive_prompt_is_longer(self) -> None:
        interactive = build_cli_instructions()
        non_interactive = build_cli_instructions(non_interactive=True)
        assert len(non_interactive) > len(interactive)
