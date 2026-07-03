"""Tests for the Harbor installed agent adapter."""

from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

# Stub Harbor modules before importing our adapter
# Harbor is not a dev dependency — we mock the entire package so
# the adapter module can be imported and tested without it.


def _install_harbor_stubs() -> tuple[type, type, type, Any]:
    """Create and register stub Harbor modules, return base classes."""

    class _BaseEnvironment:
        pass

    class _AgentContext:
        # Mirrors the real harbor AgentContext fields we populate.
        def __init__(self) -> None:
            self.n_input_tokens: int | None = None
            self.n_output_tokens: int | None = None
            self.n_cache_tokens: int | None = None
            self.cost_usd: float | None = None
            self.metadata: dict[str, Any] | None = None

    class _BaseInstalledAgent:
        model_name: str | None = None
        logs_dir: Path = Path("/tmp")
        _version: str | None = None

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def exec_as_root(self, environment: Any, command: str) -> None:
            pass

        async def exec_as_agent(
            self, environment: Any, command: str, env: dict[str, str] | None = None
        ) -> None:
            pass

    def with_prompt_template(fn: Any) -> Any:
        """No-op decorator stub."""
        return fn

    # Register stubs in sys.modules
    harbor_mod = types.ModuleType("harbor")
    harbor_agents = types.ModuleType("harbor.agents")
    harbor_agents_installed = types.ModuleType("harbor.agents.installed")
    harbor_agents_installed_base = types.ModuleType("harbor.agents.installed.base")
    harbor_environments = types.ModuleType("harbor.environments")
    harbor_environments_base = types.ModuleType("harbor.environments.base")
    harbor_models = types.ModuleType("harbor.models")
    harbor_models_agent = types.ModuleType("harbor.models.agent")
    harbor_models_agent_context = types.ModuleType("harbor.models.agent.context")

    harbor_agents_installed_base.BaseInstalledAgent = _BaseInstalledAgent  # type: ignore[attr-defined]
    harbor_agents_installed_base.with_prompt_template = with_prompt_template  # type: ignore[attr-defined]
    harbor_environments_base.BaseEnvironment = _BaseEnvironment  # type: ignore[attr-defined]
    harbor_models_agent_context.AgentContext = _AgentContext  # type: ignore[attr-defined]

    sys.modules["harbor"] = harbor_mod
    sys.modules["harbor.agents"] = harbor_agents
    sys.modules["harbor.agents.installed"] = harbor_agents_installed
    sys.modules["harbor.agents.installed.base"] = harbor_agents_installed_base
    sys.modules["harbor.environments"] = harbor_environments
    sys.modules["harbor.environments.base"] = harbor_environments_base
    sys.modules["harbor.models"] = harbor_models
    sys.modules["harbor.models.agent"] = harbor_models_agent
    sys.modules["harbor.models.agent.context"] = harbor_models_agent_context

    return _BaseInstalledAgent, _BaseEnvironment, _AgentContext, with_prompt_template


_BaseInstalledAgent, _BaseEnvironment, _AgentContext, _ = _install_harbor_stubs()

# Now safe to import (must be after stub registration)
from apps.harbor.agent import (  # noqa: E402
    PydanticDeepAgent,
    _build_install_script,
    _format_feature_flag,
    _trial_and_task,
    build_run_command,
    collect_env_vars,
    convert_model_name,
    parse_cost,
    parse_json_output,
)

# convert_model_name


