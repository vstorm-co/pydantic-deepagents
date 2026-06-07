"""Pure helpers shared by every session frontend.

Tool-kind classification, tool-call title derivation, and a self-contained
error heuristic for tool output. These were previously duplicated between the
ACP adapter and the Textual TUI; they live here so all consumers agree.
"""

from __future__ import annotations

from typing import Any

# Tool name → coarse kind string (drives icon/colour choices in any UI).
TOOL_KIND_MAP: dict[str, str] = {
    "read_file": "read",
    "edit_file": "edit",
    "write_file": "edit",
    "ls": "search",
    "glob": "search",
    "grep": "search",
    "execute": "execute",
    "web_search": "search",
    "web_fetch": "fetch",
}

# Substrings that, when a tool result starts with / contains them, mark it as an
# error for display purposes. Kept deliberately small and framework-local so
# `pydantic_deep` never imports from `apps/`.
_ERROR_MARKERS: tuple[str, ...] = (
    "error:",
    "error ",
    "traceback (most recent call last)",
    "exception:",
    "command not found",
    "no such file or directory",
    "permission denied",
    "fatal:",
)


def tool_kind(name: str) -> str:
    """Return the coarse kind for a tool name (``"other"`` if unknown)."""
    return TOOL_KIND_MAP.get(name, "other")


def tool_title(name: str, args: Any, *, max_len: int = 60) -> str:
    """Build a human-readable one-line title for a tool call.

    Mirrors the derivation used by the ACP adapter: surface the most salient
    argument (path / pattern / command / description) after the tool name.
    """
    if isinstance(args, dict):
        for key in ("path", "pattern", "command", "description"):
            value = args.get(key)
            if value:
                return f"{name}: {str(value)[:max_len]}"
    return name


def looks_like_tool_error(text: str) -> bool:
    """Heuristically decide whether a tool result represents an error.

    Conservative: only flags output that clearly contains an error marker, so a
    successful result is never mislabelled.
    """
    if not text:
        return False
    lowered = text.lower()
    return any(marker in lowered for marker in _ERROR_MARKERS)


__all__ = [
    "TOOL_KIND_MAP",
    "looks_like_tool_error",
    "tool_kind",
    "tool_title",
]
