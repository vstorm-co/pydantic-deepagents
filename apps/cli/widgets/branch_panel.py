"""Per-branch message panel — one mounted per active branch during a fork.

A :class:`BranchPanelWidget` wraps a :class:`MessageList` (the same widget
the parent chat uses) so tool-call rendering and assistant-message layout
are visually identical. The panel does not stream branch output live in
Stage 3; it shows status and replays the final ``all_messages()`` list
once the branch task completes — the chat screen attaches an
``asyncio.Task.add_done_callback`` per branch to populate it.
"""

from __future__ import annotations

import contextlib
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Static

from apps.cli.text_heuristics import looks_like_error
from apps.cli.widgets.fork_state import BranchState, state_label
from apps.cli.widgets.message_list import MessageList


class BranchPanelWidget(Vertical):
    """One branch's message stream + status header.

    Attributes:
        branch_id: Coordinator branch id (UUID).
        label: Human-readable label from the :class:`BranchSpec`.
    """

    DEFAULT_CSS = """
    BranchPanelWidget {
        height: 1fr;
        border-left: tall $primary;
        padding: 0 0 0 1;
        display: none;
    }
    BranchPanelWidget.active {
        display: block;
    }
    BranchPanelWidget > .branch-header {
        height: 1;
        padding: 0 1;
        color: $text;
        background: $surface-lighten-1;
    }
    BranchPanelWidget > MessageList {
        height: 1fr;
    }
    BranchPanelWidget > .branch-footer {
        height: auto;
        padding: 0 1;
        color: $text-muted;
    }
    """

    _STATUS_FOOTER: dict[str, str] = {
        "running": (
            "[dim]Branch is running — output appears here when finished.  "
            "[cyan]>>{label} msg[/cyan] to steer  ·  [cyan]Esc[/cyan] to terminate[/dim]"
        ),
        "done": (
            "[green]Branch finished.[/green]  "
            "[cyan]Enter[/cyan] to merge this branch as winner  ·  "
            "[cyan]Tab[/cyan] to view the other branch  ·  "
            "[cyan]/merge[/cyan] for side-by-side diff"
        ),
        "failed": (
            "[red]Branch failed.[/red]  "
            "[cyan]Tab[/cyan] to view the other branch  ·  [cyan]/merge[/cyan] to pick the survivor"
        ),
        "terminated": (
            "[dim]Branch terminated.[/dim]  "
            "[cyan]Tab[/cyan] to view the other branch  ·  [cyan]/merge[/cyan] to pick the survivor"
        ),
        "budget_exhausted": (
            "[orange1]Branch budget exhausted — total cost crossed its "
            "per-branch cap and the branch was cancelled.[/orange1]  "
            "Partial output is available; this branch can still be picked "
            "as winner in [cyan]/merge[/cyan].  Raise the cap via "
            "[cyan]/fork-config[/cyan]."
        ),
        "aggregate_budget_exhausted": (
            "[red]Aggregate fork budget exceeded — every running branch terminated.[/red]  "
            "[cyan]/fork-config[/cyan] to raise the aggregate cap  ·  "
            "[cyan]/merge[/cyan] to pick a survivor"
        ),
    }

    status: reactive[BranchState] = reactive["BranchState"]("running")
    reason: reactive[str | None] = reactive["str | None"](None)
    cost_usd: reactive[float | None] = reactive["float | None"](None)

    def __init__(self, branch_id: str, label: str, model: str | None = None) -> None:
        super().__init__()
        self.branch_id = branch_id
        self.label = label
        self.model = model  # display-only; the actual model in use for the branch
        self.can_focus = True

    def compose(self) -> ComposeResult:
        yield Static(self._render_header(), classes="branch-header")
        yield MessageList()
        yield Static(self._render_footer(), classes="branch-footer")

    def _render_header(self) -> str:
        badge = state_label(self.status)
        model_part = f"  ·  [dim]{self.model}[/dim]" if self.model else ""
        cost_part = f"  ·  [dim]${self.cost_usd:.2f}[/dim]" if self.cost_usd is not None else ""
        return f"[bold]{self.label}[/bold]  ·  {badge}{model_part}{cost_part}"

    def _render_footer(self) -> str:
        base = self._STATUS_FOOTER.get(self.status, "")
        if self.reason:
            return f"[dim]Reason:[/dim] {self.reason}\n{base}"
        return base

    def watch_status(self, _old: BranchState, _new: BranchState) -> None:
        with contextlib.suppress(Exception):  # widget not yet mounted
            self.query_one(".branch-header", Static).update(self._render_header())
        with contextlib.suppress(Exception):
            self.query_one(".branch-footer", Static).update(self._render_footer())

    def watch_reason(self, _old: str | None, _new: str | None) -> None:
        with contextlib.suppress(Exception):  # widget not yet mounted
            self.query_one(".branch-footer", Static).update(self._render_footer())

    def watch_cost_usd(self, _old: float | None, _new: float | None) -> None:
        with contextlib.suppress(Exception):  # widget not yet mounted
            self.query_one(".branch-header", Static).update(self._render_header())

    def mark_status(self, state: BranchState, reason: str | None = None) -> None:
        """Update the branch's status badge and optional reason text."""
        self.reason = reason
        self.status = state

    def replay_messages(self, messages: list[Any]) -> None:
        """Replay a completed branch's ``all_messages()`` into the panel.

        Mirrors the replay loop in the ``/load`` command in commands.py:
        user prompts → :meth:`MessageList.append_user_message`; assistant
        text → :meth:`AssistantMessage.append_text`; tool calls / returns
        rendered with the standard tool-call widget.
        """
        from pydantic_ai.messages import (
            TextPart,
            ToolCallPart,
            ToolReturnPart,
            UserPromptPart,
        )

        try:
            msg_list = self.query_one(MessageList)
        except Exception:  # pragma: no cover - widget not yet mounted
            return

        msg_list.clear_messages()
        completed_call_ids: set[str] = {
            part.tool_call_id
            for msg in messages
            for part in getattr(msg, "parts", [])
            if isinstance(part, ToolReturnPart)
        }

        for msg in messages:
            for part in getattr(msg, "parts", []):
                if isinstance(part, UserPromptPart):
                    content = part.content
                    if isinstance(content, str) and content:
                        msg_list.append_user_message(content)
                elif isinstance(part, TextPart):
                    if part.content:
                        assistant_msg = msg_list.begin_assistant_message()
                        assistant_msg.append_text(part.content)
                        assistant_msg.finalize_text()
                        msg_list.end_assistant_message()
                elif isinstance(part, ToolCallPart):
                    args = part.args_as_dict()
                    call_id = part.tool_call_id
                    assistant_msg = msg_list.current_assistant
                    if assistant_msg is None:
                        assistant_msg = msg_list.begin_assistant_message()
                    assistant_msg.add_tool_call(part.tool_name, args, call_id)
                    if call_id not in completed_call_ids:
                        if self.status == "terminated":
                            label = "Interrupted by user"
                        else:
                            label = "No return — model ended run without executing this call"
                        assistant_msg.complete_tool_call(call_id, label, 0.0, True)
                elif isinstance(part, ToolReturnPart):
                    content_str = str(part.content)
                    assistant_msg = msg_list.current_assistant
                    if assistant_msg is not None:
                        assistant_msg.complete_tool_call(
                            part.tool_call_id, content_str, 0.0, looks_like_error(content_str)
                        )

        if msg_list.current_assistant is not None:
            msg_list.current_assistant.finalize_text()
            msg_list.end_assistant_message()

    def set_active(self, active: bool) -> None:
        """Show or hide this panel — only one branch panel is visible at a time."""
        if active:
            self.add_class("active")
        else:
            self.remove_class("active")
