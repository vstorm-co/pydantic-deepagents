"""Slash command dispatcher — maps /commands to actions."""

from __future__ import annotations

import atexit
import contextlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from apps.cli.app import DeepApp

    #: A slash-command handler: receives the app and the raw argument string.
    CommandHandler = Callable[[DeepApp, str], Awaitable[None]]


from apps.cli.debug_log import get_logger
from apps.cli.forking import (
    ForkingNotEnabledError,
    ForkPickerResult,
    resolve_capability,
    start_fork_from_cli,
)
from apps.cli.modals.diff_picker import DiffPickerModal, DiffPickerResult
from apps.cli.modals.fork_config import ForkConfigModal
from apps.cli.modals.fork_picker import ForkPickerModal
from apps.cli.modals.merge_picker import MergePickerModal, MergePickerResult
from apps.cli.widgets.judge_loading import JudgeAborted, JudgeLoadingScreen
from apps.cli.widgets.merge_acceptance import MergeAcceptanceAction, MergeAcceptanceWidget
from apps.cli.widgets.status_bar import StatusBar

_FORK_ID_PREFIX_LEN = 8


async def dispatch_command(app: DeepApp, command: str) -> None:
    """Dispatch a slash command to its registered handler."""
    log = get_logger()
    parts = command.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""
    log.info("Command dispatched", command=cmd, arg=arg if arg else None)

    handler = _COMMANDS.get(cmd)
    if handler is not None:
        await handler(app, arg)
    else:
        await _dispatch_unknown(app, cmd, arg)


async def _dispatch_unknown(app: DeepApp, cmd: str, arg: str) -> None:
    """Fallback: treat the command as a skill name, else warn."""
    # Check if it's a skill command (e.g. /code-review)
    # Skills are loaded via the command picker from _discover_skill_commands()
    skill_name = cmd.lstrip("/")
    from apps.cli.modals.command_picker import _discover_skill_commands

    known_skills = {name.lstrip("/"): desc for name, desc in _discover_skill_commands()}

    if skill_name in known_skills:
        # Send as a prompt to the agent: "Use the X skill" + any args
        prompt = f"Use the {skill_name} skill."
        if arg:
            prompt += f" {arg}"
        from apps.cli.widgets.message_list import MessageList

        try:
            msg_list = app.screen.query_one(MessageList)
            msg_list.append_user_message(prompt)
            app.screen._run_agent(prompt)  # type: ignore[attr-defined]
        except Exception:
            app.notify(f"Failed to run skill: {skill_name}", severity="error")
    else:
        app.notify(f"Unknown command: {cmd}", severity="warning")


async def _cmd_quit(app: DeepApp, arg: str) -> None:
    app.exit()


async def _cmd_clear(app: DeepApp, arg: str) -> None:
    from apps.cli.widgets.message_list import MessageList

    try:
        msg_list = app.screen.query_one(MessageList)
        msg_list.clear_messages()
    except Exception:
        pass
    app.message_history.clear()
    # Starting a fresh conversation also drops any active goal.
    from apps.cli.goal import clear_goal

    clear_goal(app, notify=False)
    app.notify("History cleared")


async def _cmd_undo(app: DeepApp, arg: str) -> None:
    from apps.cli.widgets.message_list import MessageList

    if len(app.message_history) >= 2:
        app.message_history = app.message_history[:-2]
        msg = "Removed last turn"
    elif app.message_history:
        app.message_history = app.message_history[:-1]
        msg = "Removed last message"
    else:
        app.notify("No messages to undo", severity="warning")
        return
    # Keep the visible transcript in sync — otherwise the removed turn lingers
    # on screen even though the model no longer sees it.
    with contextlib.suppress(Exception):
        app.screen.query_one(MessageList).remove_last_turn()
    app.notify(msg)


async def _cmd_retry(app: DeepApp, arg: str) -> None:
    """Re-run the last user prompt, dropping the previous (bad/aborted) turn."""
    from apps.cli.widgets.message_list import MessageList

    prompt = getattr(app, "last_user_prompt", "")
    if not prompt:
        app.notify("Nothing to retry yet", severity="warning")
        return
    task = app.agent_task
    if task is not None and not task.done():
        app.notify("Agent is still running — wait for it to finish", severity="warning")
        return
    if getattr(app, "active_fork", None) is not None:
        app.notify("Can't retry while a fork is active — use /merge first", severity="warning")
        return

    chat = app.screen
    if not hasattr(chat, "_run_agent"):
        app.notify("Retry is unavailable here", severity="error")
        return
    # Drop the previous turn (request + response) so the model re-runs fresh,
    # and clear its widgets so the transcript shows one clean retry.
    if len(app.message_history) >= 2:
        app.message_history = app.message_history[:-2]
    with contextlib.suppress(Exception):
        msg_list = chat.query_one(MessageList)
        msg_list.remove_last_turn()
        msg_list.append_user_message(prompt)
    chat._run_agent(prompt)  # type: ignore[attr-defined]


async def _cmd_copy(app: DeepApp, arg: str) -> None:
    # Copy last assistant message text (including errors shown as messages)
    from apps.cli.widgets.assistant_message import AssistantMessage
    from apps.cli.widgets.message_list import MessageList

    text_to_copy = app.last_response
    # Fallback: find the last AssistantMessage widget text
    if not text_to_copy:
        try:
            msg_list = app.screen.query_one(MessageList)
            assistants = list(msg_list.query(AssistantMessage))
            if assistants:
                text_to_copy = assistants[-1].text
        except Exception:
            pass

    if not text_to_copy:
        app.notify("No response to copy", severity="warning")
        return
    try:
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text_to_copy.encode(), check=True)
        else:
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text_to_copy.encode(),
                check=True,
            )
        app.notify("Copied to clipboard")
    except Exception:
        app.notify("Failed to copy to clipboard", severity="error")


