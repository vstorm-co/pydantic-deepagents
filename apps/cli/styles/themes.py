"""Custom theme definitions for the pydantic-deep TUI.

Each theme is a full, cohesive dark palette (background → surface → panel,
foreground, and primary/secondary/accent) registered as a Textual ``Theme``.
Selected via the ``theme`` config key or the ``/theme`` command. The brand
theme is ``default`` (emerald/teal) and is always applied — the TUI never
falls back to Textual's stock palette.
"""

from __future__ import annotations

import contextlib
from typing import Any

#: Full palettes. Keys map 1:1 onto Textual ``Theme`` constructor arguments.
THEMES: dict[str, dict[str, str]] = {
    # Brand: warm amber on near-black, warm-tinted ink (Tau-inspired).
    "default": {
        "primary": "#d98e48",
        "secondary": "#c2703a",
        "accent": "#f0b072",
        "foreground": "#e9e1d4",
        "background": "#0c0a07",
        "surface": "#15110c",
        "panel": "#211a12",
        "success": "#6fcf97",
        "warning": "#fbbf24",
        "error": "#ef4444",
    },
    # Cool emerald/teal — the previous brand, kept as an option.
    "emerald": {
        "primary": "#10b981",
        "secondary": "#14b8a6",
        "accent": "#5eead4",
        "foreground": "#e6edeb",
        "background": "#0b0f0e",
        "surface": "#111816",
        "panel": "#172521",
        "success": "#10b981",
        "warning": "#f59e0b",
        "error": "#ef4444",
    },
    # Cool blue/cyan.
    "ocean": {
        "primary": "#3b82f6",
        "secondary": "#06b6d4",
        "accent": "#7dd3fc",
        "foreground": "#e6edf3",
        "background": "#0a0f1a",
        "surface": "#111827",
        "panel": "#1b2740",
        "success": "#22c55e",
        "warning": "#f59e0b",
        "error": "#ef4444",
    },
    # Warm rose/magenta.
    "rose": {
        "primary": "#f43f5e",
        "secondary": "#ec4899",
        "accent": "#fda4af",
        "foreground": "#f5e9ec",
        "background": "#140a0d",
        "surface": "#1c1117",
        "panel": "#2a1923",
        "success": "#10b981",
        "warning": "#f59e0b",
        "error": "#ef4444",
    },
    # Monochrome, near-zero hue — pure minimalist.
    "minimal": {
        "primary": "#b4b4b4",
        "secondary": "#8a8a8a",
        "accent": "#ededed",
        "foreground": "#ededed",
        "background": "#0c0c0c",
        "surface": "#161616",
        "panel": "#202020",
        "success": "#9ca3af",
        "warning": "#d4d4d4",
        "error": "#ef4444",
    },
}

_DEEP_PREFIX = "deep-"


def _theme_name(name: str) -> str:
    """Map a short theme name to its registered Textual theme name."""
    return f"{_DEEP_PREFIX}{name}"


def register_themes(app: Any) -> None:
    """Register all custom themes with the Textual app."""
    try:
        from textual.theme import Theme as TextualTheme
    except ImportError:  # pragma: no cover
        return

    for name, colors in THEMES.items():
        with contextlib.suppress(Exception):
            app.register_theme(
                TextualTheme(
                    name=_theme_name(name),
                    primary=colors["primary"],
                    secondary=colors.get("secondary"),
                    accent=colors.get("accent"),
                    foreground=colors.get("foreground"),
                    background=colors.get("background"),
                    surface=colors.get("surface"),
                    panel=colors.get("panel"),
                    success=colors.get("success", "#10b981"),
                    warning=colors.get("warning", "#f59e0b"),
                    error=colors.get("error", "#ef4444"),
                    dark=True,
                )
            )


def apply_theme(app: Any, theme_name: str) -> bool:
    """Apply a named theme to the app.

    Args:
        app: The Textual App instance.
        theme_name: One of 'default', 'ocean', 'rose', 'minimal'.

    Returns:
        True if theme was applied successfully, False otherwise.
    """
    if theme_name not in THEMES:
        return False

    try:
        app.theme = _theme_name(theme_name)
        return True
    except Exception:
        return False


def available_themes() -> list[str]:
    """Return list of available theme names."""
    return list(THEMES.keys())
