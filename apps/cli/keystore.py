"""Persistent API-key storage in `keys.toml`.

Keys live in a dedicated TOML file (separate from config.toml) and are loaded
into `os.environ` on startup. Two scopes:

- ``"global"`` — ``~/.pydantic-deep/keys.toml`` (default): user-level keys that
  apply across every project.
- ``"project"`` — ``./.pydantic-deep/keys.toml``: keys scoped to one project,
  which override global ones.

Precedence at load time: real environment variables > project keys > global keys.
These files must be git-ignored.

Usage::

    load_keys()                              # global + project → os.environ
    save_key("OPENROUTER_API_KEY", "sk-…")   # → global keys.toml
    get_stored_keys()                        # merged view (project over global)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from apps.cli.config import get_global_dir, get_project_dir

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

Scope = Literal["global", "project"]

_HEADER = "# pydantic-deep API keys (auto-generated, do not commit)"


def _keys_path(scope: Scope = "global") -> Path:
    """Path to the `keys.toml` for the given scope."""
    base = get_global_dir() if scope == "global" else get_project_dir()
    return base / "keys.toml"


def _read(path: Path) -> dict[str, str]:
    """Read a keys.toml file into a dict of non-empty string values."""
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return {}
    return {k: v for k, v in data.items() if isinstance(v, str) and v}


def _write(path: Path, data: dict[str, str]) -> None:
    """Write a dict to keys.toml (values JSON-escaped for TOML safety)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [_HEADER]
    for k in sorted(data):
        v = data[k]
        if isinstance(v, str) and v:
            # json.dumps yields a valid TOML basic string (escapes ", \, newlines).
            lines.append(f"{k} = {json.dumps(v)}")
    path.write_text("\n".join(lines) + "\n")


def load_keys() -> dict[str, str]:
    """Load stored keys into `os.environ` (global first, then project).

    Real environment variables always win — a stored key never overwrites one
    that is already set. Project keys override global ones.

    Returns:
        The effective key values now available in the environment.
    """
    merged: dict[str, str] = {**_read(_keys_path("global")), **_read(_keys_path("project"))}
    loaded: dict[str, str] = {}
    for key, value in merged.items():
        if not os.environ.get(key):
            os.environ[key] = value
        loaded[key] = os.environ[key]
    return loaded


def save_key(key_name: str, key_value: str, scope: Scope = "global") -> None:
    """Save an API key to the scope's keys.toml and set it in `os.environ`."""
    path = _keys_path(scope)
    data = _read(path)
    data[key_name] = key_value
    _write(path, data)
    os.environ[key_name] = key_value


def get_stored_keys(scope: Scope | None = None) -> dict[str, str]:
    """Return stored keys.

    With ``scope`` given, returns just that file's keys. With ``scope=None``
    (default), returns the merged view (project over global).
    """
    if scope is not None:
        return _read(_keys_path(scope))
    return {**_read(_keys_path("global")), **_read(_keys_path("project"))}


def remove_key(key_name: str, scope: Scope = "global") -> None:
    """Remove a key from the scope's keys.toml."""
    path = _keys_path(scope)
    data = _read(path)
    if data.pop(key_name, None) is not None:
        _write(path, data)


__all__ = [
    "get_stored_keys",
    "load_keys",
    "remove_key",
    "save_key",
]
