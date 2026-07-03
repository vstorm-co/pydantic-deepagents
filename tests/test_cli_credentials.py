"""Tests for CLI credential management, model history, and OpenRouter catalogue."""

from __future__ import annotations

import pytest


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    """Point global (~/.pydantic-deep) and project (./.pydantic-deep) at tmp dirs."""
    global_dir = tmp_path / "home" / ".pydantic-deep"
    project_dir = tmp_path / "proj" / ".pydantic-deep"

    for mod in ("keystore", "model_history", "onboarding_cli"):
        monkeypatch.setattr(f"apps.cli.{mod}.get_global_dir", lambda: global_dir, raising=False)
    for mod in ("keystore",):
        monkeypatch.setattr(f"apps.cli.{mod}.get_project_dir", lambda: project_dir, raising=False)
    # Clear any real env for the keys we touch.
    for var in ("OPENROUTER_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    return global_dir, project_dir


# ── credentials registry ────────────────────────────────────────────────────


class TestCredentials:
    def test_find_and_categories(self) -> None:
        from apps.cli.credentials import credentials_by_category, find_credential

        assert find_credential("OPENROUTER_API_KEY").provider_id == "openrouter"
        assert find_credential("NOPE") is None
        cats = credentials_by_category()
        assert "Model providers" in cats and "Vertex AI" in cats
        assert any(c.env_var == "LOGFIRE_TOKEN" for c in cats["Observability"])

    def test_mask(self) -> None:
        from apps.cli.credentials import mask

        assert mask("sk-or-1234567890") == "sk-o…7890"
        assert mask("short") == "•••••"
        assert mask("") == ""


# ── keystore (global/project scopes) ────────────────────────────────────────


class TestKeystore:
    def test_save_load_global(self, isolated_dirs, monkeypatch) -> None:
        from apps.cli import keystore

        keystore.save_key("OPENROUTER_API_KEY", "sk-glob")
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        loaded = keystore.load_keys()
        assert loaded["OPENROUTER_API_KEY"] == "sk-glob"

    def test_project_overrides_global(self, isolated_dirs, monkeypatch) -> None:
        from apps.cli import keystore

        keystore.save_key("DEEPSEEK_API_KEY", "sk-glob", scope="global")
        keystore.save_key("DEEPSEEK_API_KEY", "sk-proj", scope="project")
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        assert keystore.get_stored_keys()["DEEPSEEK_API_KEY"] == "sk-proj"
        keystore.load_keys()
        import os

        assert os.environ["DEEPSEEK_API_KEY"] == "sk-proj"

    def test_env_wins_over_stored(self, isolated_dirs, monkeypatch) -> None:
        from apps.cli import keystore

        keystore.save_key("ANTHROPIC_API_KEY", "sk-stored")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-real-env")
        loaded = keystore.load_keys()
        assert loaded["ANTHROPIC_API_KEY"] == "sk-real-env"

    def test_remove(self, isolated_dirs) -> None:
        from apps.cli import keystore

        keystore.save_key("OPENROUTER_API_KEY", "sk-x")
        keystore.remove_key("OPENROUTER_API_KEY")
        assert "OPENROUTER_API_KEY" not in keystore.get_stored_keys("global")

    def test_special_chars_roundtrip(self, isolated_dirs) -> None:
        from apps.cli import keystore

        val = 'sk-"weird"\\value'
        keystore.save_key("OPENAI_API_KEY", val)
        assert keystore.get_stored_keys("global")["OPENAI_API_KEY"] == val


# ── keys_cmd helpers ────────────────────────────────────────────────────────


class TestKeysCmd:
    def test_resolve_by_number_name_case(self) -> None:
        from apps.cli.credentials import CREDENTIALS
        from apps.cli.keys_cmd import resolve_credential

        assert resolve_credential("1").env_var == CREDENTIALS[0].env_var
        assert resolve_credential("OPENROUTER_API_KEY").provider_id == "openrouter"
        assert resolve_credential("openrouter_api_key").provider_id == "openrouter"
        assert resolve_credential("999") is None
        assert resolve_credential("NOT_A_KEY") is None

    def test_iter_status(self, isolated_dirs, monkeypatch) -> None:
        from apps.cli import keystore
        from apps.cli.keys_cmd import iter_key_status

        keystore.save_key("OPENROUTER_API_KEY", "sk-or-secretvalue")
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        rows = {r.credential.env_var: r for r in iter_key_status()}
        assert rows["OPENROUTER_API_KEY"].is_set
        assert rows["OPENROUTER_API_KEY"].source == "stored"
        assert "…" in rows["OPENROUTER_API_KEY"].display_value  # masked
        assert not rows["GROQ_API_KEY"].is_set


# ── model history ───────────────────────────────────────────────────────────


class TestModelHistory:
    def test_record_dedup_newest_first(self, isolated_dirs) -> None:
        from apps.cli.model_history import recent_models, record_model_use

        record_model_use("openrouter:deepseek/deepseek-v4-flash")
        record_model_use("google-cloud:gemini-3.1-pro-preview")
        record_model_use("openrouter:deepseek/deepseek-v4-flash")
        assert recent_models() == [
            "openrouter:deepseek/deepseek-v4-flash",
            "google-cloud:gemini-3.1-pro-preview",
        ]

    def test_empty_and_cap(self, isolated_dirs) -> None:
        from apps.cli.model_history import recent_models, record_model_use

        assert recent_models() == []
        record_model_use("")  # ignored
        assert recent_models() == []
        for i in range(20):
            record_model_use(f"m{i}")
        assert len(recent_models()) == 12  # capped


# ── OpenRouter parsing (pure) ───────────────────────────────────────────────


class TestOpenRouterParse:
    def test_parse(self) -> None:
        from apps.cli.openrouter_models import parse_models

        payload = {
            "data": [
                {
                    "id": "deepseek/deepseek-v4-flash",
                    "name": "DeepSeek V4 Flash",
                    "context_length": 1048576,
                    "pricing": {"prompt": "0.00000009", "completion": "0.00000018"},
                },
                {"name": "no id — skipped"},
                {"id": "x/y"},  # missing fields tolerated
            ]
        }
        models = parse_models(payload)
        assert len(models) == 2
        m = models[0]
        assert m.model_string == "openrouter:deepseek/deepseek-v4-flash"
        assert m.context_length == 1048576
        assert m.prompt_price == pytest.approx(9e-8)
        assert models[1].context_length == 0  # tolerated default


# ── onboarding helpers ──────────────────────────────────────────────────────


class TestOnboarding:
    def test_new_user_and_mark(self, isolated_dirs) -> None:
        from apps.cli.onboarding_cli import is_new_user, mark_onboarded

        assert is_new_user() is True
        mark_onboarded()
        assert is_new_user() is False

    def test_provider_credentials_deduped(self) -> None:
        from apps.cli.onboarding_cli import _provider_credentials

        provs = _provider_credentials()
        ids = [c.provider_id for c in provs]
        assert ids == list(dict.fromkeys(ids))  # no dupes
        assert "openrouter" in ids and "google" in ids
        # GEMINI + GOOGLE both map to google → only one entry
        assert ids.count("google") == 1

    def test_run_onboarding_saves_key_and_marks(self, isolated_dirs, monkeypatch) -> None:
        from apps.cli import keystore, onboarding_cli

        answers = iter(["1", "sk-or-testkey-1234567", "openrouter:anthropic/claude-sonnet-4"])
        monkeypatch.setattr("typer.prompt", lambda *a, **k: next(answers))
        monkeypatch.setattr(onboarding_cli, "set_config_value", lambda *a, **k: None)

        model = onboarding_cli.run_onboarding()
        assert model == "openrouter:anthropic/claude-sonnet-4"
        assert keystore.get_stored_keys("global")["OPENROUTER_API_KEY"] == "sk-or-testkey-1234567"
        assert onboarding_cli.is_new_user() is False  # marked onboarded

    def test_run_onboarding_skip(self, isolated_dirs, monkeypatch) -> None:
        from apps.cli import keystore, onboarding_cli

        monkeypatch.setattr("typer.prompt", lambda *a, **k: "0")
        model = onboarding_cli.run_onboarding()
        assert model is None
        assert keystore.get_stored_keys("global") == {}  # nothing saved
        assert onboarding_cli.is_new_user() is False  # still marked so we don't nag again

    def test_detection_survives_dir_created_by_other_code(self, isolated_dirs) -> None:
        # Regression: the update-check cache (and keystore) create ~/.pydantic-deep.
        # The callback must capture new-user status BEFORE that happens.
        from apps.cli.onboarding_cli import is_new_user

        global_dir, _ = isolated_dirs
        first_run = is_new_user()  # captured first, as the callback does
        global_dir.mkdir(parents=True, exist_ok=True)  # simulate update cache
        assert first_run is True
        assert is_new_user() is False  # dir now exists — proves capture must be first


# ── known models (pydantic-ai catalogue) ────────────────────────────────────


class TestKnownModels:
    def test_chat_models_grouped_and_filtered(self) -> None:
        from apps.cli.known_models import chat_models_by_provider

        cat = chat_models_by_provider()
        assert "anthropic" in cat and "xai" in cat and "groq" in cat
        # Every entry is a full provider:model string for its group.
        for prefix, models in cat.items():
            assert all(m.startswith(f"{prefix}:") for m in models)
        # Non-chat models are filtered out.
        allm = [m for ms in cat.values() for m in ms]
        assert not any("whisper" in m or "tts" in m or "guard" in m for m in allm)

    def test_provider_sections_keyed_first(self, monkeypatch) -> None:
        from apps.cli.known_models import provider_sections

        for var in ("XAI_API_KEY", "GROQ_API_KEY", "MISTRAL_API_KEY", "ANTHROPIC_API_KEY"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("XAI_API_KEY", "x")
        sections = provider_sections()
        keyed = [label for _p, label, has_key, _m in sections if has_key]
        first_has_key = sections[0][2]
        assert "xAI (Grok)" in keyed
        assert first_has_key is True  # a keyed provider sorts to the top
