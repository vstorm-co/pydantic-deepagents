"""Fixed bottom input area with hints bar and history."""

from __future__ import annotations

import contextlib
import re
from pathlib import Path
from typing import Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Input, Static, TextArea

from apps.cli.messages import (
    AttachFileRequested,
    CommandSelected,
    FileSelected,
    MultilinePasteRequested,
    PasteImageRequested,
    UserSubmitted,
)
from apps.cli.widgets.ambient import GenSquares

_MARKUP_RE = re.compile(r"\[/?[^\]]*\]")


def _strip(markup: str) -> str:
    """Remove `[...]` tags for width math."""
    return _MARKUP_RE.sub("", markup)


def _escape_markup(text: str) -> str:
    """Escape `[` so literal text isn't parsed as a Textual content-markup tag."""
    return text.replace("[", r"\[")


def _dropped_file_path(pasted: str) -> str | None:
    """If `pasted` is a single existing file path (as produced by dragging a
    file onto the terminal), return it normalized — else None.

    Terminals paste a dropped path with a trailing space, surrounding quotes,
    and/or backslash-escaped spaces; normalize those before the `is_file` check.
    """
    from pathlib import Path

    text = pasted.strip().strip("'\"")
    text = text.replace("\\ ", " ")  # macOS escapes spaces in dropped paths
    if not text or "\n" in text:
        return None
    try:
        if Path(text).expanduser().is_file():
            return str(Path(text).expanduser())
    except OSError:
        return None
    return None


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
            "[$accent]↑[/] history   "
            "[$accent]/[/] commands   "
            "[$accent]@[/] files   "
            "[$accent]Ctrl+J[/] multiline   "
            "[$accent]Ctrl+K[/] todos"
        )


