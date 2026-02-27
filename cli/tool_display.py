"""Smart tool call formatting for the CLI.

Provides compact, readable one-liners for each tool type instead of raw
argument dumps. Includes tool result previews with actual content.
"""

from __future__ import annotations

import os
from typing import Any

from rich.markup import escape

from cli.theme import Glyphs, get_glyphs, get_theme


def _abbreviate_path(path: str, max_len: int = 50) -> str:
    """Shorten a path to basename or relative from cwd."""
    try:
        rel = os.path.relpath(path)
        if len(rel) <= max_len:
            return rel
    except ValueError:
        pass
    base = os.path.basename(path)
    if len(base) <= max_len:
        return base
    glyphs = get_glyphs()
    return base[: max_len - len(glyphs.ellipsis)] + glyphs.ellipsis


def _truncate(text: str, max_len: int = 120) -> str:
    glyphs = get_glyphs()
    if len(text) > max_len:
        return text[: max_len - len(glyphs.ellipsis)] + glyphs.ellipsis
    return text


_TOOL_FORMATTERS: dict[str, Any] = {}


def _register(name: str):
    def decorator(fn: Any) -> Any:
        _TOOL_FORMATTERS[name] = fn
        return fn

    return decorator


@_register("read_file")
def _fmt_read_file(args: dict[str, Any]) -> str:
    path = _abbreviate_path(str(args.get("path", "")))
    limit = args.get("limit")
    if limit:
        return f"read_file({path}, limit={limit})"
    return f"read_file({path})"


@_register("write_file")
def _fmt_write_file(args: dict[str, Any]) -> str:
    path = _abbreviate_path(str(args.get("path", "")))
    content = str(args.get("content", ""))
    lines = content.count("\n") + 1
    return f"write_file({path}, {lines} lines)"


@_register("edit_file")
def _fmt_edit_file(args: dict[str, Any]) -> str:
    path = _abbreviate_path(str(args.get("path", "")))
    return f"edit_file({path})"


@_register("hashline_edit")
def _fmt_hashline_edit(args: dict[str, Any]) -> str:
    path = _abbreviate_path(str(args.get("path", "")))
    start = args.get("start_line", "")
    end = args.get("end_line")
    if end and end != start:
        return f"hashline_edit({path}, lines {start}-{end})"
    return f"hashline_edit({path}, line {start})"


@_register("execute")
def _fmt_execute(args: dict[str, Any]) -> str:
    cmd = str(args.get("command", ""))
    return f"execute({_truncate(cmd, 100)})"


@_register("grep")
def _fmt_grep(args: dict[str, Any]) -> str:
    pattern = args.get("pattern", "")
    path = args.get("path", "")
    if path:
        return f'grep("{pattern}", {_abbreviate_path(str(path))})'
    return f'grep("{pattern}")'


@_register("glob")
def _fmt_glob(args: dict[str, Any]) -> str:
    pattern = args.get("pattern", "")
    return f'glob("{pattern}")'


@_register("ls")
def _fmt_ls(args: dict[str, Any]) -> str:
    path = _abbreviate_path(str(args.get("path", ".")))
    return f"ls({path})"


@_register("write_todos")
def _fmt_write_todos(args: dict[str, Any]) -> str:
    todos = args.get("todos", [])
    return f"write_todos({len(todos)} items)"


@_register("read_todos")
def _fmt_read_todos(args: dict[str, Any]) -> str:
    return "read_todos()"


@_register("web_search")
def _fmt_web_search(args: dict[str, Any]) -> str:
    query = args.get("query", "")
    return f'web_search("{_truncate(query, 60)}")'


@_register("save_checkpoint")
def _fmt_save_checkpoint(args: dict[str, Any]) -> str:
    label = args.get("label", "")
    return f'save_checkpoint("{label}")'


@_register("save_plan")
def _fmt_save_plan(args: dict[str, Any]) -> str:
    name = args.get("name", "")
    return f'save_plan("{name}")'


@_register("ask_user")
def _fmt_ask_user(args: dict[str, Any]) -> str:
    question = _truncate(str(args.get("question", "")), 60)
    return f'ask_user("{question}")'


# Subagent tool names — map "task" to friendlier labels
_SUBAGENT_LABELS: dict[str, str] = {
    "planner": "Plan Agent",
    "general_purpose": "Research Agent",
    "general-purpose": "Research Agent",
}


