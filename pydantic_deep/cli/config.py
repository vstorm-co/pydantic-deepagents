"""Configuration system for the pydantic-deep CLI.

Config file: ``~/.pydantic-deep/config.toml``

Precedence: CLI arguments > config file > hardcoded defaults.
"""

from __future__ import annotations

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

DEFAULT_CONFIG_DIR = Path.home() / ".pydantic-deep"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.toml"
DEFAULT_THREADS_DIR = DEFAULT_CONFIG_DIR / "threads"

_BOOL_FIELDS = frozenset(
    {
        "include_skills",
        "include_plan",
        "include_memory",
        "include_checkpoints",
        "include_subagents",
        "include_todo",
        "context_discovery",
    }
)


@dataclass
class CliConfig:
    """CLI configuration loaded from config.toml."""

    model: str = "openai:gpt-4.1"
    working_dir: str | None = None
    shell_allow_list: list[str] = field(default_factory=list)
    include_skills: bool = True
    include_plan: bool = True
    include_memory: bool = True
    include_checkpoints: bool = True
    include_subagents: bool = True
    include_todo: bool = True
    context_discovery: bool = True


def load_config(path: Path | None = None) -> CliConfig:
    """Load config from TOML file.

    Returns defaults if file doesn't exist.
    """
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.exists():
        return CliConfig()

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    return _parse_config(data)


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
    "get_config_value",
    "load_config",
    "set_config_value",
]
