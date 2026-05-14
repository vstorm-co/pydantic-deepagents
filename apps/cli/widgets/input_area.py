"""Fixed bottom input area with hints bar and history."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Input, Static, TextArea

from apps.cli.messages import CommandSelected, FileSelected, UserSubmitted


class HintsBar(Static):
    """One-line hint bar below the input."""

    DEFAULT_CSS = """
    HintsBar {
        height: 1;
        color: $text-disabled;
        padding: 0 2;
    }
    """

    def __init__(self) -> None:
        super().__init__()

    def reset(self) -> None:
        """Restore the default keyboard hint text."""
        self.update(
            "[dim]↑[/dim] history   "
            "[dim]/[/dim] commands   "
            "[dim]@[/dim] files   "
            "[dim]Ctrl+J[/dim] multiline   "
            "[dim]Ctrl+K[/dim] todos"
        )


class PromptPrefix(Static):
    """Static '> ' prefix displayed to the left of the input."""

    DEFAULT_CSS = """
    PromptPrefix {
        width: 2;
        height: 1;
        color: $accent;
        text-style: bold;
        padding: 0 0;
    }
    """

    def __init__(self) -> None:
        super().__init__("> ")


class PromptRow(Horizontal):
    """Horizontal row containing the > prefix and the input field."""

    DEFAULT_CSS = """
    PromptRow {
        height: 1;
        padding: 0 1;
    }
    """


def _load_history(max_items: int = 500) -> list[str]:
    """Load input history from disk."""
    try:
        from apps.cli.config import get_history_path

        path = get_history_path()
        if path.exists():
            lines = path.read_text().strip().splitlines()
            return lines[-max_items:]
    except Exception:
        pass
    return []


def _save_history_line(text: str) -> None:
    """Append a line to the history file."""
    try:
        from apps.cli.config import get_history_path

        path = get_history_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as f:
            f.write(text + "\n")
    except Exception:
        pass


class PromptInput(Input):
    """Custom input with / and @ triggers and persistent input history."""

    DEFAULT_CSS = """
    PromptInput {
        dock: bottom;
        margin: 0 0;
        border: none;
        padding: 0 0;
        height: 1;
        width: 1fr;
    }
    PromptInput:focus {
        border: none;
    }
    """

    def __init__(self) -> None:
        super().__init__(placeholder="")
        self._history: list[str] = _load_history()
        self._history_index: int = -1

    def on_key(self, event: Any) -> None:
        """Handle special keys for history and triggers."""
        if event.key == "up" and not self.value:
            # Navigate history backwards
            if self._history and self._history_index < len(self._history) - 1:
                self._history_index += 1
                self.value = self._history[-(self._history_index + 1)]
                self.cursor_position = len(self.value)
            event.prevent_default()
        elif event.key == "down" and self._history_index >= 0:
            self._history_index -= 1
            if self._history_index < 0:
                self.value = ""
            else:
                self.value = self._history[-(self._history_index + 1)]
                self.cursor_position = len(self.value)
            event.prevent_default()

    async def on_input_changed(self, event: Input.Changed) -> None:
        """Detect / and @ triggers."""
        val = event.value

        # / as first character → command picker
        if val == "/":
            self.value = ""
            self.post_message(CommandSelected("/"))
            return

        # @ typed → file picker
        if val.endswith("@") and (len(val) == 1 or val[-2] == " "):
            self.value = val[:-1]
            self.post_message(FileSelected("@"))
            return

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Submit the input text."""
        text = event.value.strip()
        if text:
            # Add to history (in-memory + disk)
            if not self._history or self._history[-1] != text:
                self._history.append(text)
                _save_history_line(text)
            self._history_index = -1
            self.post_message(UserSubmitted(text))
            self.value = ""


class MultilineInput(TextArea):
    """Multiline input mode activated by Ctrl+J."""

    DEFAULT_CSS = """
    MultilineInput {
        height: auto;
        max-height: 8;
        min-height: 3;
        margin: 0 2;
        border: tall $accent;
        padding: 0 1;
    }
    """

    BINDINGS = [
        ("ctrl+j", "submit_multiline", "Send"),
        ("escape", "cancel_multiline", "Cancel"),
    ]

    def action_submit_multiline(self) -> None:
        text = self.text.strip()
        if text:
            self.post_message(UserSubmitted(text))
        self.post_message(InputArea.ExitMultiline())

    def action_cancel_multiline(self) -> None:
        self.post_message(InputArea.ExitMultiline())


class InputArea(Vertical):
    """Container for prompt input + hints, with multiline toggle."""

    DEFAULT_CSS = """
    InputArea {
        dock: bottom;
        height: auto;
        max-height: 10;
    }
    """

    is_multiline: reactive[bool] = reactive(False)
    is_agent_running: reactive[bool] = reactive(False)

    class ExitMultiline(Message):
        """Request to exit multiline mode."""

    def compose(self) -> ComposeResult:
        with PromptRow():
            yield PromptPrefix()
            yield PromptInput()
        yield HintsBar()

    @staticmethod
    def _running_hints() -> str:
        return "[dim]>>[/dim] steer   write to queue   [dim]Esc[/dim] interrupt"

    def watch_is_agent_running(self, running: bool) -> None:
        if self.is_multiline:
            return
        hints = self.query_one(HintsBar)
        if running:
            hints.update(self._running_hints())
        else:
            hints.reset()

    def watch_is_multiline(self, multiline: bool) -> None:
        prompt_rows = self.query("PromptRow")
        multi = self.query("MultilineInput")
        hints = self.query_one(HintsBar)

        if multiline:
            for pr in prompt_rows:
                pr.remove()
            self.mount(MultilineInput(), before=hints)
            hints.update(
                "[dim]Ctrl+J[/dim] send   [dim]Esc[/dim] cancel   [dim]Enter[/dim] new line"
            )
            multi_widget = self.query_one(MultilineInput)
            multi_widget.focus()
        else:
            for m in multi:
                m.remove()
            row = PromptRow()
            self.mount(row, before=hints)
            row.mount(PromptPrefix())
            p = PromptInput()
            row.mount(p)
            hints.reset()
            p.focus()

    def on_input_area_exit_multiline(self, _event: ExitMultiline) -> None:
        self.is_multiline = False

    def focus_input(self) -> None:
        """Focus the active input widget."""
        if self.is_multiline:
            multi = self.query("MultilineInput")
            if multi:
                multi.first().focus()
        else:
            prompt = self.query("PromptInput")
            if prompt:
                prompt.first().focus()

    def toggle_multiline(self) -> None:
        """Toggle between single-line and multiline mode."""
        self.is_multiline = not self.is_multiline