@_register("task")
def _fmt_task(args: dict[str, Any]) -> str:
    subagent = str(args.get("subagent_type", ""))
    desc = _truncate(str(args.get("description", "")), 60)
    label = _SUBAGENT_LABELS.get(subagent, subagent or "subagent")
    if desc:
        return f'{label}("{desc}")'
    return label


@_register("check_task")
def _fmt_check_task(args: dict[str, Any]) -> str:
    task_id = args.get("task_id", "")
    return f"check_task({task_id})"


@_register("list_active_tasks")
def _fmt_list_active_tasks(args: dict[str, Any]) -> str:
    return "list_active_tasks()"


def format_tool_call(tool_name: str, args: dict[str, Any]) -> str:
    """Format a tool call as a compact one-liner.

    Uses per-tool formatters when available, falls back to generic format.
    """
    formatter = _TOOL_FORMATTERS.get(tool_name)
    if formatter:
        return formatter(args)
    # Generic fallback: tool_name(key=val, ...)
    parts = []
    for k, v in list(args.items())[:3]:
        val = _truncate(str(v), 40)
        parts.append(f"{k}={val}")
    joined = ", ".join(parts)
    if len(args) > 3:
        joined += ", ..."
    return f"{tool_name}({joined})"


def format_tool_result(tool_name: str, result_content: Any) -> str:
    """Format a tool result as a compact summary line.

    Returns a plain-text summary (no Rich markup).
    """
    raw = str(result_content)
    flat = raw.replace("\n", " ")

    if tool_name == "read_file":
        lines = raw.count("\n")
        return f"{lines} lines read"
    if tool_name == "execute":
        if "exit code 0" in flat.lower() or "exit_code=0" in flat.lower():
            return "exit code 0"
        if "exit code" in flat.lower() or "exit_code" in flat.lower():
            return _truncate(flat, 60)
    if tool_name in ("grep", "glob"):
        matches = raw.count("\n") + 1 if raw.strip() else 0
        return f"{matches} matches"
    if tool_name in ("write_file", "edit_file", "hashline_edit"):
        return "done"
    if tool_name == "write_todos":
        return "updated"
    if tool_name == "read_todos":
        return _truncate(flat, 60)

    return _truncate(flat, 60)


# ---------------------------------------------------------------------------
# Content preview formatters (used by render_tool_result)
# ---------------------------------------------------------------------------

_PREVIEW_LINES = 3
_PREVIEW_CHARS = 300


def _preview_head(raw: str, max_lines: int = _PREVIEW_LINES) -> str:
    """Show first N lines of text with truncation marker."""
    lines = raw.splitlines()
    if not lines:
        return "(empty)"
    if len(lines) <= max_lines:
        return "\n".join(lines)
    shown = lines[:max_lines]
    remaining = len(lines) - max_lines
    glyphs = get_glyphs()
    shown.append(f"{glyphs.ellipsis} ({remaining} more lines)")
    return "\n".join(shown)


def _preview_read_file(raw: str) -> str:
    return _preview_head(raw)


def _preview_execute(raw: str) -> str:
    return _preview_head(raw)


def _preview_search(raw: str) -> str:
    """Preview grep/glob results."""
    lines = raw.splitlines()
    if not lines or not raw.strip():
        return "(no matches)"
    if len(lines) <= _PREVIEW_LINES:
        return "\n".join(lines)
    shown = lines[:_PREVIEW_LINES]
    remaining = len(lines) - _PREVIEW_LINES
    glyphs = get_glyphs()
    shown.append(f"{glyphs.ellipsis} ({remaining} more)")
    return "\n".join(shown)


def _preview_write(raw: str) -> str:
    lines = raw.count("\n") + 1 if raw.strip() else 0
    if lines:
        return f"(written, {lines} lines)"
    return "done"


def _preview_ls(raw: str) -> str:
    return _preview_head(raw)


def _preview_generic(raw: str) -> str:
    if not raw.strip():
        return "(empty)"
    if len(raw) > _PREVIEW_CHARS:
        glyphs = get_glyphs()
        return raw[:_PREVIEW_CHARS] + glyphs.ellipsis
    return _preview_head(raw)


_PREVIEW_MAP: dict[str, Any] = {
    "read_file": _preview_read_file,
    "execute": _preview_execute,
    "grep": _preview_search,
    "glob": _preview_search,
    "write_file": _preview_write,
    "edit_file": _preview_write,
    "hashline_edit": _preview_write,
    "ls": _preview_ls,
    "write_todos": lambda _: "updated",
    "read_todos": _preview_generic,
}


