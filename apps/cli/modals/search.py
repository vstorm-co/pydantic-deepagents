"""Search modal — search through conversation messages."""

from __future__ import annotations

from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from apps.cli.modals._filter_input import FilterInput
from apps.cli.widgets.assistant_message import AssistantMessage
from apps.cli.widgets.message_list import MessageList
from apps.cli.widgets.user_message import UserMessage


class SearchModal(ModalScreen[str | None]):
    """Search through conversation messages and scroll to a match."""

    DEFAULT_CSS = """
    SearchModal {
        align: center middle;
    }
    SearchModal > #search-container {
        width: 70;
        max-height: 28;
        border: tall $primary;
        background: $surface;
        padding: 1;
    }
    SearchModal > #search-container > #search-title {
        height: 1;
        margin: 0 0 1 0;
    }
    SearchModal > #search-container > #search-input {
        height: 1;
        margin: 0 0 1 0;
        border: none;
    }
    SearchModal > #search-container > #search-results {
        height: auto;
        max-height: 18;
    }
    SearchModal > #search-container > #search-hint {
        height: 1;
        color: $text-disabled;
        margin: 1 0 0 0;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._matches: list[tuple[int, str]] = []  # (widget index, snippet)

    def compose(self) -> ComposeResult:
        with Vertical(id="search-container"):
            yield Static("[bold]Search Messages[/bold]", id="search-title")
            from apps.cli.modals._filter_input import FilterInput

            yield FilterInput(
                placeholder="Type to search...",
                id="search-input",
                list_id="search-results",
                enter_selects=True,
            )
            yield OptionList(id="search-results")
            yield Static(
                "[dim]\u2191\u2193 navigate  Enter go to  Esc cancel[/dim]",
                id="search-hint",
            )

    def on_mount(self) -> None:
        self.query_one("#search-input", FilterInput).focus()

    def _collect_messages(self) -> list[tuple[int, str, str]]:
        """Collect all messages from the MessageList.

        Returns list of (child_index, role, text).
        """

        results: list[tuple[int, str, str]] = []
        try:
            msg_list = self.app.screen.query_one(MessageList)
        except Exception:
            # We're on a modal, query the screen underneath
            try:
                for screen in reversed(self.app.screen_stack):
                    try:
                        msg_list = screen.query_one(MessageList)
                        break
                    except Exception:
                        continue
                else:
                    return results
            except Exception:
                return results

        for idx, child in enumerate(msg_list.children):
            if isinstance(child, AssistantMessage):
                text = child._text or ""
                if text.strip():
                    results.append((idx, "Assistant", text))
            elif isinstance(child, UserMessage):
                text = child._text or ""
                if text.strip():
                    results.append((idx, "You", text))

        return results

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter messages as user types."""
        query = event.value.strip().lower()
        option_list = self.query_one("#search-results", OptionList)
        option_list.clear_options()
        self._matches.clear()

        if not query:
            return

        messages = self._collect_messages()
        for child_idx, role, text in messages:
            lower_text = text.lower()
            pos = lower_text.find(query)
            if pos == -1:
                continue

            # Build a snippet around the match
            start = max(0, pos - 30)
            end = min(len(text), pos + len(query) + 30)
            snippet = text[start:end].replace("\n", " ").strip()
            if start > 0:
                snippet = "..." + snippet
            if end < len(text):
                snippet = snippet + "..."

            label = f"[bold]{role}[/bold]: {escape(snippet)}"
            self._matches.append((child_idx, snippet))
            option_list.add_option(Option(label, id=str(child_idx)))

        if not self._matches:
            option_list.add_option(Option("[dim]No matches[/dim]", disabled=True))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Scroll to the selected message."""
        option_id = str(event.option.id) if event.option.id else ""
        self.dismiss(option_id)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        """Select first visible option on Enter."""
        option_list = self.query_one("#search-results", OptionList)
        if option_list.option_count > 0:
            option_list.action_select()

    def action_cancel(self) -> None:
        self.dismiss(None)
