"""Model picker modal — opened by /model."""

from __future__ import annotations

import os

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

# Models grouped by provider with key detection
_PROVIDERS_MODELS: list[tuple[str, str, list[str]]] = [
    (
        "OPENROUTER_API_KEY",
        "OpenRouter",
        [
            "openrouter:anthropic/claude-opus-4.6",
            "openrouter:anthropic/claude-sonnet-4.6",
            "openrouter:anthropic/claude-opus-4.5",
            "openrouter:anthropic/claude-sonnet-4.5",
            "openrouter:anthropic/claude-haiku-4.5",
            "openrouter:anthropic/claude-opus-4.1",
            "openrouter:anthropic/claude-opus-4",
            "openrouter:anthropic/claude-sonnet-4",
            "openrouter:anthropic/claude-3.5-haiku",
            "openrouter:anthropic/claude-3.5-sonnet",
            "openrouter:openai/gpt-5.4",
            "openrouter:openai/gpt-5.3-codex",
            "openrouter:openai/gpt-5.2-codex",
            "openrouter:google/gemma-4-26b-a4b-it:free",
            "openrouter:google/gemma-4-31b-it:free",
            "openrouter:google/gemini-3.1-flash-lite-preview",
            "openrouter:google/gemini-3.1-pro-preview",
            "openrouter:z-ai/glm-5.1",
            "openrouter:z-ai/glm-5-turbo",
            "openrouter:z-ai/glm-5",
            "openrouter:z-ai/glm-4.7",
            "openrouter:x-ai/grok-4.20-multi-agent",
            "openrouter:x-ai/grok-4.20",
            "openrouter:x-ai/grok-4.1-fast",
            "openrouter:x-ai/grok-4-fast",
        ],
    ),
    (
        "ANTHROPIC_API_KEY",
        "Anthropic",
        [
            "anthropic:claude-opus-4-6",
            "anthropic:claude-sonnet-4-6",
            "anthropic:claude-haiku-4-5",
        ],
    ),
    (
        "OPENAI_API_KEY",
        "OpenAI",
        [
            "openai:gpt-5.4",
            "openai:gpt-5.3-codex",
            "openai:gpt-5.2-codex",
        ],
    ),
    (
        "GOOGLE_API_KEY",
        "Google",
        [
            "google-gla:gemini-3.1-pro-preview",
            "google-gla:gemini-3.1-flash-lite-preview",
        ],
    ),
]


class ModelPickerModal(ModalScreen[str | None]):
    """Modal for selecting or typing a model name. Shows key status per provider."""

    DEFAULT_CSS = """
    ModelPickerModal {
        align: center middle;
    }
    ModelPickerModal > #model-container {
        width: 65;
        max-height: 28;
        border: tall $primary;
        background: $surface;
        padding: 1;
    }
    ModelPickerModal > #model-container > #model-list {
        height: auto;
        max-height: 18;
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

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, current_model: str = "") -> None:
        super().__init__()
        self._current_model = current_model

    def compose(self) -> ComposeResult:
        with Vertical(id="model-container"):
            yield Static("[bold]Select Model[/bold]")

            options: list[Option] = []
            for env_var, provider_name, models in _PROVIDERS_MODELS:
                has_key = bool(os.environ.get(env_var))
                status = "[green]✓[/green]" if has_key else "[red]✗[/red]"
                options.append(Option(f"[dim]── {status} {provider_name} ──[/dim]", disabled=True))
                for model in models:
                    label = model
                    if model == self._current_model:
                        label += "  [bold](current)[/bold]"
                    if not has_key:
                        label = f"[dim]{label}[/dim]"
                    options.append(Option(label, id=model))

            yield OptionList(*options, id="model-list")
            from apps.cli.modals._filter_input import FilterInput

            yield FilterInput(
                placeholder="Or type custom model string...",
                id="custom-input",
                list_id="model-list",
            )
            yield Static(
                "[dim]↑↓ navigate  Enter select  Esc cancel[/dim]",
                id="model-hint",
            )

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        model = str(event.option.id) if event.option.id else ""
        self.dismiss(model)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if text:
            self.dismiss(text)

    def action_cancel(self) -> None:
        self.dismiss(None)
