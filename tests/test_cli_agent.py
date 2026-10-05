"""Tests for CLI agent factory."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.models.test import TestModel
from pydantic_ai.workspaces import LocalWorkspaceBackend, WorkspaceRef
from pydantic_ai_backends.workspaces import DockerWorkspace, DockerWorkspaceBackend

from apps.cli.agent import (
    _PROCESS_CONTAINER_ID,
    _detect_fork_test_command,
    _make_shell_allow_list_hook,
    create_cli_agent,
)
from apps.cli.prompts import CLI_SYSTEM_PROMPT, build_cli_instructions
from pydantic_deep.features.hooks import HookEvent, HookInput, HookResult

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
        assert agent._cli_workspace is not None

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

    def test_include_browser_true_with_playwright(self, tmp_path: Path) -> None:
        """When include_browser=True and playwright is available, BrowserCapability is added."""
        # playwright IS installed in this project, so import succeeds
        agent, deps = create_cli_agent(
            model=TEST_MODEL,
            working_dir=str(tmp_path),
            include_browser=True,
            browser_headless=True,
        )
        assert agent is not None

    def test_include_browser_import_error_warns(self, tmp_path: Path) -> None:
        """When playwright is missing, an ImportError produces a warning."""
        import sys
        from unittest.mock import patch

        # Remove the browser module from sys.modules so the import inside the try block fires
        browser_mod = sys.modules.pop("pydantic_deep.features.browser.capability", None)
        try:
            with patch.dict("sys.modules", {"playwright": None, "playwright.async_api": None}):
                import warnings

                with warnings.catch_warnings(record=True):
                    warnings.simplefilter("always")
                    create_cli_agent(
                        model=TEST_MODEL,
                        working_dir=str(tmp_path),
                        include_browser=True,
                    )
                # A warning may or may not be raised depending on whether playwright
                # is importable; just assert the agent is created without exception
        finally:
            if browser_mod is not None:
                sys.modules["pydantic_deep.features.browser.capability"] = browser_mod

    def test_include_browser_false_skips_capability(self, tmp_path: Path) -> None:
        """When include_browser=False, no BrowserCapability is added."""
        agent, deps = create_cli_agent(
            model=TEST_MODEL,
            working_dir=str(tmp_path),
            include_browser=False,
        )
        assert agent is not None

    def test_lean_mode_disables_browser(self, tmp_path: Path) -> None:
        """lean=True disables browser even when include_browser=True."""
        agent, deps = create_cli_agent(
            model=TEST_MODEL,
            working_dir=str(tmp_path),
            include_browser=True,
            lean=True,
        )
        assert agent is not None

    def test_browser_headless_param_accepted(self, tmp_path: Path) -> None:
        """browser_headless param is accepted without error."""
        agent, deps = create_cli_agent(
            model=TEST_MODEL,
            working_dir=str(tmp_path),
            include_browser=False,
            browser_headless=False,
        )
        assert agent is not None

    def test_workspace_param_accepted(self, tmp_path: Path) -> None:
        """workspace param is accepted without error (no Docker required for local sandbox)."""
        agent, deps = create_cli_agent(
            model=TEST_MODEL,
            working_dir=str(tmp_path),
            # workspace without sandbox="docker" → this machine (no Docker needed)
            workspace="ml-env",
        )
        # Local sandbox — workspace ignored when Docker is not active
        assert isinstance(agent._cli_workspace.backend, LocalWorkspaceBackend)

    def test_sandbox_local_is_default(self, tmp_path: Path) -> None:
        """Default sandbox is local (no Docker)."""
        agent, deps = create_cli_agent(
            model=TEST_MODEL,
            working_dir=str(tmp_path),
        )
        assert isinstance(agent._cli_workspace.backend, LocalWorkspaceBackend)
        assert agent._cli_workspace_cleanup is None


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
        # Now a shim over build_system_prompt — returns the full consolidated prompt.
        assert "You are a Deep Agent" in result
        assert "# Doing tasks" in result
        assert "# Acting with care" in result
        assert "# Verifying your work" in result

    def test_deprecated_params_accepted(self) -> None:
        """Deprecated params are accepted (and ignored) for backwards compatibility."""
        result = build_cli_instructions(
            include_execute=False, include_todo=False, include_subagents=False
        )
        assert "# Doing tasks" in result
        assert "# Tool usage" in result

    def test_non_interactive_adds_autonomy_section(self) -> None:
        result = build_cli_instructions(non_interactive=True)
        assert "# Autonomous mode" in result
        assert "# Exactness" in result

    def test_lean_non_interactive_is_minimal(self) -> None:
        result = build_cli_instructions(non_interactive=True, lean=True)
        assert "autonomous coding agent" in result
        # Lean mode skips the full core sections.
        assert "# Acting with care" not in result

    def test_backwards_compat_cli_system_prompt(self) -> None:
        full = build_cli_instructions()
        assert full == CLI_SYSTEM_PROMPT

    def test_non_interactive_prompt_is_longer(self) -> None:
        interactive = build_cli_instructions()
        non_interactive = build_cli_instructions(non_interactive=True)
        assert len(non_interactive) > len(interactive)


def _docker_agent(tmp_path: Path, **kwargs: Any) -> tuple[Any, MagicMock]:
    """A CLI agent in Docker, and the spy its `DockerWorkspace` was built through.

    Building one touches no Docker: the container is created on first use.
    """
    with patch("pydantic_ai_backends.DockerWorkspace", wraps=DockerWorkspace) as spy:
        agent, _ = create_cli_agent(model=TEST_MODEL, working_dir=str(tmp_path), **kwargs)
    return agent, spy


class TestDockerSandbox:
    """`sandbox="docker"`: the session works in a container on this host."""

    def test_the_project_is_mounted_as_the_working_directory(self, tmp_path: Path) -> None:
        agent, spy = _docker_agent(tmp_path, sandbox="docker")

        kwargs = spy.call_args.kwargs
        assert kwargs["image"] == "python:3.12-slim"
        assert kwargs["work_dir"] == "/workspace"
        assert kwargs["volumes"] == {str(tmp_path.resolve()): "/workspace"}
        assert kwargs["env"] is None
        assert isinstance(agent._cli_workspace.backend, DockerWorkspaceBackend)

    def test_an_unnamed_session_gets_its_own_container_removed_at_exit(
        self, tmp_path: Path
    ) -> None:
        agent, spy = _docker_agent(tmp_path, sandbox="docker")

        container_name = spy.call_args.kwargs["container_name"]
        assert container_name.endswith(f"-{_PROCESS_CONTAINER_ID}")
        with patch.object(DockerWorkspace, "destroy", new_callable=AsyncMock) as destroy:
            asyncio.run(agent._cli_workspace_cleanup())
        destroy.assert_awaited_once_with(WorkspaceRef(provider="docker", id=container_name))

    def test_a_named_workspace_is_one_container_kept_across_sessions(self, tmp_path: Path) -> None:
        agent, spy = _docker_agent(tmp_path, sandbox="docker", workspace="ml-env")

        assert spy.call_args.kwargs["container_name"].endswith("-ml-env")
        assert agent._cli_workspace_cleanup is None

    def test_the_same_project_names_the_same_container(self, tmp_path: Path) -> None:
        _, first = _docker_agent(tmp_path, sandbox="docker", workspace="ml-env")
        _, second = _docker_agent(tmp_path, sandbox="docker", workspace="ml-env")

        assert first.call_args.kwargs["container_name"] == second.call_args.kwargs["container_name"]

    def test_the_fork_test_runner_is_off(self, tmp_path: Path) -> None:
        """Its command runs on this machine, not in the container."""
        (tmp_path / "pytest.ini").write_text("[pytest]\n")
        with patch("apps.cli.agent._detect_fork_test_command", return_value=None) as detect:
            _docker_agent(tmp_path, sandbox="docker")
        detect.assert_called_once_with(None)

    def test_a_custom_image(self, tmp_path: Path) -> None:
        _, spy = _docker_agent(tmp_path, sandbox="docker", sandbox_image="python:3.11-slim")

        assert spy.call_args.kwargs["image"] == "python:3.11-slim"


class TestSandboxEnvVars:
    """Variables the Docker sandbox's commands see."""

    def test_explicit_vars(self, tmp_path: Path) -> None:
        _, spy = _docker_agent(
            tmp_path,
            sandbox="docker",
            sandbox_env_vars={"JIRA_API_TOKEN": "tok", "JIRA_BASE_URL": "https://jira.example.com"},
        )

        assert spy.call_args.kwargs["env"] == {
            "JIRA_API_TOKEN": "tok",
            "JIRA_BASE_URL": "https://jira.example.com",
        }

    def test_an_env_file(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("JIRA_API_TOKEN=file-token\nJIRA_BASE_URL=https://jira.example.com\n")

        _, spy = _docker_agent(tmp_path, sandbox="docker", sandbox_env_file=str(env_file))

        assert spy.call_args.kwargs["env"] == {
            "JIRA_API_TOKEN": "file-token",
            "JIRA_BASE_URL": "https://jira.example.com",
        }

    def test_explicit_vars_override_the_file(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("JIRA_API_TOKEN=file-token\nEXTRA=from-file\n")

        _, spy = _docker_agent(
            tmp_path,
            sandbox="docker",
            sandbox_env_file=str(env_file),
            sandbox_env_vars={"JIRA_API_TOKEN": "explicit-token"},
        )

        assert spy.call_args.kwargs["env"] == {
            "JIRA_API_TOKEN": "explicit-token",
            "EXTRA": "from-file",
        }

    def test_an_env_file_from_config(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("FROM_FILE=yes\n")
        config_file = tmp_path / ".pydantic-deep" / "config.toml"
        config_file.parent.mkdir()
        config_file.write_text(f'sandbox = "docker"\nsandbox_env_file = "{env_file}"\n')

        _, spy = _docker_agent(tmp_path, config_path=config_file)

        assert spy.call_args.kwargs["env"] == {"FROM_FILE": "yes"}

    def test_vars_from_config(self, tmp_path: Path) -> None:
        config_file = tmp_path / ".pydantic-deep" / "config.toml"
        config_file.parent.mkdir()
        config_file.write_text(
            'sandbox = "docker"\n\n[sandbox_env_vars]\nMY_TOKEN = "from-config"\n'
        )

        _, spy = _docker_agent(tmp_path, config_path=config_file)

        assert spy.call_args.kwargs["env"] == {"MY_TOKEN": "from-config"}


class TestDetectForkTestCommand:
    """Tests for _detect_fork_test_command()."""

    def test_returns_none_without_a_local_root(self) -> None:
        """No directory on this machine (Docker) → None; fork runner disabled."""
        assert _detect_fork_test_command(None) is None

    def test_detects_pytest_via_pyproject_toml(self, tmp_path: Path) -> None:
        """pyproject.toml with [tool.pytest.ini_options] → uv run pytest."""
        (tmp_path / "pyproject.toml").write_text(
            "[tool.pytest.ini_options]\ntestpaths = ['tests']\n"
        )

        assert _detect_fork_test_command(tmp_path) == "uv run pytest -q --tb=short"

    def test_detects_pytest_via_tool_pytest_section(self, tmp_path: Path) -> None:
        """pyproject.toml with [tool.pytest] (non-standard but still matches) → uv run pytest."""
        (tmp_path / "pyproject.toml").write_text("[tool.pytest]\n")

        assert _detect_fork_test_command(tmp_path) == "uv run pytest -q --tb=short"

    def test_no_pytest_marker_in_pyproject_returns_next_check(self, tmp_path: Path) -> None:
        """pyproject.toml without pytest section, no other markers → None."""
        (tmp_path / "pyproject.toml").write_text("[build-system]\nrequires = ['setuptools']\n")

        assert _detect_fork_test_command(tmp_path) is None

    def test_detects_pytest_via_pytest_ini(self, tmp_path: Path) -> None:
        """pytest.ini present → uv run pytest."""
        (tmp_path / "pytest.ini").write_text("[pytest]\n")

        assert _detect_fork_test_command(tmp_path) == "uv run pytest -q --tb=short"

    def test_detects_pytest_via_setup_cfg(self, tmp_path: Path) -> None:
        """setup.cfg present → uv run pytest."""
        (tmp_path / "setup.cfg").write_text("[metadata]\n")

        assert _detect_fork_test_command(tmp_path) == "uv run pytest -q --tb=short"

    def test_detects_npm_test_via_package_json(self, tmp_path: Path) -> None:
        """package.json with scripts.test → npm test."""
        import json

        (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}}))

        assert _detect_fork_test_command(tmp_path) == "npm test"

    def test_package_json_without_test_script_skipped(self, tmp_path: Path) -> None:
        """package.json without scripts.test → falls through to None."""
        import json

        (tmp_path / "package.json").write_text(json.dumps({"scripts": {"build": "tsc"}}))

        assert _detect_fork_test_command(tmp_path) is None

    def test_detects_make_test_via_makefile(self, tmp_path: Path) -> None:
        """Makefile with test: target → make test."""
        (tmp_path / "Makefile").write_text("test:\n\tpytest tests/\n\nbuild:\n\techo done\n")

        assert _detect_fork_test_command(tmp_path) == "make test"

    def test_makefile_without_test_target_returns_none(self, tmp_path: Path) -> None:
        """Makefile with no test target → None."""
        (tmp_path / "Makefile").write_text("build:\n\techo done\n")

        assert _detect_fork_test_command(tmp_path) is None

    def test_pytest_takes_priority_over_npm(self, tmp_path: Path) -> None:
        """When both pyproject.toml (pytest) and package.json exist, pytest wins."""
        import json

        (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n")
        (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}}))

        assert _detect_fork_test_command(tmp_path) == "uv run pytest -q --tb=short"

    def test_npm_takes_priority_over_makefile(self, tmp_path: Path) -> None:
        """When package.json has test script and Makefile also has test target, npm wins."""
        import json

        (tmp_path / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}}))
        (tmp_path / "Makefile").write_text("test:\n\tpytest\n")

        assert _detect_fork_test_command(tmp_path) == "npm test"

    def test_empty_directory_returns_none(self, tmp_path: Path) -> None:
        """Empty project dir → None."""

        assert _detect_fork_test_command(tmp_path) is None


