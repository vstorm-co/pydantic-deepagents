"""Interactive terminal pickers for the CLI (arrow-select + type).

Thin wrappers over prompt_toolkit dialogs so `keys` and `models` can open a
selectable list and a hidden input instead of asking the user to type a number.
Each returns ``None`` when the user cancels (Esc / Ctrl-C).
"""

from __future__ import annotations

from typing import TypeVar

T = TypeVar("T")


def pick(title: str, text: str, choices: list[tuple[T, str]]) -> T | None:
    """Open an arrow-selectable radio list; return the chosen value or None."""
    if not choices:
        return None
    from prompt_toolkit.shortcuts import radiolist_dialog

    return radiolist_dialog(
        title=title,
        text=text,
        values=[(value, label) for value, label in choices],
    ).run()


def ask_value(title: str, text: str, *, password: bool = False) -> str | None:
    """Open an input dialog; return the entered string (or None if cancelled)."""
    from prompt_toolkit.shortcuts import input_dialog

    return input_dialog(title=title, text=text, password=password).run()


__all__ = ["ask_value", "pick"]
