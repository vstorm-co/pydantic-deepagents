"""Smart tool call formatting for the CLI.

Provides compact, readable one-liners for each tool type instead of raw
argument dumps. Includes tool result summaries.
"""

from __future__ import annotations

import os
from typing import Any

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
    """Format a tool result as a compact summary line."""
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
    if tool_name in ("write_file", "edit_file"):
        return "done"
    if tool_name == "write_todos":
        return "updated"
    if tool_name == "read_todos":
        return _truncate(flat, 60)

    return _truncate(flat, 60)


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
    return f"  [{theme.warning}]{glyphs.tool} {formatted}[/{theme.warning}]"


def render_tool_result(
    tool_name: str,
    result_content: Any,
    glyphs: Glyphs | None = None,
) -> str:
    """Render a tool result summary line.

    Returns a Rich markup string ready for console.print().
    """
    if glyphs is None:
        glyphs = get_glyphs()
    summary = format_tool_result(tool_name, result_content)
    return f"    [dim]{glyphs.arrow} {summary}[/dim]"


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
    "render_tool_result",
    "render_write_preview",
]
