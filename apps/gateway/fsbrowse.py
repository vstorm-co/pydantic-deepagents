"""Filesystem browsing for the desktop app's `@` file picker and folder chooser.

The desktop app operates on the real local filesystem (loopback + token gated),
so it can browse the user's machine to pick working folders and files.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def browse(path: str | None) -> dict[str, Any]:
    """List a directory. Defaults to the user's home when ``path`` is empty.

    Returns the resolved path, its parent, and entries (directories first).
    Hidden dotfiles are included but sorted after visible ones.
    """
    base = Path(path).expanduser() if path else Path.home()
    try:
        base = base.resolve()
    except OSError:
        base = Path.home()
    if not base.is_dir():
        base = base.parent if base.parent.is_dir() else Path.home()

    entries: list[dict[str, Any]] = []
    try:
        for child in base.iterdir():
            try:
                is_dir = child.is_dir()
            except OSError:
                continue
            entries.append({"name": child.name, "is_dir": is_dir, "path": str(child)})
    except PermissionError:
        entries = []

    entries.sort(key=lambda e: (not e["is_dir"], e["name"].startswith("."), e["name"].lower()))

    parent = str(base.parent) if base.parent != base else None
    return {"path": str(base), "parent": parent, "entries": entries}


__all__ = ["browse"]
