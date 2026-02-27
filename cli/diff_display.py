"""Diff and file preview rendering for tool calls.

Provides colored unified diffs with gutter bars for ``edit_file`` approvals,
syntax-highlighted content previews for ``write_file``, and inline
change previews shown after tool execution.
"""

from __future__ import annotations

import difflib
from pathlib import PurePath

from cli.theme import get_glyphs, get_theme


def _escape_markup(text: str) -> str:
    """Escape Rich markup characters ``[`` and ``]``."""
    return text.replace("[", r"\[").replace("]", r"\]")


def format_diff_rich(diff_text: str, *, max_lines: int = 80) -> str:
    """Format a unified diff with colored gutter bars.

    Additions get a green gutter bar, deletions get a red gutter bar,
    and context lines get a dim vertical bar.

    Returns a Rich markup string ready for ``console.print()``.
    """
    theme = get_theme()
    glyphs = get_glyphs()
    lines = diff_text.splitlines()
    out: list[str] = []
    additions = 0
    deletions = 0
    shown = 0

    for line in lines:
        # Skip diff headers (---, +++, @@)
        if line.startswith("---") or line.startswith("+++"):
            continue
        if line.startswith("@@"):
            out.append(f"[{theme.info}]{_escape_markup(line)}[/{theme.info}]")
            shown += 1
            continue

        if shown >= max_lines:
            remaining = len(lines) - shown
            if remaining > 0:
                msg = f"{glyphs.ellipsis} {remaining} more lines"
                out.append(f"[{theme.muted}]{msg}[/{theme.muted}]")
            break

        if line.startswith("+"):
            additions += 1
            out.append(
                f"[bold {theme.success}]{glyphs.gutter_bar}[/bold {theme.success}] "
                f"[{theme.success}]{_escape_markup(line[1:])}[/{theme.success}]"
            )
        elif line.startswith("-"):
            deletions += 1
            out.append(
                f"[bold {theme.error}]{glyphs.gutter_bar}[/bold {theme.error}] "
                f"[{theme.error}]{_escape_markup(line[1:])}[/{theme.error}]"
            )
        else:
            content = line[1:] if line.startswith(" ") else line
            out.append(
                f"[{theme.muted}]{glyphs.box_vertical}[/{theme.muted}] "
                f"[{theme.muted}]{_escape_markup(content)}[/{theme.muted}]"
            )
        shown += 1

    # Stats line
    stats_parts: list[str] = []
    if additions:
        stats_parts.append(f"[{theme.success}]+{additions}[/{theme.success}]")
    if deletions:
        stats_parts.append(f"[{theme.error}]-{deletions}[/{theme.error}]")
    if stats_parts:
        out.append("  " + " ".join(stats_parts))

    return "\n".join(out)


def generate_edit_diff(old_string: str, new_string: str) -> str:
    """Generate a unified diff from edit_file old_string/new_string."""
    old_lines = old_string.splitlines(keepends=True)
    new_lines = new_string.splitlines(keepends=True)
    diff = difflib.unified_diff(old_lines, new_lines, lineterm="")
    return "\n".join(diff)


def render_edit_approval(path: str, old_string: str, new_string: str) -> str:
    """Render the full approval display for an ``edit_file`` call.

    Shows the file path header and a gutter-bar diff with stats.
    """
    theme = get_theme()
    diff_text = generate_edit_diff(old_string, new_string)
    if not diff_text.strip():
        return f"[{theme.muted}](no changes)[/{theme.muted}]"

    header = f"[bold {theme.info}]File:[/bold {theme.info}] {_escape_markup(path)}"
    body = format_diff_rich(diff_text)
    return f"{header}\n{body}"


