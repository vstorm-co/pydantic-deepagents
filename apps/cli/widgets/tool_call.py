"""Expandable tool call widget with status indicators."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

_SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


def _format_args_preview(tool_name: str, args: dict[str, Any]) -> str:
    """Format tool call arguments as a compact one-liner."""
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
        cmd = args.get("command", "?")
        return str(cmd)[:60]
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
    elif tool_name in ("web_search", "web_fetch"):
        query = args.get("query") or args.get("url", "?")
        return f'"{query[:50]}"'
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

    _spinner_index: int = 0
    _timer_handle: object | None = None

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
        self.result_preview: str = ""

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
        args_preview = _format_args_preview(self.tool_name, self.args)
        if args_preview:
            call_str = f"{self.tool_name}([dim]{args_preview}[/dim])"
        else:
            call_str = self.tool_name

        yield Static(
            f"{prefix}◆ {call_str}",
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
        self._timer_handle = self.set_interval(1 / 12, self._tick_spinner)

    def _tick_spinner(self) -> None:
        if self.status != "pending":
            return
        self._spinner_index = (self._spinner_index + 1) % len(_SPINNER_FRAMES)
        self.elapsed += 1 / 12
        self._refresh_header()

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

    def _build_preview(self, result: str) -> str:
        """Build a preview string for the tool result.

        For edit_file: shows a mini diff with old/new strings.
        For write_file: shows "wrote N lines to <path>".
        For everything else: shows first 3 lines + truncation.
        """
        prefix = "│  " if self.is_subagent_tool else ""

        # Inline diff for edit_file
        if self.tool_name == "edit_file":
            old = self.args.get("old_string", "")
            new = self.args.get("new_string", "")
            if old or new:
                diff_lines: list[str] = []
                for line in old.splitlines()[:3]:
                    diff_lines.append(f"{prefix}    ⎿  [red]- {line}[/red]")
                if old.count("\n") > 3:
                    diff_lines.append(
                        f"[dim]{prefix}    ⎿  ... ({old.count(chr(10)) - 2} more removed)[/dim]"
                    )
                for line in new.splitlines()[:3]:
                    diff_lines.append(f"{prefix}    ⎿  [green]+ {line}[/green]")
                if new.count("\n") > 3:
                    diff_lines.append(
                        f"[dim]{prefix}    ⎿  ... ({new.count(chr(10)) - 2} more added)[/dim]"
                    )
                return "\n".join(diff_lines) if diff_lines else ""

        # Summary for write_file
        if self.tool_name == "write_file":
            path = self.args.get("file_path") or self.args.get("path", "")
            content = self.args.get("content", "")
            n_lines = content.count("\n") + 1 if content else 0
            return f"[dim]{prefix}    ⎿  wrote {n_lines} lines to {path}[/dim]"

        # Default: first 3 lines
        lines = result.strip().splitlines()
        if lines:
            preview_lines = lines[:3]
            if len(lines) > 3:
                preview_lines.append(f"... ({len(lines) - 3} more lines)")
            return "\n".join(f"[dim]{prefix}    ⎿  {line}[/dim]" for line in preview_lines)
        return ""

    def _refresh_header(self) -> None:
        try:
            header = self.query_one("#tool-header", Static)
        except Exception:
            return
        prefix = "│  " if self.is_subagent_tool else ""
        args_preview = _format_args_preview(self.tool_name, self.args)

        if self.status == "pending":
            if args_preview:
                call_str = f"{self.tool_name}([dim]{args_preview}[/dim])"
            else:
                call_str = self.tool_name
            frame = _SPINNER_FRAMES[self._spinner_index]
            right = f"{frame} {self.elapsed:.1f}s"
            header.update(f"{prefix}◆ {call_str}  {right}")
        elif self.status == "success":
            call_str = f"{self.tool_name}({args_preview})" if args_preview else self.tool_name
            header.update(
                f"{prefix}[green]◆[/green] {call_str}"
                f"  [dim]{self.elapsed:.1f}s[/dim] [bold green]✓[/bold green]"
            )
        elif self.status == "error":
            call_str = f"{self.tool_name}({args_preview})" if args_preview else self.tool_name
            header.update(
                f"{prefix}[red]◆[/red] {call_str}"
                f"  [dim]{self.elapsed:.1f}s[/dim] [bold red]✗[/bold red]"
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
            formatted = "\n".join(f"[dim]{prefix}    ⎿  {line}[/dim]" for line in lines)
            expanded_output.update(formatted)
            expanded_output.add_class("visible")
        else:
            expanded_output.remove_class("visible")

    def action_toggle_expand(self) -> None:
        if self.result_text:
            self.expanded = not self.expanded
            self._refresh_output()

    async def on_click(self) -> None:
        self.action_toggle_expand()
