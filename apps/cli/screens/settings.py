"""Settings screen — interactive configuration form backed by config.toml."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Input, Static

from apps.cli.config import DEFAULT_CONFIG_PATH, CliConfig, load_config, set_config_value


class SettingsScreen(Screen):
    """Full-screen settings form. Reads from config.toml, writes on Save."""

    DEFAULT_CSS = """
    SettingsScreen {
        background: $background;
    }
    #settings-scroll {
        height: 1fr;
        padding: 1 4;
    }
    .section-title {
        text-style: bold;
        margin: 1 0 0 0;
    }
    .setting-row {
        height: auto;
        margin: 0 0 0 0;
    }
    .setting-label {
        margin: 1 0 0 0;
        color: $text-muted;
    }
    #settings-actions {
        dock: bottom;
        height: 3;
        padding: 1 4;
        background: $surface;
    }
    #settings-actions Button {
        margin: 0 1 0 0;
    }
    """

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._config = None
        self._config_path = None

    def compose(self) -> ComposeResult:
        self._config = load_config()
        self._config_path = DEFAULT_CONFIG_PATH

        with VerticalScroll(id="settings-scroll"):
            yield Static("[bold]Settings[/bold]  [dim]({self._config_path})[/dim]\n")

            # ── Model ──
            yield Static("Model", classes="section-title")
            yield Input(value=self._config.model, id="cfg-model")

            # ── Features ──
            yield Static("Features", classes="section-title")
            yield Checkbox("Skills", value=self._config.include_skills, id="cfg-include_skills")
            yield Checkbox("Memory", value=self._config.include_memory, id="cfg-include_memory")
            yield Checkbox(
                "Subagents", value=self._config.include_subagents, id="cfg-include_subagents"
            )
            yield Checkbox("Todo list", value=self._config.include_todo, id="cfg-include_todo")
            yield Checkbox("Plan mode", value=self._config.include_plan, id="cfg-include_plan")
            yield Checkbox("Web search", value=self._config.web_search, id="cfg-web_search")
            yield Checkbox("Web fetch", value=self._config.web_fetch, id="cfg-web_fetch")
            yield Checkbox("Teams", value=self._config.include_teams, id="cfg-include_teams")
            yield Checkbox(
                "Context discovery",
                value=self._config.context_discovery,
                id="cfg-context_discovery",
            )

            # ── Display ──
            yield Static("Display", classes="section-title")
            yield Checkbox("Show cost", value=self._config.show_cost, id="cfg-show_cost")
            yield Checkbox("Show tokens", value=self._config.show_tokens, id="cfg-show_tokens")

            # ── Advanced ──
            yield Static("Advanced", classes="section-title")
            yield Static("Approve tools (comma-separated)", classes="setting-label")
            yield Input(
                value=", ".join(self._config.approve_tools),
                id="cfg-approve_tools",
            )
            yield Static("Thinking effort (high/medium/low)", classes="setting-label")
            yield Input(value=self._config.thinking_effort, id="cfg-thinking_effort")
            yield Static("Temperature (leave empty for default)", classes="setting-label")
            yield Input(
                value=str(self._config.temperature) if self._config.temperature is not None else "",
                id="cfg-temperature",
                placeholder="e.g. 0.7",
            )

        with Horizontal(id="settings-actions"):
            yield Button("Save", variant="primary", id="btn-save")
            yield Button("Reset to defaults", variant="warning", id="btn-reset")
            yield Button("Back (Esc)", variant="default", id="btn-back")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-save":
            self._save_config()
        elif event.button.id == "btn-reset":
            self._reset_to_defaults()
        elif event.button.id == "btn-back":
            self.app.pop_screen()

    def _save_config(self) -> None:
        """Save current form values to config.toml."""

        if self._config_path is None:
            return

        fields_to_save: list[tuple[str, str]] = []

        # Text inputs
        model = self.query_one("#cfg-model", Input).value.strip()
        if model:
            fields_to_save.append(("model", model))

        approve = self.query_one("#cfg-approve_tools", Input).value.strip()
        fields_to_save.append(("approve_tools", approve))

        # Always persist thinking_effort: an empty string is coerced to None by
        # set_config_value, so clearing the field resets it to the default
        # ("high") instead of silently keeping the old persisted value.
        thinking = self.query_one("#cfg-thinking_effort", Input).value.strip()
        fields_to_save.append(("thinking_effort", thinking))

        # Always persist temperature: an empty string is coerced to None by
        # set_config_value, so clearing the field resets it to the provider
        # default instead of silently keeping the old persisted value.
        temp = self.query_one("#cfg-temperature", Input).value.strip()
        fields_to_save.append(("temperature", temp))

        # Checkboxes
        checkbox_fields = [
            "include_skills",
            "include_memory",
            "include_subagents",
            "include_todo",
            "include_plan",
            "web_search",
            "web_fetch",
            "include_teams",
            "context_discovery",
            "show_cost",
            "show_tokens",
        ]
        for field_name in checkbox_fields:
            cb = self.query_one(f"#cfg-{field_name}", Checkbox)
            fields_to_save.append((field_name, "true" if cb.value else "false"))

        # Write all values
        try:
            for key, value in fields_to_save:
                set_config_value(self._config_path, key, value)
            self.app.notify("\u2713 Settings saved to config.toml", severity="information")

            # Update app model if changed
            if model and model != self.app.model_name:
                self.app.model_name = model  # type: ignore[attr-defined]
        except Exception as e:
            self.app.notify(f"Error saving: {e}", severity="error")

    def _reset_to_defaults(self) -> None:
        """Reset all form fields to default config values."""

        defaults = CliConfig()

        try:
            self.query_one("#cfg-model", Input).value = defaults.model
            self.query_one("#cfg-approve_tools", Input).value = ", ".join(defaults.approve_tools)
            self.query_one("#cfg-thinking_effort", Input).value = defaults.thinking_effort
            self.query_one("#cfg-temperature", Input).value = (
                str(defaults.temperature) if defaults.temperature is not None else ""
            )

            checkbox_fields = [
                "include_skills",
                "include_memory",
                "include_subagents",
                "include_todo",
                "include_plan",
                "web_search",
                "web_fetch",
                "include_teams",
                "context_discovery",
                "show_cost",
                "show_tokens",
            ]
            for field_name in checkbox_fields:
                cb = self.query_one(f"#cfg-{field_name}", Checkbox)
                cb.value = getattr(defaults, field_name)

            self.app.notify("\u2713 Reset to defaults (not saved yet)", severity="information")
        except Exception as e:
            self.app.notify(f"Error resetting: {e}", severity="error")

    def action_go_back(self) -> None:
        self.app.pop_screen()
