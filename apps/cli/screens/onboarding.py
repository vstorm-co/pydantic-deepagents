"""Onboarding screen — first-run setup wizard with API key input."""

from __future__ import annotations

import os

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, OptionList, Static
from textual.widgets.option_list import Option

from apps.cli.keystore import save_key

_PROVIDERS = [
    ("openrouter", "OpenRouter", "OPENROUTER_API_KEY", "https://openrouter.ai/keys"),
    ("anthropic", "Anthropic (Claude)", "ANTHROPIC_API_KEY", "https://console.anthropic.com/"),
    ("openai", "OpenAI (GPT)", "OPENAI_API_KEY", "https://platform.openai.com/api-keys"),
    ("google", "Google (Gemini)", "GOOGLE_API_KEY", "https://aistudio.google.com/apikey"),
    ("ollama", "Ollama (local, free)", "", ""),
]


def _check_provider_status() -> list[tuple[str, str, str, bool]]:
    """Return providers with their key status (checks env vars + keys.toml)."""
    # Ensure keys.toml is loaded
    try:
        from apps.cli.keystore import load_keys

        load_keys()
    except Exception:
        pass

    result: list[tuple[str, str, str, bool]] = []
    for provider_id, name, env_var, _url in _PROVIDERS:
        has_key = bool(os.environ.get(env_var)) if env_var else provider_id == "ollama"
        result.append((provider_id, name, env_var, has_key))
    return result


class ProviderPickerModal(ModalScreen[str | None]):
    """Provider selection modal with key status indicators."""

    DEFAULT_CSS = """
    ProviderPickerModal {
        align: center middle;
    }
    ProviderPickerModal > #provider-container {
        width: 65;
        height: auto;
        border: tall $primary;
        background: $surface;
        padding: 1 2;
    }
    ProviderPickerModal > #provider-container > #provider-list {
        height: auto;
        max-height: 10;
        margin: 1 0;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        providers = _check_provider_status()

        with Vertical(id="provider-container"):
            yield Static("[bold]Select AI Provider[/bold]\n")
            options: list[Option] = []
            for provider_id, name, env_var, has_key in providers:
                if has_key:
                    label = f"[green]✓[/green] {name}"
                elif env_var:
                    label = f"[red]✗[/red] {name}  [dim]({env_var} not set)[/dim]"
                else:
                    label = f"  {name}"
                options.append(Option(label, id=provider_id))

            yield OptionList(*options, id="provider-list")
            yield Static("\n[dim]↑↓ navigate  Enter select  Esc cancel[/dim]")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option.id) if event.option.id else None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class ApiKeyModal(ModalScreen[str | None]):
    """Modal for entering an API key."""

    DEFAULT_CSS = """
    ApiKeyModal {
        align: center middle;
    }
    ApiKeyModal > #key-container {
        width: 70;
        height: auto;
        border: tall $primary;
        background: $surface;
        padding: 1 2;
    }
    ApiKeyModal > #key-container > #key-input {
        margin: 1 0;
    }
    ApiKeyModal > #key-container > #key-actions {
        margin: 1 0 0 0;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, provider_name: str, env_var: str, url: str) -> None:
        super().__init__()
        self._provider_name = provider_name
        self._env_var = env_var
        self._url = url

    def compose(self) -> ComposeResult:
        with Vertical(id="key-container"):
            yield Static(f"[bold]Configure {self._provider_name}[/bold]\n")
            if self._url:
                yield Static(f"Get your key at: [bold]{self._url}[/bold]\n")
            yield Static(f"{self._env_var}:")
            yield Input(
                placeholder="sk-...",
                password=True,
                id="key-input",
            )
            yield Static(
                "\n[dim]The key will be saved to .pydantic-deep/keys.toml "
                "and loaded automatically on next startup.[/dim]"
            )
            with Vertical(id="key-actions"):
                yield Button("Set key & continue", variant="primary", id="btn-set")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#key-input", Input).focus()

    def _save_and_dismiss(self) -> None:
        """Save the key to keys.toml + os.environ and dismiss."""
        key = self.query_one("#key-input", Input).value.strip()
        if not key:
            self.app.notify("Please enter a key", severity="warning")
            return

        save_key(self._env_var, key)
        self.dismiss(key)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-set":
            self._save_and_dismiss()
        elif event.button.id == "btn-cancel":
            self.dismiss(None)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        self._save_and_dismiss()

    def action_cancel(self) -> None:
        self.dismiss(None)
