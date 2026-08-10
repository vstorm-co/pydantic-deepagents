"""Tests for the named OrcaRouter provider integration (providers, credentials,
model resolution, live catalogue, CLI command, picker and onboarding)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic_ai.models.openai import OpenAIChatModel
from typer.testing import CliRunner

from apps.cli.main import app
from apps.cli.model_resolve import (
    ORCAROUTER_BASE_URL,
    resolve_cli_model,
    resolve_orcarouter_model,
)
from apps.cli.providers import (
    ORCAROUTER_API_KEY_ENV,
    ORCAROUTER_PREFIX,
    PROVIDER_DEFAULT_MODELS,
    PROVIDERS,
)

runner = CliRunner()


class TestProviderTable:
    def test_orcarouter_entry_present(self) -> None:
        entry = next(p for p in PROVIDERS if p.id == "orcarouter")
        assert entry.name == "OrcaRouter"
        assert entry.env_var == ORCAROUTER_API_KEY_ENV
        assert entry.key_url == "https://www.orcarouter.ai"
        assert entry.default_model.startswith(ORCAROUTER_PREFIX)

    def test_default_models_includes_orcarouter(self) -> None:
        assert PROVIDER_DEFAULT_MODELS["orcarouter"].startswith(ORCAROUTER_PREFIX)

    def test_prefix_constant(self) -> None:
        assert ORCAROUTER_PREFIX == "orcarouter:"
        assert ORCAROUTER_API_KEY_ENV == "ORCAROUTER_API_KEY"


class TestResolveOrcarouterModel:
    def test_happy_path_builds_openai_chat_model(self) -> None:
        model = resolve_orcarouter_model("orcarouter:openai/gpt-5.5")
        assert isinstance(model, OpenAIChatModel)
        assert model.model_name == "openai/gpt-5.5"
        # The whole point: the client talks to the OrcaRouter gateway, fixed URL.
        assert str(model.base_url) == f"{ORCAROUTER_BASE_URL}/"

    def test_empty_name_defaults_to_auto_router(self) -> None:
        model = resolve_orcarouter_model("orcarouter:")
        assert model.model_name == "orcarouter/auto"

    def test_api_key_read_from_keystore_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(ORCAROUTER_API_KEY_ENV, "sk-orca-test")
        model = resolve_orcarouter_model("orcarouter:openai/gpt-5.5")
        assert model.client.api_key == "sk-orca-test"

    def test_no_api_key_uses_noop_never_the_openai_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv(ORCAROUTER_API_KEY_ENV, raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-the-users-real-openai-key")
        model = resolve_orcarouter_model("orcarouter:openai/gpt-5.5")
        # The user's real OpenAI key must never be sent to the OrcaRouter gateway.
        assert model.client.api_key == "sk-noop"


class TestResolveCliModel:
    def test_orcarouter_string_is_converted(self) -> None:
        model = resolve_cli_model("orcarouter:anthropic/claude-sonnet-4.6")
        assert isinstance(model, OpenAIChatModel)
        assert model.model_name == "anthropic/claude-sonnet-4.6"

    def test_plain_model_string_passes_through(self) -> None:
        assert resolve_cli_model("anthropic:claude-sonnet-4-6") == "anthropic:claude-sonnet-4-6"
        assert resolve_cli_model("openrouter:anthropic/claude-sonnet-4") == (
            "openrouter:anthropic/claude-sonnet-4"
        )

    def test_openai_compatible_sentinel_still_handled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from apps.cli.config import CliConfig

        monkeypatch.setattr("apps.cli.config.load_config", lambda *_a, **_k: CliConfig())
        monkeypatch.setattr(
            "apps.cli.model_resolve.load_config",
            lambda *_a, **_k: CliConfig(base_url="http://localhost:8080/v1"),
        )
        model = resolve_cli_model("openai-compatible:qwen2.5")
        assert isinstance(model, OpenAIChatModel)
        assert model.model_name == "qwen2.5"


class TestCredentialRegistration:
    def test_orcarouter_key_is_manageable(self) -> None:
        from apps.cli.credentials import CREDENTIALS, find_credential

        cred = find_credential(ORCAROUTER_API_KEY_ENV)
        assert cred is not None
        assert cred.provider_id == "orcarouter"
        assert cred in CREDENTIALS

    def test_orcarouter_is_a_first_run_provider(self) -> None:
        """OrcaRouter is a key-first provider: it must appear in onboarding."""
        from apps.cli.onboarding_cli import _provider_credentials

        assert any(c.env_var == ORCAROUTER_API_KEY_ENV for c in _provider_credentials())


class TestPickAvailableModel:
    def test_orcarouter_kept_when_key_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from apps.cli.app import DeepApp

        monkeypatch.setenv(ORCAROUTER_API_KEY_ENV, "sk-orca")
        for var in ("ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "OPENAI_API_KEY"):
            monkeypatch.delenv(var, raising=False)
        assert (
            DeepApp._pick_available_model("orcarouter:openai/gpt-5.5")
            == "orcarouter:openai/gpt-5.5"
        )

    def test_orcarouter_without_key_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from apps.cli.app import DeepApp

        for var in (ORCAROUTER_API_KEY_ENV, "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        assert DeepApp._pick_available_model("orcarouter:openai/gpt-5.5").startswith("openai")


class TestOrcaRouterParse:
    def test_parse(self) -> None:
        from apps.cli.orcarouter_models import parse_models

        payload = {
            "data": [
                {
                    "id": "openai/gpt-5.5",
                    "name": "GPT 5.5",
                    "context_length": 400000,
                    "pricing": {"prompt": "0.00000020", "completion": "0.00000080"},
                },
                {"name": "no id — skipped"},
                {"id": "deepseek/deepseek-v4-flash"},  # missing fields tolerated
            ]
        }
        models = parse_models(payload)
        assert len(models) == 2
        m = models[0]
        assert m.model_string == "orcarouter:openai/gpt-5.5"
        assert m.context_length == 400000
        assert m.prompt_price == pytest.approx(2e-7)
        assert models[1].context_length == 0  # tolerated default

    def test_parse_tolerates_non_dict_items(self) -> None:
        from apps.cli.orcarouter_models import parse_models

        assert parse_models({"data": ["junk", {"id": ""}, None]}) == []


class TestOrcaRouterCatalogue:
    @pytest.fixture
    def seed_dir(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
        monkeypatch.setattr("apps.cli.orcarouter_models.get_global_dir", lambda: tmp_path)
        return tmp_path

    def test_cache_path_under_global_dir(self, seed_dir: Path) -> None:
        from apps.cli.orcarouter_models import _cache_path

        assert _cache_path() == seed_dir / "cache" / "orcarouter_models.json"

    def test_read_cache_missing(self, seed_dir: Path) -> None:
        from apps.cli.orcarouter_models import _read_cache

        assert _read_cache(max_age=10**12) is None

    def test_read_cache_fresh(self, seed_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import json

        from apps.cli.orcarouter_models import _read_cache

        monkeypatch.setattr(
            "apps.cli.orcarouter_models.time", type("T", (), {"time": lambda: 1000.0})
        )
        (seed_dir / "cache").mkdir(parents=True)
        (seed_dir / "cache" / "orcarouter_models.json").write_text(
            json.dumps(
                {
                    "fetched_at": 1000.0,
                    "payload": {"data": [{"id": "openai/gpt-5.5", "context_length": 400000}]},
                }
            )
        )
        models = _read_cache(max_age=3600)
        assert models is not None and models[0].id == "openai/gpt-5.5"

    def test_read_cache_stale(self, seed_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import json

        from apps.cli.orcarouter_models import _read_cache

        monkeypatch.setattr(
            "apps.cli.orcarouter_models.time", type("T", (), {"time": lambda: 2000.0})
        )
        (seed_dir / "cache").mkdir(parents=True)
        (seed_dir / "cache" / "orcarouter_models.json").write_text(
            json.dumps({"fetched_at": 1000.0, "payload": {"data": []}})
        )
        assert _read_cache(max_age=600) is None

    def test_read_cache_corrupt(self, seed_dir: Path) -> None:
        from apps.cli.orcarouter_models import _read_cache

        (seed_dir / "cache").mkdir(parents=True)
        (seed_dir / "cache" / "orcarouter_models.json").write_text("{not json")
        assert _read_cache(max_age=10**12) is None

    def test_write_cache_roundtrip(self, seed_dir: Path) -> None:
        import json

        from apps.cli.orcarouter_models import _read_cache, _write_cache

        payload = {"data": [{"id": "openai/gpt-5.5", "context_length": 400000}]}
        _write_cache(payload)
        assert (seed_dir / "cache" / "orcarouter_models.json").exists()
        blob = json.loads((seed_dir / "cache" / "orcarouter_models.json").read_text())
        assert blob["payload"] == payload
        # A fresh cache (fetched_at = now) reads straight back.
        assert _read_cache(max_age=3600) is not None

    def test_cached_models_empty(self, seed_dir: Path) -> None:
        from apps.cli.orcarouter_models import cached_models

        assert cached_models() == []

    def test_fetch_uses_fresh_cache(self, seed_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import json
        import time

        from apps.cli.orcarouter_models import fetch_orcarouter_models

        (seed_dir / "cache").mkdir(parents=True)
        (seed_dir / "cache" / "orcarouter_models.json").write_text(
            json.dumps(
                {
                    "fetched_at": time.time(),
                    "payload": {"data": [{"id": "openai/gpt-5.5", "context_length": 400000}]},
                }
            )
        )
        called = False

        def _no_network(*_a: object, **_k: object) -> object:
            nonlocal called
            called = True
            raise AssertionError("should not hit the network")

        import httpx

        monkeypatch.setattr(httpx, "get", _no_network)
        models = fetch_orcarouter_models()
        assert models[0].id == "openai/gpt-5.5"
        assert not called

    def test_fetch_network_success(self, seed_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import httpx

        from apps.cli.orcarouter_models import fetch_orcarouter_models

        class _Resp:
            def raise_for_status(self) -> None:
                pass

            def json(self) -> dict[str, object]:
                return {"data": [{"id": "openai/gpt-5.5", "context_length": 400000}]}

        monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp())
        models = fetch_orcarouter_models(force_refresh=True)
        assert models[0].id == "openai/gpt-5.5"
        assert (seed_dir / "cache" / "orcarouter_models.json").exists()  # cached

    def test_fetch_network_failure_returns_stale_cache(
        self, seed_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json
        import time

        import httpx

        from apps.cli.orcarouter_models import fetch_orcarouter_models

        (seed_dir / "cache").mkdir(parents=True)
        (seed_dir / "cache" / "orcarouter_models.json").write_text(
            json.dumps(
                {
                    "fetched_at": time.time() - 10_000,  # stale (beyond TTL)
                    "payload": {"data": [{"id": "deepseek/deepseek-v4-flash"}]},
                }
            )
        )

        def _raise(*_a: object, **_k: object) -> object:
            raise OSError("network down")

        monkeypatch.setattr(httpx, "get", _raise)
        models = fetch_orcarouter_models()
        assert models[0].id == "deepseek/deepseek-v4-flash"  # stale cache fallback

    def test_fetch_network_failure_no_cache_returns_empty(
        self, seed_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import httpx

        from apps.cli.orcarouter_models import fetch_orcarouter_models

        def _raise(*_a: object, **_k: object) -> object:
            raise OSError("network down")

        monkeypatch.setattr(httpx, "get", _raise)
        assert fetch_orcarouter_models() == []


class TestModelPickerOrcaSection:
    """The /model picker shows an OrcaRouter section when the catalogue is cached."""

    async def test_orca_models_listed_when_cached(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from textual.app import App

        from apps.cli import orcarouter_models
        from apps.cli.modals.model_picker import ModelPickerModal

        # Seed both caches so the modal mounts without triggering a live
        # OpenRouter refresh (empty OpenRouter cache would spawn a fetch).
        monkeypatch.setattr("apps.cli.orcarouter_models.get_global_dir", lambda: tmp_path)
        orcarouter_models._write_cache(
            {"data": [{"id": "openai/gpt-5.5", "context_length": 400000, "pricing": {}}]}
        )
        from apps.cli import openrouter_models

        monkeypatch.setattr("apps.cli.openrouter_models.get_global_dir", lambda: tmp_path)
        openrouter_models._write_cache(
            {"data": [{"id": "deepseek/deepseek-v4-flash", "pricing": {}}]}
        )
        monkeypatch.setattr("apps.cli.model_history.get_global_dir", lambda: tmp_path / "nohist")

        class _Harness(App[None]):
            async def on_mount(self) -> None:
                await self.push_screen(ModelPickerModal("x"))

        async with _Harness().run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            from textual.widgets import OptionList

            ol = pilot.app.screen.query_one("#model-list", OptionList)
            ids = [
                oid
                for i in range(ol.option_count)
                if (oid := ol.get_option_at_index(i).id) is not None
            ]
            assert any(i.startswith("orcarouter:openai/gpt-5.5") for i in ids)


class TestModelsOrcarouterCommand:
    def test_lists_models(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from apps.cli.orcarouter_models import OrcaRouterModel

        monkeypatch.setattr(
            "apps.cli.orcarouter_models.fetch_orcarouter_models",
            lambda **kw: [
                OrcaRouterModel(
                    id="openai/gpt-5.5",
                    name="GPT 5.5",
                    context_length=400000,
                    prompt_price=2e-7,
                    completion_price=8e-7,
                )
            ],
        )
        result = runner.invoke(app, ["models", "orcarouter"])
        assert result.exit_code == 0
        assert "orcarouter:openai/gpt-5.5" in result.output

    def test_search_filters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from apps.cli.orcarouter_models import OrcaRouterModel

        monkeypatch.setattr(
            "apps.cli.orcarouter_models.fetch_orcarouter_models",
            lambda **kw: [
                OrcaRouterModel(
                    id="openai/gpt-5.5",
                    name="GPT 5.5",
                    context_length=400000,
                    prompt_price=2e-7,
                    completion_price=8e-7,
                ),
                OrcaRouterModel(
                    id="deepseek/deepseek-v4-flash",
                    name="DeepSeek V4 Flash",
                    context_length=1_000_000,
                    prompt_price=1e-7,
                    completion_price=2e-7,
                ),
            ],
        )
        result = runner.invoke(app, ["models", "orcarouter", "deepseek"])
        assert result.exit_code == 0
        assert "deepseek/deepseek-v4-flash" in result.output
        assert "gpt-5.5" not in result.output
