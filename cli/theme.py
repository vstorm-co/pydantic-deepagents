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
    primary="#10b981",  # Emerald
    accent="#34d399",  # Light emerald
    success="#10b981",
    warning="#fbbf24",  # Amber
    error="#ef4444",  # Red
    info="#3b82f6",  # Blue
    text="#e5e7eb",  # Light gray
    muted="#6b7280",  # Gray
)

CLASSIC_THEME = Theme(
    name="classic",
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
    "classic": CLASSIC_THEME,
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
    tool_prefix: str
    output_prefix: str

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

    # Diff display
    gutter_bar: str
    box_vertical: str

    # Progress bar
    progress_filled: str
    progress_empty: str

    # Animation
    spinner_frames: tuple[str, ...]


UNICODE_GLYPHS = Glyphs(
    tool="\u25b8",  # ▸
    arrow="\u2514\u2500",  # └─
    lightning="\u25b8",  # ▸
    tool_prefix="\u23fa",  # ⏺
    output_prefix="\u23bf",  # ⎿
    success="\u2713",  # ✓
    error="\u2717",  # ✗
    warning="!",
    pending="\u25cb",  # ○
    active="\u25cf",  # ●
    bullet="\u2022",  # •
    ellipsis="\u2026",  # …
    separator="\u2500",  # ─
    gutter_bar="\u258c",  # ▌
    box_vertical="\u2502",  # │
    progress_filled="\u2588",  # █
    progress_empty="\u2591",  # ░
    spinner_frames=(
        "\u280b",
        "\u2819",
        "\u2839",
        "\u2838",
        "\u283c",
        "\u2834",
        "\u2826",
        "\u2827",
        "\u2807",
        "\u280f",
    ),
)

ASCII_GLYPHS = Glyphs(
    tool=">",
    arrow="`-",
    lightning=">",
    tool_prefix="(*)",
    output_prefix="|",
    success="ok",
    error="x",
    warning="!",
    pending="[ ]",
    active="[*]",
    bullet="-",
    ellipsis="...",
    separator="-",
    gutter_bar="|",
    box_vertical="|",
    progress_filled="#",
    progress_empty="-",
    spinner_frames=("-", "\\", "|", "/"),
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
    "CLASSIC_THEME",
    "DEFAULT_THEME",
    "Glyphs",
    "MINIMAL_THEME",
    "Theme",
    "UNICODE_GLYPHS",
    "detect_unicode_support",
    "get_glyphs",
    "get_theme",
]