async def _cmd_model(app: DeepApp, arg: str) -> None:
    from apps.cli.modals.fallback_picker import FallbackPickerModal
    from apps.cli.modals.model_picker import ModelPickerModal

    async def _handle_fallback(primary: str, fallback: str | None) -> None:
        app.set_fallback_and_reconfigure(primary, fallback)

    async def _handle_model(result: str | None) -> None:
        if result:
            primary = result

            def _on_fallback_picked(fb: str | None) -> None:
                app.call_later(_handle_fallback, primary, fb)

            app.push_screen(
                FallbackPickerModal(result, app.fallback_model_name or None),
                _on_fallback_picked,
            )

    app.push_screen(ModelPickerModal(app.model_name), _handle_model)


async def _cmd_context(app: DeepApp, arg: str) -> None:
    from apps.cli.modals.context_view import ContextViewModal

    total_input = 0
    for msg in app.message_history:
        usage = getattr(msg, "usage", None)
        if usage and hasattr(usage, "input_tokens"):
            total_input += usage.input_tokens or 0

    # Use callback values if available, otherwise estimate
    ctx_current = app.context_current if app.context_current > 0 else total_input
    ctx_max = app.context_max if app.context_max > 0 else 200_000
    ctx_pct = ctx_current / ctx_max if ctx_max > 0 else 0.0

    async def _handle_ctx(result: str | None) -> None:
        if result == "compact":
            await dispatch_command(app, "/compact")

    app.push_screen(
        ContextViewModal(
            pct=ctx_pct,
            current=ctx_current,
            maximum=ctx_max,
            message_count=len(app.message_history),
        ),
        _handle_ctx,
    )


async def _cmd_compact(app: DeepApp, arg: str) -> None:
    from apps.cli.modals.compact import CompactModal

    async def _handle_compact(result: tuple[str, str] | None) -> None:
        if result is None:
            return
        mode, focus = result
        history = app.message_history

        if mode == "trim":
            # Zero-cost: just keep last 20 messages
            keep = min(20, len(history))
            app.message_history = history[-keep:]
            app.notify(f"Trimmed to last {keep} messages")
        elif mode == "llm":
            compacted = False
            try:
                agent = app.agent
                if agent is not None:
                    for cap in getattr(agent, "_capabilities", []):
                        cap_type = type(cap).__name__
                        if "ContextManager" in cap_type:
                            compact = getattr(cap, "compact", None)
                            if compact is not None:
                                app.notify("Compacting with LLM...", severity="information")
                                app.message_history = await compact(history, focus)
                                compacted = True
                                app.notify("Context compacted (LLM)")
                            break
            except Exception:
                pass

            if not compacted:
                # Fallback: trim to last 30 messages
                keep = min(30, len(history))
                app.message_history = history[-keep:]
                app.notify(f"Compacted (kept last {keep} messages)")
        else:
            app.notify(f"Unknown compact mode: {mode}", severity="warning")
            return

        try:
            status = app.screen.query_one(StatusBar)
            status.message_count = len(app.message_history)
        except Exception:
            pass

    app.push_screen(CompactModal(), _handle_compact)


async def _cmd_copy_all(app: DeepApp, arg: str) -> None:
    try:
        from apps.cli.widgets.assistant_message import AssistantMessage
        from apps.cli.widgets.message_list import MessageList
        from apps.cli.widgets.user_message import UserMessage

        msg_list = app.screen.query_one(MessageList)
        lines: list[str] = []
        for child in msg_list.children:
            if isinstance(child, UserMessage):
                lines.append(f"You: {child.text}")
            elif isinstance(child, AssistantMessage):
                lines.append(f"Assistant: {child.text}")
            lines.append("")

        full_text = "\n".join(lines)
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=full_text.encode(), check=True)
        else:
            subprocess.run(
                ["xclip", "-selection", "clipboard"], input=full_text.encode(), check=True
            )
        app.notify(f"Copied {len(lines)} lines to clipboard")
    except Exception as e:
        app.notify(f"Failed to copy: {e}", severity="error")


async def _cmd_export(app: DeepApp, arg: str) -> None:
    """Write the conversation to a Markdown file (`/export [path]`)."""
    from datetime import datetime

    from apps.cli.widgets.assistant_message import AssistantMessage
    from apps.cli.widgets.message_list import MessageList
    from apps.cli.widgets.user_message import UserMessage

    try:
        msg_list = app.screen.query_one(MessageList)
    except Exception:
        app.notify("Nothing to export", severity="warning")
        return

    lines: list[str] = ["# Conversation", ""]
    count = 0
    for child in msg_list.children:
        if isinstance(child, UserMessage):
            lines += ["## You", "", child.text, ""]
            count += 1
        elif isinstance(child, AssistantMessage):
            lines += ["## Assistant", "", child.text, ""]
            count += 1

    if count == 0:
        app.notify("Nothing to export", severity="warning")
        return

    if arg.strip():
        path = Path(arg.strip()).expanduser()
    else:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = Path.cwd() / f"conversation-{ts}.md"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
    except OSError as e:
        app.notify(f"Export failed: {e}", severity="error")
        return
    app.notify(f"Exported {count} messages → {path}")