class TestConvertModelName:
    def test_slash_to_colon(self) -> None:
        assert convert_model_name("anthropic/claude-opus-4-6") == "anthropic:claude-opus-4-6"

    def test_already_colon(self) -> None:
        assert convert_model_name("openai:gpt-5.4") == "openai:gpt-5.4"

    def test_bare_model(self) -> None:
        assert convert_model_name("gpt-5.4") == "gpt-5.4"

    def test_nested_slash(self) -> None:
        assert convert_model_name("openai/o3-2025-04-16") == "openai:o3-2025-04-16"

    def test_google_vertex_explicit(self) -> None:
        # Vertex → pydantic-ai `google-cloud:` provider.
        assert (
            convert_model_name("google/gemini-3.1-pro-preview", vertex=True)
            == "google-cloud:gemini-3.1-pro-preview"
        )

    def test_google_gla_explicit(self) -> None:
        # Developer API → pydantic-ai `google:` provider.
        assert (
            convert_model_name("gemini/gemini-3.1-pro-preview", vertex=False)
            == "google:gemini-3.1-pro-preview"
        )

    def test_vertex_prefix_always_vertex(self) -> None:
        assert convert_model_name("vertex/gemini-3.5-flash") == "google-cloud:gemini-3.5-flash"

    def test_google_cloud_prefix_passthrough(self) -> None:
        assert convert_model_name("google-cloud/gemini-3.1-pro-preview") == (
            "google-cloud:gemini-3.1-pro-preview"
        )

    def test_google_autodetect_vertex_from_env(self) -> None:
        with patch.dict(os.environ, {"GOOGLE_CLOUD_PROJECT": "vstorm-495409"}, clear=True):
            assert (
                convert_model_name("google/gemini-3.1-pro-preview")
                == "google-cloud:gemini-3.1-pro-preview"
            )

    def test_google_autodetect_gla_when_flag_false(self) -> None:
        with patch.dict(
            os.environ,
            {"GOOGLE_CLOUD_PROJECT": "p", "GOOGLE_GENAI_USE_VERTEXAI": "false"},
            clear=True,
        ):
            assert (
                convert_model_name("google/gemini-3.1-pro-preview")
                == "google:gemini-3.1-pro-preview"
            )


# collect_env_vars


