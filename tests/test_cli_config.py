"""Tests for CLI config system."""

from __future__ import annotations

from pathlib import Path

import pytest

from cli.config import (
    CliConfig,
    _apply_env_overrides,
    _coerce_value,
    _parse_config,
    _write_toml,
    format_config,
    get_config_value,
    load_config,
    set_config_value,
)


class TestCliConfig:
    """Tests for CliConfig defaults."""

    def test_default_model(self) -> None:
        config = CliConfig()
        assert config.model == "openrouter:openai/gpt-4.1"

    def test_default_working_dir(self) -> None:
        config = CliConfig()
        assert config.working_dir is None

    def test_default_shell_allow_list(self) -> None:
        config = CliConfig()
        assert config.shell_allow_list == []

    def test_all_features_enabled_by_default(self) -> None:
        config = CliConfig()
        assert config.include_skills is True
        assert config.include_plan is True
        assert config.include_memory is True
        assert config.include_subagents is True
        assert config.include_todo is True
        assert config.context_discovery is True


class TestLoadConfig:
    """Tests for load_config()."""

    def test_returns_defaults_when_no_file(self, tmp_path: Path) -> None:
        config = load_config(tmp_path / "nonexistent.toml")
        assert config.model == "openrouter:openai/gpt-4.1"

    def test_loads_from_file(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text('model = "anthropic:claude-sonnet-4-20250514"\n')

        config = load_config(config_file)
        assert config.model == "anthropic:claude-sonnet-4-20250514"

    def test_partial_config(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text("include_skills = false\n")

        config = load_config(config_file)
        assert config.include_skills is False
        assert config.model == "openrouter:openai/gpt-4.1"  # default preserved

    def test_ignores_unknown_keys(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text('unknown_key = "value"\nmodel = "test"\n')

        config = load_config(config_file)
        assert config.model == "test"
        assert not hasattr(config, "unknown_key")


class TestParseConfig:
    """Tests for _parse_config()."""

    def test_empty_dict(self) -> None:
        config = _parse_config({})
        assert config.model == "openrouter:openai/gpt-4.1"

    def test_full_dict(self) -> None:
        data = {
            "model": "test-model",
            "working_dir": "/tmp",
            "shell_allow_list": ["python"],
            "include_skills": False,
        }
        config = _parse_config(data)
        assert config.model == "test-model"
        assert config.working_dir == "/tmp"
        assert config.shell_allow_list == ["python"]
        assert config.include_skills is False

    def test_filters_unknown_keys(self) -> None:
        data = {"model": "test", "random_key": "value"}
        config = _parse_config(data)
        assert config.model == "test"


class TestGetConfigValue:
    """Tests for get_config_value()."""

    def test_valid_key(self) -> None:
        config = CliConfig(model="test")
        assert get_config_value("model", config) == "test"

    def test_invalid_key(self) -> None:
        config = CliConfig()
        with pytest.raises(KeyError, match="Unknown config key"):
            get_config_value("nonexistent", config)


class TestSetConfigValue:
    """Tests for set_config_value()."""

    def test_creates_file(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        set_config_value(config_file, "model", "test-model")

        assert config_file.exists()
        config = load_config(config_file)
        assert config.model == "test-model"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        config_file = tmp_path / "subdir" / "config.toml"
        set_config_value(config_file, "model", "test")
        assert config_file.exists()

    def test_updates_existing(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text('model = "old"\n')

        set_config_value(config_file, "model", "new")
        config = load_config(config_file)
        assert config.model == "new"

    def test_preserves_other_keys(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text('model = "original"\ninclude_skills = true\n')

        set_config_value(config_file, "model", "changed")
        config = load_config(config_file)
        assert config.model == "changed"
        assert config.include_skills is True

    def test_invalid_key_raises(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        with pytest.raises(KeyError, match="Unknown config key"):
            set_config_value(config_file, "bad_key", "value")


class TestCoerceValue:
    """Tests for _coerce_value()."""

    def test_bool_true(self) -> None:
        assert _coerce_value("include_skills", "true") is True
        assert _coerce_value("include_skills", "True") is True
        assert _coerce_value("include_skills", "1") is True
        assert _coerce_value("include_skills", "yes") is True

    def test_bool_false(self) -> None:
        assert _coerce_value("include_skills", "false") is False
        assert _coerce_value("include_skills", "0") is False
        assert _coerce_value("include_skills", "no") is False

    def test_all_bool_fields(self) -> None:
        bool_fields = [
            "include_skills",
            "include_plan",
            "include_memory",
            "include_subagents",
            "include_todo",
            "context_discovery",
        ]
        for field in bool_fields:
            assert _coerce_value(field, "true") is True

    def test_list_value(self) -> None:
        result = _coerce_value("shell_allow_list", "python,pip,npm")
        assert result == ["python", "pip", "npm"]

    def test_list_with_spaces(self) -> None:
        result = _coerce_value("shell_allow_list", " python , pip , npm ")
        assert result == ["python", "pip", "npm"]

    def test_list_empty_string(self) -> None:
        result = _coerce_value("shell_allow_list", "")
        assert result == []

    def test_working_dir_none(self) -> None:
        assert _coerce_value("working_dir", "none") is None
        assert _coerce_value("working_dir", "null") is None
        assert _coerce_value("working_dir", "") is None

    def test_string_value(self) -> None:
        assert _coerce_value("model", "openai:gpt-4o") == "openai:gpt-4o"


class TestWriteToml:
    """Tests for _write_toml()."""

    def test_writes_string(self, tmp_path: Path) -> None:
        f = tmp_path / "test.toml"
        _write_toml(f, {"model": "test"})
        assert f.read_text() == 'model = "test"\n'

    def test_writes_bool(self, tmp_path: Path) -> None:
        f = tmp_path / "test.toml"
        _write_toml(f, {"include_skills": True})
        assert f.read_text() == "include_skills = true\n"

    def test_writes_false(self, tmp_path: Path) -> None:
        f = tmp_path / "test.toml"
        _write_toml(f, {"include_skills": False})
        assert f.read_text() == "include_skills = false\n"

    def test_writes_list(self, tmp_path: Path) -> None:
        f = tmp_path / "test.toml"
        _write_toml(f, {"shell_allow_list": ["python", "pip"]})
        assert f.read_text() == 'shell_allow_list = ["python", "pip"]\n'

    def test_skips_none(self, tmp_path: Path) -> None:
        f = tmp_path / "test.toml"
        _write_toml(f, {"model": "test", "working_dir": None})
        assert f.read_text() == 'model = "test"\n'

    def test_sorts_keys(self, tmp_path: Path) -> None:
        f = tmp_path / "test.toml"
        _write_toml(f, {"z_key": "b", "a_key": "a"})
        content = f.read_text()
        assert content.index("a_key") < content.index("z_key")


class TestFormatConfig:
    """Tests for format_config()."""

    def test_includes_all_fields(self) -> None:
        config = CliConfig()
        result = format_config(config)
        assert "model" in result
        assert "include_skills" in result
        assert "context_discovery" in result

    def test_shows_values(self) -> None:
        config = CliConfig(model="test-model")
        result = format_config(config)
        assert "test-model" in result


class TestNewConfigFields:
    """Tests for theme, show_cost, show_tokens fields."""

    def test_default_theme(self) -> None:
        config = CliConfig()
        assert config.theme == "default"

    def test_default_show_cost(self) -> None:
        config = CliConfig()
        assert config.show_cost is True

    def test_default_show_tokens(self) -> None:
        config = CliConfig()
        assert config.show_tokens is True

    def test_loads_theme_from_file(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text('theme = "minimal"\n')
        config = load_config(config_file)
        assert config.theme == "minimal"

    def test_loads_show_cost_false(self, tmp_path: Path) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text("show_cost = false\n")
        config = load_config(config_file)
        assert config.show_cost is False

    def test_coerce_show_cost(self) -> None:
        assert _coerce_value("show_cost", "true") is True
        assert _coerce_value("show_cost", "false") is False

    def test_coerce_show_tokens(self) -> None:
        assert _coerce_value("show_tokens", "true") is True


class TestEnvVarOverrides:
    """Tests for _apply_env_overrides() and env var precedence."""

    def test_model_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        config = CliConfig()
        monkeypatch.setenv("PYDANTIC_DEEP_MODEL", "anthropic:claude-sonnet")
        _apply_env_overrides(config)
        assert config.model == "anthropic:claude-sonnet"

    def test_working_dir_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        config = CliConfig()
        monkeypatch.setenv("PYDANTIC_DEEP_WORKING_DIR", "/tmp/project")
        _apply_env_overrides(config)
        assert config.working_dir == "/tmp/project"

    def test_theme_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        config = CliConfig()
        monkeypatch.setenv("PYDANTIC_DEEP_THEME", "minimal")
        _apply_env_overrides(config)
        assert config.theme == "minimal"

    def test_no_env_vars_no_change(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("PYDANTIC_DEEP_MODEL", raising=False)
        monkeypatch.delenv("PYDANTIC_DEEP_WORKING_DIR", raising=False)
        monkeypatch.delenv("PYDANTIC_DEEP_THEME", raising=False)
        config = CliConfig()
        _apply_env_overrides(config)
        assert config.model == "openrouter:openai/gpt-4.1"
        assert config.working_dir is None
        assert config.theme == "default"

    def test_env_overrides_config_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        config_file = tmp_path / "config.toml"
        config_file.write_text('model = "openai:gpt-4o"\n')
        monkeypatch.setenv("PYDANTIC_DEEP_MODEL", "anthropic:claude-sonnet")
        config = load_config(config_file)
        assert config.model == "anthropic:claude-sonnet"