async def _cmd_cost(app: DeepApp, arg: str) -> None:
    total_input = 0
    total_output = 0
    for msg in app.message_history:
        usage = getattr(msg, "usage", None)
        if usage is None:
            continue
        total_input += getattr(usage, "input_tokens", 0) or 0
        total_output += getattr(usage, "output_tokens", 0) or 0
    # Prefer the authoritative cost from CostTracking (genai-prices, accurate
    # per active model). Fall back to a rough Sonnet-rate heuristic only when
    # no tracked cost has been reported — gating on `cost_known`, not a
    # `> 0` test, so a genuine $0 turn is shown as $0.0000 (C5).
    if app.cost_known:
        cost_label = f"${app.total_cost:.4f}"
    else:
        est_cost = (total_input * 3.0 + total_output * 15.0) / 1_000_000
        cost_label = f"~${est_cost:.4f}"
    app.notify(
        f"Cost: {cost_label}  ·  Input: {total_input:,} tokens  ·  Output: {total_output:,} tokens"
    )


async def _cmd_tokens(app: DeepApp, arg: str) -> None:
    count = len(app.message_history)
    total_input = 0
    total_output = 0
    for msg in app.message_history:
        usage = getattr(msg, "usage", None)
        if usage is None:
            continue
        total_input += getattr(usage, "input_tokens", 0) or 0
        total_output += getattr(usage, "output_tokens", 0) or 0
    app.notify(
        f"{count} messages  ·  {total_input:,} input tokens  ·  {total_output:,} output tokens"
    )


async def _cmd_shells(app: DeepApp, arg: str) -> None:
    """List background shells started via run_in_background."""
    deps = getattr(app, "deps", None)
    backend = getattr(deps, "backend", None)
    lister = getattr(backend, "list_background", None)
    if not callable(lister):
        app.notify("Background shells aren't supported by this backend", severity="warning")
        return
    try:
        shells = list(lister())
    except Exception:
        app.notify("Could not read background shells", severity="error")
        return
    if not shells:
        app.notify("No background shells")
        return

    running = sum(1 for s in shells if getattr(s, "running", False))
    lines: list[str] = []
    for s in shells[:8]:
        if getattr(s, "running", False):
            state = "running"
        else:
            state = f"exit {getattr(s, 'exit_code', '?')}"
        cmd = " ".join(str(getattr(s, "command", "")).split())[:40]
        lines.append(f"{getattr(s, 'shell_id', '?')} [{state}] {cmd}")
    if len(shells) > 8:
        lines.append(f"… +{len(shells) - 8} more")
    summary = f"{running} running / {len(shells)} total\n" + "\n".join(lines)
    app.notify(summary, timeout=8)


async def _cmd_todos(app: DeepApp, arg: str) -> None:
    # The TODO list is now pinned above the input whenever tasks exist, so this
    # just reports the current state.
    from apps.cli.widgets.todos_panel import TodosWidget

    try:
        todos = list(app.screen.query_one(TodosWidget).todos)
    except Exception:
        todos = []
    if not todos:
        app.notify("No todos yet", severity="information")
        return
    done = sum(1 for t in todos if getattr(t, "status", "") == "completed")
    app.notify(f"{done}/{len(todos)} todos complete — shown above the input")


async def _cmd_paste(app: DeepApp, arg: str) -> None:
    handler = getattr(app.screen, "attach_clipboard_image", None)
    if handler is not None:
        handler()
    else:
        app.notify("Image paste is unavailable on this screen", severity="warning")


async def _cmd_info(app: DeepApp, arg: str) -> None:
    from apps.cli.modals.info_view import InfoModal

    app.push_screen(InfoModal())


async def _cmd_mcp(app: DeepApp, arg: str) -> None:
    from apps.cli.modals.mcp_view import MCPViewModal

    app.push_screen(MCPViewModal())


async def _cmd_skills(app: DeepApp, arg: str) -> None:
    from apps.cli.modals.skills_view import SkillsViewModal

    app.push_screen(SkillsViewModal())


async def _cmd_diff(app: DeepApp, arg: str) -> None:
    from apps.cli.modals.diff_view import DiffViewModal

    app.push_screen(DiffViewModal(working_dir=app.working_dir))


async def _cmd_screenshot(app: DeepApp, arg: str) -> None:
    # Export the current TUI as an SVG - handy for docs / marketing assets.
    try:
        filename = arg.strip() or None
        saved = app.save_screenshot(filename)
        app.notify(f"📸 Screenshot saved: {saved}")
    except Exception as exc:  # pragma: no cover - defensive
        app.notify(f"Screenshot failed: {exc}", severity="error")


async def _cmd_version(app: DeepApp, arg: str) -> None:
    app.notify(f"pydantic-deep v{app.app_version}")


async def _cmd_remember(app: DeepApp, arg: str) -> None:
    from apps.cli.modals.remember import RememberModal

    async def _handle_remember(result: str | None) -> None:
        if result:
            import os

            memory_path = os.path.join(app.working_dir, ".pydantic-deep", "main", "MEMORY.md")
            os.makedirs(os.path.dirname(memory_path), exist_ok=True)
            with open(memory_path, "a") as f:
                f.write(f"\n- {result}\n")
            app.notify("Saved to memory")

    app.push_screen(RememberModal(initial_text=arg), _handle_remember)


async def _cmd_remind(app: DeepApp, arg: str) -> None:
    from apps.cli.modals.remind_picker import ReminderPickerModal
    from apps.cli.reminder import _apply_reminder_mode

    current = getattr(app, "_reminder_mode", "off")

    async def _handle_remind(mode: str | None) -> None:
        if mode is None:
            return
        _apply_reminder_mode(app, mode)

    app.push_screen(ReminderPickerModal(current_mode=current), _handle_remind)


async def _cmd_goal(app: DeepApp, arg: str) -> None:
    from apps.cli.goal import handle_goal_command

    await handle_goal_command(app, arg)


async def _cmd_settings(app: DeepApp, arg: str) -> None:
    from apps.cli.modals.settings_view import SettingsModal

    app.push_screen(SettingsModal())


