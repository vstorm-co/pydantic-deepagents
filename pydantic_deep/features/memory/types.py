"""Data types for the memory feature."""

from __future__ import annotations

from dataclasses import dataclass


class MemoryAccessError(Exception):
    """The backend denied access to the memory path.

    Raised by `load_memory` when a read fails for a reason other than the
    file being missing or empty (e.g. the memory directory is outside the
    backend's allowed directories). This keeps a genuine permission/backend
    failure distinguishable from "no memory saved yet" — see issue #135.
    """


@dataclass
class MemoryFile:
    """A loaded agent memory file."""

    agent_name: str
    """Agent that owns this memory: "main", "code-reviewer", etc."""
    path: str
    """Full path in backend: "/.deep/memory/main/MEMORY.md"."""
    content: str
    """Memory file content."""
