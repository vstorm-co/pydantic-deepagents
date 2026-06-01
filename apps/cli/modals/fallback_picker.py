"""Fallback model picker — opened after /model to optionally select a fallback."""

from __future__ import annotations

import os

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from apps.cli.modals.model_picker import _PROVIDERS_MODELS

_NO_FALLBACK_ID = "__no_fallback__"


class FallbackPickerModal(ModalScreen[str | None]):
    """Modal for selecting an optional fallback model.

    Returns the selected model string, or `None` when the user chooses
    "No fallback" or dismisses the modal.
    """

    DEFAULT_CSS = """
    FallbackPickerModal {
        align: center middle;
    }
    FallbackPickerModal > #fallback-container {
        width: 65;
        max-height: 30;
        border: tall $warning;
        background: $surface;
        padding: 1;
    }
    FallbackPickerModal > #fallback-container > #fallback-list {
        height: auto;
        max-height: 20;
    }
    FallbackPickerModal > #fallback-container > #custom-input {
        margin: 1 0 0 0;
        height: 1;
        border: none;
    }
    FallbackPickerModal > #fallback-container > #fallback-hint {
        height: 1;
        color: $text-disabled;
        margin: 1 0 0 0;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, primary_model: str, current_fallback: str | None = None) -> None:
        super().__init__()
        self._primary_model = primary_model
        self._current_fallback = current_fallback

    def compose(self) -> ComposeResult:
        with Vertical(id="fallback-container"):
            yield Static(f"[bold]Select fallback for[/bold] [cyan]{self._primary_model}[/cyan]")

            options: list[Option] = []

            no_label = "[bold]No fallback[/bold]"
            if self._current_fallback is None:
                no_label += "  [bold](current)[/bold]"
            options.append(Option(no_label, id=_NO_FALLBACK_ID))
            options.append(Option("[dim]──────────────────────────[/dim]", disabled=True))

            for env_var, provider_name, models in _PROVIDERS_MODELS:
                has_key = bool(os.environ.get(env_var))
                status = "[green]✓[/green]" if has_key else "[red]✗[/red]"
                options.append(Option(f"[dim]── {status} {provider_name} ──[/dim]", disabled=True))
                for model in models:
                    if model == self._primary_model:
                        continue
                    label = model
                    if model == self._current_fallback:
                        label += "  [bold](current)[/bold]"
                    if not has_key:
                        label = f"[dim]{label}[/dim]"
                    options.append(Option(label, id=model))

            yield OptionList(*options, id="fallback-list")
            from apps.cli.modals._filter_input import FilterInput

            yield FilterInput(
                placeholder="Or type custom fallback model...",
                id="custom-input",
                list_id="fallback-list",
            )
            yield Static(
                "[dim]↑↓ navigate  Enter select  Esc cancel[/dim]",
                id="fallback-hint",
            )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        option_id = str(event.option.id) if event.option.id else ""
        if option_id == _NO_FALLBACK_ID:
            self.dismiss(None)
        else:
            self.dismiss(option_id)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if text:
            self.dismiss(text)

    def action_cancel(self) -> None:
        self.dismiss(self._current_fallback)