async def _cmd_load(app: DeepApp, arg: str) -> None:
    from apps.cli.modals.session_picker import SessionPickerModal

    async def _handle_load(session_id: str | None) -> None:
        if not session_id:
            return
        try:
            import json

            from pydantic_ai.messages import ModelMessagesTypeAdapter

            from apps.cli.config import get_sessions_dir

            messages_path = get_sessions_dir() / session_id / "messages.json"
            if not messages_path.exists():
                app.notify(f"Session {session_id} not found", severity="error")
                return

            json.loads(messages_path.read_text())
            history = ModelMessagesTypeAdapter.validate_json(messages_path.read_bytes())
            app.message_history = list(history)

            from apps.cli.widgets.message_list import MessageList

            msg_list = app.screen.query_one(MessageList)
            msg_list.clear_messages()
            msg_list.replay_messages_into(history)

            app.notify(
                f"Loaded session: {len(history)} messages",
                severity="information",
            )

            status = app.screen.query_one(StatusBar)
            status.message_count = len(history)

            msg_list.scroll_end(animate=False)
        except Exception as e:
            app.notify(f"Failed to load session: {e}", severity="error")

    app.push_screen(SessionPickerModal(), _handle_load)


async def _cmd_improve(app: DeepApp, arg: str) -> None:  # noqa: C901
    log = get_logger()
    days = int(arg) if arg and arg.isdigit() else 7
    app.notify(f"Analyzing sessions from last {days} days...")

    async def _run_improve(days: int = days) -> None:
        try:
            from pathlib import Path

            from apps.cli.config import get_sessions_dir
            from apps.cli.keystore import load_keys
            from apps.cli.modals.improve_review import ImproveReviewModal
            from pydantic_deep.features.improve.analyzer import ImprovementAnalyzer

            # Ensure API keys are available (improve creates its own agents)
            load_keys()

            # Use the same model as the current agent
            model = app.model_name
            if not model or model in ("test", "preview"):
                from apps.cli.config import load_config
                from pydantic_deep.models import DEFAULT_IMPROVE_MODEL

                model = load_config().model or DEFAULT_IMPROVE_MODEL

            def _on_progress(stage: str, current: int, total: int) -> None:
                if stage == "discovering":
                    app.notify("Discovering sessions...", timeout=3)
                elif stage == "extracting":
                    app.notify(
                        f"Extracting insights: {current}/{total} sessions...",
                        timeout=5,
                    )
                elif stage == "synthesizing":
                    app.notify("Synthesizing changes...", timeout=5)
                elif stage == "done":
                    pass  # Report will be shown in modal

            log.info("Improve starting", model=model, days=days)
            analyzer = ImprovementAnalyzer(
                model=model,
                sessions_dir=get_sessions_dir(),
                working_dir=Path(app.working_dir),
                on_progress=_on_progress,
            )
            report = await analyzer.analyze(days=days)

            if report.failed_sessions > 0:
                err_msg = f"{report.failed_sessions} session(s) failed extraction"
                if report.extraction_errors:
                    details = "; ".join(f"{sid}: {exc}" for sid, exc in report.extraction_errors)
                    err_msg += f" ({details})"
                elif report.last_error:
                    err_msg += f": {report.last_error}"
                app.notify(err_msg, severity="warning", timeout=10)

            if not report.proposed_changes:
                app.notify("No improvements found.", severity="information")
                return

            async def _handle_review(
                selected: list | None,
                _analyzer: ImprovementAnalyzer = analyzer,
                _report: Any = report,
            ) -> None:
                if selected is None:
                    app.notify("Improve skipped")
                    return
                modified = await _analyzer.apply_changes(selected)
                _report.accepted_changes = list(selected)
                _analyzer.save_improve_state(_report)
                app.notify(
                    f"Applied {len(modified)} changes: {', '.join(modified)}",
                    severity="information",
                )

            app.push_screen(ImproveReviewModal(report), _handle_review)
        except Exception as e:
            import traceback

            error_detail = traceback.format_exc()
            log.error("Improve pipeline failed", exc_info=True)
            try:
                app.screen.add_system_message(  # type: ignore[attr-defined]
                    f"**Improve failed:**\n\n```\n{error_detail}\n```"
                )
            except Exception:
                app.notify(f"Improve failed: {e}", severity="error")

    app._spawn_tracked(_run_improve(), label="/improve")


async def _cmd_help(app: DeepApp, arg: str) -> None:
    from apps.cli.modals.help_view import HelpModal

    app.push_screen(HelpModal())


async def _cmd_provider(app: DeepApp, arg: str) -> None:
    from apps.cli.providers import PROVIDER_DEFAULT_MODELS as _PROVIDER_DEFAULT_MODELS
    from apps.cli.screens.onboarding import _PROVIDERS, ApiKeyModal, ProviderPickerModal

    async def _handle_provider(provider_id: str | None) -> None:
        if provider_id is None:
            return
        if provider_id == "ollama":
            app.reconfigure_agent(model="ollama:llama3.3")
            return
        for pid, name, env_var, url in _PROVIDERS:
            if pid == provider_id:
                default_model = _PROVIDER_DEFAULT_MODELS.get(pid, "")

                async def _handle_key(
                    key: str | None,
                    _name: str = name,
                    _model: str = default_model,
                ) -> None:
                    if key:
                        app.notify(f"✓ {_name} key set! Connecting...", severity="information")
                        app.reconfigure_agent(model=_model)

                app.push_screen(ApiKeyModal(name, env_var, url), _handle_key)
                return

    app.push_screen(ProviderPickerModal(), _handle_provider)


async def _cmd_save(app: DeepApp, arg: str) -> None:
    app.notify("Sessions are auto-saved after each turn")


