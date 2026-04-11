"""Tests for CLI update-checking and self-update functionality."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from apps.cli.update import (
    UpdateInfo,
    _fetch_latest_version,
    _find_uv,
    _get_cache_path,
    _load_cache,
    _save_cache,
    _version_gt,
    check_for_update,
    run_update,
)

# ── _get_cache_path ───────────────────────────────────────────────────────────


class TestGetCachePath:
    def test_returns_path_under_home(self) -> None:
        path = _get_cache_path()
        assert path.name == "update_check.json"
        assert ".pydantic-deep" in str(path)


# ── _version_gt ───────────────────────────────────────────────────────────────


class TestVersionGt:
    def test_greater_patch(self) -> None:
        assert _version_gt("0.3.6", "0.3.5") is True

    def test_greater_minor(self) -> None:
        assert _version_gt("0.4.0", "0.3.5") is True

    def test_greater_major(self) -> None:
        assert _version_gt("1.0.0", "0.9.9") is True

    def test_less(self) -> None:
        assert _version_gt("0.3.0", "0.3.5") is False

    def test_equal(self) -> None:
        assert _version_gt("0.3.5", "0.3.5") is False

    def test_prerelease_stripped(self) -> None:
        # "0.4.0a1" numeric parts → (0, 4, 0), same as "0.4.0"
        assert _version_gt("0.4.0a1", "0.3.5") is True

    def test_empty_strings(self) -> None:
        assert _version_gt("", "") is False

    def test_non_numeric(self) -> None:
        assert _version_gt("bad", "also-bad") is False


# ── _load_cache ───────────────────────────────────────────────────────────────


class TestLoadCache:
    def test_fresh_cache_returned(self, tmp_path: Path) -> None:
        cache = tmp_path / "update_check.json"
        cache.write_text(
            json.dumps(
                {
                    "version": "1.0.0",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        )
        result = _load_cache(cache)
        assert result is not None
        assert result["version"] == "1.0.0"

    def test_stale_cache_returns_none(self, tmp_path: Path) -> None:
        cache = tmp_path / "update_check.json"
        old = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        cache.write_text(json.dumps({"version": "1.0.0", "checked_at": old}))
        assert _load_cache(cache) is None

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert _load_cache(tmp_path / "nonexistent.json") is None

    def test_corrupted_json_returns_none(self, tmp_path: Path) -> None:
        cache = tmp_path / "update_check.json"
        cache.write_text("not valid json!!!")
        assert _load_cache(cache) is None

    def test_missing_key_returns_none(self, tmp_path: Path) -> None:
        cache = tmp_path / "update_check.json"
        cache.write_text(json.dumps({"version": "1.0.0"}))  # no checked_at
        assert _load_cache(cache) is None


# ── _save_cache ───────────────────────────────────────────────────────────────


class TestSaveCache:
    def test_writes_version_and_timestamp(self, tmp_path: Path) -> None:
        cache = tmp_path / "sub" / "update_check.json"
        _save_cache("1.2.3", cache)
        data = json.loads(cache.read_text())
        assert data["version"] == "1.2.3"
        assert "checked_at" in data

    def test_silently_ignores_write_error(self, tmp_path: Path) -> None:
        # Make parent a file so mkdir fails — should not raise
        blocker = tmp_path / "blocker"
        blocker.write_text("I am a file")
        _save_cache("1.0.0", blocker / "update_check.json")


# ── _fetch_latest_version ────────────────────────────────────────────────────


class TestFetchLatestVersion:
    def test_parses_pypi_response(self) -> None:
        body = json.dumps({"info": {"version": "9.9.9"}}).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            assert _fetch_latest_version() == "9.9.9"

    def test_returns_none_on_network_error(self) -> None:
        with patch("urllib.request.urlopen", side_effect=OSError("timeout")):
            assert _fetch_latest_version() is None


# ── _find_uv ─────────────────────────────────────────────────────────────────


class TestFindUv:
    def test_returns_path_when_found(self) -> None:
        with patch("shutil.which", return_value="/usr/bin/uv"):
            assert _find_uv() == "/usr/bin/uv"

    def test_returns_none_when_not_found(self) -> None:
        with patch("shutil.which", return_value=None):
            assert _find_uv() is None


# ── check_for_update ──────────────────────────────────────────────────────────


class TestCheckForUpdate:
    def test_update_available_from_fresh_cache(self, tmp_path: Path) -> None:
        cache = tmp_path / "update_check.json"
        cache.write_text(
            json.dumps(
                {
                    "version": "99.0.0",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        )
        with patch("pydantic_deep.__version__", "0.1.0"):
            result = check_for_update(cache)
        assert result == UpdateInfo(current="0.1.0", latest="99.0.0")

    def test_no_update_from_fresh_cache(self, tmp_path: Path) -> None:
        cache = tmp_path / "update_check.json"
        cache.write_text(
            json.dumps(
                {
                    "version": "0.1.0",
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                }
            )
        )
        with patch("pydantic_deep.__version__", "99.0.0"):
            assert check_for_update(cache) is None

    def test_fetches_from_pypi_when_no_cache(self, tmp_path: Path) -> None:
        cache = tmp_path / "update_check.json"
        with (
            patch("apps.cli.update._fetch_latest_version", return_value="99.0.0"),
            patch("pydantic_deep.__version__", "0.1.0"),
        ):
            result = check_for_update(cache)
        assert result is not None
        assert result.latest == "99.0.0"
        # Cache should now be written
        assert cache.exists()

    def test_returns_none_when_fetch_fails(self, tmp_path: Path) -> None:
        cache = tmp_path / "update_check.json"
        with patch("apps.cli.update._fetch_latest_version", return_value=None):
            assert check_for_update(cache) is None

    def test_uses_default_cache_path_when_none_given(self) -> None:
        with (
            patch("apps.cli.update._load_cache", return_value=None),
            patch("apps.cli.update._fetch_latest_version", return_value=None),
        ):
            result = check_for_update()
        assert result is None


# ── run_update ────────────────────────────────────────────────────────────────


class TestRunUpdate:
    def test_uses_uv_when_available(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        with (
            patch("apps.cli.update._find_uv", return_value="/usr/bin/uv"),
            patch("subprocess.run", return_value=mock_proc) as mock_run,
        ):
            code = run_update()
        assert code == 0
        mock_run.assert_called_once_with(["/usr/bin/uv", "tool", "upgrade", "pydantic-deep"])

    def test_falls_back_to_pip_without_uv(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        with (
            patch("apps.cli.update._find_uv", return_value=None),
            patch("subprocess.run", return_value=mock_proc) as mock_run,
        ):
            code = run_update()
        assert code == 0
        args = mock_run.call_args[0][0]
        assert args[0] == sys.executable
        assert "pip" in args
        assert "pydantic-deep[cli]" in args

    def test_propagates_nonzero_exit_code(self) -> None:
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        with (
            patch("apps.cli.update._find_uv", return_value="/usr/bin/uv"),
            patch("subprocess.run", return_value=mock_proc),
        ):
            assert run_update() == 1
