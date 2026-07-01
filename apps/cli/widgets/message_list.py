"""Scrollable message list container."""

from __future__ import annotations

import contextlib
from typing import Any

from pydantic_ai.messages import TextPart, ToolCallPart, ToolReturnPart, UserPromptPart
from textual.containers import VerticalScroll

from apps.cli.text_heuristics import looks_like_error
from apps.cli.widgets.assistant_message import AssistantMessage
from apps.cli.widgets.user_message import UserMessage


class MessageList(VerticalScroll):
    """Scrollable container for chat messages. Auto-scrolls to bottom."""

    DEFAULT_CSS = """
    MessageList {
        height: 1fr;
        padding: 0 0;
    }
    """

    _current_assistant: AssistantMessage | None = None

    def append_user_message(self, text: str, attachments: list[str] | None = None) -> UserMessage:
        """Add a user message and scroll to bottom."""
        msg = UserMessage(text, attachments=attachments)
        self.mount(msg)
        self.scroll_end(animate=False)
        return msg

    def begin_assistant_message(self) -> AssistantMessage:
        """Start a new assistant message turn."""
        msg = AssistantMessage()
        self._current_assistant = msg
        self.mount(msg)
        self.scroll_end(animate=False)
        return msg

    @property
    def current_assistant(self) -> AssistantMessage | None:
        """The currently active assistant message (during streaming)."""
        return self._current_assistant

    def end_assistant_message(self) -> None:
        """Finalize the current assistant message."""
        if self._current_assistant:
            self._current_assistant.finalize_text()
            self._current_assistant = None
        self.scroll_end(animate=False)

    def remove_last_if_empty(self) -> None:
        """Remove the current assistant message if it has no visible content."""
        msg = self._current_assistant
        if msg is not None and msg.is_empty:
            self._current_assistant = None
            with contextlib.suppress(Exception):
                msg.remove()

    def remove_last_turn(self) -> None:
        """Remove the trailing assistant reply and its preceding user message.

        Keeps the visible transcript in sync when a turn is dropped from history
        (``/undo``, ``/retry``). When the tail is a lone user message with no
        reply yet, only that message is removed.
        """
        removed_assistant = False
        for child in reversed(list(self.children)):
            if isinstance(child, AssistantMessage) and not removed_assistant:
                with contextlib.suppress(Exception):
                    child.remove()
                removed_assistant = True
            elif isinstance(child, UserMessage):
                with contextlib.suppress(Exception):
                    child.remove()
                break
        self._current_assistant = None

    def clear_messages(self) -> None:
        """Remove all messages."""
        self._current_assistant = None
        for child in list(self.children):
            child.remove()

    def replay_messages_into(self, messages: list[Any]) -> None:
        """Render a stored message transcript into this list.

        Single source of truth for transcript replay (C4): used by `/load` and
        by branch-merge replay. A tool call with no matching return part (the
        run was interrupted) is shown completed with an "Interrupted" marker;
        returned tool content is flagged as an error via `looks_like_error`.
        """
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
                        self.append_user_message(content)
                elif isinstance(part, TextPart):
                    if part.content:
                        assistant = self.begin_assistant_message()
                        assistant.append_text(part.content)
                        assistant.finalize_text()
                        self.end_assistant_message()
                elif isinstance(part, ToolCallPart):
                    assistant = self.current_assistant or self.begin_assistant_message()
                    assistant.add_tool_call(part.tool_name, part.args_as_dict(), part.tool_call_id)
                    if part.tool_call_id not in completed_call_ids:
                        assistant.complete_tool_call(part.tool_call_id, "Interrupted", 0.0, True)
                elif isinstance(part, ToolReturnPart):
                    content_str = str(part.content)
                    assistant = self.current_assistant
                    if assistant is not None:
                        assistant.complete_tool_call(
                            part.tool_call_id, content_str, 0.0, looks_like_error(content_str)
                        )
        if self.current_assistant is not None:
            self.current_assistant.finalize_text()
            self.end_assistant_message()
