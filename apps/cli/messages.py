"""Custom Textual messages for agent ↔ UI communication.

All communication from the background agent worker to the widget tree
goes through these typed messages.
"""

from __future__ import annotations

import asyncio
from typing import Any

from textual.message import Message

# Streaming messages


class AgentTextComplete(Message):
    """The model finished producing text for the current turn."""

    def __init__(self, full_text: str) -> None:
        super().__init__()
        self.full_text = full_text


class AgentThinking(Message):
    """Status update while the agent is processing (e.g. "thinking…")."""

    def __init__(self, status: str) -> None:
        super().__init__()
        self.status = status


# Approval messages


class ApprovalRequested(Message):
    """A tool needs user approval before running."""

    def __init__(
        self,
        tool_name: str,
        args: dict[str, Any],
        future: asyncio.Future[str],
    ) -> None:
        super().__init__()
        self.tool_name = tool_name
        self.args = args
        self.future = future


# Agent lifecycle messages


class AgentRunStarted(Message):
    """The agent has started processing a user prompt."""


class AgentComplete(Message):
    """The agent run has finished."""

    def __init__(self, history: list[Any] | None = None) -> None:
        super().__init__()
        self.history = history or []


class AgentError(Message):
    """An error occurred during agent execution."""

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error


# Status messages


class CostUpdated(Message):
    """Cost information has been updated."""

    def __init__(
        self,
        run_cost: float,
        total_cost: float,
        total_input_tokens: int = 0,
        total_output_tokens: int = 0,
    ) -> None:
        super().__init__()
        self.run_cost = run_cost
        self.total_cost = total_cost
        self.total_input_tokens = total_input_tokens
        self.total_output_tokens = total_output_tokens


class ContextUpdated(Message):
    """Context window usage has been updated."""

    def __init__(self, pct: float, current: int, maximum: int) -> None:
        super().__init__()
        self.pct = pct
        self.current = current
        self.maximum = maximum


class TodosUpdated(Message):
    """TODO list has been updated."""

    def __init__(self, todos: list[Any]) -> None:
        super().__init__()
        self.todos = todos


class CompressionStarted(Message):
    """Context compression has started."""


class CompressionComplete(Message):
    """Context compression has finished."""


# User input messages


class UserSubmitted(Message):
    """User submitted a prompt."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class CommandSelected(Message):
    """A slash command was selected from the picker."""

    def __init__(self, command: str) -> None:
        super().__init__()
        self.command = command


class FileSelected(Message):
    """A file was selected from the file picker."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path


class PasteImageRequested(Message):
    """User asked to paste an image from the clipboard (Ctrl+V)."""


class AttachFileRequested(Message):
    """A file path was dropped onto the input — attach it to the next prompt."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path


class MultilinePasteRequested(Message):
    """Multi-line text was pasted into the single-line input — switch to
    multiline mode and keep the pasted structure intact."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text