async def _cmd_theme(app: DeepApp, arg: str) -> None:
    from apps.cli.styles.themes import apply_theme, available_themes

    if arg:
        if apply_theme(app, arg):
            app.notify(f"Theme: {arg}")
            try:
                from apps.cli.config import DEFAULT_CONFIG_PATH, set_config_value

                set_config_value(DEFAULT_CONFIG_PATH, "theme", arg)
            except Exception:
                pass
        else:
            names = ", ".join(available_themes())
            app.notify(f"Unknown theme: {arg}. Available: {names}", severity="warning")
    else:
        names = ", ".join(available_themes())
        app.notify(f"Available themes: {names}. Use /theme <name>")


async def _cmd_bug(app: DeepApp, arg: str) -> None:
    import webbrowser

    webbrowser.open("https://github.com/vstorm-co/pydantic-deepagents/issues")
    app.notify("Opened GitHub issues in browser")


async def _cmd_fork(app: DeepApp, arg: str) -> None:
    if arg.strip().startswith("diff"):
        rest = arg.strip()[len("diff") :].strip()
        await _dispatch_fork_open_diff(app, rest or None)
    else:
        await _dispatch_fork(app)


async def _cmd_fork_config(app: DeepApp, arg: str) -> None:
    _dispatch_fork_config(app)


async def _cmd_merge(app: DeepApp, arg: str) -> None:
    await _dispatch_merge(app)


_COMMANDS: dict[str, CommandHandler] = {
    "/quit": _cmd_quit,
    "/exit": _cmd_quit,
    "/q": _cmd_quit,
    "/clear": _cmd_clear,
    "/undo": _cmd_undo,
    "/retry": _cmd_retry,
    "/copy": _cmd_copy,
    "/export": _cmd_export,
    "/model": _cmd_model,
    "/context": _cmd_context,
    "/compact": _cmd_compact,
    "/copy-all": _cmd_copy_all,
    "/cost": _cmd_cost,
    "/tokens": _cmd_tokens,
    "/todos": _cmd_todos,
    "/shells": _cmd_shells,
    "/paste": _cmd_paste,
    "/mcp": _cmd_mcp,
    "/skills": _cmd_skills,
    "/diff": _cmd_diff,
    "/screenshot": _cmd_screenshot,
    "/version": _cmd_version,
    "/remember": _cmd_remember,
    "/remind": _cmd_remind,
    "/goal": _cmd_goal,
    "/settings": _cmd_settings,
    "/load": _cmd_load,
    "/improve": _cmd_improve,
    "/help": _cmd_help,
    "/info": _cmd_info,
    "/provider": _cmd_provider,
    "/save": _cmd_save,
    "/theme": _cmd_theme,
    "/bug": _cmd_bug,
    "/fork": _cmd_fork,
    "/fork-config": _cmd_fork_config,
    "/merge": _cmd_merge,
}


# Fork dispatch helpers


async def _dispatch_fork(app: DeepApp) -> None:
    """Handle `/fork` — open the picker modal and spawn branches on submit."""

    if app.agent is None:
        app.notify("Agent not configured — use /provider first", severity="error")
        return
    if resolve_capability(app.agent) is None:
        app.notify(
            "Forking is not enabled on this agent. Restart with forking=True.",
            severity="error",
        )
        return
    if app.active_fork is not None:
        if app.active_fork.adopted:
            app.notify(
                "agent already forked — resolve it first (/merge or pick a branch).",
                severity="warning",
            )
        else:
            app.notify("Fork already active — /merge to resolve first", severity="warning")
        return
    task = app.agent_task
    if task is not None and not task.done():
        app.notify("Agent run in progress — press Esc or wait, then /fork", severity="warning")
        return

    async def _on_result(result: ForkPickerResult | None) -> None:
        if result is None:
            return
        try:
            session = await start_fork_from_cli(app, result)
        except ForkingNotEnabledError as e:
            app.notify(str(e), severity="error")
            return
        except Exception as e:  # pragma: no cover - defensive
            from apps.cli.debug_log import get_logger

            get_logger().error("Fork failed", exc_info=True)
            app.notify(f"Fork failed: {e}", severity="error")
            return
        app.active_fork = session
        labels = ", ".join(s.label for s in result.specs)
        app.notify(f"Forked: {labels}", severity="information")

    app.push_screen(ForkPickerModal(), _on_result)


# /fork-config


def _dispatch_fork_config(app: DeepApp) -> None:
    """Handle `/fork-config` — open the settings modal."""

    if app.agent is None:
        app.notify("Agent not configured — use /provider first", severity="error")
        return
    if app.active_fork is not None:
        app.notify(
            "Fork active — /merge to resolve first, then /fork-config",
            severity="warning",
        )
        return
    task = app.agent_task
    if task is not None and not task.done():
        app.notify(
            "Agent run in progress — press Esc or wait, then /fork-config",
            severity="warning",
        )
        return
    app.push_screen(ForkConfigModal())