def render_write_approval(path: str, content: str) -> str:
    """Render the full approval display for a ``write_file`` call.

    Shows the file path header and a syntax-highlighted content preview.
    Large files are truncated with a head/tail preview.
    """
    theme = get_theme()
    glyphs = get_glyphs()

    # Detect language from extension
    ext = PurePath(path).suffix.lstrip(".")
    lang_map = {"py": "python", "js": "javascript", "ts": "typescript", "rb": "ruby"}
    lang = lang_map.get(ext, ext)

    lines = content.splitlines()
    total = len(lines)
    head_n = 20
    tail_n = 10

    header = f"[bold {theme.info}]File:[/bold {theme.info}] {_escape_markup(path)} ({total} lines)"

    if total <= head_n + tail_n:
        # Show all
        preview = "\n".join(
            f"[{theme.muted}]{i + 1:>4}[/{theme.muted}] {_escape_markup(line)}"
            for i, line in enumerate(lines)
        )
    else:
        # Head + tail
        head_lines = [
            f"[{theme.muted}]{i + 1:>4}[/{theme.muted}] {_escape_markup(line)}"
            for i, line in enumerate(lines[:head_n])
        ]
        tail_lines = [
            f"[{theme.muted}]{total - tail_n + i + 1:>4}[/{theme.muted}] {_escape_markup(line)}"
            for i, line in enumerate(lines[-tail_n:])
        ]
        skipped = total - head_n - tail_n
        mid = f"[{theme.muted}]     {glyphs.ellipsis} {skipped} lines omitted[/{theme.muted}]"
        preview = "\n".join(head_lines) + "\n" + mid + "\n" + "\n".join(tail_lines)

    lang_tag = f" [{theme.muted}]{lang}[/{theme.muted}]" if lang else ""
    return f"{header}{lang_tag}\n{preview}"


# ---------------------------------------------------------------------------
# Inline change previews (shown after tool execution)
# ---------------------------------------------------------------------------

_INLINE_MAX_LINES = 12


def render_inline_edit_diff(
    old_string: str,
    new_string: str,
    *,
    max_lines: int = _INLINE_MAX_LINES,
) -> str:
    """Render a compact inline diff for ``edit_file`` changes.

    Shows gutter-bar additions/deletions without headers.
    """
    diff_text = generate_edit_diff(old_string, new_string)
    if not diff_text.strip():
        return ""
    return format_diff_rich(diff_text, max_lines=max_lines)


def render_inline_hashline_edit(
    new_content: str,
    start_line: int,
    *,
    max_lines: int = _INLINE_MAX_LINES,
) -> str:
    """Render a compact preview of ``hashline_edit`` new content."""
    theme = get_theme()
    glyphs = get_glyphs()
    lines = new_content.splitlines()
    if not lines:
        return ""

    out: list[str] = []
    for i, line in enumerate(lines[:max_lines]):
        lineno = start_line + i
        out.append(
            f"[bold {theme.success}]{glyphs.gutter_bar}[/bold {theme.success}] "
            f"[{theme.muted}]{lineno:>4}[/{theme.muted}] "
            f"[{theme.success}]{_escape_markup(line)}[/{theme.success}]"
        )

    remaining = len(lines) - max_lines
    if remaining > 0:
        out.append(f"[{theme.muted}]  {glyphs.ellipsis} {remaining} more lines[/{theme.muted}]")

    return "\n".join(out)


def render_inline_write(
    content: str,
    *,
    max_lines: int = _INLINE_MAX_LINES,
) -> str:
    """Render a compact preview of ``write_file`` content."""
    theme = get_theme()
    glyphs = get_glyphs()
    lines = content.splitlines()
    if not lines:
        return ""

    out: list[str] = []
    for i, line in enumerate(lines[:max_lines]):
        out.append(
            f"[bold {theme.success}]{glyphs.gutter_bar}[/bold {theme.success}] "
            f"[{theme.muted}]{i + 1:>4}[/{theme.muted}] "
            f"{_escape_markup(line)}"
        )

    remaining = len(lines) - max_lines
    if remaining > 0:
        out.append(f"[{theme.muted}]  {glyphs.ellipsis} {remaining} more lines[/{theme.muted}]")

    return "\n".join(out)


def render_inline_change(
    tool_name: str,
    args: dict[str, object],
) -> str | None:
    """Render an inline change preview for a file-modifying tool.

    Returns Rich markup string, or None if no preview is applicable.
    """
    if tool_name == "edit_file":
        old_s = str(args.get("old_string", ""))
        new_s = str(args.get("new_string", ""))
        if old_s or new_s:
            return render_inline_edit_diff(old_s, new_s)
    elif tool_name == "hashline_edit":
        new_content = str(args.get("new_content", ""))
        start_line = int(args.get("start_line", 1))  # type: ignore[arg-type]
        if new_content:
            return render_inline_hashline_edit(new_content, start_line)
    elif tool_name == "write_file":
        content = str(args.get("content", ""))
        if content:
            return render_inline_write(content)
    return None