class TestCollectEnvVars:
    def test_collects_present_vars(self) -> None:
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test", "OPENAI_API_KEY": "sk-oai"}):
            env = collect_env_vars()
        assert env["ANTHROPIC_API_KEY"] == "sk-test"
        assert env["OPENAI_API_KEY"] == "sk-oai"

    def test_skips_empty_vars(self) -> None:
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}, clear=True):
            env = collect_env_vars()
        assert "ANTHROPIC_API_KEY" not in env

    def test_dotenv_not_crash_when_unavailable(self) -> None:
        """collect_env_vars works even if dotenv import fails inside it."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-x"}, clear=True):
            env = collect_env_vars()
        assert env["ANTHROPIC_API_KEY"] == "sk-x"


# build_run_command


class TestBuildRunCommand:
    def test_basic_command(self) -> None:
        cmd = build_run_command(instruction="Fix the bug")
        # `--logfire` is a top-level flag and must precede the `run` subcommand.
        assert "pydantic-deep --logfire run" in cmd
        assert "--json" in cmd
        assert "'Fix the bug'" in cmd

    def test_logfire_can_be_disabled(self) -> None:
        cmd = build_run_command(instruction="Fix", logfire=False)
        assert "--logfire" not in cmd
        assert "pydantic-deep run" in cmd

    def test_gcp_creds_guard_present(self) -> None:
        cmd = build_run_command(instruction="Fix")
        assert "GCP_CREDS_B64" in cmd
        assert "GOOGLE_APPLICATION_CREDENTIALS" in cmd

    def test_with_model(self) -> None:
        cmd = build_run_command(instruction="Fix", model="anthropic:claude-opus-4-6")
        assert "--model" in cmd
        assert "anthropic:claude-opus-4-6" in cmd

    def test_with_max_turns(self) -> None:
        cmd = build_run_command(instruction="Fix", max_turns=50)
        assert "--max-turns 50" in cmd

    def test_with_timeout(self) -> None:
        cmd = build_run_command(instruction="Fix", timeout=300)
        assert "--timeout 300" in cmd

    def test_pipes_to_log(self) -> None:
        cmd = build_run_command(instruction="Fix")
        assert "tee /logs/agent/pydantic-deep.txt" in cmd

    def test_escapes_instruction(self) -> None:
        cmd = build_run_command(instruction="Fix the 'bug' in \"auth.py\"")
        # shlex.quote wraps in single quotes
        assert "'" in cmd

    def test_sets_path(self) -> None:
        cmd = build_run_command(instruction="Fix")
        assert "/opt/pydantic-deep-venv/bin" in cmd


# parse_json_output


class TestParseJsonOutput:
    def test_clean_json(self) -> None:
        data = {"output": "Done", "usage": {"total_tokens": 100, "requests": 3}}
        result = parse_json_output(json.dumps(data))
        assert result is not None
        assert result["output"] == "Done"
        assert result["usage"]["total_tokens"] == 100

    def test_json_with_prefix_logs(self) -> None:
        text = "WARNING: some log\n" + json.dumps(
            {"output": "Done", "usage": {"total_tokens": 50, "requests": 1}}
        )
        result = parse_json_output(text)
        assert result is not None
        assert result["output"] == "Done"

    def test_no_json(self) -> None:
        result = parse_json_output("Just plain text output")
        assert result is None

    def test_empty_string(self) -> None:
        result = parse_json_output("")
        assert result is None

    def test_nested_json(self) -> None:
        data = {
            "output": "Fixed the test",
            "usage": {
                "total_tokens": 1500,
                "request_tokens": 1200,
                "response_tokens": 300,
                "requests": 5,
            },
        }
        text = f"Some prefix log\n{json.dumps(data, indent=2)}\n"
        result = parse_json_output(text)
        assert result is not None
        assert result["usage"]["total_tokens"] == 1500


# parse_cost


class TestParseCost:
    def test_extracts_cost(self) -> None:
        assert parse_cost("Total Cost: $1.23") == 1.23

    def test_no_cost(self) -> None:
        assert parse_cost("No cost info here") is None

    def test_cost_integer(self) -> None:
        assert parse_cost("Cost: $5") == 5.0

    def test_cost_small(self) -> None:
        assert parse_cost("Cost: $0.0042") == 0.0042


# _build_install_script


class TestBuildInstallScript:
    def test_contains_uv_install(self) -> None:
        script = _build_install_script("main")
        assert "uv" in script
        assert "astral.sh" in script

    def test_contains_git_ref(self) -> None:
        script = _build_install_script("feat/benchmark")
        assert "feat/benchmark" in script

    def test_creates_venv(self) -> None:
        script = _build_install_script("main")
        assert "/opt/pydantic-deep-venv" in script

    def test_verifies_install(self) -> None:
        script = _build_install_script("main")
        assert "pydantic-deep --version" in script

    def test_creates_log_dir(self) -> None:
        script = _build_install_script("main")
        assert "mkdir -p /logs/agent" in script


# PydanticDeepAgent


class TestPydanticDeepAgent:
    def test_instantiation(self) -> None:
        agent = PydanticDeepAgent()
        assert agent._max_turns is None
        assert agent._timeout is None

    def test_instantiation_with_params(self) -> None:
        agent = PydanticDeepAgent(max_turns=50, timeout=300)
        assert agent._max_turns == 50
        assert agent._timeout == 300

    def test_browser_and_liteparse_default_off(self) -> None:
        # Their extras aren't installed in the container, so we force them off.
        agent = PydanticDeepAgent()
        assert agent._feature_flags["browser"] is False
        assert agent._feature_flags["liteparse"] is False
        cmd = build_run_command(instruction="x", feature_flags=agent._feature_flags)
        assert "--no-browser" in cmd
        assert "--no-liteparse" in cmd

    async def test_install(self) -> None:
        agent = PydanticDeepAgent()
        agent.exec_as_root = AsyncMock()
        env = MagicMock()

        await agent.install(env)

        agent.exec_as_root.assert_called_once()
        call_args = agent.exec_as_root.call_args
        script = call_args.kwargs.get(
            "command", call_args.args[1] if len(call_args.args) > 1 else ""
        )
        assert "pydantic-deep" in script

    async def test_install_custom_git_ref(self) -> None:
        agent = PydanticDeepAgent()
        agent.exec_as_root = AsyncMock()
        env = MagicMock()

        with patch.dict(os.environ, {"PYDANTIC_DEEP_GIT_REF": "feat/benchmark"}):
            await agent.install(env)

        call_args = agent.exec_as_root.call_args
        # command passed as keyword
        script = call_args.kwargs.get(
            "command", call_args.args[1] if len(call_args.args) > 1 else ""
        )
        assert "feat/benchmark" in script

    async def test_run(self) -> None:
        agent = PydanticDeepAgent(max_turns=25)
        agent.model_name = "anthropic/claude-opus-4-6"
        agent.exec_as_agent = AsyncMock()
        env = MagicMock()
        context = _AgentContext()

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}, clear=True):
            await agent.run("Fix the bug", env, context)

        agent.exec_as_agent.assert_called_once()
        call_kwargs = agent.exec_as_agent.call_args[1]
        assert "anthropic:claude-opus-4-6" in call_kwargs["command"]
        assert "--max-turns 25" in call_kwargs["command"]
        assert "ANTHROPIC_API_KEY" in call_kwargs["env"]

    async def test_run_no_model(self) -> None:
        agent = PydanticDeepAgent()
        agent.model_name = None
        agent.exec_as_agent = AsyncMock()
        with patch.dict(os.environ, {}, clear=True):
            await agent.run("Fix the bug", MagicMock(), _AgentContext())

        cmd = agent.exec_as_agent.call_args[1]["command"]
        assert "--model" not in cmd

    def test_populate_context_no_log(self, tmp_path: Path) -> None:
        agent = PydanticDeepAgent()
        agent.logs_dir = tmp_path
        context = _AgentContext()

        agent.populate_context_post_run(context)
        assert context.cost_usd is None

    def test_populate_context_with_json(self, tmp_path: Path) -> None:
        agent = PydanticDeepAgent()
        log_dir = tmp_path / "command-0"
        log_dir.mkdir(parents=True)
        agent.logs_dir = tmp_path
        data = {
            "output": "Done",
            "usage": {
                "total_tokens": 5000,
                "request_tokens": 4000,
                "response_tokens": 1000,
                "requests": 10,
            },
        }
        (log_dir / "stdout.txt").write_text(json.dumps(data))

        context = _AgentContext()
        agent.populate_context_post_run(context)
        assert context.n_input_tokens == 4000
        assert context.n_output_tokens == 1000

    def test_populate_context_with_cost(self, tmp_path: Path) -> None:
        agent = PydanticDeepAgent()
        log_dir = tmp_path / "command-0"
        log_dir.mkdir(parents=True)
        agent.logs_dir = tmp_path
        (log_dir / "stdout.txt").write_text("Result done.\nCost: $0.42\n")

        context = _AgentContext()
        agent.populate_context_post_run(context)
        assert context.cost_usd == 0.42

    def test_populate_context_no_parseable(self, tmp_path: Path) -> None:
        agent = PydanticDeepAgent()
        log_dir = tmp_path / "command-0"
        log_dir.mkdir(parents=True)
        agent.logs_dir = tmp_path
        (log_dir / "stdout.txt").write_text("Just plain text, no JSON or cost.")

        context = _AgentContext()
        agent.populate_context_post_run(context)
        assert context.cost_usd is None
        assert context.n_input_tokens is None

    def test_populate_context_prefers_tee_file(self, tmp_path: Path) -> None:
        # Our own tee'd file wins over Harbor's command capture.
        agent = PydanticDeepAgent()
        agent.logs_dir = tmp_path
        data = {"output": "Done", "usage": {"request_tokens": 7, "response_tokens": 3}}
        (tmp_path / "pydantic-deep.txt").write_text(json.dumps(data))

        context = _AgentContext()
        agent.populate_context_post_run(context)
        assert context.n_input_tokens == 7
        assert context.n_output_tokens == 3


class TestTrialAndTask:
    def test_from_session_id(self) -> None:
        # Harbor sets session_id = f"{trial_name}__agent".
        trial, task = _trial_and_task("sparql-university__Ab3Xy9q__agent", None)
        assert trial == "sparql-university__Ab3Xy9q"
        assert task == "sparql-university"

    def test_from_logs_dir(self) -> None:
        trial, task = _trial_and_task(None, Path("/runs/job1/hello-world__Zz9Qw2p/agent"))
        assert trial == "hello-world__Zz9Qw2p"
        assert task == "hello-world"

    def test_session_id_wins_over_logs_dir(self) -> None:
        trial, task = _trial_and_task("real-task__Uuu1234__agent", Path("/x/other__Vvv/agent"))
        assert trial == "real-task__Uuu1234"
        assert task == "real-task"

    def test_task_name_with_double_underscore_preserved(self) -> None:
        # Only the trailing __<uuid> is stripped; task names keep inner "__".
        trial, task = _trial_and_task("foo__bar__Uuu1234__agent", None)
        assert task == "foo__bar"

    def test_none_when_no_identifiers(self) -> None:
        assert _trial_and_task(None, None) == (None, None)

    async def test_run_with_feature_flags(self) -> None:
        agent = PydanticDeepAgent(
            web_search="false",
            web_fetch="false",
            memory="false",
            thinking="minimal",
        )
        agent.model_name = "anthropic/claude-opus-4-6"
        agent.exec_as_agent = AsyncMock()
        with patch.dict(os.environ, {}, clear=True):
            await agent.run("Fix bug", MagicMock(), _AgentContext())

        cmd = agent.exec_as_agent.call_args[1]["command"]
        assert "--no-web-search" in cmd
        assert "--no-web-fetch" in cmd
        assert "--no-memory" in cmd
        assert "--thinking minimal" in cmd


class TestFormatFeatureFlag:
    def test_bool_true(self) -> None:
        assert _format_feature_flag("web_search", True) == "--web-search"
        assert _format_feature_flag("web_search", "true") == "--web-search"

    def test_bool_false(self) -> None:
        assert _format_feature_flag("web_search", False) == "--no-web-search"
        assert _format_feature_flag("web_search", "false") == "--no-web-search"

    def test_underscore_to_dash(self) -> None:
        assert _format_feature_flag("web_fetch", False) == "--no-web-fetch"

    def test_browser_headless_uses_headed_for_false(self) -> None:
        # This flag's "off" form is --browser-headed, not --no-browser-headless.
        assert _format_feature_flag("browser_headless", True) == "--browser-headless"
        assert _format_feature_flag("browser_headless", False) == "--browser-headed"

    def test_thinking(self) -> None:
        assert _format_feature_flag("thinking", "high") == "--thinking high"
        assert _format_feature_flag("thinking", "false") == "--thinking false"

    def test_temperature(self) -> None:
        assert _format_feature_flag("temperature", 0.5) == "--temperature 0.5"
        assert _format_feature_flag("temperature", "0.0") == "--temperature 0.0"

    def test_sandbox_and_workspace(self) -> None:
        assert _format_feature_flag("sandbox", "docker") == "--sandbox docker"
        assert _format_feature_flag("workspace", "ml-env") == "--workspace ml-env"

    def test_value_flag_is_shell_quoted(self) -> None:
        assert _format_feature_flag("workspace", "my env") == "--workspace 'my env'"

    def test_all_bool_flags(self) -> None:
        for flag in ["todo", "subagents", "skills", "plan", "memory", "teams", "context"]:
            assert _format_feature_flag(flag, True) == f"--{flag}"
            assert _format_feature_flag(flag, False) == f"--no-{flag}"


class TestFeatureCoverage:
    """Guard: the adapter must forward every agent feature the CLI exposes.

    Mirrors the feature options of `pydantic-deep run` (apps/cli/main.py). If a
    new CLI feature is added, update this set and the flag tables together.
    """

    EXPECTED = frozenset(
        {
            "web_search",
            "web_fetch",
            "thinking",
            "todo",
            "subagents",
            "skills",
            "plan",
            "memory",
            "teams",
            "context",
            "temperature",
            "sandbox",
            "workspace",
            "browser",
            "browser_headless",
            "liteparse",
        }
    )

    def test_constructor_exposes_every_feature(self) -> None:
        assert set(PydanticDeepAgent()._feature_flags) == self.EXPECTED

    def test_flag_tables_cover_every_feature(self) -> None:
        from apps.harbor.agent import _BOOL_FLAGS, _VALUE_FLAGS

        assert set(_BOOL_FLAGS) | set(_VALUE_FLAGS) == self.EXPECTED

    def test_matches_cli_run_signature(self) -> None:
        # Cross-check against the real CLI so drift is caught at the source.
        import inspect

        from apps.cli.main import run as cli_run

        cli_params = set(inspect.signature(cli_run).parameters)
        # Operational params handled outside _feature_flags.
        operational = {
            "task",
            "task_file",
            "working_dir",
            "model",
            "output_json",
            "max_turns",
            "timeout",
            "verbose",
        }
        # CLI uses `include_*` prefixes and `context_discovery`; normalize to our
        # short feature names.
        normalized = {
            p.replace("include_", "").replace("context_discovery", "context")
            for p in cli_params
            if p not in operational
        }
        assert normalized == self.EXPECTED
