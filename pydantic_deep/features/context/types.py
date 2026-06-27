"""Data types for the context-files feature."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ContextFile:
    """A loaded project context file."""

    name: str
    """Filename: "AGENTS.md"."""
    path: str
    """Full path: "/project/AGENTS.md"."""
    content: str
    """File content."""
