"""Branch tool-approval modal — shown when a fork branch awaits user approval."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class BranchApprovalModal(ModalScreen[bool]):
    """Modal dialog surfaced when a branch task needs permission to run a tool.

    Branch tasks cannot reach the main :class:`~apps.cli.modals.approval.ApprovalModal`
    because they run as background asyncio coroutines with no direct path
    to the TUI event loop.  Instead the branch suspends on an
    :class:`asyncio.Queue` and the TUI poll loop surfaces *this* modal.

    Returns `True` if the user approves, `False` if they deny.
    Single-key bindings — no Enter required.

    Args:
        branch_label: Human-readable branch name shown in the title.
        description: `"tool_name: arg"` string describing the blocked call.
    """

    DEFAULT_CSS = """
    BranchApprovalModal {
        align: center middle;
    }
    BranchApprovalModal > #ba-container {
        width: 76;
        height: auto;
        border: wide $warning;
        background: $surface;
        padding: 1 2;
    }
    BranchApprovalModal > #ba-container > #ba-title {
        text-style: bold;
        color: $warning;
        margin: 0 0 1 0;
    }
    BranchApprovalModal > #ba-container > #ba-description {
        margin: 0 0 1 0;
        padding: 1 2;
        background: $surface-darken-1;
    }
    BranchApprovalModal > #ba-container > #ba-actions {
        margin: 1 0 0 0;
        padding: 1 0;
        text-style: bold;
    }
    """

    BINDINGS = [
        Binding("y", "approve", "Yes, allow", show=True),
        Binding("n", "deny", "No, skip", show=True),
        Binding("escape", "deny", "Cancel", show=False),
    ]

    def __init__(self, branch_label: str, description: str) -> None:
        super().__init__()
        self._branch_label = branch_label
        self._description = description

    def compose(self) -> ComposeResult:
        with Vertical(id="ba-container"):
            yield Static(
                f"⏸  Branch [bold]{self._branch_label}[/bold] awaits approval",
                id="ba-title",
            )
            yield Static(
                self._description,
                id="ba-description",
            )
            yield Static(
                "[bold reverse] Y [/] Allow    "
                "[bold red reverse] N [/] Deny    "
                "[dim]Esc[/dim] deny",
                id="ba-actions",
            )

    def action_approve(self) -> None:
        self.dismiss(True)

    def action_deny(self) -> None:
        self.dismiss(False)