def _format_result_preview(tool_name: str, raw: str) -> str:
    """Format tool result as a content preview."""
    if not raw.strip():
        return "(empty)"
    formatter = _PREVIEW_MAP.get(tool_name, _preview_generic)
    return formatter(raw)


# ---------------------------------------------------------------------------
# Rich-rendered output (used by interactive/non-interactive display)
# ---------------------------------------------------------------------------


def render_tool_call(
    tool_name: str,
    args: dict[str, Any],
    glyphs: Glyphs | None = None,
) -> str:
    """Render a full tool call line with glyph prefix and theme colors.

    Returns a Rich markup string ready for console.print().
    """
    if glyphs is None:
        glyphs = get_glyphs()
    theme = get_theme()
    formatted = format_tool_call(tool_name, args)
    return f"[bold {theme.warning}]{glyphs.tool_prefix} {formatted}[/bold {theme.warning}]"


def render_tool_call_success(
    tool_name: str,
    args: dict[str, Any],
    elapsed: float | None = None,
    glyphs: Glyphs | None = None,
) -> str:
    """Render a tool call in success state with optional elapsed time.

    Returns a Rich markup string: ``✓ tool(args) (1.2s)``
    """
    if glyphs is None:
        glyphs = get_glyphs()
    theme = get_theme()
    formatted = format_tool_call(tool_name, args)
    elapsed_str = ""
    if elapsed is not None and elapsed > 1.0:
        elapsed_str = f" [{theme.muted}]({elapsed:.1f}s)[/{theme.muted}]"
    return f"[{theme.success}]{glyphs.success} {formatted}[/{theme.success}]{elapsed_str}"


def render_tool_call_error(
    tool_name: str,
    args: dict[str, Any],
    glyphs: Glyphs | None = None,
) -> str:
    """Render a tool call in error state.

    Returns a Rich markup string: ``✗ tool(args)``
    """
    if glyphs is None:
        glyphs = get_glyphs()
    theme = get_theme()
    formatted = format_tool_call(tool_name, args)
    return f"[{theme.error}]{glyphs.error} {formatted}[/{theme.error}]"


def render_tool_result(
    tool_name: str,
    result_content: Any,
    glyphs: Glyphs | None = None,
    *,
    error: bool = False,
) -> str:
    """Render a tool result with content preview.

    Shows actual output (first few lines) with the output_prefix glyph.
    Returns a Rich markup string ready for console.print().
    """
    if glyphs is None:
        glyphs = get_glyphs()
    theme = get_theme()
    color = theme.error if error else theme.muted

    raw = str(result_content)
    preview = _format_result_preview(tool_name, raw)
    lines = preview.splitlines()

    if not lines:
        return ""

    parts: list[str] = []
    # First line gets the output_prefix glyph (⎿)
    first = escape(lines[0])
    parts.append(f"[{color}]{glyphs.output_prefix} {first}[/{color}]")
    # Continuation lines indented to align with first line content
    for line in lines[1:]:
        parts.append(f"[{color}]  {escape(line)}[/{color}]")

    return "\n".join(parts)


def render_write_preview(content: str, language: str = "", max_lines: int = 20) -> str:
    """Render a head/tail preview of written file content.

    Shows the first and last lines with a truncation marker in between
    when the content exceeds *max_lines*.
    """
    lines = content.splitlines()
    if len(lines) <= max_lines:
        preview = content
    else:
        head = lines[: max_lines // 2]
        tail = lines[-(max_lines // 2) :]
        omitted = len(lines) - len(head) - len(tail)
        preview = "\n".join(head + [f"  ... ({omitted} lines omitted) ..."] + tail)

    lang_label = f" ({language})" if language else ""
    return f"[dim]Preview{lang_label}:[/dim]\n{preview}"


def render_diff(diff_text: str) -> str:
    """Render a unified diff with colored Rich markup.

    Green for additions, red for removals, cyan for range headers, dim for context.
    """
    lines: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            lines.append(f"[bold]{line}[/bold]")
        elif line.startswith("@@"):
            lines.append(f"[cyan]{line}[/cyan]")
        elif line.startswith("+"):
            lines.append(f"[green]{line}[/green]")
        elif line.startswith("-"):
            lines.append(f"[red]{line}[/red]")
        else:
            lines.append(f"[dim]{line}[/dim]")
    return "\n".join(lines)


__all__ = [
    "format_tool_call",
    "format_tool_result",
    "render_diff",
    "render_tool_call",
    "render_tool_call_error",
    "render_tool_call_success",
    "render_tool_result",
    "render_write_preview",
]
