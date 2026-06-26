"""File picker modal — opened by typing @."""

from __future__ import annotations

import os
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from apps.cli.modals._filter_input import FilterInput

_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    "dist",
    "build",
    ".eggs",
    "*.egg-info",
}


def _scan_files(root: str | Path, max_files: int = 500) -> list[str]:
    """Scan working directory for files, respecting skip dirs."""
    root = Path(root)
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Filter out skip dirs in-place
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]
        for f in sorted(filenames):
            if f.startswith("."):
                continue
            rel = os.path.relpath(os.path.join(dirpath, f), root)
            files.append(rel)
            if len(files) >= max_files:
                return files
    return files


class FilePickerModal(ModalScreen[str | None]):
    """Floating file picker with real-time fuzzy filtering."""

    DEFAULT_CSS = """
    FilePickerModal {
        align: center middle;
    }
    FilePickerModal > #picker-container {
        width: 70;
        max-height: 24;
        border: tall $primary;
        background: $surface;
        padding: 1;
    }
    FilePickerModal > #picker-container > #file-filter {
        height: 1;
        margin: 0 0 1 0;
        border: none;
    }
    FilePickerModal > #picker-container > #file-list {
        height: auto;
        max-height: 16;
    }
    FilePickerModal > #picker-container > #file-hint {
        height: 1;
        color: $text-disabled;
        margin: 1 0 0 0;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, working_dir: str | Path = ".") -> None:
        super().__init__()
        self._working_dir = Path(working_dir)
        self._all_files: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-container"):
            yield Static("[bold]Files[/bold]", id="file-title")
            from apps.cli.modals._filter_input import FilterInput

            yield FilterInput(
                placeholder="Type to filter...",
                id="file-filter",
                list_id="file-list",
                enter_selects=True,
            )
            yield OptionList(id="file-list")
            yield Static(
                "[dim]↑↓ navigate  Enter select  Esc cancel[/dim]",
                id="file-hint",
            )

    def on_mount(self) -> None:
        self._all_files = _scan_files(self._working_dir)
        self._update_list(self._all_files[:50])

        self.query_one("#file-filter", FilterInput).focus()

    def _update_list(self, files: list[str]) -> None:
        option_list = self.query_one("#file-list", OptionList)
        option_list.clear_options()
        for f in files:
            option_list.add_option(Option(f, id=f))

    def on_input_changed(self, event: Input.Changed) -> None:
        from apps.cli.fuzzy import fuzzy_filter

        filtered = fuzzy_filter(event.value, self._all_files, key=lambda f: f)
        self._update_list(filtered[:50])

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        path = str(event.option.id) if event.option.id else ""
        self.dismiss(path)

    def action_cancel(self) -> None:
        self.dismiss(None)
