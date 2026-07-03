"""Model picker modal — opened by /model.

Lists recently-used models, the live OpenRouter catalogue (fetched and cached,
with an offline fallback), and the other providers. Type to filter or enter a
custom model string.
"""

from __future__ import annotations

import os

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

# Shown only when the live OpenRouter catalogue can't be fetched (offline).
_OPENROUTER_FALLBACK = [
    "openrouter:deepseek/deepseek-v4-flash",
    "openrouter:anthropic/claude-sonnet-4.6",
    "openrouter:openai/gpt-5.4",
    "openrouter:google/gemini-3.1-pro-preview",
]

# How many OpenRouter models to list (the filter narrows the rest).
_OPENROUTER_LIMIT = 250


class ModelPickerModal(ModalScreen[str | None]):
    """Select or type a model. Shows recent, OpenRouter (live), and providers."""

    DEFAULT_CSS = """
    ModelPickerModal {
        align: center middle;
    }
    ModelPickerModal > #model-container {
        width: 72;
        max-height: 30;
        border: tall $primary;
        background: $surface;
        padding: 1;
    }
    ModelPickerModal > #model-container > #model-list {
        height: auto;
        max-height: 20;
    }
    ModelPickerModal > #model-container > #custom-input {
        margin: 1 0 0 0;
        height: 1;
        border: none;
    }
    ModelPickerModal > #model-container > #model-hint {
        height: 1;
        color: $text-disabled;
        margin: 1 0 0 0;
    }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, current_model: str = "") -> None:
        super().__init__()
        self._current_model = current_model
        self._used_fallback = False
        # Flat (model, has_key) list across all sections, for search.
        self._all_models: list[tuple[str, bool]] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="model-container"):
            yield Static("[bold]Select Model[/bold]")
            yield OptionList(*self._build_options(), id="model-list")
            from apps.cli.modals._filter_input import FilterInput

            yield FilterInput(
                placeholder="Type to filter, or enter a custom model string…",
                id="custom-input",
                list_id="model-list",
            )
            yield Static(
                "[dim]↑↓ navigate  Enter select  Esc cancel  ·  OpenRouter refreshes live[/dim]",
                id="model-hint",
            )

    def on_mount(self) -> None:
        # Focus the filter input so the user can type to search immediately.
        self.query_one("#custom-input", Input).focus()
        # If we rendered from an empty/absent cache, fetch live in the background.
        if self._used_fallback:
            self._refresh_openrouter()

    # ── option building ─────────────────────────────────────────────────

    def _build_options(self) -> list[Option]:
        from apps.cli.known_models import provider_sections
        from apps.cli.model_history import recent_models
        from apps.cli.openrouter_models import cached_models

        options: list[Option] = []
        seen: set[str] = set()  # option ids must be unique across sections
        self._all_models = []

        def add(model: str, *, has_key: bool) -> None:
            if model in seen:
                return
            seen.add(model)
            self._all_models.append((model, has_key))
            options.append(self._model_option(model, has_key=has_key))

        def header(label: str, *, has_key: bool | None = None) -> None:
            status = ""
            if has_key is not None:
                status = "[green]✓[/green] " if has_key else "[red]✗[/red] "
            options.append(Option(f"[dim]── {status}{label} ──[/dim]", disabled=True))

        # Recently used
        recent = recent_models()
        if recent:
            header("★ Recently used")
            for model in recent:
                add(model, has_key=True)

        # OpenRouter — live catalogue, with an offline fallback list
        or_key = bool(os.environ.get("OPENROUTER_API_KEY"))
        cached = cached_models()
        if cached:
            header("OpenRouter (live)", has_key=or_key)
            for m in cached[:_OPENROUTER_LIMIT]:
                add(m.model_string, has_key=or_key)
        else:
            self._used_fallback = True
            header("OpenRouter", has_key=or_key)
            for model in _OPENROUTER_FALLBACK:
                add(model, has_key=or_key)

        # Every native provider pydantic-ai knows about — keyed ones first
        for _prefix, label, has_key, models in provider_sections():
            header(label, has_key=has_key)
            for model in models:
                add(model, has_key=has_key)

        return options

    def _model_option(self, model: str, *, has_key: bool) -> Option:
        label = model
        if model == self._current_model:
            label += "  [bold](current)[/bold]"
        if not has_key:
            label = f"[dim]{label}[/dim]"
        return Option(label, id=model)

    @work(thread=True, exclusive=True)
    def _refresh_openrouter(self) -> None:
        """Fetch the live OpenRouter catalogue and rebuild the list if it arrives."""
        from apps.cli.openrouter_models import fetch_openrouter_models

        models = fetch_openrouter_models()
        if models:
            self.app.call_from_thread(self._repopulate)

    def _repopulate(self) -> None:
        """Rebuild the option list from the (now-cached) catalogue."""
        self._used_fallback = False
        try:
            option_list = self.query_one("#model-list", OptionList)
        except Exception:
            return
        option_list.clear_options()
        option_list.add_options(self._build_options())

    # ── events ──────────────────────────────────────────────────────────

    def on_input_changed(self, event: Input.Changed) -> None:
        """Live-filter the list as the user types; restore grouping when empty."""
        try:
            option_list = self.query_one("#model-list", OptionList)
        except Exception:
            return
        query = event.value.strip()
        option_list.clear_options()
        if not query:
            option_list.add_options(self._build_options())
            return
        from apps.cli.fuzzy import fuzzy_filter

        matches = fuzzy_filter(query, self._all_models, key=lambda t: t[0])
        if matches:
            for model, has_key in matches:
                option_list.add_option(self._model_option(model, has_key=has_key))
            option_list.highlighted = 0  # so Enter picks the top match
        else:
            option_list.add_option(
                Option("[dim]No match — press Enter to use what you typed[/dim]", disabled=True)
            )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option.id) if event.option.id else "")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        # A bare filter term (no provider prefix) means "pick the highlighted
        # match", not "use this literal string" — otherwise typing `qwen` and
        # hitting Enter would set the model to the un-resolvable name `qwen`.
        if ":" not in text:
            chosen = self._highlighted_model()
            if chosen:
                self.dismiss(chosen)
                return
        if text:
            self.dismiss(text)

    def _highlighted_model(self) -> str | None:
        """The id of the currently-highlighted list option, if any."""
        try:
            ol = self.query_one("#model-list", OptionList)
        except Exception:
            return None
        if ol.highlighted is None:
            return None
        opt = ol.get_option_at_index(ol.highlighted)
        return str(opt.id) if opt is not None and opt.id else None

    def action_cancel(self) -> None:
        self.dismiss(None)
