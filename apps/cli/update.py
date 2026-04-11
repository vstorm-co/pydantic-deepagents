"""Version checking and self-update functionality for pydantic-deep CLI."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple

PYPI_URL = "https://pypi.org/pypi/pydantic-deep/json"
_CHECK_INTERVAL_SECS: int = 86_400  # 24 hours


class UpdateInfo(NamedTuple):
    current: str
    latest: str


def _get_cache_path() -> Path:
    return Path.home() / ".pydantic-deep" / "update_check.json"


def _version_gt(a: str, b: str) -> bool:
    """Return True if version string *a* is greater than *b*.

    Only numeric dot-separated components are compared, so pre-release
    suffixes (e.g. ``0.4.0a1``) are stripped automatically.
    """

    def _parts(v: str) -> tuple[int, ...]:
        return tuple(int(x) for x in v.split(".") if x.isdigit())

    return _parts(a) > _parts(b)


def _load_cache(cache_path: Path) -> dict[str, Any] | None:
    """Return cached version data if still fresh (< 24 h), else ``None``."""
    try:
        data: dict[str, Any] = json.loads(cache_path.read_text())
        checked_at = datetime.fromisoformat(data["checked_at"])
        age = (datetime.now(timezone.utc) - checked_at).total_seconds()
        if age < _CHECK_INTERVAL_SECS:
            return data
    except Exception:
        pass
    return None


def _save_cache(latest_version: str, cache_path: Path) -> None:
    """Persist *latest_version* and a timestamp to *cache_path*."""
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "version": latest_version,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        )
    except Exception:
        pass


def _fetch_latest_version() -> str | None:
    """Fetch the latest pydantic-deep version from PyPI (2-second timeout)."""
    try:
        with urllib.request.urlopen(PYPI_URL, timeout=2) as resp:
            data: dict[str, Any] = json.loads(resp.read())
            return str(data["info"]["version"])
    except Exception:
        return None


def _find_uv() -> str | None:
    """Return path to the ``uv`` executable if available, else ``None``."""
    return shutil.which("uv")


def check_for_update(cache_path: Path | None = None) -> UpdateInfo | None:
    """Check if a newer version of pydantic-deep is available on PyPI.

    Uses a 24-hour file-based cache so the network is only hit once per day.
    Returns ``None`` when already up-to-date or when the check cannot be
    completed (e.g. no internet access).
    """
    from pydantic_deep import __version__

    path = cache_path if cache_path is not None else _get_cache_path()
    cached = _load_cache(path)
    if cached:
        latest = cached["version"]
    else:
        latest = _fetch_latest_version()
        if latest is None:
            return None
        _save_cache(latest, path)

    if _version_gt(latest, __version__):
        return UpdateInfo(current=__version__, latest=latest)
    return None


def run_update() -> int:
    """Upgrade pydantic-deep to the latest version.

    Uses ``uv tool upgrade`` when uv is available, otherwise falls back to
    ``pip install --upgrade``.  Returns the subprocess exit code.
    """
    uv = _find_uv()
    if uv:
        return subprocess.run([uv, "tool", "upgrade", "pydantic-deep"]).returncode
    return subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade", "pydantic-deep[cli]"]
    ).returncode
