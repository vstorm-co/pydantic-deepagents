"""Tests for clipboard image grabbing (apps/cli/clipboard_image.py)."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.cli import clipboard_image as ci

# A 1x1 transparent PNG.
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_grab_prefers_first_non_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ci, "_grab_via_pillow", lambda: None)
    monkeypatch.setattr(ci, "_grab_via_pngpaste", lambda: (_PNG, "image/png"))
    monkeypatch.setattr(ci, "_grab_via_osascript", lambda: (b"never", "image/png"))
    result = ci.grab_clipboard_image()
    assert result is not None
    data, mt = result
    assert data == _PNG
    assert mt == "image/png"


def test_grab_returns_none_when_all_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ci, "_grab_via_pillow", lambda: None)
    monkeypatch.setattr(ci, "_grab_via_pngpaste", lambda: None)
    monkeypatch.setattr(ci, "_grab_via_osascript", lambda: None)
    assert ci.grab_clipboard_image() is None


def test_pngpaste_missing_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: None)
    assert ci._grab_via_pngpaste() is None


def test_pngpaste_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/pngpaste")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=0, stdout=_PNG),
    )
    result = ci._grab_via_pngpaste()
    assert result == (_PNG, "image/png")


def test_pngpaste_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/pngpaste")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout=b""),
    )
    assert ci._grab_via_pngpaste() is None


def test_osascript_non_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert ci._grab_via_osascript() is None


def test_osascript_no_image(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(ci, "_macos_clipboard_has_image", lambda: False)
    assert ci._grab_via_osascript() is None


def test_osascript_success(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(ci, "_macos_clipboard_has_image", lambda: True)

    target = tmp_path / "clip.png"
    target.write_bytes(_PNG)
    monkeypatch.setattr(tempfile, "mkstemp", lambda suffix="": (0, str(target)))

    def fake_run(*args: object, **kwargs: object) -> SimpleNamespace:
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    # File is unlinked in finally; capture bytes before by reading inside run.
    result = ci._grab_via_osascript()
    assert result is not None
    assert result[1] == "image/png"


def test_macos_clipboard_has_image(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout="«class PNGf», 1234", stderr=""),
    )
    assert ci._macos_clipboard_has_image() is True

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout="«class utf8», 10", stderr=""),
    )
    assert ci._macos_clipboard_has_image() is False


def test_macos_clipboard_info_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*a, **k):
        raise subprocess.SubprocessError("nope")

    monkeypatch.setattr(subprocess, "run", boom)
    assert ci._macos_clipboard_has_image() is False
