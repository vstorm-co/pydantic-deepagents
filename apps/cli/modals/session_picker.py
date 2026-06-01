"""Session picker modal — /load command. Shows actual saved sessions."""

from __future__ import annotations

import json
from datetime import datetime

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from apps.cli.config import get_sessions_dir
from apps.cli.modals._filter_input import FilterInput


def _load_sessions() -> list[dict[str, str]]:
    """Discover saved sessions from the sessions directory."""

    sessions_dir = get_sessions_dir()
    if not sessions_dir.is_dir():
        return []

    sessions: list[dict[str, str]] = []
    for session_dir in sorted(sessions_dir.iterdir(), reverse=True):
        if not session_dir.is_dir():
            continue

        messages_file = session_dir / "messages.json"
        if not messages_file.exists():
            continue

        session_id = session_dir.name
        msg_count = 0
        first_user_msg = ""
        modified = ""

        try:
            stat = messages_file.stat()
            modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")

            data = json.loads(messages_file.read_text())
            if isinstance(data, list):
                msg_count = len(data)
                # Find first user message for preview
                for msg in data:
                    parts = msg.get("parts", [])
                    for part in parts:
                        if part.get("part_kind") == "user-prompt" and part.get("content"):
                            first_user_msg = str(part["content"])[:50]
                            break
                    if first_user_msg:
                        break
        except Exception:
            pass

        sessions.append(
            {
                "id": session_id,
                "date": modified,
                "messages": str(msg_count),
                "preview": first_user_msg,
            }
        )

    return sessions[:50]  # Limit to 50 most recent


class SessionPickerModal(ModalScreen[str | None]):
    """Session browser for loading saved conversations."""

    DEFAULT_CSS = """
    SessionPickerModal {
        align: center middle;
    }
    SessionPickerModal > #session-container {
        width: 80;
        max-height: 28;
        border: tall $primary;
        background: $surface;
        padding: 1 2;
    }
    SessionPickerModal > #session-container > #session-filter {
        height: 1;
        margin: 0 0 1 0;
        border: none;
    }
    SessionPickerModal > #session-container > #session-list {
        height: auto;
        max-height: 18;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._sessions: list[dict[str, str]] = []

    def compose(self) -> ComposeResult:
        self._sessions = _load_sessions()

        with Vertical(id="session-container"):
            yield Static(f"[bold]Load Session[/bold]  ({len(self._sessions)} found)\n")
            from apps.cli.modals._filter_input import FilterInput

            yield FilterInput(
                placeholder="Type to filter...",
                id="session-filter",
                list_id="session-list",
                enter_selects=True,
            )
            yield OptionList(*self._make_options(self._sessions), id="session-list")
            yield Static(
                "\n[dim]↑↓ navigate  Enter load  Esc cancel[/dim]",
                id="session-hint",
            )

    def _make_options(self, sessions: list[dict[str, str]]) -> list[Option]:
        options: list[Option] = []
        for s in sessions:
            label = f"{s['date']}  [dim]{s['messages']} msgs[/dim]  {s['preview']}"
            options.append(Option(label, id=s["id"]))
        return options

    def on_mount(self) -> None:
        self.query_one("#session-filter", FilterInput).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        query = event.value.strip().lower()
        if query:
            filtered = [
                s
                for s in self._sessions
                if query in s["preview"].lower() or query in s["id"].lower() or query in s["date"]
            ]
        else:
            filtered = self._sessions

        option_list = self.query_one("#session-list", OptionList)
        option_list.clear_options()
        for opt in self._make_options(filtered):
            option_list.add_option(opt)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        session_id = str(event.option.id) if event.option.id else ""
        self.dismiss(session_id)

    def action_cancel(self) -> None:
        self.dismiss(None)