async def _dispatch_merge(app: DeepApp) -> None:
    """Handle `/merge` — dispatch on :attr:`MergeStrategy.kind`."""

    session = app.active_fork
    if session is None:
        app.notify("No active fork — type /fork to start one", severity="warning")
        return
    report = await session.build_diff()
    if report is None:  # pragma: no cover - defensive: session implies a live fork
        app.notify("Cannot build diff report", severity="error")
        return
    statuses = session.inspect()
    strategy = session.handle.merge_strategy

    async def _commit_pick(branch_id: str) -> None:
        """Shared post-pick commit path used by every flow."""
        active = app.active_fork
        if active is None:  # pragma: no cover - defensive: another flow cleared it
            return
        try:
            result = await active.merge(branch_id)
        except Exception as e:  # pragma: no cover - defensive
            from apps.cli.debug_log import get_logger

            get_logger().error("Merge failed", exc_info=True)
            app.notify(f"Merge failed: {e}", severity="error")
            return

        from pydantic_deep.features.patch import patch_tool_calls_processor

        parent_len = len(app.message_history)
        patched = patch_tool_calls_processor(list(result.history_after_merge))
        app.message_history = patched
        runtime = active.coordinator.branches.get(branch_id)
        label = runtime.spec.label if runtime else branch_id
        steer = runtime.spec.steer if runtime else ""
        if app.deps is not None:
            app.deps.fork_coordinator = None
        app.active_fork = None
        _replay_branch_into_main_chat(app, patched[parent_len:], label, steer, result)
        app.notify(_format_merge_notification(label, result), severity="information")

    async def _on_pick(picked: MergePickerResult | None) -> None:
        if picked is None:
            return
        await _commit_pick(picked.branch_id)

    async def _on_open_in_editor(branch_id: str) -> None:
        """Bridge the merge picker's `o` binding into the diff picker.

        The merge picker passes the currently-highlighted branch id; we
        detect the editor kind once and open the diff picker pre-checked
        with only that branch. User can toggle more branches via Space.
        """
        from pydantic_deep.features.forking.editor import EditorDetector

        kind = EditorDetector.detect()
        if kind == "tui":
            app.notify(
                "No external diff tool detected — use the panels here, or "
                "set PYDANTIC_DEEP_DIFFTOOL.",
                severity="warning",
            )
            return
        await _open_diff_picker(app, kind=kind, initial_branch_id=branch_id)

    def _push_picker(
        *,
        preselected_id: str | None = None,
        subtitle: str | None = None,
    ) -> None:
        """Push :class:`MergePickerModal` with the shared per-dispatch context.

        Closes over `report` / `statuses` / `session.label_to_id` /
        `_on_open_in_editor` / `_on_pick` so each call site collapses to
        one line. `preselected_id` and `subtitle` carry the only
        per-call-site variation across the three picker call sites.
        """
        app.push_screen(
            MergePickerModal(
                report,
                statuses,
                session.label_to_id,
                on_open_in_editor=_on_open_in_editor,
                preselected_branch_id=preselected_id,
                verdict_subtitle=subtitle,
            ),
            _on_pick,
        )

    if strategy.kind == "manual":
        _push_picker()
        return

    async def _on_judge_complete(result: Any) -> None:
        await _handle_judge_result(
            app,
            result=result,
            session=session,
            strategy=strategy,
            report=report,
            statuses=statuses,
            push_picker=_push_picker,
            commit_pick=_commit_pick,
            on_open_in_editor=_on_open_in_editor,
            on_pick=_on_pick,
        )

    app.push_screen(JudgeLoadingScreen(session.coordinator, strategy), _on_judge_complete)


async def _handle_judge_result(
    app: DeepApp,
    *,
    result: Any,
    session: Any,
    strategy: Any,
    report: Any,
    statuses: list[Any],
    push_picker: Any,
    commit_pick: Any,
    on_open_in_editor: Any,
    on_pick: Any,
) -> None:
    """Route JudgeLoadingScreen result to the appropriate next screen."""

    if isinstance(result, Exception):
        from apps.cli.debug_log import get_logger

        exc_name = type(result).__name__
        severity = "information" if isinstance(result, JudgeAborted) else "warning"
        get_logger().error("Judge resolve failed", exc_info=True, exc_name=exc_name)
        app.notify(
            f"{exc_name}: {result} — falling back to manual picker.",
            severity=severity,
        )
        push_picker()
        return

    outcome = result
    if outcome.committed and outcome.merge_result is not None:
        from pydantic_deep.features.patch import patch_tool_calls_processor

        parent_len = len(app.message_history)
        patched = patch_tool_calls_processor(list(outcome.merge_result.history_after_merge))
        app.message_history = patched
        runtime = session.coordinator.branches.get(outcome.merge_result.winner_branch_id)
        label = runtime.spec.label if runtime else outcome.merge_result.winner_branch_id
        steer = runtime.spec.steer if runtime else ""
        if app.deps is not None:
            app.deps.fork_coordinator = None
        app.active_fork = None
        _replay_branch_into_main_chat(app, patched[parent_len:], label, steer, outcome.merge_result)
        app.notify(_format_auto_merge_notification(label, outcome), severity="information")
        return

    if not outcome.auto_eligible:
        verdict = outcome.verdict
        if verdict is None:  # pragma: no cover - defensive: non-manual always has a verdict
            push_picker()
            return
        _runtime = session.coordinator.branches.get(verdict.winner_branch_id)
        _winner_label = _runtime.spec.label if _runtime else verdict.winner_branch_id
        subtitle = _format_verdict_subtitle(
            outcome=outcome,
            threshold=strategy.confidence_threshold,
            above_threshold=False,
            winner_label=_winner_label,
        )
        push_picker(preselected_id=verdict.winner_branch_id, subtitle=subtitle)
        return

    # auto_with_fallback above threshold — defer to acceptance widget
    await _dispatch_acceptance_widget(
        app,
        report=report,
        statuses=statuses,
        outcome=outcome,
        strategy=strategy,
        on_pick=on_pick,
        on_open_in_editor=on_open_in_editor,
        commit_pick=commit_pick,
    )


