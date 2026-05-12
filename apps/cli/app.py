"""Root Textual application for pydantic-deep TUI."""

from __future__ import annotations

import asyncio
import contextlib
import subprocess
from pathlib import Path
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.reactive import reactive

from apps.cli.screens.chat import ChatScreen
from apps.cli.widgets.header import DeepHeader
from apps.cli.widgets.status_bar import StatusBar


def _detect_git_branch(working_dir: str) -> str:
    """Detect git branch, return empty string if not a git repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            cwd=working_dir,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


class DeepApp(App):
    """pydantic-deep TUI — Textual-based interactive AI coding assistant."""

    TITLE = "pydantic-deep"
    CSS_PATH = "styles/app.tcss"

    BINDINGS = [
        Binding("ctrl+c", "interrupt", "Interrupt", show=False),
        Binding("ctrl+d", "quit", "Quit", show=False),
        Binding("f1", "show_help", "Help"),
        Binding("f2", "show_settings", "Settings"),
        Binding("f5", "show_context", "Context"),
    ]

    # ── Reactive state ────────────────────────────────────────────

    is_streaming: reactive[bool] = reactive(False)
    model_name: reactive[str] = reactive("")
    app_version: reactive[str] = reactive("0.0.0")
    context_pct: reactive[float] = reactive(0.0)
    context_current: reactive[int] = reactive(0)
    context_max: reactive[int] = reactive(0)
    total_cost: reactive[float] = reactive(0.0)
    current_cost: reactive[float] = reactive(0.0)

    def __init__(
        self,
        agent: Agent[Any, str] | None = None,
        deps: Any | None = None,
        working_dir: str | Path = ".",
        model: str = "anthropic:claude-sonnet-4-6",
        version: str = "0.0.0",
        message_history: list[ModelMessage] | None = None,
        startup_error: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.agent = agent
        self.deps = deps
        self.working_dir = str(working_dir)
        self._model = model
        self._version = version
        self._branch = _detect_git_branch(str(working_dir))
        self.message_history: list[ModelMessage] = message_history or []
        self.last_response: str = ""
        self._agent_task: asyncio.Task[Any] | None = None
        self._startup_error = startup_error
        self.queue = getattr(deps, "message_queue", None)

        # Register custom themes
        from apps.cli.styles.themes import register_themes

        register_themes(self)

        # Apply theme from config
        self._apply_configured_theme()

    def notify(  # type: ignore[override]
        self,
        message: str,
        *,
        title: str = "",
        severity: str = "information",
        timeout: float = 5,
    ) -> None:
        """Show notification and log it to the session log file."""
        from apps.cli.debug_log import get_logger

        level = "info" if severity == "information" else severity
        getattr(get_logger(), level, get_logger().info)(f"[notify] {message}")
        super().notify(message, title=title, severity=severity, timeout=timeout)  # type: ignore[arg-type]

    def _apply_configured_theme(self) -> None:
        """Read theme from config and apply it."""
        try:
            from apps.cli.config import load_config

            config = load_config()
            if config.theme and config.theme != "default":
                from apps.cli.styles.themes import apply_theme

                apply_theme(self, config.theme)
        except Exception:
            pass

    def on_mount(self) -> None:
        self.model_name = self._model
        self.app_version = self._version
        self.push_screen(ChatScreen())
        # Sync state to widgets after screen is pushed
        self.call_later(self._sync_widgets)
        # Show startup error if agent creation failed
        if self._startup_error:
            # Check if this is truly first run (no config.toml)
            from apps.cli.config import get_config_path

            if not get_config_path().exists():
                self.call_later(self._show_onboarding)
            else:
                self.call_later(self._show_startup_error)

    def _sync_widgets(self) -> None:
        """Sync app state to header and status bar widgets."""
        try:
            header = self.screen.query_one(DeepHeader)
            header.version = self._version
            header.model_name = self._model
            header.branch = self._branch
        except NoMatches:
            pass
        try:
            status = self.screen.query_one(StatusBar)
            status.model_name = self._model
        except NoMatches:
            pass

    def compose(self) -> ComposeResult:
        """Empty — ChatScreen is pushed on mount."""
        return []

    def _show_startup_error(self) -> None:
        """Show startup error and open provider setup."""
        from apps.cli.widgets.message_list import MessageList

        try:
            msg_list = self.screen.query_one(MessageList)
            assistant = msg_list.begin_assistant_message()
            error_text = (
                f"**Agent failed to start:**\n\n"
                f"```\n{self._startup_error}\n```\n\n"
                f"Use `/provider` to configure your API key.\n"
            )
            assistant.append_text(error_text)
            assistant.finalize_text()
            msg_list.end_assistant_message()
        except Exception:
            pass

        # Auto-open provider setup
        self.handle_command("/provider")

    def _show_onboarding(self) -> None:
        """Show onboarding flow for first-time users."""
        from apps.cli.widgets.message_list import MessageList

        try:
            msg_list = self.screen.query_one(MessageList)
            assistant = msg_list.begin_assistant_message()
            welcome_text = (
                "**Welcome to pydantic-deep!**\n\n"
                "It looks like this is your first time here. "
                "Let's set up your AI provider to get started.\n"
            )
            assistant.append_text(welcome_text)
            assistant.finalize_text()
            msg_list.end_assistant_message()
        except Exception:
            pass

        # Open provider picker for onboarding
        self.handle_command("/provider")

    def reconfigure_agent(self, model: str | None = None) -> None:
        """Try to recreate the agent (after API key is set).

        If model is None, reads from config. If config model fails,
        tries to detect a working model from available API keys.
        """
        from apps.cli.config import load_config
        from apps.cli.debug_log import get_logger

        log = get_logger()
        config = load_config()
        effective = model or config.model

        # If the effective model requires a key we don't have, try to pick
        # a model that matches an available key
        if not model:
            effective = self._pick_available_model(effective)

        log.info("Reconfiguring agent", model=effective)

        try:
            from apps.cli.agent import create_cli_agent

            agent, deps = create_cli_agent(
                model=effective,
                working_dir=self.working_dir,
            )
            self.agent = agent
            self.deps = deps
            self.queue = getattr(deps, "message_queue", None)
            self._startup_error = None
            self.model_name = effective

            # Save the working model to config
            try:
                from apps.cli.config import DEFAULT_CONFIG_PATH, set_config_value

                set_config_value(DEFAULT_CONFIG_PATH, "model", effective)
            except Exception:
                pass

            log.info("Agent reconfigured successfully", model=effective)
            self.notify(f"Agent ready! Model: {effective}", severity="information")
        except Exception as exc:
            log.error("Agent reconfiguration failed", exc_info=True, model=effective)
            self.notify(f"Still failing: {exc}", severity="error", timeout=10)

    @staticmethod
    def _pick_available_model(current: str) -> str:
        """If the current model's provider key isn't set, pick one that is."""
        import os

        # Map provider prefix → env var → default model
        provider_keys = [
            ("openrouter:", "OPENROUTER_API_KEY", "openrouter:anthropic/claude-sonnet-4"),
            ("anthropic:", "ANTHROPIC_API_KEY", "anthropic:claude-sonnet-4-6"),
            ("openai:", "OPENAI_API_KEY", "openai:gpt-4.1"),
            ("google", "GOOGLE_API_KEY", "google-gla:gemini-2.5-pro"),
        ]

        # Check if current model's key is available
        for prefix, env_var, _ in provider_keys:
            if current.startswith(prefix) and os.environ.get(env_var):
                return current  # Current model's key is set, keep it

        # Current model's key not set — find first available
        for _prefix, env_var, default_model in provider_keys:
            if os.environ.get(env_var):
                return default_model

        return current  # No keys at all — return as-is, will fail with clear error

    # ── Watchers — propagate to widgets ───────────────────────────

    def watch_model_name(self, name: str) -> None:
        try:
            self.screen.query_one(DeepHeader).model_name = name
            self.screen.query_one(StatusBar).model_name = name
        except (NoMatches, Exception):
            pass

    def watch_is_streaming(self, streaming: bool) -> None:
        with contextlib.suppress(NoMatches, Exception):
            self.screen.query_one(DeepHeader).is_streaming = streaming

    def watch_context_pct(self, pct: float) -> None:
        with contextlib.suppress(NoMatches, Exception):
            self.screen.query_one(StatusBar).context_pct = pct

    def watch_total_cost(self, cost: float) -> None:
        with contextlib.suppress(NoMatches, Exception):
            self.screen.query_one(StatusBar).total_cost = cost

    def watch_current_cost(self, cost: float) -> None:
        with contextlib.suppress(NoMatches, Exception):
            self.screen.query_one(StatusBar).current_cost = cost

    # ── Command handling ──────────────────────────────────────────

    def handle_command(self, command: str) -> None:
        """Dispatch a slash command."""
        from apps.cli.commands import dispatch_command

        asyncio.create_task(dispatch_command(self, command))

    # ── Shell commands ────────────────────────────────────────────

    def run_shell_command(self, command: str) -> None:
        """Execute a shell command and show output in message list + save to session."""
        from apps.cli.widgets.message_list import MessageList

        try:
            msg_list = self.screen.query_one(MessageList)
        except (NoMatches, Exception):
            self.notify("Cannot run shell command now", severity="error")
            return

        msg_list.append_user_message(f"!{command}")

        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=self.working_dir,
                timeout=60,
            )
            stdout = result.stdout.rstrip() if result.stdout else ""
            stderr = result.stderr.rstrip() if result.stderr else ""
            exit_code = result.returncode

            parts: list[str] = []
            if stdout:
                parts.append(f"```\n{stdout}\n```")
            if stderr:
                parts.append(f"**stderr:**\n```\n{stderr}\n```")
            if exit_code != 0:
                parts.append(f"Exit code: {exit_code}")
            if not parts:
                parts.append("(no output)")

            output_text = "\n\n".join(parts)

        except subprocess.TimeoutExpired:
            output_text = "**Error:** Command timed out (60s)"
        except Exception as e:
            output_text = f"**Error:** {e}"

        # Use add_system_message to show + persist to session
        try:
            self.screen.add_system_message(output_text)  # type: ignore[attr-defined]
        except Exception:
            # Fallback: just show without saving
            assistant = msg_list.begin_assistant_message()
            assistant.append_text(output_text)
            assistant.finalize_text()
            msg_list.end_assistant_message()

    # ── Actions ───────────────────────────────────────────────────

    def action_interrupt(self) -> None:
        """Handle Ctrl+C — cancel running agent or exit."""
        if self._agent_task and not self._agent_task.done():
            self._agent_task.cancel()
            self.is_streaming = False
            self.notify("Agent interrupted", severity="warning")
        else:
            self.exit()

    def action_show_help(self) -> None:
        self.handle_command("/help")

    def action_show_settings(self) -> None:
        self.handle_command("/settings")

    def action_show_context(self) -> None:
        self.handle_command("/context")
