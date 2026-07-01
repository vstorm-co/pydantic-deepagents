"""Expandable tool call widget with status indicators."""

from __future__ import annotations

import difflib
import os
import re
from typing import Any

from rich.console import Group, RenderableType
from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.reactive import reactive
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Static

from apps.cli.widgets.spinner import Spinner

# How many diff/preview lines to show before collapsing the rest behind a
# "... N more" marker. The full content is always available in expanded view.
_PREVIEW_LIMIT = 12

# File extensions → Pygments lexer names, used to syntax-highlight freshly
# written file content. The "ansi_dark" theme is deliberately ANSI-based so the
# colors track the user's terminal theme instead of fighting it.
_LANG_BY_EXT: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".json": "json",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".md": "markdown",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".sql": "sql",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".rb": "ruby",
    ".php": "php",
    ".xml": "xml",
    ".kt": "kotlin",
    ".swift": "swift",
}


def _lang_for_path(path: str) -> str | None:
    """Return a Pygments lexer name for ``path`` by extension, or ``None``.

    Filenames without a usable extension (e.g. ``Dockerfile``) fall back to a
    name match so common config files still highlight.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in _LANG_BY_EXT:
        return _LANG_BY_EXT[ext]
    base = os.path.basename(path).lower()
    if base == "dockerfile":
        return "docker"
    if base == "makefile":
        return "make"
    return None


def _highlight(content: str, lang: str) -> Syntax:
    """Build a terminal-theme-friendly :class:`Syntax` renderable for code."""
    return Syntax(
        content,
        lang,
        theme="ansi_dark",
        background_color="default",
        word_wrap=True,
    )


# A single monochrome marker for every tool call — cohesive with the minimalist
# theme and width-stable (unlike emoji, whose cell width varies by terminal).
# The tool name carries the meaning; status (spinner/✓/✗) shows progress.
_TOOL_MARKER = "›"


def _tool_icon(tool_name: str) -> str:
    """Return the leading marker for a tool call."""
    return _TOOL_MARKER


def _rich_escape(text: str) -> str:
    """Escape every `[` so Rich's markup parser can't mis-pair tags.

    `rich.markup.escape` only protects `[` followed by `[a-z#/@]`,
    so payloads like `[{'label': ...}]` slip through and confuse the
    parser when neighbouring real tags exist (`[dim]...[/dim]`).
    """
    return text.replace("[", r"\[")


def _diff_lines(
    old: str, new: str, prefix: str, *, limit: int = _PREVIEW_LIMIT
) -> tuple[list[str], int, int]:
    """Build a colored unified-style diff between ``old`` and ``new``.

    Returns ``(rendered_lines, added_count, removed_count)``. Uses
    :class:`difflib.SequenceMatcher` so unchanged regions are skipped and
    changed lines are interleaved as ``- removed`` / ``+ added``.
    """
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines, autojunk=False)

    rendered: list[str] = []
    added = 0
    removed = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete"):
            for line in old_lines[i1:i2]:
                removed += 1
                if len(rendered) < limit:
                    rendered.append(f"{prefix}    ⎿  [$error]- {_rich_escape(line)}[/]")
        if tag in ("replace", "insert"):
            for line in new_lines[j1:j2]:
                added += 1
                if len(rendered) < limit:
                    rendered.append(f"{prefix}    ⎿  [$success]+ {_rich_escape(line)}[/]")

    shown = added + removed
    if shown > limit:
        rendered.append(f"[dim]{prefix}    ⎿  ... ({shown - limit} more changed lines)[/dim]")
    return rendered, added, removed


_DISCOVERED_NAME_RE = re.compile(r"""['"]name['"]\s*:\s*['"]([^'"]+)['"]""")


def _discovered_tool_names(result: str) -> list[str]:
    """Names from a `search_tools` result (handles JSON or Python dict-repr)."""
    if "discovered_tools" not in result:
        return []
    return _DISCOVERED_NAME_RE.findall(result)


def _special_args_preview(tool_name: str, args: dict[str, Any]) -> str | None:
    """Compact header for background-shell / web / search tools.

    Returns ``None`` when ``tool_name`` is not one of these, so the caller falls
    through to the main dispatch. Kept separate so :func:`_format_args_preview`
    stays under the complexity budget.
    """
    if tool_name == "run_in_background":
        one_line = " ".join(str(args.get("command", "?")).split())
        return one_line[:79] + "…" if len(one_line) > 80 else one_line
    if tool_name in ("read_output", "kill_shell"):
        return str(args.get("shell_id", "?"))
    if tool_name == "list_shells":
        return ""
    if tool_name in ("web_search", "web_fetch"):
        query = args.get("query") or args.get("url", "?")
        return f'"{query[:50]}"'
    if tool_name == "search_tools":
        queries = args.get("queries") or []
        if isinstance(queries, list) and queries:
            return ", ".join(f'"{q}"' for q in queries[:3])
        return ""
    return None


def _format_args_preview(tool_name: str, args: dict[str, Any]) -> str:
    """Format tool call arguments as a compact one-liner.

    The header is a single line, so long values are trimmed here only; the
    full value (command, diff, content) is rendered in the body/expanded view.
    """
    special = _special_args_preview(tool_name, args)
    if special is not None:
        return special
    if tool_name == "read_file":
        path = args.get("file_path") or args.get("path", "?")
        parts = [str(path)]
        if "limit" in args:
            parts.append(f"limit={args['limit']}")
        if "offset" in args:
            parts.append(f"offset={args['offset']}")
        return ", ".join(parts)
    elif tool_name == "write_file":
        path = args.get("file_path") or args.get("path", "?")
        content = args.get("content", "")
        lines = content.count("\n") + 1 if content else 0
        return f"{path}, {lines} lines"
    elif tool_name == "edit_file":
        path = args.get("file_path") or args.get("path", "?")
        return str(path)
    elif tool_name == "execute":
        cmd = str(args.get("command", "?"))
        # Show the full command on a single logical line; collapse newlines so
        # multi-line scripts stay readable in the one-line header.
        one_line = " ".join(cmd.split())
        if len(one_line) > 80:
            return one_line[:79] + "…"
        return one_line
    elif tool_name == "grep":
        pattern = args.get("pattern", "?")
        path = args.get("path", ".")
        return f'"{pattern}", {path}'
    elif tool_name == "glob":
        pattern = args.get("pattern", "?")
        return f'"{pattern}"'
    elif tool_name == "task":
        name = args.get("subagent_type") or args.get("name", "?")
        desc = args.get("description", "")
        return f'{name}, "{desc[:40]}"'
    elif tool_name in (
        "read_todos",
        "write_todos",
        "add_todo",
        "update_todo_status",
        "remove_todo",
    ):
        return ""
    else:
        # Generic: show first 2 args
        items = list(args.items())[:2]
        parts = [f"{k}={repr(v)[:30]}" for k, v in items]
        return ", ".join(parts)


class ToolCallWidget(Widget):
    """A single tool call with expandable output.

    States: pending (spinner), success (checkmark), error (cross).
    Click or Enter toggles expanded output view.
    """

    can_focus = True

    DEFAULT_CSS = """
    ToolCallWidget {
        height: auto;
        padding: 0 1;
    }
    ToolCallWidget .tool-header {
        height: 1;
    }
    ToolCallWidget .tool-output {
        padding: 0 0 0 3;
        color: $text-muted;
        display: none;
    }
    ToolCallWidget .tool-output.visible {
        display: block;
    }
    ToolCallWidget .tool-output-expanded {
        padding: 0 0 0 3;
        color: $text-muted;
        display: none;
    }
    ToolCallWidget .tool-output-expanded.visible {
        display: block;
    }
    """

    BINDINGS = [
        ("enter", "toggle_expand", "Expand"),
    ]

    status: reactive[str] = reactive("pending")  # pending, success, error
    elapsed: reactive[float] = reactive(0.0)
    expanded: reactive[bool] = reactive(False)

    _timer_handle: Timer | None = None

    def __init__(
        self,
        tool_name: str,
        args: dict[str, Any],
        call_id: str,
        *,
        is_subagent_tool: bool = False,
    ) -> None:
        super().__init__()
        self.tool_name = tool_name
        self.args = args
        self.call_id = call_id
        self.is_subagent_tool = is_subagent_tool
        self.result_text: str = ""
        # A string (Rich markup) for most tools, or a Rich renderable (e.g. a
        # syntax-highlighted code block) for freshly written files.
        self.result_preview: RenderableType = ""
        # Diff line counts for edit_file/write_file, surfaced in the header.
        self._added: int = 0
        self._removed: int = 0
        # Set when the user interrupts: shows immediate "stopping" feedback
        # while cancellation propagates to the underlying process.
        self._cancelling: bool = False
        self._spinner = Spinner()

    @property
    def is_hidden_tool(self) -> bool:
        """TODO tools are hidden from the UI."""
        return self.tool_name in (
            "read_todos",
            "write_todos",
            "add_todo",
            "update_todo_status",
            "remove_todo",
        )

    def compose(self) -> ComposeResult:
        prefix = "│  " if self.is_subagent_tool else ""
        args_preview = _rich_escape(_format_args_preview(self.tool_name, self.args))
        icon = _tool_icon(self.tool_name)
        if args_preview:
            call_str = f"{self.tool_name}([dim]{args_preview}[/dim])"
        else:
            call_str = self.tool_name

        yield Static(
            f"{prefix}{icon} {call_str}",
            id="tool-header",
            classes="tool-header",
        )
        yield Static("", id="tool-output", classes="tool-output")
        yield Static("", id="tool-output-expanded", classes="tool-output-expanded")

    def on_mount(self) -> None:
        if self.is_hidden_tool:
            self.display = False
            return
        if self.status != "pending":
            self._refresh_header()
            self._refresh_output()
            return
        self._timer_handle = self._spinner.start_on(
            self,
            gate=lambda: self.status == "pending",
            on_advance=self._refresh_header,
        )

    def complete(self, result: str, elapsed: float, error: bool = False) -> None:
        """Mark this tool call as completed."""
        self.result_text = result
        self.elapsed = elapsed
        self.status = "error" if error else "success"

        # Generate preview based on tool type
        self.result_preview = self._build_preview(result)

        if self._timer_handle:
            self._timer_handle.stop()
            self._timer_handle = None

        self._refresh_header()
        self._refresh_output()

    def _build_preview(self, result: str) -> RenderableType:
        """Build a preview for the tool result.

        - ``edit_file``: a real +/- diff (difflib) with a "... N more" tail.
        - ``write_file``: a syntax-highlighted preview of a new file, or a
          real +/- diff when overwriting.
        - ``execute``: the full command (``$ ...``) followed by its output.
        - everything else: first lines of the result + truncation marker.

        Returns Rich markup (``str``) for most tools, or a Rich renderable for
        syntax-highlighted new-file writes.
        """
        prefix = "│  " if self.is_subagent_tool else ""

        # Real diff for edit_file
        if self.tool_name == "edit_file":
            old = self.args.get("old_string", "")
            new = self.args.get("new_string", "")
            if old or new:
                lines, added, removed = _diff_lines(old, new, prefix)
                self._added, self._removed = added, removed
                return "\n".join(lines) if lines else ""

        # write_file: real diff against the pre-write content when overwriting,
        # otherwise show the new content as additions (new file).
        if self.tool_name == "write_file":
            path = self.args.get("file_path") or self.args.get("path", "")
            content = self.args.get("content", "")
            old = self.args.get("_old_content")
            if old is not None and old != content:
                lines, added, removed = _diff_lines(old, content, prefix)
                self._added, self._removed = added, removed
                head = f"[dim]{prefix}    ⎿  updated {_rich_escape(str(path))}[/dim]"
                return "\n".join([head, *lines]) if lines else head
            content_lines = content.splitlines() if content else []
            self._added = len(content_lines)
            self._removed = 0
            head_markup = (
                f"[dim]{prefix}    ⎿  wrote {len(content_lines)} lines to "
                f"{_rich_escape(str(path))}[/dim]"
            )
            lang = _lang_for_path(str(path))
            # Top-level writes of a known language render as a real
            # syntax-highlighted block. Subagent calls keep the line-prefixed
            # text form so the "│" nesting bar stays intact.
            if lang is not None and content.strip() and not self.is_subagent_tool:
                shown = "\n".join(content_lines[:_PREVIEW_LIMIT])
                parts: list[RenderableType] = [
                    Text.from_markup(head_markup),
                    _highlight(shown, lang),
                ]
                if len(content_lines) > _PREVIEW_LIMIT:
                    parts.append(
                        Text.from_markup(
                            f"[dim]    ⎿  ... "
                            f"({len(content_lines) - _PREVIEW_LIMIT} more added)[/dim]"
                        )
                    )
                return Group(*parts)
            body = [
                f"{prefix}    ⎿  [$success]+ {_rich_escape(line)}[/]"
                for line in content_lines[:_PREVIEW_LIMIT]
            ]
            if len(content_lines) > _PREVIEW_LIMIT:
                body.append(
                    f"[dim]{prefix}    ⎿  ... "
                    f"({len(content_lines) - _PREVIEW_LIMIT} more added)[/dim]"
                )
            return "\n".join([head_markup, *body])

        # Full command + output for execute
        if self.tool_name == "execute":
            cmd = str(self.args.get("command", ""))
            cmd_lines = [
                f"{prefix}    ⎿  [bold cyan]$ {_rich_escape(line)}[/bold cyan]"
                for line in cmd.splitlines()
            ]
            out_lines = result.strip().splitlines()
            shown_out = out_lines[:_PREVIEW_LIMIT]
            body = [f"[dim]{prefix}    ⎿  {_rich_escape(line)}[/dim]" for line in shown_out]
            if len(out_lines) > _PREVIEW_LIMIT:
                body.append(
                    f"[dim]{prefix}    ⎿  ... ({len(out_lines) - _PREVIEW_LIMIT} more lines)[/dim]"
                )
            return "\n".join([*cmd_lines, *body])

        # Background launch: show the command (▷) then the start confirmation.
        if self.tool_name == "run_in_background":
            cmd = str(self.args.get("command", ""))
            cmd_lines = [
                f"{prefix}    ⎿  [bold $accent]▷ {_rich_escape(line)}[/]"
                for line in cmd.splitlines()
            ]
            out_lines = result.strip().splitlines()
            body = [
                f"[dim]{prefix}    ⎿  {_rich_escape(line)}[/dim]"
                for line in out_lines[:_PREVIEW_LIMIT]
            ]
            return "\n".join([*cmd_lines, *body])

        # Tool search: show the discovered tool names as accent chips, not raw JSON.
        if self.tool_name == "search_tools":
            names = _discovered_tool_names(result)
            if names:
                count = len(names)
                head = (
                    f"[dim]{prefix}    ⎿  discovered {count} tool{'s' if count != 1 else ''}[/dim]"
                )
                shown = names[:_PREVIEW_LIMIT]
                chips = "  ".join(f"[$accent]{_rich_escape(n)}[/]" for n in shown)
                more = (
                    f"  [dim]+{count - _PREVIEW_LIMIT} more[/dim]" if count > _PREVIEW_LIMIT else ""
                )
                return f"{head}\n{prefix}       {chips}{more}"

        # Default: first lines of the result
        lines = result.strip().splitlines()
        if lines:
            preview_lines = lines[:_PREVIEW_LIMIT]
            if len(lines) > _PREVIEW_LIMIT:
                preview_lines.append(f"... ({len(lines) - _PREVIEW_LIMIT} more lines)")
            return "\n".join(
                f"[dim]{prefix}    ⎿  {_rich_escape(line)}[/dim]" for line in preview_lines
            )
        return ""

    def _diff_badge(self) -> str:
        """Compact ``+N -M`` badge for edit/write tools (empty when no change)."""
        parts = []
        if self._added:
            parts.append(f"[$success]+{self._added}[/]")
        if self._removed:
            parts.append(f"[$error]-{self._removed}[/]")
        return ("  " + " ".join(parts)) if parts else ""

    def _refresh_header(self) -> None:
        try:
            header = self.query_one("#tool-header", Static)
        except Exception:
            return
        prefix = "│  " if self.is_subagent_tool else ""
        args_preview = _rich_escape(_format_args_preview(self.tool_name, self.args))
        icon = _tool_icon(self.tool_name)
        badge = self._diff_badge()

        if self.status == "pending":
            if args_preview:
                call_str = f"{self.tool_name}([dim]{args_preview}[/dim])"
            else:
                call_str = self.tool_name
            if self._cancelling:
                header.update(f"{prefix}[$warning]{icon}[/] {call_str}  [$warning]⏹ stopping…[/]")
            else:
                frame = self._spinner.frame
                right = f"[$accent]{frame}[/] [$text-muted]{self._spinner.elapsed:.1f}s[/]"
                header.update(f"{prefix}[$accent]{icon}[/] {call_str}  {right}")
        elif self.status == "success":
            call_str = f"{self.tool_name}({args_preview})" if args_preview else self.tool_name
            header.update(
                f"{prefix}[$success]{icon}[/] {call_str}{badge}"
                f"  [$text-muted]{self.elapsed:.1f}s[/] [$success b]✓[/]"
            )
        elif self.status == "error":
            call_str = f"{self.tool_name}({args_preview})" if args_preview else self.tool_name
            header.update(
                f"{prefix}[$error]{icon}[/] {call_str}{badge}"
                f"  [$text-muted]{self.elapsed:.1f}s[/] [$error b]✗[/]"
            )

    def _refresh_output(self) -> None:
        try:
            output = self.query_one("#tool-output", Static)
        except Exception:
            return
        if self.result_preview and not self.expanded:
            output.update(self.result_preview)
            output.add_class("visible")
        else:
            output.remove_class("visible")

        try:
            expanded_output = self.query_one("#tool-output-expanded", Static)
        except Exception:
            return
        if self.expanded and self.result_text:
            prefix = "│  " if self.is_subagent_tool else ""
            lines = self.result_text.strip().splitlines()
            formatted = "\n".join(
                f"[dim]{prefix}    ⎿  {_rich_escape(line)}[/dim]" for line in lines
            )
            expanded_output.update(formatted)
            expanded_output.add_class("visible")
        else:
            expanded_output.remove_class("visible")

    def mark_cancelling(self) -> None:
        """Show an immediate "stopping" indicator for an in-flight call.

        No-op once the call has finished. The flag is honoured by
        :meth:`_refresh_header` so the spinner tick doesn't overwrite it.
        """
        if self.status != "pending":
            return
        self._cancelling = True
        self._refresh_header()

    def action_toggle_expand(self) -> None:
        if self.result_text:
            self.expanded = not self.expanded
            self._refresh_output()

    async def on_click(self) -> None:
        self.action_toggle_expand()
