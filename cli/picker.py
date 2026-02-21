"""Interactive terminal picker for the CLI.

Provides an arrow-key navigable inline selection list with real-time
fuzzy filtering.  Uses Rich for styling and raw terminal I/O for input.
Falls back to numbered input in non-TTY environments.
"""

from __future__ import annotations

import select as _select
import sys
import termios
import tty
from dataclasses import dataclass
from typing import Any

from rich.console import Console


@dataclass
class PickerItem:
    """An item in the interactive picker."""

    label: str
    """Main display text (Rich markup supported)."""
    value: Any
    """Arbitrary value returned on selection."""
    description: str = ""
    """Secondary text shown below label (Rich markup supported)."""


def _read_key() -> str:
    """Read a single keypress, handling escape sequences.

    Uses ``os.read`` instead of ``sys.stdin.read`` to bypass Python's
    internal IO buffer.  With ``sys.stdin.read`` the runtime may consume
    all available bytes (e.g. the full ``\\x1b[A`` arrow sequence) into
    its buffer while ``select.select`` on the raw fd sees nothing left,
    causing arrow keys to be mis-detected as bare Escape.
    """
    import os

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = os.read(fd, 1).decode("utf-8", errors="replace")
        if ch == "\x1b":
            # Check if more bytes follow (escape sequence vs bare Escape)
            if _select.select([fd], [], [], 0.05)[0]:
                ch2 = os.read(fd, 1).decode("utf-8", errors="replace")
                if ch2 == "[":
                    ch3 = os.read(fd, 1).decode("utf-8", errors="replace")
                    return {"A": "up", "B": "down"}.get(ch3, "unknown")
                return "unknown"
            return "escape"
        if ch in ("\r", "\n"):
            return "enter"
        if ch == "\x7f" or ch == "\x08":
            return "backspace"
        if ch == "\x03":
            return "interrupt"
        # Printable ASCII
        if ch.isprintable() and len(ch) == 1:
            return ch
        return "unknown"
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _numbered_fallback(
    items: list[PickerItem],
    *,
    title: str,
    console: Console,
) -> PickerItem | None:
    """Numbered selection fallback for non-TTY environments."""
    console.print(f"\n[bold]{title}[/bold]\n")
    for i, item in enumerate(items, 1):
        console.print(f"  {i}. {item.label}")
        if item.description:
            console.print(f"     [dim]{item.description}[/dim]")
    console.print()
    try:
        choice = input("Select number (or Enter to cancel): ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if not choice:
        return None
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(items):
            return items[idx]
    except ValueError:
        pass
    return None


def _fuzzy_match(query: str, text: str) -> bool:
    """Check if all characters of *query* appear in *text* in order (case-insensitive)."""
    q = query.lower()
    t = text.lower()
    qi = 0
    for ch in t:
        if qi < len(q) and ch == q[qi]:
            qi += 1
    return qi == len(q)


def interactive_select(
    items: list[PickerItem],
    *,
    title: str = "Select",
    empty_message: str = "No items available.",
    console: Console | None = None,
    max_visible: int = 10,
    filterable: bool = True,
) -> PickerItem | None:
    """Interactive picker with arrow-key navigation and fuzzy filtering.

    Renders a list of items inline in the terminal. Navigate with
    arrow keys (or j/k), select with Enter, cancel with Esc.

    When *filterable* is True (default), typing characters filters the
    list in real time using fuzzy matching.

    Falls back to numbered input in non-TTY environments.

    Args:
        items: List of PickerItem to choose from.
        title: Title displayed above the list.
        empty_message: Message shown when items is empty.
        console: Rich Console to use for output.
        max_visible: Maximum number of items visible at once.
        filterable: Enable real-time fuzzy filtering.

    Returns:
        Selected PickerItem, or None if cancelled.
    """
    con = console or Console(highlight=False)

    if not items:
        con.print(f"[dim]{empty_message}[/dim]")
        return None

    if not sys.stdin.isatty():
        return _numbered_fallback(items, title=title, console=con)

    all_items = items
    query = ""
    filtered = list(all_items)
    cursor = 0

    def _apply_filter() -> None:
        nonlocal filtered, cursor
        if not query:
            filtered = list(all_items)
        else:
            filtered = [it for it in all_items if _fuzzy_match(query, it.label)]
        cursor = 0

    def _build() -> list[str]:
        n = len(filtered)
        vis = min(n, max_visible)
        out: list[str] = [""]

        # Title with search query
        if filterable and query:
            from rich.markup import escape
            out.append(f" [bold]{title}[/bold]  [cyan]{escape(query)}[/cyan]")
        else:
            out.append(f" [bold]{title}[/bold]")

        out.append("")

        if not filtered:
            out.append(f"   [dim]No matches for \"{query}\"[/dim]")
            out += ["", " [dim]\u2191\u2193 navigate  Enter select  esc cancel[/dim]"]
            return out

        # Calculate visible window around cursor
        if n <= vis:
            lo, hi = 0, n
        else:
            half = vis // 2
            lo = max(0, cursor - half)
            hi = min(n, lo + vis)
            if hi == n:
                lo = n - vis

        if lo > 0:
            out.append("   [dim]\u2191 more[/dim]")

        for i in range(lo, hi):
            it = filtered[i]
            if i == cursor:
                out.append(f"  [bold cyan]\u276f {it.label}[/bold cyan]")
                if it.description:
                    out.append(f"    [cyan]{it.description}[/cyan]")
            else:
                out.append(f"    {it.label}")
                if it.description:
                    out.append(f"    [dim]{it.description}[/dim]")

        if hi < n:
            out.append(f"   [dim]\u2193 more ({n - hi})[/dim]")

        hint = "\u2191\u2193 navigate  Enter select  esc cancel"
        if filterable:
            hint = "Type to filter  " + hint
        out += ["", f" [dim]{hint}[/dim]"]
        return out

    def _draw(lines: list[str]) -> int:
        for line in lines:
            con.print(line)
        return len(lines)

    def _clear(count: int) -> None:
        sys.stdout.write(f"\x1b[{count}A\x1b[J")
        sys.stdout.flush()

    built = _build()
    lc = _draw(built)

    try:
        while True:
            key = _read_key()
            n = len(filtered)

            if key in ("up", "k") and not query:
                if n > 0:
                    cursor = (cursor - 1) % n
            elif key == "up":
                if n > 0:
                    cursor = (cursor - 1) % n
            elif key in ("down", "j") and not query:
                if n > 0:
                    cursor = (cursor + 1) % n
            elif key == "down":
                if n > 0:
                    cursor = (cursor + 1) % n
            elif key == "enter":
                _clear(lc)
                if filtered:
                    return filtered[cursor]
                return None
            elif key in ("escape", "interrupt"):
                _clear(lc)
                return None
            elif key == "backspace" and filterable:
                if query:
                    query = query[:-1]
                    _apply_filter()
                else:
                    _clear(lc)
                    return None
            elif filterable and len(key) == 1 and key.isprintable():
                query += key
                _apply_filter()
            else:
                continue

            _clear(lc)
            built = _build()
            lc = _draw(built)
    except (EOFError, KeyboardInterrupt):
        _clear(lc)
        return None


__all__ = ["PickerItem", "interactive_select"]
