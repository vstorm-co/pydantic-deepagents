"""Interactive settings modal — /settings.

A compact, themed overlay for changing settings straight from the CLI: arrow
keys move, space toggles a feature, enter edits a value (model via the picker,
thinking effort and theme cycle in place). Every change is persisted to
config.toml immediately and applied live where it can be (model, theme).
"""

from __future__ import annotations

import contextlib

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from apps.cli.config import DEFAULT_CONFIG_PATH, load_config, set_config_value

_THINKING_CYCLE = ["high", "medium", "low"]

# (config key, label) for the boolean feature toggles, in display order.
_TOGGLES: list[tuple[str, str]] = [
    ("include_skills", "Skills"),
    ("include_memory", "Memory"),
    ("include_subagents", "Subagents"),
    ("include_plan", "Plan mode"),
    ("include_todo", "Todos"),
    ("web_search", "Web search"),
    ("web_fetch", "Web fetch"),
    ("tool_search", "Tool search (defer tools)"),
    ("include_browser", "Browser"),
    ("include_teams", "Teams"),
    ("context_discovery", "Context discovery"),
    ("show_cost", "Show cost"),
    ("show_tokens", "Show tokens"),
]


class SettingsModal(ModalScreen[None]):
    """Arrow-key settings overlay backed by config.toml."""

    DEFAULT_CSS = """
    SettingsModal {
        align: center middle;
    }
    SettingsModal > #settings-box {
        width: 60;
        max-height: 90%;
        border: tall $accent;
        background: $surface;
        padding: 1 2;
    }
    SettingsModal #settings-title {
        text-style: bold;
        color: $foreground;
        padding: 0 0 1 0;
    }
    SettingsModal #settings-body {
        height: auto;
    }
    SettingsModal #settings-hint {
        color: $text-muted;
        padding: 1 0 0 0;
    }
    """

    BINDINGS = [
        Binding("up", "move(-1)", "Up", show=False),
        Binding("down", "move(1)", "Down", show=False),
        Binding("space", "activate", "Toggle", show=False),
        Binding("enter", "activate", "Edit", show=False),
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
    ]

    def __init__(self) -> None:
        super().__init__()
        # Each row: ("value"|"toggle", key, label). Value rows come first.
        self._rows: list[tuple[str, str, str]] = [
            ("value", "model", "Model"),
            ("value", "thinking_effort", "Thinking"),
            ("value", "theme", "Theme"),
            *[("toggle", key, label) for key, label in _TOGGLES],
        ]
        self._sel = 0

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="settings-box"):
            yield Static("◆ settings", id="settings-title")
            yield Static(id="settings-body")
            yield Static(
                "[$text-muted]↑↓ move   space toggle   enter edit   esc close[/]",
                id="settings-hint",
            )

    def on_mount(self) -> None:
        self._repaint()

    # ── rendering ────────────────────────────────────────────────────

    def _repaint(self) -> None:
        cfg = load_config()
        lines: list[str] = []
        for i, (kind, key, label) in enumerate(self._rows):
            selected = i == self._sel
            marker = "[$accent]▸[/]" if selected else " "
            label_m = f"[$accent b]{label}[/]" if selected else f"[$foreground]{label}[/]"
            if kind == "toggle":
                on = bool(getattr(cfg, key, False))
                glyph = "[$success]◉[/]" if on else "[$text-muted]○[/]"
                lines.append(f"{marker} {glyph}  {label_m}")
            else:
                value = str(getattr(cfg, key, "") or "—")
                lines.append(f"{marker} {label_m}  [$text-muted]{value}[/]")
            # Blank line after the value block, before the toggles.
            if i == 2:
                lines.append("")
        self.query_one("#settings-body", Static).update("\n".join(lines))

    # ── actions ──────────────────────────────────────────────────────

    def action_move(self, delta: int) -> None:
        self._sel = (self._sel + delta) % len(self._rows)
        self._repaint()

    def action_activate(self) -> None:
        kind, key, _label = self._rows[self._sel]
        if kind == "toggle":
            self._toggle(key)
        elif key == "model":
            self._edit_model()
        elif key == "thinking_effort":
            self._cycle_thinking()
        elif key == "theme":
            self._cycle_theme()

    def _persist(self, key: str, value: str) -> None:
        with contextlib.suppress(Exception):
            set_config_value(DEFAULT_CONFIG_PATH, key, value)

    def _apply_live(self) -> None:
        """Rebuild the agent from the freshly-persisted config so the change
        takes effect now — no restart needed."""
        reconfigure = getattr(self.app, "reconfigure_agent", None)
        if reconfigure is not None:
            with contextlib.suppress(Exception):
                reconfigure()

    def _toggle(self, key: str) -> None:
        cfg = load_config()
        new = not bool(getattr(cfg, key, False))
        self._persist(key, "true" if new else "false")
        self._apply_live()
        self._repaint()
        self.app.notify(f"{key} {'on' if new else 'off'}")

    def _cycle_thinking(self) -> None:
        cfg = load_config()
        cur = cfg.thinking_effort or "high"
        idx = _THINKING_CYCLE.index(cur) if cur in _THINKING_CYCLE else -1
        nxt = _THINKING_CYCLE[(idx + 1) % len(_THINKING_CYCLE)]
        self._persist("thinking_effort", nxt)
        self._apply_live()
        self._repaint()

    def _cycle_theme(self) -> None:
        from apps.cli.styles.themes import apply_theme, available_themes

        themes = available_themes()
        cfg = load_config()
        cur = cfg.theme if cfg.theme in themes else themes[0]
        nxt = themes[(themes.index(cur) + 1) % len(themes)]
        apply_theme(self.app, nxt)
        self._persist("theme", nxt)
        self._repaint()

    def _edit_model(self) -> None:
        from apps.cli.modals.model_picker import ModelPickerModal

        def _on_pick(result: str | None) -> None:
            if not result:
                return
            self._persist("model", result)
            with contextlib.suppress(Exception):
                self.app.reconfigure_agent(model=result)  # type: ignore[attr-defined]
                self.app.model_name = result  # type: ignore[attr-defined]
            self._repaint()
            self.app.notify(f"Model: {result}")

        self.app.push_screen(ModelPickerModal(self.app.model_name), _on_pick)

    def action_dismiss(self, result: object = None) -> None:
        self.dismiss(None)
