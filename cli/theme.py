"""Theme and glyph system for the pydantic-deep CLI.

Provides a configurable color palette and Unicode/ASCII glyph sets with
automatic terminal capability detection.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    """Terminal color palette."""

    name: str
    # Brand
    primary: str
    accent: str
    # Status
    success: str
    warning: str
    error: str
    info: str
    # Text
    text: str
    muted: str


DEFAULT_THEME = Theme(
    name="default",
    primary="green",
    accent="cyan",
    success="green",
    warning="yellow",
    error="red",
    info="blue",
    text="white",
    muted="dim",
)

MINIMAL_THEME = Theme(
    name="minimal",
    primary="blue",
    accent="cyan",
    success="green",
    warning="yellow",
    error="red",
    info="blue",
    text="white",
    muted="dim",
)

_THEMES: dict[str, Theme] = {
    "default": DEFAULT_THEME,
    "minimal": MINIMAL_THEME,
}


def get_theme(name: str | None = None) -> Theme:
    """Get a theme by name.

    Falls back to the default theme for unknown names.
    """
    if name is None:
        name = os.environ.get("PYDANTIC_DEEP_THEME", "default")
    return _THEMES.get(name, DEFAULT_THEME)


@dataclass(frozen=True)
class Glyphs:
    """Character set for terminal output."""

    # Tool calls
    tool: str
    arrow: str
    lightning: str

    # Status
    success: str
    error: str
    warning: str
    pending: str
    active: str

    # UI
    bullet: str
    ellipsis: str
    separator: str


UNICODE_GLYPHS = Glyphs(
    tool="\u23fa",  # ⏺
    arrow="\u2192",  # →
    lightning="\u26a1",  # ⚡
    success="\u2713",  # ✓
    error="\u2717",  # ✗
    warning="\u26a0",  # ⚠
    pending="\u25cb",  # ○
    active="\u25cf",  # ●
    bullet="\u2022",  # •
    ellipsis="\u2026",  # …
    separator="\u2500",  # ─
)

ASCII_GLYPHS = Glyphs(
    tool="(*)",
    arrow="->",
    lightning="!",
    success="[OK]",
    error="[X]",
    warning="[!]",
    pending="[ ]",
    active="[*]",
    bullet="-",
    ellipsis="...",
    separator="-",
)


def detect_unicode_support() -> bool:
    """Detect whether the terminal supports Unicode output."""
    override = os.environ.get("PYDANTIC_DEEP_CHARSET", "auto").lower()
    if override == "unicode":
        return True
    if override == "ascii":
        return False

    # Check stdout encoding
    encoding = getattr(sys.stdout, "encoding", "") or ""
    if "utf" in encoding.lower():
        return True

    # Check LANG / LC_ALL
    for var in ("LANG", "LC_ALL", "LC_CTYPE"):
        val = os.environ.get(var, "")
        if "utf" in val.lower():
            return True

    return False


def get_glyphs() -> Glyphs:
    """Get the appropriate glyph set for the current terminal."""
    return UNICODE_GLYPHS if detect_unicode_support() else ASCII_GLYPHS


__all__ = [
    "ASCII_GLYPHS",
    "DEFAULT_THEME",
    "Glyphs",
    "MINIMAL_THEME",
    "Theme",
    "UNICODE_GLYPHS",
    "detect_unicode_support",
    "get_glyphs",
    "get_theme",
]