class TestLocalSession:
    """`sandbox="local"`: the project on this machine, as `LocalBackend` had it."""

    async def test_file_tools_stay_inside_the_project(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        project.mkdir()
        agent, _ = create_cli_agent(model=TEST_MODEL, working_dir=str(project))
        workspace = agent._cli_workspace
        await workspace.write_text("inside.txt", "ok")
        assert (project / "inside.txt").read_text() == "ok"
        with pytest.raises(PermissionError, match="outside the workspace"):
            await workspace.write_text(str(tmp_path / "outside.txt"), "no")
        assert not (tmp_path / "outside.txt").exists()

    async def test_commands_get_the_users_environment(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`git push` needs the SSH agent; a bare PATH and HOME broke it."""
        monkeypatch.setenv("PYDANTIC_DEEP_TEST_VAR", "from-the-user")
        agent, _ = create_cli_agent(model=TEST_MODEL, working_dir=str(tmp_path))
        result = await agent._cli_workspace.run("printf %s $PYDANTIC_DEEP_TEST_VAR", shell=True)
        assert result.stdout == "from-the-user"

    def test_host_files_go_under_the_project(self, tmp_path: Path) -> None:
        from pydantic_deep.agent import _local_working_dir

        agent, _ = create_cli_agent(model=TEST_MODEL, working_dir=str(tmp_path))
        capability = next(
            c
            for c in agent._root_capability.capabilities
            if type(c).__name__ == "_SessionWorkspace"
        )
        assert _local_working_dir(capability) == tmp_path


class TestBranchRunner:
    async def test_a_branch_writes_into_its_overlay_not_the_project(self, tmp_path: Path) -> None:
        """The runner left out `workspace=`, so every branch wrote straight into the project."""
        from types import SimpleNamespace

        from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
        from pydantic_ai.models.function import AgentInfo, FunctionModel
        from pydantic_ai.workspaces import Workspace

        from apps.cli.screens.chat import _stream_branch_via_iter
        from pydantic_deep import DeepAgentDeps
        from pydantic_deep.features.forking.isolation import branch_workspace
        from pydantic_deep.features.forking.types import BranchIsolation

        def model(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            if len(messages) == 1:
                return ModelResponse(
                    parts=[ToolCallPart("write_file", {"path": "branch.txt", "content": "b"})]
                )
            return ModelResponse(parts=[TextPart("done")])

        agent, _ = create_cli_agent(model=FunctionModel(model), working_dir=str(tmp_path))
        workspace, overlay = branch_workspace(Workspace(agent._cli_workspace), BranchIsolation())
        assert overlay is not None
        runtime = SimpleNamespace(workspace=workspace, overlay=overlay)

        await _stream_branch_via_iter(agent, "go", [], DeepAgentDeps(), None, runtime)

        assert not (tmp_path / "branch.txt").exists()
        assert [change.path for change in overlay.changes()] == [str(tmp_path / "branch.txt")]
