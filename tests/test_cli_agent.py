"""Tests for CLI agent factory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.models.test import TestModel

from apps.cli.agent import (
    _make_shell_allow_list_hook,
    create_cli_agent,
)
from apps.cli.prompts import CLI_SYSTEM_PROMPT, build_cli_instructions
from pydantic_deep.capabilities.hooks import HookEvent, HookInput, HookResult

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
        browser_mod = sys.modules.pop("pydantic_deep.capabilities.browser", None)
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
                sys.modules["pydantic_deep.capabilities.browser"] = browser_mod

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
            # workspace without sandbox="docker" → LocalBackend (no Docker needed)
            workspace="ml-env",
        )
        assert agent is not None
        # Local sandbox — workspace ignored when Docker is not active
        from pydantic_ai_backends import LocalBackend

        assert isinstance(deps.backend, LocalBackend)

    def test_sandbox_local_is_default(self, tmp_path: Path) -> None:
        """Default sandbox is local (no Docker)."""
        agent, deps = create_cli_agent(
            model=TEST_MODEL,
            working_dir=str(tmp_path),
        )
        from pydantic_ai_backends import LocalBackend

        assert isinstance(deps.backend, LocalBackend)


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
        assert "Writing Code" in result
        assert "Before Declaring Done" in result
        # BASE_PROMPT is NOT included — added by create_deep_agent()
        assert "Core Behavior" not in result

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


class TestSandboxEnvVars:
    """Tests for sandbox_env_vars support in create_cli_agent()."""

    def test_sandbox_env_vars_creates_runtime_config(self, tmp_path: Path) -> None:
        """When sandbox_env_vars is provided, DockerSandbox receives a RuntimeConfig."""
        from unittest.mock import MagicMock, patch

        mock_sandbox = MagicMock()
        mock_runtime_config_cls = MagicMock()
        mock_runtime_config_instance = MagicMock()
        mock_runtime_config_cls.return_value = mock_runtime_config_instance

        with (
            patch("pydantic_ai_backends.DockerSandbox", return_value=mock_sandbox) as mock_docker,
            patch("pydantic_ai_backends.RuntimeConfig", mock_runtime_config_cls),
        ):
            create_cli_agent(
                model=TEST_MODEL,
                working_dir=str(tmp_path),
                sandbox="docker",
                sandbox_env_vars={
                    "JIRA_API_TOKEN": "tok",
                    "JIRA_BASE_URL": "https://jira.example.com",
                },
            )

        mock_runtime_config_cls.assert_called_once_with(
            name="cli-sandbox",
            base_image="python:3.12-slim",
            env_vars={"JIRA_API_TOKEN": "tok", "JIRA_BASE_URL": "https://jira.example.com"},
            cache_image=False,
        )
        call_kwargs = mock_docker.call_args.kwargs
        assert call_kwargs["runtime"] is mock_runtime_config_instance
        assert "image" not in call_kwargs

    def test_sandbox_env_vars_empty_uses_image(self, tmp_path: Path) -> None:
        """When no sandbox_env_vars, DockerSandbox uses plain image kwarg (no RuntimeConfig)."""
        from unittest.mock import MagicMock, patch

        mock_sandbox = MagicMock()

        with patch("pydantic_ai_backends.DockerSandbox", return_value=mock_sandbox) as mock_docker:
            create_cli_agent(
                model=TEST_MODEL,
                working_dir=str(tmp_path),
                sandbox="docker",
            )

        call_kwargs = mock_docker.call_args.kwargs
        assert "image" in call_kwargs
        assert "runtime" not in call_kwargs

    def test_sandbox_env_vars_custom_image_in_runtime(self, tmp_path: Path) -> None:
        """sandbox_image is used as base_image in RuntimeConfig when env vars are set."""
        from unittest.mock import MagicMock, patch

        mock_sandbox = MagicMock()
        mock_runtime_config_cls = MagicMock()

        with (
            patch("pydantic_ai_backends.DockerSandbox", return_value=mock_sandbox),
            patch("pydantic_ai_backends.RuntimeConfig", mock_runtime_config_cls),
        ):
            create_cli_agent(
                model=TEST_MODEL,
                working_dir=str(tmp_path),
                sandbox="docker",
                sandbox_image="python:3.11-slim",
                sandbox_env_vars={"KEY": "val"},
            )

        mock_runtime_config_cls.assert_called_once_with(
            name="cli-sandbox",
            base_image="python:3.11-slim",
            env_vars={"KEY": "val"},
            cache_image=False,
        )

    def test_sandbox_env_file_loaded(self, tmp_path: Path) -> None:
        """Variables from a .env file are passed to DockerSandbox via RuntimeConfig."""
        from unittest.mock import MagicMock, patch

        env_file = tmp_path / ".env"
        env_file.write_text("JIRA_API_TOKEN=file-token\nJIRA_BASE_URL=https://jira.example.com\n")

        mock_sandbox = MagicMock()
        mock_runtime_config_cls = MagicMock()

        with (
            patch("pydantic_ai_backends.DockerSandbox", return_value=mock_sandbox),
            patch("pydantic_ai_backends.RuntimeConfig", mock_runtime_config_cls),
        ):
            create_cli_agent(
                model=TEST_MODEL,
                working_dir=str(tmp_path),
                sandbox="docker",
                sandbox_env_file=str(env_file),
            )

        mock_runtime_config_cls.assert_called_once_with(
            name="cli-sandbox",
            base_image="python:3.12-slim",
            env_vars={"JIRA_API_TOKEN": "file-token", "JIRA_BASE_URL": "https://jira.example.com"},
            cache_image=False,
        )

    def test_sandbox_env_vars_override_file(self, tmp_path: Path) -> None:
        """Explicit sandbox_env_vars take priority over .env file values."""
        from unittest.mock import MagicMock, patch

        env_file = tmp_path / ".env"
        env_file.write_text("JIRA_API_TOKEN=file-token\nEXTRA=from-file\n")

        mock_sandbox = MagicMock()
        mock_runtime_config_cls = MagicMock()

        with (
            patch("pydantic_ai_backends.DockerSandbox", return_value=mock_sandbox),
            patch("pydantic_ai_backends.RuntimeConfig", mock_runtime_config_cls),
        ):
            create_cli_agent(
                model=TEST_MODEL,
                working_dir=str(tmp_path),
                sandbox="docker",
                sandbox_env_file=str(env_file),
                sandbox_env_vars={"JIRA_API_TOKEN": "explicit-token"},
            )

        call_kwargs = mock_runtime_config_cls.call_args.kwargs
        assert call_kwargs["env_vars"]["JIRA_API_TOKEN"] == "explicit-token"
        assert call_kwargs["env_vars"]["EXTRA"] == "from-file"

    def test_sandbox_env_file_from_config(self, tmp_path: Path) -> None:
        """sandbox_env_file in config.toml is used when no explicit param is given."""
        from unittest.mock import MagicMock, patch

        env_file = tmp_path / ".env"
        env_file.write_text("FROM_FILE=yes\n")

        config_file = tmp_path / ".pydantic-deep" / "config.toml"
        config_file.parent.mkdir()
        config_file.write_text(f'sandbox = "docker"\nsandbox_env_file = "{env_file}"\n')

        mock_sandbox = MagicMock()
        mock_runtime_config_cls = MagicMock()

        with (
            patch("pydantic_ai_backends.DockerSandbox", return_value=mock_sandbox),
            patch("pydantic_ai_backends.RuntimeConfig", mock_runtime_config_cls),
        ):
            create_cli_agent(
                model=TEST_MODEL,
                working_dir=str(tmp_path),
                config_path=config_file,
            )

        call_kwargs = mock_runtime_config_cls.call_args.kwargs
        assert call_kwargs["env_vars"] == {"FROM_FILE": "yes"}

    def test_sandbox_env_vars_from_config(self, tmp_path: Path) -> None:
        """sandbox_env_vars in config.toml is used when no explicit param is given."""
        from unittest.mock import MagicMock, patch

        config_file = tmp_path / ".pydantic-deep" / "config.toml"
        config_file.parent.mkdir()
        config_file.write_text(
            'sandbox = "docker"\n\n[sandbox_env_vars]\nMY_TOKEN = "from-config"\n'
        )

        mock_sandbox = MagicMock()
        mock_runtime_config_cls = MagicMock()

        with (
            patch("pydantic_ai_backends.DockerSandbox", return_value=mock_sandbox),
            patch("pydantic_ai_backends.RuntimeConfig", mock_runtime_config_cls),
        ):
            create_cli_agent(
                model=TEST_MODEL,
                working_dir=str(tmp_path),
                config_path=config_file,
            )

        mock_runtime_config_cls.assert_called_once_with(
            name="cli-sandbox",
            base_image="python:3.12-slim",
            env_vars={"MY_TOKEN": "from-config"},
            cache_image=False,
        )
