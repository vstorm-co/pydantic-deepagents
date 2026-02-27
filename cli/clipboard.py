"""Clipboard image utilities for the CLI.

Supports grabbing images from the system clipboard on macOS using
``pngpaste`` (preferred, fast) with ``osascript`` as a built-in fallback.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from shutil import which


@dataclass
class ClipboardImage:
    """An image grabbed from the system clipboard."""

    data: bytes
    media_type: str = "image/png"

    def to_binary_content(self):  # type: ignore[no-untyped-def]
        """Convert to pydantic-ai ``BinaryContent``."""
        from pydantic_ai.messages import BinaryContent

        return BinaryContent(data=self.data, media_type=self.media_type)


def get_clipboard_image() -> ClipboardImage | None:
    """Get image data from the system clipboard.

    Returns:
        :class:`ClipboardImage` or ``None`` if no image in clipboard.
    """
    if sys.platform != "darwin":
        return None

    # Method 1: pngpaste — fast, single subprocess call
    pngpaste = which("pngpaste")
    if pngpaste:
        try:
            result = subprocess.run(
                [pngpaste, "-"],
                capture_output=True,
                timeout=3,
            )
            if result.returncode == 0 and result.stdout:
                return ClipboardImage(data=result.stdout)
        except (subprocess.TimeoutExpired, OSError):
            pass

    # Method 2: osascript fallback (built-in on macOS)
    return _get_clipboard_via_osascript()


def _get_clipboard_via_osascript() -> ClipboardImage | None:
    """Grab clipboard image via AppleScript."""
    osascript = which("osascript")
    if not osascript:
        return None  # pragma: no cover

    try:
        # Check if clipboard contains image data
        check = subprocess.run(
            [osascript, "-e", "clipboard info"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        info = check.stdout.lower()
        if "pngf" not in info and "tiff" not in info:
            return None

        # Write clipboard PNG to temp file
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name

        script = (
            "set pngData to the clipboard as «class PNGf»\n"
            f'set theFile to open for access POSIX file "{tmp_path}" '
            "with write permission\n"
            "write pngData to theFile\n"
            "close access theFile\n"
        )

        result = subprocess.run(
            [osascript, "-e", script],
            capture_output=True,
            timeout=5,
        )

        tmp_file = Path(tmp_path)
        try:
            if result.returncode == 0:
                data = tmp_file.read_bytes()
                if data:
                    return ClipboardImage(data=data)
        finally:
            tmp_file.unlink(missing_ok=True)

    except (subprocess.TimeoutExpired, OSError):
        pass

    return None


__all__ = ["ClipboardImage", "get_clipboard_image"]
