"""Persistent API key storage in .pydantic-deep/keys.toml.

Keys are saved to a dedicated TOML file (separate from config.toml)
and loaded into os.environ on startup. This file should be in .gitignore.

Usage:
    # On app startup:
    load_keys()  # reads keys.toml → os.environ

    # When user enters a key via /provider:
    save_key("OPENROUTER_API_KEY", "sk-or-...")

    # Check what's stored:
    get_stored_keys()  # → {"OPENROUTER_API_KEY": "sk-or-..."}
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from apps.cli.config import get_project_dir

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]


def _keys_path() -> Path:
    """Path to keys.toml file."""

    return get_project_dir() / "keys.toml"


def load_keys() -> dict[str, str]:
    """Load keys from keys.toml and set them in os.environ.

    Only sets keys that are NOT already in the environment
    (env vars take precedence over stored keys).

    Returns:
        Dict of key_name → key_value that were loaded.
    """
    path = _keys_path()
    if not path.exists():
        return {}

    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return {}

    loaded: dict[str, str] = {}
    for key, value in data.items():
        if isinstance(value, str) and value:
            # Don't overwrite existing env vars
            if not os.environ.get(key):
                os.environ[key] = value
                loaded[key] = value
            else:
                loaded[key] = os.environ[key]

    return loaded


def save_key(key_name: str, key_value: str) -> None:
    """Save an API key to keys.toml and set in os.environ."""
    path = _keys_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Read existing
    data: dict[str, Any] = {}
    if path.exists():
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
        except Exception:
            pass

    # Update
    data[key_name] = key_value

    # Write
    lines: list[str] = ["# pydantic-deep API keys (auto-generated, do not commit)"]
    for k in sorted(data):
        v = data[k]
        if isinstance(v, str) and v:
            # json.dumps yields a valid TOML basic string (escapes ", \, newlines)
            # so tokens with special chars don't corrupt the whole file.
            lines.append(f"{k} = {json.dumps(v)}")
    path.write_text("\n".join(lines) + "\n")

    # Also set in current process
    os.environ[key_name] = key_value


def get_stored_keys() -> dict[str, str]:
    """Get all stored keys (without loading them into environ)."""
    path = _keys_path()
    if not path.exists():
        return {}

    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        return {k: v for k, v in data.items() if isinstance(v, str) and v}
    except Exception:
        return {}


def remove_key(key_name: str) -> None:
    """Remove a key from keys.toml."""
    path = _keys_path()
    if not path.exists():
        return

    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return

    data.pop(key_name, None)

    lines: list[str] = ["# pydantic-deep API keys (auto-generated, do not commit)"]
    for k in sorted(data):
        v = data[k]
        if isinstance(v, str) and v:
            # json.dumps yields a valid TOML basic string (escapes ", \, newlines)
            # so tokens with special chars don't corrupt the whole file.
            lines.append(f"{k} = {json.dumps(v)}")
    path.write_text("\n".join(lines) + "\n")
