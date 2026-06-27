"""Root Textual application for pydantic-deep TUI."""

from __future__ import annotations

import asyncio
import contextlib
import os
import subprocess
from pathlib import Path
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage
from textual.app import App, ComposeResult, ScreenStackError
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.reactive import reactive

from apps.cli.commands import dispatch_command
from apps.cli.config import load_config
from apps.cli.debug_log import get_logger
from apps.cli.forking import CLIForkSession
from apps.cli.screens.chat import ChatScreen
from apps.cli.styles.themes import register_themes
from apps.cli.widgets.header import DeepHeader
from apps.cli.widgets.message_list import MessageList
from apps.cli.widgets.status_bar import StatusBar
from pydantic_deep.goal import GoalEvaluator, GoalState
from pydantic_deep.models import DEFAULT_JUDGE_MODEL


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
    """pydantic-deep TUI - Textual-based interactive AI coding assistant."""

    TITLE = "pydantic-deep"
    CSS_PATH = "styles/app.tcss"

    BINDINGS = [
        Binding("ctrl+c", "interrupt", "Interrupt", show=False),
        Binding("escape", "escape_key", "Interrupt/Focus", show=False),
        Binding("ctrl+d", "quit", "Quit", show=False),
        Binding("ctrl+v", "paste_image", "Paste image", show=False),
        Binding("f1", "show_help", "Help"),
        Binding("f2", "show_settings", "Settings"),
        Binding("f5", "show_context", "Context"),
    ]

    is_streaming: reactive[bool] = reactive(False)
    model_name: reactive[str] = reactive("")
    fallback_model_name: reactive[str] = reactive("")
    app_version: reactive[str] = reactive("0.0.0")
    context_pct: reactive[float] = reactive(0.0)
    context_current: reactive[int] = reactive(0)
    context_max: reactive[int] = reactive(0)
    total_cost: reactive[float] = reactive(0.0)
    current_cost: reactive[float] = reactive(0.0)
    #: True once CostTracking has reported an authoritative cost. Distinguishes
    #: "genuinely $0 / cached / un-priceable" from "not yet known" so the status
    #: bar doesn't clobber a real zero with a fabricated estimate (C5).
    cost_known: reactive[bool] = reactive(False)
    active_fork: reactive[CLIForkSession | None] = reactive(None)
    fork_branch_count: reactive[int] = reactive(2)
    fork_aggregate_budget_usd: reactive[float | None] = reactive["float | None"](None)
    fork_branch_models: reactive[list[str | None]] = reactive(list, always_update=True)
    fork_branch_budgets: reactive[list[float | None]] = reactive(list, always_update=True)
    fork_merge_strategy: reactive[str] = reactive("auto_with_fallback")
    fork_judge_model: reactive[str] = reactive(DEFAULT_JUDGE_MODEL)
    fork_confidence_threshold: reactive[float] = reactive(0.80)

    agent_task: asyncio.Task[None] | None = None

    def __init__(
        self,
        agent: Agent[Any, str] | None = None,
        deps: Any | None = None,
        working_dir: str | Path = ".",
        model: str = "anthropic:claude-sonnet-4-6",
        version: str = "0.0.0",
        message_history: list[ModelMessage] | None = None,
        startup_error: str | None = None,
        on_cost_update: Any | None = None,
        on_context_update: Any | None = None,
        on_reminder: Any | None = None,
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
        #: Text of the most recent user prompt — powers `/retry`.
        self.last_user_prompt: str = ""
        self._startup_error = startup_error
        self.queue = getattr(deps, "message_queue", None)
        # Active goaql-completion loop (set via /goal). The evaluator is created
        # lazily on first use so sessions that never set a goal pay nothing.
        self._goal: GoalState | None = None
        self._goal_evaluator: GoalEvaluator | None = None
        # Status-bar / reminder callbacks, retained so reconfigure_agent (e.g.
        # after /model) recreates the agent with the same wiring. Without this,
        # the cost/token/context status bar and reminder notifications go dead
        # for the rest of the session after the first reconfigure.
        self._on_cost_update = on_cost_update
        self._on_context_update = on_context_update
        self._on_reminder = on_reminder
        # Strong references to fire-and-forget background tasks. asyncio only
        # holds a weak reference, so an untracked create_task can be GC'd
        # mid-flight and its exceptions silently dropped.
        self._background_tasks: set[asyncio.Task[Any]] = set()

        # Register custom themes

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

        level = "info" if severity == "information" else severity
        getattr(get_logger(), level, get_logger().info)(f"[notify] {message}")
        super().notify(message, title=title, severity=severity, timeout=timeout)  # type: ignore[arg-type]

    def _apply_configured_theme(self) -> None:
        """Read theme from config and apply it.

        Always applies a `deep-*` theme — including `default` — so the brand
        palette is the baseline and the TUI never shows Textual's stock theme.
        """
        try:
            from apps.cli.config import load_config
            from apps.cli.styles.themes import apply_theme

            config = load_config()
            apply_theme(self, config.theme or "default")
        except Exception:
            pass

    def _seed_fork_settings_from_config(self) -> None:
        """Pull the four fork CLI knobs out of `config.toml` into reactive state.

        Run on mount so :class:`ForkPickerModal` sees the persisted values when
        the user opens `/fork`. Errors are swallowed deliberately - a corrupt
        config should never break startup, just fall back to defaults.
        """
        try:
            from apps.cli.config import load_config

            config = load_config()
            self.fork_branch_count = config.fork_branch_count
            self.fork_aggregate_budget_usd = config.fork_aggregate_budget_usd
            self.fork_branch_models = list(config.fork_branch_models)
            self.fork_branch_budgets = list(config.fork_branch_budgets)
            self.fork_merge_strategy = config.fork_merge_strategy
            self.fork_judge_model = config.fork_judge_model
            self.fork_confidence_threshold = config.fork_confidence_threshold
        except Exception:  # pragma: no cover - defensive: bad config shouldn't break startup
            pass

    def on_mount(self) -> None:
        self.model_name = self._model
        try:
            from apps.cli.config import load_config

            self.fallback_model_name = load_config().fallback_model or ""
        except Exception as exc:
            self.notify(f"Could not read fallback model from config: {exc}", severity="warning")
        self.app_version = self._version
        self._seed_fork_settings_from_config()
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
        """Empty - ChatScreen is pushed on mount."""
        return []

    def _show_startup_error(self) -> None:
        """Show startup error and open provider setup."""

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
        """Recreate the agent from the current config.

        `model` overrides `config.model` when provided. `fallback_model` is
        always read from `config.fallback_model` - callers that want to change
        it should write to the config first (see :meth:`set_fallback_and_reconfigure`).
        If `model` is None and the config model lacks an available API key, picks
        a working model from available keys.
        """

        log = get_logger()
        config = load_config()
        effective = model or config.model

        # If the effective model requires a key we don't have, try to pick
        # a model that matches an available key
        if not model:
            effective = self._pick_available_model(effective)

        effective_fallback = config.fallback_model or None

        log.info("Reconfiguring agent", model=effective, fallback=effective_fallback)
        self.notify(f"Configuring {effective}…", severity="information")
        # create_cli_agent does heavy blocking work (config loads, MCP server
        # construction, DockerSandbox startup, git subprocesses). Run it off the
        # event loop so the TUI stays responsive, then apply on the main thread (C2).
        self.run_worker(
            lambda: self._reconfigure_worker(effective, effective_fallback),
            thread=True,
            exclusive=True,
            group="reconfigure-agent",
        )

    def _reconfigure_worker(self, effective: str, effective_fallback: str | None) -> None:
        """Build the agent in a worker thread; hand results back to the main thread (C2)."""
        from apps.cli.agent import create_cli_agent

        try:
            agent, deps = create_cli_agent(
                model=effective,
                fallback_model=effective_fallback,
                working_dir=self.working_dir,
                on_cost_update=self._on_cost_update,
                on_context_update=self._on_context_update,
                on_reminder=self._on_reminder,
            )
        except Exception as exc:
            get_logger().error("Agent reconfiguration failed", exc_info=True, model=effective)
            self.call_from_thread(
                self.notify, f"Still failing: {exc}", severity="error", timeout=10
            )
            return
        self.call_from_thread(
            self._apply_reconfigured_agent, agent, deps, effective, effective_fallback
        )

    def _apply_reconfigured_agent(
        self, agent: Any, deps: Any, effective: str, effective_fallback: str | None
    ) -> None:
        """Assign the freshly-built agent and persist the model (main thread, C2)."""
        self.agent = agent
        self.deps = deps
        self.queue = getattr(deps, "message_queue", None)
        self._startup_error = None
        self.model_name = effective
        self.fallback_model_name = effective_fallback or ""

        try:
            from apps.cli.config import DEFAULT_CONFIG_PATH, set_config_value

            set_config_value(DEFAULT_CONFIG_PATH, "model", effective)
        except Exception:
            pass

        msg = f"Agent ready! Model: {effective}"
        if effective_fallback:
            msg += f" → fallback: {effective_fallback}"
        get_logger().info(
            "Agent reconfigured successfully", model=effective, fallback=effective_fallback
        )
        self.notify(msg, severity="information")

    def set_fallback_and_reconfigure(self, model: str, fallback: str | None) -> None:
        """Persist `fallback` to config (empty string clears it), then reconfigure
        the agent with `model`. Used by the `/model` flow where the user picks a
        primary model and then chooses a fallback (or "No fallback") in a follow-up
        modal."""
        try:
            from apps.cli.config import DEFAULT_CONFIG_PATH, set_config_value

            set_config_value(DEFAULT_CONFIG_PATH, "fallback_model", fallback or "")
        except Exception as exc:
            self.notify(f"Could not persist fallback model: {exc}", severity="warning")
        self.reconfigure_agent(model=model)

    @staticmethod
    def _pick_available_model(current: str) -> str:
        """If the current model's provider key isn't set, pick one that is."""
        from apps.cli.providers import PROVIDERS

        # Keyed providers only — a model name starts with its provider id.
        keyed = [p for p in PROVIDERS if p.env_var]

        # Current model's key is set → keep it.
        for p in keyed:
            if current.startswith(p.id) and os.environ.get(p.env_var):
                return current

        # Current model's key not set → fall back to the first provider with a key.
        for p in keyed:
            if os.environ.get(p.env_var):
                return p.default_model

        return current  # No keys at all - return as-is, will fail with clear error

    # Watchers - propagate to widgets

    def watch_model_name(self, name: str) -> None:
        # Only the "not ready yet" cases are expected: no screen on the stack
        # (reactive init before mount) or the target widget not mounted. Any
        # other error is a real bug — don't bury it under bare `except` (C11).
        with contextlib.suppress(NoMatches, ScreenStackError):
            self.screen.query_one(DeepHeader).model_name = name
            self.screen.query_one(StatusBar).model_name = name

    def watch_is_streaming(self, streaming: bool) -> None:
        with contextlib.suppress(NoMatches, ScreenStackError):
            self.screen.query_one(DeepHeader).is_streaming = streaming

    def watch_context_pct(self, pct: float) -> None:
        with contextlib.suppress(NoMatches, ScreenStackError):
            self.screen.query_one(StatusBar).context_pct = pct

    def watch_total_cost(self, cost: float) -> None:
        with contextlib.suppress(NoMatches, ScreenStackError):
            self.screen.query_one(StatusBar).total_cost = cost

    def watch_current_cost(self, cost: float) -> None:
        with contextlib.suppress(NoMatches, ScreenStackError):
            self.screen.query_one(StatusBar).current_cost = cost

    def watch_active_fork(self, new: CLIForkSession | None) -> None:
        """Drive fork view enter/exit on the chat screen when `active_fork` flips.

        We only swallow :class:`NoMatches` here - that's the legitimate case
        when the chat screen isn't the top screen (e.g. a modal is open and
        catches the query). Any other exception is a real bug in the fork
        view setup and is surfaced to the user via :meth:`notify` so the
        fork doesn't silently fail to start / clean up.
        """
        screen = self.screen
        action: tuple[str, Any] = (
            ("enter_fork_view", new) if new is not None else ("exit_fork_view", None)
        )
        method_name, arg = action
        handler = getattr(screen, method_name, None)
        if handler is None:
            return
        try:
            if arg is None:
                handler()
            else:
                handler(arg)
        except NoMatches:
            pass
        except Exception as exc:  # pragma: no cover - defensive surfacing
            self.notify(f"Fork view error: {exc}", severity="error", timeout=10)

    # Command handling

    def _spawn_tracked(self, coro: Any, *, label: str) -> asyncio.Task[Any]:
        """Schedule `coro` as a tracked background task.

        Keeps a strong reference until completion (so the task can't be
        garbage-collected mid-flight) and surfaces any non-cancellation
        exception via :meth:`notify` instead of letting it vanish silently.
        """
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)

        def _done(t: asyncio.Task[Any]) -> None:
            self._background_tasks.discard(t)
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:  # pragma: no cover - defensive surfacing
                self.notify(f"{label} failed: {exc}", severity="error", timeout=10)

        task.add_done_callback(_done)
        return task

    def handle_command(self, command: str) -> None:
        """Dispatch a slash command."""

        self._spawn_tracked(dispatch_command(self, command), label=f"Command {command}")

    # Shell commands

    def run_shell_command(self, command: str) -> None:
        """Run a shell command without blocking the UI; show + persist output.

        The subprocess runs in a worker thread (via `_run_shell_async`) so a
        long command like `!make test` keeps the TUI responsive instead of
        freezing the event loop for up to the 60s timeout.
        """
        try:
            msg_list = self.screen.query_one(MessageList)
        except (NoMatches, Exception):
            self.notify("Cannot run shell command now", severity="error")
            return

        msg_list.append_user_message(f"!{command}")
        screen = self.screen
        self._spawn_tracked(
            self._run_shell_async(command, screen, msg_list),
            label=f"shell {command[:20]}",
        )

    async def _run_shell_async(self, command: str, screen: Any, msg_list: Any) -> None:
        """Worker for `run_shell_command` — runs the subprocess off the event loop."""
        try:
            result = await asyncio.to_thread(
                subprocess.run,
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

        # Use add_system_message to show + persist to session.
        try:
            screen.add_system_message(output_text)
        except Exception:
            # Fallback: just show without saving.
            assistant = msg_list.begin_assistant_message()
            assistant.append_text(output_text)
            assistant.finalize_text()
            msg_list.end_assistant_message()

    # Actions

    def _signal_cancelling(self) -> None:
        """Immediately flag in-flight tool calls as stopping for instant feedback.

        Cancellation propagation (killing subprocesses) can take a moment; this
        gives the user visible acknowledgement that Esc/Ctrl+C registered.
        """
        from apps.cli.widgets.message_list import MessageList

        with contextlib.suppress(Exception):
            msg_list = self.screen.query_one(MessageList)
            current = msg_list.current_assistant
            if current is not None:
                current.mark_pending_cancelling()

    def action_interrupt(self) -> None:
        """Handle Ctrl+C - cancel running agent or exit."""
        if self.agent_task and not self.agent_task.done():
            self._signal_cancelling()
            self.agent_task.cancel()
            self.notify("Agent interrupted", severity="warning")
        else:
            self.exit()

    def action_escape_key(self) -> None:
        """Handle Esc - fork-aware: terminate branch / abort fork, then interrupt, then focus."""
        if self.active_fork is not None:
            screen = self.screen
            handler = getattr(screen, "fork_action_escape", None)
            if handler is not None:
                # Route through _spawn_tracked so the abort/terminate coroutine
                # keeps a strong ref and can't be GC'd mid-flight (C7).
                self._spawn_tracked(handler(), label="fork-esc")
                return

        if self.agent_task and not self.agent_task.done():
            self._signal_cancelling()
            self.agent_task.cancel()
            self.notify("Agent interrupted", severity="warning")
        else:
            # Idle Esc clears pending attachments first, if any.
            clear = getattr(self.screen, "clear_attachments", None)
            pending = bool(getattr(self.screen, "_pending_images", None)) or bool(
                getattr(self.screen, "_attachment_labels", None)
            )
            if clear is not None and pending:
                clear()
                return

            from apps.cli.widgets.input_area import InputArea

            with contextlib.suppress(NoMatches):
                self.screen.query_one(InputArea).focus_input()

    def action_paste_image(self) -> None:
        """Attach an image from the clipboard to the next prompt (Ctrl+V)."""
        handler = getattr(self.screen, "attach_clipboard_image", None)
        if handler is not None:
            handler()

    def action_show_help(self) -> None:
        self.handle_command("/help")

    def action_show_settings(self) -> None:
        self.handle_command("/settings")

    def action_show_context(self) -> None:
        self.handle_command("/context")
