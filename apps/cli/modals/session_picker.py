"""Session picker modal — /load command. Shows actual saved sessions."""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from apps.cli.config import get_sessions_dir
from apps.cli.fuzzy import fuzzy_filter
from apps.cli.modals._filter_input import FilterInput


def _load_sessions() -> list[dict[str, str]]:
    """Discover saved sessions, most-recently-modified first.

    Reads + JSON-parses each session's messages.json, so callers should run
    this off the event loop (it can be slow with many large sessions).
    """

    sessions_dir = get_sessions_dir()
    if not sessions_dir.is_dir():
        return []

    # Sort by messages.json mtime (newest first) rather than directory name,
    # which is a uuid/id and doesn't reflect recency.
    candidates: list[tuple[float, object]] = []
    for session_dir in sessions_dir.iterdir():
        if not session_dir.is_dir():
            continue
        messages_file = session_dir / "messages.json"
        if not messages_file.exists():
            continue
        try:
            mtime = messages_file.stat().st_mtime
        except OSError:
            mtime = 0.0
        candidates.append((mtime, session_dir))
    candidates.sort(key=lambda c: c[0], reverse=True)

    sessions: list[dict[str, str]] = []
    for _mtime, session_dir in candidates[:50]:  # 50 most recent
        messages_file = session_dir / "messages.json"  # type: ignore[operator]
        session_id = session_dir.name  # type: ignore[attr-defined]
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

    return sessions


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
        with Vertical(id="session-container"):
            yield Static("[bold]Load Session[/bold]  [dim]loading…[/dim]", id="session-title")
            yield FilterInput(
                placeholder="Type to filter...",
                id="session-filter",
                list_id="session-list",
                enter_selects=True,
            )
            yield OptionList(id="session-list")
            yield Static(
                "\n[dim]↑↓ navigate  Enter load  Esc cancel[/dim]",
                id="session-hint",
            )

    @staticmethod
    def _key(s: dict[str, str]) -> str:
        return f"{s['date']} {s['id']} {s['preview']}"

    def _make_options(self, sessions: list[dict[str, str]]) -> list[Option]:
        options: list[Option] = []
        for s in sessions:
            label = f"{s['date']}  [dim]{s['messages']} msgs[/dim]  {s['preview']}"
            options.append(Option(label, id=s["id"]))
        return options

    def on_mount(self) -> None:
        self.query_one("#session-filter", FilterInput).focus()
        # Reading + parsing many messages.json files can be slow — do it off the
        # event loop so opening /load never freezes the UI.
        self.run_worker(self._load(), exclusive=True)

    async def _load(self) -> None:
        with contextlib.suppress(Exception):
            self._sessions = await asyncio.to_thread(_load_sessions)
        with contextlib.suppress(Exception):
            self.query_one("#session-title", Static).update(
                f"[bold]Load Session[/bold]  ({len(self._sessions)} found)"
            )
            self._populate(self._sessions)

    def _populate(self, sessions: list[dict[str, str]]) -> None:
        option_list = self.query_one("#session-list", OptionList)
        option_list.clear_options()
        for opt in self._make_options(sessions):
            option_list.add_option(opt)

    def on_input_changed(self, event: Input.Changed) -> None:
        filtered = fuzzy_filter(event.value, self._sessions, key=self._key)
        self._populate(filtered)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        session_id = str(event.option.id) if event.option.id else ""
        self.dismiss(session_id)

    def action_cancel(self) -> None:
        self.dismiss(None)