class SessionFooter(Static):
    """One-line footer under the input: session + workspace, at a glance.

    Shows ``provider · model · thinking`` and ``~/path ⎇ branch`` in a single
    dim row. Width-aware: drops the workspace half first, then trims, so it
    never overflows and ghosts beside the input.
    """

    DEFAULT_CSS = """
    SessionFooter {
        height: 1;
        color: $text-muted;
        padding: 0 2;
    }
    """

    _width: int = 200

    def on_resize(self, event: Any) -> None:
        self._width = event.size.width
        self.refresh_session()

    def refresh_session(self) -> None:
        from rich.cells import cell_len

        app = self.app
        model = str(getattr(app, "model_name", "") or "")
        short_model = model.split(":", 1)[1] if ":" in model else model
        provider = model.split(":", 1)[0] if ":" in model else ""
        thinking = ""
        try:
            from apps.cli.config import load_config

            thinking = str(load_config().thinking_effort or "")
        except Exception:
            pass
        branch = str(getattr(app, "_branch", "") or "")
        path = self._short_path(str(getattr(app, "working_dir", ".")))

        session: list[str] = []
        if provider:
            session.append(f"[$accent]{provider}[/]")
        if short_model:
            session.append(short_model)
        if thinking:
            session.append(f"thinking {thinking}")
        workspace = path + (f"  [$text-muted]⎇ {branch}[/]" if branch else "")

        left = "  [$text-muted]·[/]  ".join(session)
        gap = "      "
        full = f"{left}{gap}{workspace}" if left else workspace
        # Drop the workspace half if the whole line won't fit.
        if cell_len(_strip(full)) > self._width - 2 and left:
            full = left
        self.update(full)

    @staticmethod
    def _short_path(path: str) -> str:
        try:
            p = Path(path)
            home = Path.home()
            text = f"~/{p.relative_to(home)}" if p.is_relative_to(home) else str(p)
        except Exception:
            text = path
        return text if len(text) <= 36 else "…" + text[-35:]


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
        super().__init__("❯ ")


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
        margin: 0 0;
        border: none;
        padding: 0 0;
        height: 1;
        width: 1fr;
        background: transparent;
    }
    PromptInput:focus {
        border: none;
    }
    """

    def __init__(self) -> None:
        super().__init__(placeholder="")
        self._history: list[str] = _load_history()
        self._history_index: int = -1

    def _on_paste(self, event: Any) -> None:
        """Intercept a dropped file path before it's inserted as raw text.

        Dragging a file onto the terminal arrives as a bracketed paste. If the
        pasted text is an existing file, attach it instead of typing the path;
        otherwise fall back to the normal paste-inserts-text behavior.
        """
        path = _dropped_file_path(event.text)
        if path is not None:
            self.post_message(AttachFileRequested(path))
            event.stop()
            return
        # A multi-line paste (e.g. a code block) can't survive a single-line
        # input — hand it to multiline mode with the structure preserved,
        # prepending whatever the user already typed.
        if "\n" in event.text:
            combined = self.value + event.text
            self.post_message(MultilinePasteRequested(combined))
            event.stop()
            return
        super()._on_paste(event)

    def on_key(self, event: Any) -> None:
        """Handle special keys for history and triggers."""
        if event.key == "ctrl+v":
            # The focused Input consumes the key before app-level bindings run,
            # so trigger the clipboard-image paste from here directly.
            event.prevent_default()
            event.stop()
            self.post_message(PasteImageRequested())
            return
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
        margin: 0;
        border: none;
        padding: 0;
        background: transparent;
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
        max-height: 12;
        padding: 0 1 0 1;
    }
    InputArea #prompt-shell {
        height: auto;
    }
    InputArea #gen-squares {
        margin: 0 1 0 0;
    }
    InputArea #prompt-box {
        width: 1fr;
        height: auto;
        border: round $panel;
        padding: 0 1;
    }
    InputArea #prompt-box:focus-within {
        border: round $accent;
    }
    InputArea #attachments-bar {
        height: 1;
        color: $accent;
        padding: 0 2;
        display: none;
    }
    InputArea #attachments-bar.visible {
        display: block;
    }
    """

    is_multiline: reactive[bool] = reactive(False)
    is_agent_running: reactive[bool] = reactive(False)

    class ExitMultiline(Message):
        """Request to exit multiline mode."""

    def compose(self) -> ComposeResult:
        yield Static(id="attachments-bar")
        with Horizontal(id="prompt-shell"):
            yield GenSquares(id="gen-squares")
            with Vertical(id="prompt-box"):  # noqa: SIM117 - distinct nesting levels
                with PromptRow():
                    yield PromptPrefix()
                    yield PromptInput()
        yield HintsBar()
        yield SessionFooter()

    def set_attachments(self, labels: list[str]) -> None:
        """Show pending attachment chips above the prompt (hide when empty)."""
        try:
            bar = self.query_one("#attachments-bar", Static)
        except NoMatches:
            return
        bar.set_class(bool(labels), "visible")
        if labels:
            # Escape `[` so a bracketed label like [Image #1] isn't parsed as markup.
            chips = "  ".join(f"[$accent]{_escape_markup(label)}[/]" for label in labels)
            bar.update(f"{chips}   [$text-muted]esc to clear[/]")

    @staticmethod
    def _running_hints() -> str:
        return "[$accent]>>[/] steer   write to queue   [$accent]Esc[/] interrupt"

    def watch_is_agent_running(self, running: bool) -> None:
        # Light up the squares to the left of the prompt while generating.
        for squares in self.query("#gen-squares").results(GenSquares):
            squares.active = running
        if self.is_multiline:
            return
        hints = self.query_one(HintsBar)
        if running:
            hints.update(self._running_hints())
        else:
            hints.reset()

    def watch_is_multiline(self, multiline: bool) -> None:
        try:
            box = self.query_one("#prompt-box", Vertical)
        except NoMatches:
            return  # not composed yet
        hints = self.query_one(HintsBar)
        has_multi = bool(box.query("MultilineInput"))
        has_single = bool(box.query("PromptRow"))

        # Idempotent: the reactive fires once at mount with the composed state
        # already in place, so don't rebuild (that duplicated the prompt row).
        if multiline and has_multi:
            return
        if not multiline and has_single and not has_multi:
            return

        if multiline:
            for pr in box.query("PromptRow"):
                pr.remove()
            box.mount(MultilineInput())
            hints.update(
                "[$accent]Ctrl+J[/] send   [$accent]Esc[/] cancel   [$accent]Enter[/] new line"
            )
            self.query_one(MultilineInput).focus()
        else:
            for m in box.query("MultilineInput"):
                m.remove()
            row = PromptRow()
            box.mount(row)
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

    def prefill(self, text: str) -> None:
        """Put `text` in the single-line input, cursor at end, and focus it.

        Used when a picked command expects an inline argument (e.g. `/goal `):
        rather than running with no argument, the command is staged so the user
        can type the rest and submit.
        """
        self.is_multiline = False
        prompts = self.query("PromptInput")
        if not prompts:
            return
        prompt = prompts.first()
        prompt.value = text  # type: ignore[attr-defined]
        prompt.cursor_position = len(text)  # type: ignore[attr-defined]
        prompt.focus()

    def toggle_multiline(self) -> None:
        """Toggle between single-line and multiline mode."""
        self.is_multiline = not self.is_multiline

    def enter_multiline_with(self, text: str) -> None:
        """Switch to multiline mode and load `text`, cursor at the end."""
        self.is_multiline = True

        def _load() -> None:
            with contextlib.suppress(Exception):
                ml = self.query_one(MultilineInput)
                ml.text = text
                ml.move_cursor(ml.document.end)
                ml.focus()

        # watch_is_multiline mounts the MultilineInput on the next refresh, so
        # defer loading the text until it exists.
        self.call_after_refresh(_load)

    def on_multiline_paste_requested(self, event: MultilinePasteRequested) -> None:
        """A multi-line paste arrived in the single-line input — preserve it."""
        event.stop()
        self.enter_multiline_with(event.text)
