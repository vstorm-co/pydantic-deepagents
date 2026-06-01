"""Tool approval modal — shown when a tool needs user permission."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class ApprovalModal(ModalScreen[str]):
    """Modal dialog for tool execution approval.

    Returns one of: "yes", "always", "no", "edit"
    Single-key binding — no Enter needed.
    """

    DEFAULT_CSS = """
    ApprovalModal {
        align: center middle;
    }
    ApprovalModal > #approval-container {
        width: 76;
        height: auto;
        border: wide $warning;
        background: $surface;
        padding: 1 2;
    }
    ApprovalModal > #approval-container > #approval-title {
        text-style: bold;
        color: $warning;
        margin: 0 0 1 0;
    }
    ApprovalModal > #approval-container > #approval-details {
        margin: 0 0 1 0;
    }
    ApprovalModal > #approval-container > #approval-command {
        margin: 0 0 1 0;
        padding: 1 2;
        background: $surface-darken-1;
    }
    ApprovalModal > #approval-container > #approval-actions {
        margin: 1 0 0 0;
        padding: 1 0;
        text-style: bold;
    }
    """

    BINDINGS = [
        Binding("y", "approve_once", "Yes, once", show=True),
        Binding("a", "approve_always", "Always allow", show=True),
        Binding("n", "deny", "No, skip", show=True),
        Binding("escape", "deny", "Cancel", show=False),
    ]

    def __init__(
        self,
        tool_name: str,
        args: dict[str, Any],
        position: tuple[int, int] | None = None,
    ) -> None:
        super().__init__()
        self._tool_name = tool_name
        self._args = args
        # (index, total) when several tool calls await approval this turn, so
        # the user understands that confirming runs one of N pending calls.
        self._position = position

    def compose(self) -> ComposeResult:
        with Vertical(id="approval-container"):
            suffix = ""
            if self._position is not None and self._position[1] > 1:
                idx, total = self._position
                suffix = f"  [dim]({idx} of {total})[/dim]"
            yield Static(
                f"\u26a0  Approve tool call?{suffix}",
                id="approval-title",
            )

            # Format details
            details_lines = [f"[bold]Tool:[/bold]  {self._tool_name}"]
            for key, value in self._args.items():
                if key == "command":
                    # Command shown separately below
                    continue
                val_str = str(value)
                if len(val_str) > 80:
                    val_str = val_str[:77] + "..."
                details_lines.append(f"[bold]{key}:[/bold]  {val_str}")

            yield Static("\n".join(details_lines), id="approval-details")

            # Show full command for execute tool
            command = self._args.get("command")
            if command:
                yield Static(
                    f"[bold]$[/bold] {command}",
                    id="approval-command",
                )

            yield Static(
                "[bold reverse] Y [/] Yes, once    "
                "[bold reverse] A [/] Always allow    "
                "[bold red reverse] N [/] No, skip    "
                "[dim]Esc[/dim] cancel",
                id="approval-actions",
            )

    def action_approve_once(self) -> None:
        self.dismiss("yes")

    def action_approve_always(self) -> None:
        self.dismiss("always")

    def action_deny(self) -> None:
        self.dismiss("no")
