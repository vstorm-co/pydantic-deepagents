"""Tests for OpenAI-compatible local model support in the CLI (issue #175)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.models.openai import OpenAIChatModel

from apps.cli.agent import create_cli_agent
from apps.cli.app import DeepApp
from apps.cli.config import CliConfig
from apps.cli.model_resolve import resolve_cli_model, resolve_openai_compatible_model
from apps.cli.providers import OPENAI_COMPATIBLE_PREFIX, PROVIDER_DEFAULT_MODELS, PROVIDERS


def _patch_load_config(monkeypatch: pytest.MonkeyPatch, config: CliConfig) -> None:
    """Pin the config every on-demand `load_config()` call sees.

    `model_resolve` binds the name at import time, so patching only
    `apps.cli.config.load_config` would miss it.
    """
    monkeypatch.setattr("apps.cli.config.load_config", lambda *_a, **_k: config)
    monkeypatch.setattr("apps.cli.model_resolve.load_config", lambda *_a, **_k: config)


class TestProviderTable:
    def test_openai_compatible_entry_present(self) -> None:
        entry = next(p for p in PROVIDERS if p.id == "openai-compatible")
        assert entry.env_var == ""  # keyless
        assert entry.default_model.startswith(OPENAI_COMPATIBLE_PREFIX)

    def test_default_models_includes_openai_compatible(self) -> None:
        assert PROVIDER_DEFAULT_MODELS["openai-compatible"].startswith(OPENAI_COMPATIBLE_PREFIX)

    def test_prefix_constant(self) -> None:
        assert OPENAI_COMPATIBLE_PREFIX == "openai-compatible:"


class TestResolveOpenAICompatibleModel:
    def test_happy_path_builds_openai_chat_model(self) -> None:
        cfg = CliConfig(base_url="http://localhost:8080/v1")
        model = resolve_openai_compatible_model("openai-compatible:qwen2.5", cfg)
        assert isinstance(model, OpenAIChatModel)
        assert model.model_name == "qwen2.5"
        # The whole point of the feature: the configured endpoint is what the
        # client talks to.
        assert str(model.base_url) == "http://localhost:8080/v1/"

    def test_empty_name_defaults_to_local_model(self) -> None:
        cfg = CliConfig(base_url="http://localhost:8080/v1")
        model = resolve_openai_compatible_model("openai-compatible:", cfg)
        assert model.model_name == "local-model"

    def test_missing_base_url_raises(self) -> None:
        with pytest.raises(ValueError, match="No base_url"):
            resolve_openai_compatible_model("openai-compatible:x", CliConfig())

    def test_api_key_read_from_keystore_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "lm-studio")
        cfg = CliConfig(base_url="http://localhost:1234/v1")
        model = resolve_openai_compatible_model("openai-compatible:phi", cfg)
        assert model.client.api_key == "lm-studio"

    def test_no_api_key_uses_noop_never_the_openai_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("OPENAI_COMPATIBLE_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-the-users-real-openai-key")
        cfg = CliConfig(base_url="http://localhost:1234/v1")
        model = resolve_openai_compatible_model("openai-compatible:phi", cfg)
        # `OpenAIProvider` would fall back to OPENAI_API_KEY if we passed none;
        # the user's real key must never be sent to an arbitrary endpoint.
        assert model.client.api_key == "sk-noop"


class TestResolveCliModel:
    def test_plain_model_string_passes_through(self) -> None:
        assert resolve_cli_model("anthropic:claude-sonnet-4-6") == "anthropic:claude-sonnet-4-6"

    def test_ollama_is_not_treated_as_local_endpoint(self) -> None:
        assert resolve_cli_model("ollama:llama3.3") == "ollama:llama3.3"

    def test_sentinel_is_converted(self) -> None:
        cfg = CliConfig(base_url="http://localhost:8080/v1")
        model = resolve_cli_model("openai-compatible:qwen2.5", cfg)
        assert isinstance(model, OpenAIChatModel)
        assert model.model_name == "qwen2.5"

    def test_config_is_loaded_on_demand_when_omitted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_load_config(monkeypatch, CliConfig(base_url="http://localhost:9999/v1"))
        model = resolve_cli_model("openai-compatible:phi")
        assert isinstance(model, OpenAIChatModel)
        assert str(model.base_url) == "http://localhost:9999/v1/"


class _StopBuild(Exception):
    """Short-circuits create_cli_agent right after the model is resolved."""


class TestCreateCliAgentLocalModel:
    def _write_config(self, tmp_path: Path, body: str) -> Path:
        cfg = tmp_path / "config.toml"
        cfg.write_text(body)
        return cfg

    def _capture_agent_kwargs(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        model: str,
        tmp_path: Path,
        config_body: str,
    ) -> dict[str, object]:
        import apps.cli.agent as agent_mod

        captured: dict[str, object] = {}

        def spy(*_args: object, **kwargs: object) -> object:
            captured.update(kwargs)
            raise _StopBuild

        monkeypatch.setattr(agent_mod, "create_deep_agent", spy)
        with pytest.raises(_StopBuild):
            create_cli_agent(
                model=model,
                working_dir=str(tmp_path),
                config_path=self._write_config(tmp_path, config_body),
            )
        return captured

    def test_prefix_model_is_converted_to_instance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        kwargs = self._capture_agent_kwargs(
            monkeypatch,
            model="openai-compatible:qwen2.5",
            tmp_path=tmp_path,
            config_body='base_url = "http://localhost:8080/v1"\n',
        )
        model = kwargs["model"]
        assert isinstance(model, OpenAIChatModel)
        assert model.model_name == "qwen2.5"

    def test_plain_string_model_not_converted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        kwargs = self._capture_agent_kwargs(
            monkeypatch,
            model="anthropic:claude-sonnet-4-6",
            tmp_path=tmp_path,
            config_body="",
        )
        assert kwargs["model"] == "anthropic:claude-sonnet-4-6"

    def test_prefix_fallback_model_is_converted_too(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A local endpoint is as valid a fallback as it is a primary — passing
        the raw sentinel through would crash in `infer_model`."""
        kwargs = self._capture_agent_kwargs(
            monkeypatch,
            model="anthropic:claude-sonnet-4-6",
            tmp_path=tmp_path,
            config_body=(
                'base_url = "http://localhost:8080/v1"\n'
                'fallback_model = "openai-compatible:qwen2.5"\n'
            ),
        )
        fallback = kwargs["fallback_model"]
        assert isinstance(fallback, OpenAIChatModel)
        assert fallback.model_name == "qwen2.5"

    def test_no_fallback_stays_none(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        kwargs = self._capture_agent_kwargs(
            monkeypatch,
            model="anthropic:claude-sonnet-4-6",
            tmp_path=tmp_path,
            config_body="",
        )
        assert kwargs["fallback_model"] is None


class TestLocalEndpointModal:
    @pytest.fixture
    def app(self) -> DeepApp:
        return DeepApp(model="test", version="0.0.0")

    async def test_connect_persists_and_dismisses_with_model_string(
        self, app: DeepApp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from textual.widgets import Input

        from apps.cli.screens.onboarding import LocalEndpointModal

        saved: list[tuple[str, str]] = []
        monkeypatch.setattr(
            "apps.cli.config.set_config_value",
            lambda _p, k, v: saved.append((k, v)),
        )
        keys: list[tuple[str, str]] = []
        monkeypatch.setattr(
            "apps.cli.screens.onboarding.save_key",
            lambda k, v: keys.append((k, v)),
        )
        result: list[str | None] = []
        modal = LocalEndpointModal()
        async with app.run_test(size=(120, 40)) as pilot:
            await app.push_screen(modal, lambda r: result.append(r))
            await pilot.pause()
            modal.query_one("#local-url", Input).value = "http://localhost:8080/v1"
            modal.query_one("#local-model", Input).value = "qwen2.5"
            modal.query_one("#local-key", Input).value = "secret"
            modal._save_and_dismiss()
            await pilot.pause()
        assert result == ["openai-compatible:qwen2.5"]
        assert ("base_url", "http://localhost:8080/v1") in saved
        assert keys == [("OPENAI_COMPATIBLE_API_KEY", "secret")]
        assert not any(k == "local_api_key" for k, _v in saved)

    async def test_blank_model_name_defaults(
        self, app: DeepApp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from textual.widgets import Input

        from apps.cli.screens.onboarding import LocalEndpointModal

        monkeypatch.setattr("apps.cli.config.set_config_value", lambda _p, _k, _v: None)
        result: list[str | None] = []
        modal = LocalEndpointModal()
        async with app.run_test(size=(120, 40)) as pilot:
            await app.push_screen(modal, lambda r: result.append(r))
            await pilot.pause()
            modal.query_one("#local-url", Input).value = "http://localhost:8080/v1"
            modal._save_and_dismiss()
            await pilot.pause()
        assert result == ["openai-compatible:local-model"]

    async def test_schemeless_url_warns_and_stays_open(self, app: DeepApp) -> None:
        """`localhost:8080/v1` is what a llama.cpp log prints; without a scheme
        it only fails on the first message, deep inside httpx."""
        from textual.widgets import Input

        from apps.cli.screens.onboarding import LocalEndpointModal

        result: list[str | None] = []
        modal = LocalEndpointModal()
        async with app.run_test(size=(120, 40)) as pilot:
            await app.push_screen(modal, lambda r: result.append(r))
            await pilot.pause()
            modal.query_one("#local-url", Input).value = "localhost:8080/v1"
            modal._save_and_dismiss()
            await pilot.pause()
            assert result == []
            modal.action_cancel()
            await pilot.pause()
        assert result == [None]

    async def test_blank_url_warns_and_stays_open(self, app: DeepApp) -> None:
        from apps.cli.screens.onboarding import LocalEndpointModal

        result: list[str | None] = []
        modal = LocalEndpointModal()
        async with app.run_test(size=(120, 40)) as pilot:
            await app.push_screen(modal, lambda r: result.append(r))
            await pilot.pause()
            modal._save_and_dismiss()
            await pilot.pause()
            # Modal did not dismiss — no callback fired yet.
            assert result == []
            modal.action_cancel()
            await pilot.pause()
        assert result == [None]

    async def test_enter_submits_from_any_field(
        self, app: DeepApp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from textual.widgets import Input

        from apps.cli.screens.onboarding import LocalEndpointModal

        monkeypatch.setattr("apps.cli.config.set_config_value", lambda _p, _k, _v: None)
        result: list[str | None] = []
        modal = LocalEndpointModal()
        async with app.run_test(size=(120, 40)) as pilot:
            await app.push_screen(modal, lambda r: result.append(r))
            await pilot.pause()
            url_input = modal.query_one("#local-url", Input)
            url_input.value = "http://localhost:8080/v1"
            modal.on_input_submitted(Input.Submitted(url_input, url_input.value))
            await pilot.pause()
        assert result == ["openai-compatible:local-model"]


class TestProviderCommandRouting:
    @pytest.fixture
    def app(self) -> DeepApp:
        return DeepApp(model="test", version="0.0.0")

    async def test_openai_compatible_opens_local_endpoint_modal(
        self, app: DeepApp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from apps.cli.commands import _cmd_provider
        from apps.cli.screens.onboarding import LocalEndpointModal, ProviderPickerModal

        pushes: list[tuple[Any, Any]] = []
        reconfigured: list[str] = []
        monkeypatch.setattr(app, "reconfigure_agent", lambda model=None: reconfigured.append(model))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            # Patch after mount so the app's own initial screen push isn't captured.
            monkeypatch.setattr(
                app, "push_screen", lambda screen, cb=None: pushes.append((screen, cb))
            )
            await _cmd_provider(app, "")
            # First push: the provider picker. Drive its callback.
            screen0, cb0 = pushes[0]
            assert isinstance(screen0, ProviderPickerModal)
            await cb0("openai-compatible")
            # Second push: the local-endpoint modal. Drive its callback.
            screen1, cb1 = pushes[1]
            assert isinstance(screen1, LocalEndpointModal)
            await cb1("openai-compatible:qwen2.5")
        assert reconfigured == ["openai-compatible:qwen2.5"]

    async def test_openai_compatible_cancel_does_not_reconfigure(
        self, app: DeepApp, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from apps.cli.commands import _cmd_provider
        from apps.cli.screens.onboarding import LocalEndpointModal

        pushes: list[tuple[Any, Any]] = []
        reconfigured: list[str] = []
        monkeypatch.setattr(app, "reconfigure_agent", lambda model=None: reconfigured.append(model))
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            monkeypatch.setattr(
                app, "push_screen", lambda screen, cb=None: pushes.append((screen, cb))
            )
            await _cmd_provider(app, "")
            await pushes[0][1]("openai-compatible")
            screen1, cb1 = pushes[1]
            assert isinstance(screen1, LocalEndpointModal)
            await cb1(None)  # user cancelled the endpoint modal
        assert reconfigured == []


class TestOnboardingStatus:
    def test_openai_compatible_reported_ready(self) -> None:
        from apps.cli.screens.onboarding import _check_provider_status

        status = {pid: has_key for pid, _n, _e, has_key in _check_provider_status()}
        assert status["openai-compatible"] is True


class TestPickAvailableModel:
    """A keyless local model must survive an implicit reconfigure, not get
    swapped for a cloud default."""

    def test_openai_compatible_kept_without_openai_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from apps.cli.app import DeepApp

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
        assert (
            DeepApp._pick_available_model("openai-compatible:qwen2.5")
            == "openai-compatible:qwen2.5"
        )

    def test_ollama_kept_with_only_cloud_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from apps.cli.app import DeepApp

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
        assert DeepApp._pick_available_model("ollama:llama3.3") == "ollama:llama3.3"

    def test_keyed_model_without_key_still_falls_back(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from apps.cli.app import DeepApp

        for var in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GOOGLE_API_KEY"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        assert DeepApp._pick_available_model("anthropic:claude-sonnet-4-6").startswith("openai")


class TestReminderModelWiring:
    """The LLM reminder generator must receive the resolved model, not the raw
    `openai-compatible:...` string — at startup *and* on the live mode switch."""

    def test_build_reminder_config_accepts_model_instance(self) -> None:
        from apps.cli.reminder import _build_reminder_config
        from pydantic_deep.features.periodic_reminder import LLMReminderGenerator

        cfg = CliConfig(base_url="http://localhost:8080/v1")
        model = resolve_openai_compatible_model("openai-compatible:qwen2.5", cfg)
        reminder_cfg = _build_reminder_config(
            periodic_reminder=True,
            reminder_mode="llm",
            config=cfg,
            reminder_model=model,
        )
        assert isinstance(reminder_cfg.generator, LLMReminderGenerator)
        assert reminder_cfg.generator.model is model

    def test_build_reminder_config_resolves_a_raw_sentinel(self) -> None:
        from apps.cli.reminder import _build_reminder_config
        from pydantic_deep.features.periodic_reminder import LLMReminderGenerator

        cfg = CliConfig(model="openai-compatible:qwen2.5", base_url="http://localhost:8080/v1")
        reminder_cfg = _build_reminder_config(
            periodic_reminder=True, reminder_mode="llm", config=cfg
        )
        assert isinstance(reminder_cfg.generator, LLMReminderGenerator)
        assert isinstance(reminder_cfg.generator.model, OpenAIChatModel)

    def test_live_switch_resolves_the_apps_model_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`/remind llm` rebuilds the generator from `app.model_name`, which
        holds the raw CLI string."""
        from apps.cli.reminder import _resolve_reminder_model

        _patch_load_config(monkeypatch, CliConfig(base_url="http://localhost:8080/v1"))
        app = DeepApp(model="openai-compatible:qwen2.5", version="0.0.0")
        model = _resolve_reminder_model(app)
        assert isinstance(model, OpenAIChatModel)
        assert model.model_name == "qwen2.5"

    def test_live_switch_leaves_a_normal_model_alone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from apps.cli.reminder import _resolve_reminder_model

        _patch_load_config(monkeypatch, CliConfig())
        app = DeepApp(model="anthropic:claude-sonnet-4-6", version="0.0.0")
        assert _resolve_reminder_model(app) == "anthropic:claude-sonnet-4-6"


class TestGoalEvaluatorWiring:
    def test_goal_evaluator_gets_the_resolved_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without this the evaluator fails on every turn with
        "Evaluator error; continuing." and the goal never completes."""
        from apps.cli.goal import get_goal_evaluator

        _patch_load_config(monkeypatch, CliConfig(base_url="http://localhost:8080/v1"))
        app = DeepApp(model="openai-compatible:qwen2.5", version="0.0.0")
        evaluator = get_goal_evaluator(app)
        assert isinstance(evaluator.model, OpenAIChatModel)
        assert evaluator.model.model_name == "qwen2.5"


class TestCredentialRegistration:
    def test_local_endpoint_key_is_manageable(self) -> None:
        """`/provider` writes this key, so `keys list` / `keys set` / `/keys`
        must be able to see and change it."""
        from apps.cli.credentials import CREDENTIALS, find_credential

        cred = find_credential("OPENAI_COMPATIBLE_API_KEY")
        assert cred is not None
        assert cred in CREDENTIALS

    def test_local_endpoint_key_is_not_a_first_run_provider(self) -> None:
        """It must stay out of the key-first onboarding list: the provider needs
        a base URL, and picking it there would set a model with no endpoint."""
        from apps.cli.onboarding_cli import _provider_credentials

        assert all(c.env_var != "OPENAI_COMPATIBLE_API_KEY" for c in _provider_credentials())
