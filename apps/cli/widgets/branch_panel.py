"""Per-branch message panel - one mounted per active branch during a fork.

A :class:`BranchPanelWidget` wraps a :class:`MessageList` (the same widget
the parent chat uses) so tool-call rendering and assistant-message layout
are visually identical. The panel does not stream branch output live;
it shows status and replays the final `all_messages()` list once the
branch task completes - the chat screen attaches an
`asyncio.Task.add_done_callback` per branch to populate it.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from pydantic_ai.messages import TextPart, ToolCallPart, ToolReturnPart, UserPromptPart
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widgets import Static

from apps.cli.text_heuristics import looks_like_error
from apps.cli.widgets.fork_state import BranchState, state_label
from apps.cli.widgets.message_list import MessageList

if TYPE_CHECKING:
    from apps.cli.widgets.assistant_message import AssistantMessage


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
            "[dim]Branch is running - output appears here when finished.  "
            "[cyan]>>{label} msg[/cyan] to steer  ·  [cyan]Esc[/cyan] to terminate[/dim]"
        ),
        "done": (
            "[green]Branch finished.[/green]  "
            "[cyan]Enter[/cyan] to merge this branch as winner  ·  "
            "[cyan]Tab[/cyan] to view the other branch  ·  "
            "[cyan]/merge[/cyan] to resolve (strategy from /fork-config)"
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
            "[orange1]Branch budget exhausted - total cost crossed its "
            "per-branch cap and the branch was cancelled.[/orange1]  "
            "Partial output is available; this branch can still be picked "
            "as winner in [cyan]/merge[/cyan].  Raise the cap via "
            "[cyan]/fork-config[/cyan]."
        ),
        "aggregate_budget_exhausted": (
            "[red]Aggregate fork budget exceeded - every running branch terminated.[/red]  "
            "[cyan]/fork-config[/cyan] to raise the aggregate cap  ·  "
            "[cyan]/merge[/cyan] to pick a survivor"
        ),
    }

    status: reactive[BranchState] = reactive["BranchState"]("running")
    reason: reactive[str | None] = reactive["str | None"](None)
    cost_usd: reactive[float | None] = reactive["float | None"](None)
    blocked_count: reactive[int] = reactive[int](0)
    awaiting_approval: reactive[bool] = reactive[bool](False)

    def __init__(self, branch_id: str, label: str, model: str | None = None) -> None:
        super().__init__()
        self.branch_id = branch_id
        self.label = label
        self.model = model  # display-only; the actual model in use for the branch
        self.can_focus = True
        self._last_replayed_len: int = 0
        self._rendered_call_ids: set[str] = set()
        # call_id -> the AssistantMessage that holds its tool-call widget. Lets a
        # ToolReturnPart arriving in a later tick complete the row via a direct
        # reference instead of scanning `msg_list.children` - which may not have
        # flushed the freshly-mounted message yet, leaving the spinner stuck.
        self._rendered_call_msgs: dict[str, AssistantMessage] = {}
        self.streaming: bool = False
        # True once the terminal transcript has been rendered. Both the task
        # done-callback and the poll tick race to render a finished branch;
        # this makes the second a no-op so the panel isn't cleared + re-rendered
        # twice (C8).
        self._final_replayed: bool = False

    def compose(self) -> ComposeResult:
        yield Static(self._render_header(), classes="branch-header")
        yield MessageList()
        yield Static(self._render_footer(), classes="branch-footer")

    def _render_header(self) -> str:
        badge = state_label(self.status)
        model_part = f"  ·  [dim]{self.model}[/dim]" if self.model else ""
        cost_part = f"  ·  [dim]${self.cost_usd:.2f}[/dim]" if self.cost_usd is not None else ""
        # ⏸ awaiting takes priority - it means the branch is actively waiting
        # right now. The ⚠ blocked count is a historical tally of past denials.
        if self.awaiting_approval:
            approval_part = "  ·  [yellow]⏸ awaiting approval[/yellow]"
        elif self.blocked_count:
            approval_part = f"  ·  [orange1]⚠ {self.blocked_count} denied[/orange1]"
        else:
            approval_part = ""
        return f"[bold]{self.label}[/bold]  ·  {badge}{model_part}{cost_part}{approval_part}"

    def _render_footer(self) -> str:
        base = self._STATUS_FOOTER.get(self.status, "")
        if self.reason:
            escaped = self.reason.replace("[", r"\[")
            return f"[dim]Reason:[/dim] {escaped}\n{base}"
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

    def watch_blocked_count(self, _old: int, _new: int) -> None:
        with contextlib.suppress(Exception):  # widget not yet mounted
            self.query_one(".branch-header", Static).update(self._render_header())

    def watch_awaiting_approval(self, _old: bool, _new: bool) -> None:
        with contextlib.suppress(Exception):  # widget not yet mounted
            self.query_one(".branch-header", Static).update(self._render_header())

    def mark_status(self, state: BranchState, reason: str | None = None) -> None:
        """Update the branch's status badge and optional reason text."""
        if state == "running":
            # Reset the replay watermark AND clear the rendered list together.
            # replay_messages_append re-slices from _last_replayed_len=0, so leaving
            # the old messages mounted would re-render the whole transcript on top
            # of itself (duplicated). A done→running flip (continued turn) replays
            # the full history afresh, so a clean list is correct.
            self._last_replayed_len = 0
            self._rendered_call_ids = set()
            self._rendered_call_msgs = {}
            self._final_replayed = False
            with contextlib.suppress(NoMatches):
                self.query_one(MessageList).clear_messages()
        self.reason = reason
        self.status = state

    def replay_final(self, messages: list[Any]) -> None:
        """Idempotent terminal replay — render a finished branch's transcript once.

        The single entry point for both branch-completion renderers (the task
        done-callback and the poll tick). Whichever fires first renders; the
        other is a no-op, so the panel isn't cleared and re-rendered twice (C8).
        Reset by `mark_status("running")` for a continued turn.
        """
        if self._final_replayed:
            return
        self._final_replayed = True
        self.replay_messages(messages)

    def replay_messages(self, messages: list[Any]) -> None:
        """Replay a completed branch's `all_messages()` into the panel.

        Mirrors the replay loop in the `/load` command in commands.py:
        user prompts → :meth:`MessageList.append_user_message`; assistant
        text → :meth:`AssistantMessage.append_text`; tool calls / returns
        rendered with the standard tool-call widget.
        """

        try:
            msg_list = self.query_one(MessageList)
        except NoMatches:  # pragma: no cover - widget not yet mounted
            return

        msg_list.clear_messages()
        # A fresh full replay rebuilds the panel from scratch - reset the
        # per-call reference map so stale entries from a prior replay can't
        # complete rows in the newly cleared list.
        self._rendered_call_msgs = {}
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
                    assistant_msg = msg_list.current_assistant or msg_list.begin_assistant_message()
                    assistant_msg.add_tool_call(part.tool_name, args, call_id)
                    # Hold a reference to the message that rendered this call so
                    # its ToolReturnPart completes the right row even after a
                    # trailing TextPart ends the assistant message (nulling
                    # current_assistant), and so a later incremental append tick
                    # can complete a call first rendered here.
                    self._rendered_call_msgs[call_id] = assistant_msg
                    if call_id not in completed_call_ids:
                        if self.status == "terminated":
                            label = "Interrupted by user"
                        else:
                            label = "No return - model ended run without executing this call"
                        assistant_msg.complete_tool_call(call_id, label, 0.0, True)
                elif isinstance(part, ToolReturnPart):
                    # Complete via the held reference rather than
                    # current_assistant, which is None once a TextPart in the
                    # same response ended the assistant message - that would
                    # leave the tool row spinning forever.
                    held = self._rendered_call_msgs.get(part.tool_call_id)
                    if held is not None:
                        content_str = str(part.content)
                        held.complete_tool_call(
                            part.tool_call_id, content_str, 0.0, looks_like_error(content_str)
                        )

        if msg_list.current_assistant is not None:
            msg_list.current_assistant.finalize_text()
            msg_list.end_assistant_message()

        self._last_replayed_len = len(messages)
        self._rendered_call_ids = set(self._rendered_call_msgs)

    def replay_messages_append(self, messages: list[Any]) -> None:
        """Append only new messages since the last replay - incremental update.

        Called by the poll loop on each tick with the branch's current
        `partial_history`. Only processes messages from index
        `_last_replayed_len` onward, avoiding a full clear + re-render.
        """

        if len(messages) <= self._last_replayed_len:
            return

        try:
            msg_list = self.query_one(MessageList)
        except NoMatches:  # pragma: no cover - widget not yet mounted
            return

        new_messages = messages[self._last_replayed_len :]
        for msg in new_messages:
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
                    call_id = part.tool_call_id
                    if call_id in self._rendered_call_ids:
                        continue
                    args = part.args_as_dict()
                    assistant_msg = msg_list.current_assistant or msg_list.begin_assistant_message()
                    assistant_msg.add_tool_call(part.tool_name, args, call_id)
                    self._rendered_call_ids.add(call_id)
                    self._rendered_call_msgs[call_id] = assistant_msg
                elif isinstance(part, ToolReturnPart):
                    # Complete the row via the message that rendered the call,
                    # held by reference. current_assistant may be None (a prior
                    # tick ended with a text part) and scanning msg_list.children
                    # can miss a freshly-mounted message whose mount hasn't flushed
                    # yet - leaving the spinner stuck across the tick boundary.
                    held = self._rendered_call_msgs.get(part.tool_call_id)
                    if held is not None:
                        content_str = str(part.content)
                        held.complete_tool_call(
                            part.tool_call_id, content_str, 0.0, looks_like_error(content_str)
                        )

        self._last_replayed_len = len(messages)

    def note_streamed_messages(self, messages: list[Any]) -> None:
        """Advance the replay watermark to cover already live-streamed messages.

        `_stream_branch_via_iter` renders a branch's output live via streaming
        deltas without touching `_last_replayed_len`. Once it stops (and
        `streaming` flips False) a poll tick would call
        :meth:`replay_messages_append` from index 0 and re-render - double - the
        whole transcript before the branch is marked `done`. Calling this with
        the streamed transcript moves the watermark past it so that append is a
        no-op.
        """

        self._last_replayed_len = len(messages)
        self._rendered_call_ids.update(
            part.tool_call_id
            for msg in messages
            for part in getattr(msg, "parts", [])
            if isinstance(part, ToolCallPart)
        )

    def set_active(self, active: bool) -> None:
        """Show or hide this panel - only one branch panel is visible at a time."""
        if active:
            self.add_class("active")
        else:
            self.remove_class("active")
