"""Custom theme definitions for the pydantic-deep TUI.

Themes are registered as Textual Theme objects and can be switched
via config.toml `theme` key or the `/theme` command.
"""

from __future__ import annotations

from typing import Any

THEMES: dict[str, dict[str, str]] = {
    "default": {
        "primary": "#10b981",
        "accent": "#6ee7b7",
        "error": "#ef4444",
        "warning": "#f59e0b",
    },
    "ocean": {
        "primary": "#3b82f6",
        "accent": "#93c5fd",
        "error": "#ef4444",
        "warning": "#f59e0b",
    },
    "rose": {
        "primary": "#f43f5e",
        "accent": "#fda4af",
        "error": "#ef4444",
        "warning": "#f59e0b",
    },
    "minimal": {
        "primary": "#a0a0a0",
        "accent": "#d0d0d0",
        "error": "#ef4444",
        "warning": "#f59e0b",
    },
}


def register_themes(app: Any) -> None:
    """Register all custom themes with the Textual app."""
    try:
        from textual.theme import Theme as TextualTheme
    except ImportError:  # pragma: no cover
        return

    for name, colors in THEMES.items():
        theme_name = f"deep-{name}" if name != "default" else "deep-default"
        try:
            theme = TextualTheme(
                name=theme_name,
                primary=colors["primary"],
                accent=colors["accent"],
                error=colors.get("error", "#ef4444"),
                warning=colors.get("warning", "#f59e0b"),
                dark=True,
            )
            app.register_theme(theme)
        except Exception:
            pass


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

    textual_name = f"deep-{theme_name}" if theme_name != "default" else "deep-default"
    try:
        app.theme = textual_name
        return True
    except Exception:
        return False


def available_themes() -> list[str]:
    """Return list of available theme names."""
    return list(THEMES.keys())
