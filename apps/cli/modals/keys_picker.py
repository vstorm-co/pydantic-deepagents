"""Credential picker modal — opened by /keys.

Lists every credential from the registry (grouped, with set/unset status) so the
user can pick one and enter its value via `ApiKeyModal`.
"""

from __future__ import annotations

import os

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from apps.cli.credentials import CREDENTIALS


class KeysPickerModal(ModalScreen[str | None]):
    """Pick a credential to set. Dismisses with the chosen env-var name, or None."""

    DEFAULT_CSS = """
    KeysPickerModal {
        align: center middle;
    }
    KeysPickerModal > #keys-container {
        width: 72;
        max-height: 30;
        border: tall $primary;
        background: $surface;
        padding: 1;
    }
    KeysPickerModal > #keys-container > #keys-list {
        height: auto;
        max-height: 20;
    }
    KeysPickerModal > #keys-container > #keys-filter {
        margin: 1 0 0 0;
        height: 1;
        border: none;
    }
    KeysPickerModal > #keys-container > #keys-hint {
        height: 1;
        color: $text-disabled;
        margin: 1 0 0 0;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="keys-container"):
            yield Static("[bold]Set a credential[/bold]")

            options: list[Option] = []
            last_category = ""
            for cred in CREDENTIALS:
                if cred.category != last_category:
                    options.append(Option(f"[dim]── {cred.category} ──[/dim]", disabled=True))
                    last_category = cred.category
                is_set = bool(os.environ.get(cred.env_var))
                mark = "[green]✓[/green]" if is_set else "[dim]○[/dim]"
                options.append(
                    Option(f"{mark} {cred.env_var}  [dim]{cred.label}[/dim]", id=cred.env_var)
                )

            yield OptionList(*options, id="keys-list")
            from apps.cli.modals._filter_input import FilterInput

            yield FilterInput(placeholder="Type to filter…", id="keys-filter", list_id="keys-list")
            yield Static("[dim]↑↓ navigate  Enter select  Esc cancel[/dim]", id="keys-hint")

    def on_mount(self) -> None:
        # Focus the filter so the user can type to search immediately.
        self.query_one("#keys-filter", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Live-filter credentials by env var or label as the user types."""
        try:
            option_list = self.query_one("#keys-list", OptionList)
        except Exception:
            return
        query = event.value.strip().lower()
        option_list.clear_options()
        if not query:
            self._add_all(option_list)
            return
        any_match = False
        for cred in CREDENTIALS:
            if query in cred.env_var.lower() or query in cred.label.lower():
                is_set = bool(os.environ.get(cred.env_var))
                mark = "[green]✓[/green]" if is_set else "[dim]○[/dim]"
                option_list.add_option(
                    Option(f"{mark} {cred.env_var}  [dim]{cred.label}[/dim]", id=cred.env_var)
                )
                any_match = True
        if any_match:
            option_list.highlighted = 0  # so Enter picks the top match

    def _add_all(self, option_list: OptionList) -> None:
        last_category = ""
        for cred in CREDENTIALS:
            if cred.category != last_category:
                option_list.add_option(Option(f"[dim]── {cred.category} ──[/dim]", disabled=True))
                last_category = cred.category
            is_set = bool(os.environ.get(cred.env_var))
            mark = "[green]✓[/green]" if is_set else "[dim]○[/dim]"
            option_list.add_option(
                Option(f"{mark} {cred.env_var}  [dim]{cred.label}[/dim]", id=cred.env_var)
            )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option.id) if event.option.id else None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        # Prefer the highlighted credential; fall back to the typed env-var name.
        try:
            ol = self.query_one("#keys-list", OptionList)
            if ol.highlighted is not None:
                opt = ol.get_option_at_index(ol.highlighted)
                if opt is not None and opt.id:
                    self.dismiss(str(opt.id))
                    return
        except Exception:
            pass
        text = event.value.strip().upper()
        if text:
            self.dismiss(text)

    def action_cancel(self) -> None:
        self.dismiss(None)
