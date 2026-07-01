"""Read images from the system clipboard for multimodal prompts.

Tries several strategies in order so the feature works out-of-the-box without
extra dependencies on macOS (via ``osascript``), and still supports Pillow /
``pngpaste`` when present. Returns raw PNG bytes + media type, or ``None`` when
the clipboard holds no image.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

__all__ = ["grab_clipboard_image", "ClipboardImage"]

# (data, media_type) for a grabbed clipboard image.
ClipboardImage = tuple[bytes, str]


def _grab_via_pillow() -> ClipboardImage | None:
    """Cross-platform grab using Pillow's ImageGrab, if installed."""
    try:
        from PIL import ImageGrab
    except Exception:
        return None
    try:
        img = ImageGrab.grabclipboard()
    except Exception:
        return None
    if img is None or isinstance(img, list):
        # A list means file paths were copied, not raw image data.
        return None
    import io

    buf = io.BytesIO()
    try:
        img.save(buf, format="PNG")
    except Exception:
        return None
    return buf.getvalue(), "image/png"


def _grab_via_pngpaste() -> ClipboardImage | None:
    """Grab via the ``pngpaste`` CLI (macOS, ``brew install pngpaste``)."""
    if shutil.which("pngpaste") is None:
        return None
    try:
        proc = subprocess.run(["pngpaste", "-"], capture_output=True, timeout=5)
    except Exception:
        return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    return proc.stdout, "image/png"


def _macos_clipboard_has_image() -> bool:
    """True when the macOS clipboard contains PNG or TIFF image data."""
    try:
        info = subprocess.run(
            ["osascript", "-e", "clipboard info"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return False
    out = info.stdout or ""
    return "PNGf" in out or "TIFF picture" in out or "class PNGf" in out


def _grab_via_osascript() -> ClipboardImage | None:
    """Grab on macOS using only the always-present ``osascript`` binary.

    Dumps the clipboard PNG payload to a temp file via AppleScript, then reads
    the bytes back. Returns ``None`` if the clipboard has no PNG image.
    """
    if sys.platform != "darwin":
        return None
    if not _macos_clipboard_has_image():
        return None

    fd, name = tempfile.mkstemp(suffix=".png")
    os.close(fd)  # we only need the path; AppleScript writes the bytes
    tmp = Path(name)
    script = (
        f'set theFile to (POSIX file "{tmp}")\n'
        "set fh to open for access theFile with write permission\n"
        "try\n"
        "    write (the clipboard as «class PNGf») to fh\n"
        "    close access fh\n"
        "on error errMsg\n"
        "    close access fh\n"
        "    error errMsg\n"
        "end try\n"
    )
    try:
        proc = subprocess.run(
            ["osascript", "-e", script], capture_output=True, text=True, timeout=10
        )
        if proc.returncode != 0:
            return None
        data = tmp.read_bytes()
        if not data:
            return None
        return data, "image/png"
    except Exception:
        return None
    finally:
        with contextlib.suppress(Exception):
            tmp.unlink()


def grab_clipboard_image() -> ClipboardImage | None:
    """Return ``(png_bytes, media_type)`` from the clipboard, or ``None``.

    Strategy order: Pillow (cross-platform) -> ``pngpaste`` -> macOS
    ``osascript``. The first that yields image bytes wins.
    """
    for grabber in (_grab_via_pillow, _grab_via_pngpaste, _grab_via_osascript):
        result = grabber()
        if result is not None:
            return result
    return None
