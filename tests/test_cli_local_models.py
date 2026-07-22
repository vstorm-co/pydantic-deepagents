"""Tests for OpenAI-compatible local model support in the CLI (issue #175)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic_ai.models.openai import OpenAIChatModel

from apps.cli.agent import _resolve_openai_compatible_model, create_cli_agent
from apps.cli.app import DeepApp
from apps.cli.config import CliConfig
from apps.cli.providers import OPENAI_COMPATIBLE_PREFIX, PROVIDER_DEFAULT_MODELS, PROVIDERS


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
        model = _resolve_openai_compatible_model("openai-compatible:qwen2.5", cfg)
        assert isinstance(model, OpenAIChatModel)
        assert model.model_name == "qwen2.5"

    def test_empty_name_defaults_to_local_model(self) -> None:
        cfg = CliConfig(base_url="http://localhost:8080/v1")
        model = _resolve_openai_compatible_model("openai-compatible:", cfg)
        assert model.model_name == "local-model"

    def test_missing_base_url_raises(self) -> None:
        with pytest.raises(ValueError, match="No base_url"):
            _resolve_openai_compatible_model("openai-compatible:x", CliConfig())

    def test_api_key_read_from_keystore_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_COMPATIBLE_API_KEY", "lm-studio")
        cfg = CliConfig(base_url="http://localhost:1234/v1")
        model = _resolve_openai_compatible_model("openai-compatible:phi", cfg)
        assert isinstance(model, OpenAIChatModel)

    def test_no_api_key_still_builds_with_noop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("OPENAI_COMPATIBLE_API_KEY", raising=False)
        cfg = CliConfig(base_url="http://localhost:1234/v1")
        model = _resolve_openai_compatible_model("openai-compatible:phi", cfg)
        assert isinstance(model, OpenAIChatModel)


class _StopBuild(Exception):
    """Short-circuits create_cli_agent right after the model is resolved."""


class TestCreateCliAgentLocalModel:
    def _write_config(self, tmp_path: Path, body: str) -> Path:
        cfg = tmp_path / "config.toml"
        cfg.write_text(body)
        return cfg

    def _capture_model_arg(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        model: str,
        tmp_path: Path,
        config_body: str,
    ) -> object:
        import apps.cli.agent as agent_mod

        captured: dict[str, object] = {}

        def spy(*_args: object, **kwargs: object) -> object:
            captured["model"] = kwargs.get("model")
            raise _StopBuild

        monkeypatch.setattr(agent_mod, "create_deep_agent", spy)
        with pytest.raises(_StopBuild):
            create_cli_agent(
                model=model,
                working_dir=str(tmp_path),
                config_path=self._write_config(tmp_path, config_body),
            )
        return captured["model"]

    def test_prefix_model_is_converted_to_instance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        model = self._capture_model_arg(
            monkeypatch,
            model="openai-compatible:qwen2.5",
            tmp_path=tmp_path,
            config_body='base_url = "http://localhost:8080/v1"\n',
        )
        assert isinstance(model, OpenAIChatModel)
        assert model.model_name == "qwen2.5"

    def test_plain_string_model_not_converted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        model = self._capture_model_arg(
            monkeypatch,
            model="anthropic:claude-sonnet-4-6",
            tmp_path=tmp_path,
            config_body="",
        )
        assert model == "anthropic:claude-sonnet-4-6"


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
    `openai-compatible:...` string."""

    def test_build_reminder_config_accepts_model_instance(self) -> None:
        from apps.cli.reminder import _build_reminder_config
        from pydantic_deep.features.periodic_reminder import LLMReminderGenerator

        cfg = CliConfig(base_url="http://localhost:8080/v1")
        model = _resolve_openai_compatible_model("openai-compatible:qwen2.5", cfg)
        reminder_cfg = _build_reminder_config(
            periodic_reminder=True,
            reminder_mode="llm",
            config=cfg,
            reminder_model=model,
        )
        assert isinstance(reminder_cfg.generator, LLMReminderGenerator)
        assert reminder_cfg.generator.model is model
