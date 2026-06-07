"""Screen capture → attach-to-agent helper.

Captures the screen into the session's ``uploads/`` folder so the agent can
read it. macOS uses the built-in ``screencapture``; other platforms raise a
clear error the UI surfaces.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def take_screenshot(cwd: str) -> dict[str, Any]:
    """Capture the screen to ``<cwd>/uploads/`` and return the file metadata."""
    if sys.platform != "darwin":
        raise RuntimeError("Screen capture is currently supported on macOS only.")

    dest_dir = Path(cwd) / "uploads"
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = f"screenshot-{int(time.time())}.png"
    dest = dest_dir / name
    # -x silences the capture sound; capture the whole screen.
    subprocess.run(["screencapture", "-x", str(dest)], check=True, timeout=20)
    return {"path": f"uploads/{name}", "name": name, "size": dest.stat().st_size}


__all__ = ["take_screenshot"]