async def _dispatch_acceptance_widget(
    app: DeepApp,
    *,
    report: Any,
    statuses: list[Any],
    outcome: Any,
    strategy: Any,
    on_pick: Any,
    on_open_in_editor: Any,
    commit_pick: Any,
) -> None:
    """Push :class:`MergeAcceptanceWidget` and route its actions."""

    session = app.active_fork
    if session is None:  # pragma: no cover - defensive
        return
    verdict = outcome.verdict
    winner_id = verdict.winner_branch_id
    runtime = session.coordinator.branches.get(winner_id)
    winner_label = runtime.spec.label if runtime else winner_id

    async def _on_acceptance(action: MergeAcceptanceAction | None) -> None:
        if action is None:
            # Escape pressed — cancel without merging
            return
        if action == "accept":
            await commit_pick(winner_id)
            return
        if action == "diff":
            # Re-engage acceptance widget after diff explorer closes
            async def _on_diff_dismissed(_: Any) -> None:
                await _dispatch_acceptance_widget(
                    app,
                    report=report,
                    statuses=statuses,
                    outcome=outcome,
                    strategy=strategy,
                    on_pick=on_pick,
                    on_open_in_editor=on_open_in_editor,
                    commit_pick=commit_pick,
                )

            app.push_screen(
                MergePickerModal(
                    report,
                    statuses,
                    session.label_to_id,
                    on_open_in_editor=on_open_in_editor,
                ),
                _on_diff_dismissed,
            )
            return
        subtitle = _format_verdict_subtitle(
            outcome=outcome,
            threshold=strategy.confidence_threshold,
            above_threshold=True,
            winner_label=winner_label,
        )
        app.push_screen(
            MergePickerModal(
                report,
                statuses,
                session.label_to_id,
                on_open_in_editor=on_open_in_editor,
                preselected_branch_id=winner_id,
                verdict_subtitle=subtitle,
            ),
            on_pick,
        )

    if outcome.merge_result is not None:
        fork_id_for_widget = outcome.merge_result.fork_id
    else:
        fork_id_for_widget = session.coordinator.fork_id or "?"

    app.push_screen(
        MergeAcceptanceWidget(
            fork_id=fork_id_for_widget,
            winner_label=winner_label,
            effective_confidence=outcome.effective_confidence,
            verdict=verdict,
        ),
        _on_acceptance,
    )


def _format_auto_merge_notification(label: str, outcome: Any) -> str:
    """Render the post-auto-merge notification — confidence + 1-line reasoning."""
    verdict = outcome.verdict
    parts = [
        f"Auto-merged: kept branch {label}",
        f"confidence {outcome.effective_confidence:.2f}",
    ]
    if verdict is not None and verdict.reasoning:
        first_sentence = verdict.reasoning.split(". ", 1)[0].rstrip(".")
        parts.append(first_sentence)
    return " · ".join(parts)


def _format_verdict_subtitle(
    *, outcome: Any, threshold: float, above_threshold: bool, winner_label: str
) -> str:
    """Compose the verdict-subtitle string the picker mounts as a Static row."""
    verdict = outcome.verdict
    if verdict is None:  # pragma: no cover - dispatcher only calls this with a verdict
        return ""
    confidence = outcome.effective_confidence
    if above_threshold:
        header = (
            f"Judge picked: [bold]{winner_label}[/bold] "
            f"(confidence {confidence:.2f} ≥ threshold {threshold:.2f})"
        )
    else:
        header = (
            f"Judge picked: [bold]{winner_label}[/bold] "
            f"(confidence {confidence:.2f} — below threshold {threshold:.2f})"
        )
    return f"{header}\nWhy: {verdict.reasoning}"


def _format_merge_notification(label: str, result: Any) -> str:
    """Render the post-merge notification — applied count, conflicts, errors."""
    parts = [f"Merged: kept branch {label}", f"{len(result.applied_paths)} files applied"]
    if result.deleted_paths:
        parts.append(f"{len(result.deleted_paths)} deleted")
    if result.conflicts:
        parts.append(f"conflicts: {', '.join(result.conflicts)}")
    if result.errors:
        parts.append(f"errors: {len(result.errors)}")
    if result.blocked_commands:
        parts.append(f"denied: {len(result.blocked_commands)}")
    return " · ".join(parts)


async def _dispatch_fork_open_diff(app: DeepApp, _path_arg: str | None) -> None:
    """Handle `/fork diff` — external diff inspection via picker.

    Always opens :class:`DiffPickerModal` so the user can pick a touched
    path + branch subset from a list. Any path argument typed after the
    command is ignored — the picker supersedes it.

    Falls back to the in-TUI :class:`MergePickerModal` (diff-explore
    mode) when no external editor is detected.
    """
    from pydantic_deep.features.forking.editor import EditorDetector

    session = app.active_fork
    if session is None:
        app.notify(
            "No active fork — type /fork to start one, then /fork diff",
            severity="warning",
        )
        return
    coordinator = session.coordinator
    if coordinator.materializer is None:  # pragma: no cover - defensive
        app.notify("Materializer not initialised", severity="error")
        return

    kind = EditorDetector.detect()
    if kind == "tui":
        report = await session.build_diff()
        if report is None:  # pragma: no cover - defensive
            app.notify("Cannot build diff report", severity="error")
            return
        statuses = session.inspect()
        # Browse-only (view_only): /fork diff inspects, it doesn't resolve — Enter just closes
        # rather than committing a pick that push_screen would silently discard.
        app.push_screen(MergePickerModal(report, statuses, session.label_to_id, view_only=True))
        return

    await _open_diff_picker(app, kind=kind, initial_branch_id=None)


#: Temp dirs created by `_labeled_symlinks`, removed at interpreter exit (C13).
_FORK_SYMLINK_DIRS: set[Path] = set()


def _cleanup_fork_symlink_dirs() -> None:
    """Remove every temp dir `_labeled_symlinks` created (atexit hook, C13)."""
    for d in _FORK_SYMLINK_DIRS:
        shutil.rmtree(d, ignore_errors=True)


