"""Data types for the memory feature."""

from __future__ import annotations

from dataclasses import dataclass


class MemoryAccessError(Exception):
    """The workspace refused the memory path.

    Raised by `load_memory` when a read fails for a reason other than the
    file being missing or empty (permission denied, or a directory where the
    file should be). This keeps a genuine permission failure distinguishable
    from "no memory saved yet" — see issue #135.
    """


@dataclass
class MemoryFile:
    """A loaded agent memory file."""

    agent_name: str
    """Agent that owns this memory: "main", "code-reviewer", etc."""
    path: str
    """Path in the workspace: ".deep/memory/main/MEMORY.md"."""
    content: str
    """Memory file content."""
