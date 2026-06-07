"""File-upload handling for the gateway.

Saves uploaded files under ``<session cwd>/uploads/`` so the agent's file tools
(rooted at the same cwd) can read them. Filenames are reduced to their basename
to prevent path traversal.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

UPLOAD_SUBDIR = "uploads"


def save_upload(cwd: str, filename: str | None, data: bytes) -> dict[str, Any]:
    """Write ``data`` to ``<cwd>/uploads/<safe name>`` and return its metadata."""
    safe = Path(filename or "file").name or "file"
    dest_dir = Path(cwd) / UPLOAD_SUBDIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / safe
    dest.write_bytes(data)
    return {"path": f"{UPLOAD_SUBDIR}/{safe}", "name": safe, "size": len(data)}


def list_uploads(cwd: str) -> list[dict[str, Any]]:
    """List files in ``<cwd>/uploads/`` (newest first)."""
    upload_dir = Path(cwd) / UPLOAD_SUBDIR
    if not upload_dir.is_dir():
        return []
    files = [f for f in upload_dir.iterdir() if f.is_file()]
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return [
        {"name": f.name, "path": f"{UPLOAD_SUBDIR}/{f.name}", "size": f.stat().st_size}
        for f in files
    ]


__all__ = ["UPLOAD_SUBDIR", "list_uploads", "save_upload"]