atexit.register(_cleanup_fork_symlink_dirs)


def _link_or_copy(src: Path, dst: Path) -> None:
    """Symlink `dst` → `src`, copying instead where symlinks need privilege (Windows, C13)."""
    try:
        dst.symlink_to(src)
    except OSError:
        shutil.copy2(src, dst)


def _labeled_symlinks(
    parent_path: Path | None,
    branch_paths: list[Path],
    labels: list[str],
    basename: str,
    fork_id: str,
) -> tuple[Path | None, list[Path]]:
    """Return short-path symlinks so editor title bars show branch labels.

    Creates `{tempdir}/pd_{fork_id}/parent/{basename}` and
    `{tempdir}/pd_{fork_id}/{label}/{basename}` symlinks pointing at the
    materialiser paths.  Keeping the temp-dir prefix short ensures the
    label component stays visible in PyCharm/VS Code title truncation. The
    temp dir is tracked for cleanup at exit, and falls back to a copy where
    symlinks aren't permitted (C13).
    """
    tmp = Path(tempfile.gettempdir()) / f"pd_{fork_id[:_FORK_ID_PREFIX_LEN]}"
    tmp.mkdir(exist_ok=True)
    _FORK_SYMLINK_DIRS.add(tmp)
    sym_branches: list[Path] = []
    for bp, label in zip(branch_paths, labels, strict=True):
        d = tmp / label
        d.mkdir(exist_ok=True)
        link = d / basename
        _link_or_copy(bp.resolve(), link)
        sym_branches.append(link)
    if parent_path is not None:
        pd = tmp / "parent"
        pd.mkdir(exist_ok=True)
        plink = pd / basename
        _link_or_copy(parent_path.resolve(), plink)
        return plink, sym_branches
    return None, sym_branches


async def _open_diff_picker(
    app: DeepApp,
    *,
    kind: str,
    initial_branch_id: str | None,
) -> None:
    """Show :class:`DiffPickerModal` and dispatch the editor on confirm.

    Extracted so the merge picker's "Open in editor" button can reuse
    the same flow with `initial_branch_id` set to the merge picker's
    currently-highlighted branch.
    """
    from pydantic_deep.features.forking.editor import EditorDetector

    session = app.active_fork
    if session is None:  # pragma: no cover - defensive: caller already checked
        return
    report = await session.build_diff()
    if report is None:  # pragma: no cover - defensive
        app.notify("Cannot build diff report", severity="error")
        return
    statuses = session.inspect()
    coordinator = session.coordinator
    materializer = coordinator.materializer
    if materializer is None:  # pragma: no cover - defensive
        app.notify("Materializer not initialised", severity="error")
        return

    def _id_to_label(bid: str) -> str:
        return next(
            (lbl for lbl, b in session.label_to_id.items() if b == bid),
            bid,
        )

    def _on_pick(picked: DiffPickerResult | None) -> None:
        if picked is None:
            return
        parent_path = materializer.parent_path(picked.path) if picked.include_parent else None
        branch_paths = []
        for bid in picked.branch_ids:
            label = _id_to_label(bid)
            branch_paths.append(materializer.branch_path(label, picked.path))
        labels = [_id_to_label(bid) for bid in picked.branch_ids]
        basename = Path(picked.path).name
        sym_parent, sym_branches = _labeled_symlinks(
            parent_path, branch_paths, labels, basename, materializer.fork_id
        )
        EditorDetector.invoke(kind, sym_parent, sym_branches)
        if picked.include_parent:
            app.notify(f"{kind} diff: parent  ←→  {', '.join(labels)}")
        else:
            app.notify(f"{kind} diff: {' ←→ '.join(labels)}")

    app.notify(
        "Files are read-only snapshots — edits won't affect /merge",
        severity="warning",
        timeout=6,
    )
    app.push_screen(
        DiffPickerModal(report, statuses, session.label_to_id, initial_branch_id=initial_branch_id),
        _on_pick,
    )


def _replay_branch_into_main_chat(
    app: DeepApp,
    branch_messages: list[Any],
    label: str,
    steer: str,
    result: Any,
) -> None:
    """Append the winning branch's new messages to the main MessageList.

    `branch_messages` is the slice of the patched history that belongs
    to the branch (everything after the parent's pre-fork history).  The
    steer appears as a user message, the branch's tool calls and text
    responses follow, and a compact system summary closes the turn so the
    parent agent has file-change context for its next run.
    """

    try:
        from apps.cli.screens.chat import ChatScreen
        from apps.cli.widgets.message_list import MessageList

        chat = app.screen
        if not isinstance(chat, ChatScreen):
            return
        msg_list = chat.query_one(MessageList)
    except Exception:
        return

    msg_list.replay_messages_into(branch_messages)
    chat.add_system_message(_build_replay_summary(label, result))


def _build_replay_summary(label: str, result: Any) -> str:
    """Render the post-merge replay summary shown in the main chat.

    Bundles applied paths, deleted paths, and any tool calls that were denied
    by the user during the branch run into a single multi-line system message.
    """
    paths = list(result.applied_paths)
    paths += [f"{p} (deleted)" for p in result.deleted_paths]
    path_str = "\n  ".join(paths) if paths else "no file changes"
    summary = f"✓ Fork merged — branch '{label}' applied. Files changed:\n  {path_str}"
    if result.blocked_commands:
        blocked_list = "\n  ".join(f"- {entry}" for entry in result.blocked_commands)
        summary += (
            f"\n⚠ {len(result.blocked_commands)} tool calls denied by user during "
            f"branch run:\n  {blocked_list}"
        )
    return summary
