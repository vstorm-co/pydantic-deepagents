"""Configuration system for the pydantic-deep CLI.

Config file: ``.pydantic-deep/config.toml`` (in working directory)

Precedence: CLI arguments > config file > hardcoded defaults.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    try:
        import tomllib  # type: ignore[import-not-found,no-redefine]
    except ImportError:
        import tomli as tomllib  # type: ignore[import-not-found,no-redefine]


def get_project_dir() -> Path:
    """Return ``.pydantic-deep/`` in CWD."""
    return Path.cwd() / ".pydantic-deep"


def get_config_path() -> Path:
    """Return path to ``config.toml``."""
    return get_project_dir() / "config.toml"


def get_sessions_dir() -> Path:
    """Return path to ``sessions/`` directory."""
    return get_project_dir() / "sessions"


def get_history_path() -> Path:
    """Return path to ``history.txt``."""
    return get_project_dir() / "history.txt"


# Keep these for backward compatibility — used by imports
DEFAULT_CONFIG_DIR = get_project_dir()
DEFAULT_CONFIG_PATH = get_config_path()
DEFAULT_THREADS_DIR = get_sessions_dir()

_BOOL_FIELDS = frozenset(
    {
        "include_skills",
        "include_plan",
        "include_memory",
        "include_checkpoints",
        "include_subagents",
        "include_todo",
        "context_discovery",
        "show_cost",
        "show_tokens",
        "thinking",
        "logfire",
    }
)

_INT_FIELDS = frozenset({"max_history", "thinking_budget"})

_FLOAT_FIELDS = frozenset({"temperature"})


@dataclass
class CliConfig:
    """CLI configuration loaded from config.toml."""

    model: str = "openrouter:openai/gpt-4.1"
    working_dir: str | None = None
    shell_allow_list: list[str] = field(default_factory=list)
    theme: str = "default"
    charset: str = "auto"
    show_cost: bool = True
    show_tokens: bool = True
    history_file: str = ""  # empty = use get_history_path() at runtime
    max_history: int = 1000
    include_skills: bool = True
    include_plan: bool = True
    include_memory: bool = True
    include_checkpoints: bool = True
    include_subagents: bool = True
    include_todo: bool = True
    context_discovery: bool = True
    temperature: float | None = None
    reasoning_effort: str | None = None
    thinking: bool = False
    thinking_budget: int | None = None
    logfire: bool = False


def load_config(path: Path | None = None) -> CliConfig:
    """Load config from TOML file with environment variable overrides.

    Precedence: environment variables > config file > defaults.
    """
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.exists():
        config = CliConfig()
    else:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
        config = _parse_config(data)

    _apply_env_overrides(config)
    return config


def _apply_env_overrides(config: CliConfig) -> None:
    """Apply PYDANTIC_DEEP_* environment variable overrides."""
    env_model = os.environ.get("PYDANTIC_DEEP_MODEL")
    if env_model:
        config.model = env_model

    env_working_dir = os.environ.get("PYDANTIC_DEEP_WORKING_DIR")
    if env_working_dir:
        config.working_dir = env_working_dir

    env_theme = os.environ.get("PYDANTIC_DEEP_THEME")
    if env_theme:
        config.theme = env_theme

    env_charset = os.environ.get("PYDANTIC_DEEP_CHARSET")
    if env_charset:
        config.charset = env_charset


def validate_config(config: CliConfig) -> list[str]:
    """Validate config values, returning a list of warning messages."""
    warnings: list[str] = []
    if config.model and ":" not in config.model:
        warnings.append(f"Model '{config.model}' missing provider prefix (e.g. 'openai:gpt-4.1')")
    if config.working_dir:
        from pathlib import Path as _Path

        if not _Path(config.working_dir).exists():
            warnings.append(f"Working directory '{config.working_dir}' does not exist")
    known_themes = {"default", "minimal"}
    if config.theme not in known_themes:
        warnings.append(
            f"Unknown theme '{config.theme}'. Known themes: {', '.join(sorted(known_themes))}"
        )
    known_charsets = {"auto", "unicode", "ascii"}
    if config.charset not in known_charsets:
        warnings.append(
            f"Unknown charset '{config.charset}'. Known: {', '.join(sorted(known_charsets))}"
        )
    if config.max_history < 0:
        warnings.append("max_history must be non-negative")
    return warnings


def _parse_config(data: dict[str, Any]) -> CliConfig:
    """Parse TOML dict into CliConfig, ignoring unknown keys."""
    valid_fields = {f.name for f in fields(CliConfig)}
    filtered = {k: v for k, v in data.items() if k in valid_fields}
    return CliConfig(**filtered)


def get_config_value(key: str, config: CliConfig) -> Any:
    """Get a config value by key.

    Raises:
        KeyError: If the key is not a valid config field.
    """
    if not hasattr(config, key):
        msg = f"Unknown config key: {key}"
        raise KeyError(msg)
    return getattr(config, key)


def set_config_value(path: Path, key: str, value: str) -> None:
    """Set a config value in the TOML file.

    Creates the file and parent directories if they don't exist.
    """
    valid_fields = {f.name for f in fields(CliConfig)}
    if key not in valid_fields:
        msg = f"Unknown config key: {key}. Valid keys: {', '.join(sorted(valid_fields))}"
        raise KeyError(msg)

    if path.exists():
        with open(path, "rb") as f:
            data = tomllib.load(f)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {}

    data[key] = _coerce_value(key, value)
    _write_toml(path, data)


def _coerce_value(key: str, value: str) -> Any:
    """Coerce string value to the correct type based on the field."""
    if key in _BOOL_FIELDS:
        return value.lower() in ("true", "1", "yes")
    if key in _INT_FIELDS:
        return int(value)
    if key in _FLOAT_FIELDS:
        return float(value)
    if key == "shell_allow_list":
        return [v.strip() for v in value.split(",") if v.strip()]
    if key == "working_dir" and value.lower() in ("none", "null", ""):
        return None
    return value


def _write_toml(path: Path, data: dict[str, Any]) -> None:
    """Write a flat key-value dict as TOML."""
    lines: list[str] = []
    for key in sorted(data):
        value = data[key]
        if value is None:
            continue
        if isinstance(value, bool):
            lines.append(f"{key} = {'true' if value else 'false'}")
        elif isinstance(value, float):
            lines.append(f"{key} = {value}")
        elif isinstance(value, int):
            lines.append(f"{key} = {value}")
        elif isinstance(value, list):
            items = ", ".join(f'"{v}"' for v in value)
            lines.append(f"{key} = [{items}]")
        else:
            lines.append(f'{key} = "{value}"')
    path.write_text("\n".join(lines) + "\n")


def format_config(config: CliConfig) -> str:
    """Format config for display."""
    lines: list[str] = []
    for f in fields(config):
        value = getattr(config, f.name)
        lines.append(f"  {f.name} = {value!r}")
    return "\n".join(lines)


__all__ = [
    "CliConfig",
    "DEFAULT_CONFIG_DIR",
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_THREADS_DIR",
    "format_config",
    "get_config_path",
    "get_config_value",
    "get_history_path",
    "get_project_dir",
    "get_sessions_dir",
    "load_config",
    "set_config_value",
]
