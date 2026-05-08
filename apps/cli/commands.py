"""Slash command dispatcher — maps /commands to actions."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apps.cli.app import DeepApp

from apps.cli.widgets.status_bar import StatusBar


async def dispatch_command(app: DeepApp, command: str) -> None:  # noqa: C901
    """Dispatch a slash command to the appropriate handler."""
    from apps.cli.debug_log import get_logger

    log = get_logger()

    parts = command.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1] if len(parts) > 1 else ""
    log.info("Command dispatched", command=cmd, arg=arg if arg else None)

    if cmd in ("/quit", "/exit", "/q"):
        app.exit()

    elif cmd == "/clear":
        from apps.cli.widgets.message_list import MessageList

        try:
            msg_list = app.screen.query_one(MessageList)
            msg_list.clear_messages()
        except Exception:
            pass
        app.message_history.clear()
        app.notify("History cleared")

    elif cmd == "/undo":
        if len(app.message_history) >= 2:
            app.message_history = app.message_history[:-2]
            app.notify("Removed last turn")
        elif app.message_history:
            app.message_history = app.message_history[:-1]
            app.notify("Removed last message")
        else:
            app.notify("No messages to undo", severity="warning")

    elif cmd == "/copy":
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
                    text_to_copy = assistants[-1]._text
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

    elif cmd == "/model":
        from apps.cli.modals.model_picker import ModelPickerModal

        async def _handle(result: str | None) -> None:
            if result:
                app.model_name = result
                # Try to reconfigure agent with new model
                app.reconfigure_agent(model=result)

        app.push_screen(ModelPickerModal(app.model_name), _handle)

    elif cmd == "/context":
        from apps.cli.modals.context_view import ContextViewModal

        # Calculate from message history
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

    elif cmd == "/compact":
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
                # LLM-based: keep more context (last 30) since we can't
                # easily call the summarization processor from here.
                # Try to use ContextManagerCapability if available.
                compacted = False
                try:
                    agent = app.agent
                    if agent is not None:
                        for cap in getattr(agent, "_capabilities", []):
                            cap_type = type(cap).__name__
                            if "ContextManager" in cap_type:
                                # Found ContextManagerCapability — trigger compression
                                compress = getattr(cap, "compress", None)
                                if compress is not None:
                                    app.notify("Compacting with LLM...", severity="information")
                                    await compress(history)
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

            # Update status bar message count
            try:
                status = app.screen.query_one(StatusBar)
                status.message_count = len(app.message_history)
            except Exception:
                pass

        app.push_screen(CompactModal(), _handle_compact)

    elif cmd == "/copy-all":
        # Copy entire conversation as text
        try:
            from apps.cli.widgets.assistant_message import AssistantMessage
            from apps.cli.widgets.message_list import MessageList
            from apps.cli.widgets.user_message import UserMessage

            msg_list = app.screen.query_one(MessageList)
            lines: list[str] = []
            for child in msg_list.children:
                if isinstance(child, UserMessage):
                    lines.append(f"You: {child._text}")
                elif isinstance(child, AssistantMessage):
                    lines.append(f"Assistant: {child._text}")
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

    elif cmd == "/cost":
        # Calculate from message history for accuracy
        total_input = 0
        total_output = 0
        for msg in app.message_history:
            usage = getattr(msg, "usage", None)
            if usage is None:
                continue
            total_input += getattr(usage, "input_tokens", 0) or 0
            total_output += getattr(usage, "output_tokens", 0) or 0
        est_cost = (total_input * 3.0 + total_output * 15.0) / 1_000_000
        app.notify(
            f"Cost: ~${est_cost:.4f}  ·  "
            f"Input: {total_input:,} tokens  ·  Output: {total_output:,} tokens"
        )

    elif cmd == "/tokens":
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

    elif cmd == "/todos":
        from apps.cli.widgets.side_panel import SidePanel

        try:
            side = app.screen.query_one(SidePanel)
            if side.has_class("visible"):
                side.remove_class("visible")
            else:
                side.add_class("visible")
        except Exception:
            app.notify("No todos yet", severity="information")

    elif cmd == "/skills":
        from apps.cli.modals.skills_view import SkillsViewModal

        app.push_screen(SkillsViewModal())

    elif cmd == "/diff":
        from apps.cli.modals.diff_view import DiffViewModal

        app.push_screen(DiffViewModal(working_dir=app.working_dir))

    elif cmd == "/version":
        app.notify(f"pydantic-deep v{app.app_version}")

    elif cmd == "/remember":
        from apps.cli.modals.remember import RememberModal

        async def _handle_remember(result: str | None) -> None:
            if result:
                # Append to MEMORY.md
                import os

                memory_path = os.path.join(app.working_dir, ".pydantic-deep", "main", "MEMORY.md")
                os.makedirs(os.path.dirname(memory_path), exist_ok=True)
                with open(memory_path, "a") as f:
                    f.write(f"\n- {result}\n")
                app.notify("Saved to memory")

        app.push_screen(RememberModal(initial_text=arg), _handle_remember)

    elif cmd == "/settings":
        from apps.cli.screens.settings import SettingsScreen

        app.push_screen(SettingsScreen())

    elif cmd == "/load":
        from apps.cli.modals.session_picker import SessionPickerModal

        async def _handle_load(session_id: str | None) -> None:  # noqa: C901
            if not session_id:
                return
            # Load session messages
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

                # Clear messages and replay loaded history in the UI
                from apps.cli.widgets.message_list import MessageList

                msg_list = app.screen.query_one(MessageList)
                msg_list.clear_messages()

                completed_call_ids: set[str] = set()
                for msg in history:
                    for part in msg.parts:
                        if getattr(part, "part_kind", "") == "tool-return":
                            call_id = getattr(part, "tool_call_id", "")
                            if call_id:
                                completed_call_ids.add(call_id)

                # Replay messages into the message list
                for msg in history:
                    for part in msg.parts:
                        kind = getattr(part, "part_kind", "")
                        if kind == "user-prompt":
                            content = getattr(part, "content", "")
                            if isinstance(content, str) and content:
                                msg_list.append_user_message(content)
                        elif kind == "text":
                            content = getattr(part, "content", "")
                            if isinstance(content, str) and content:
                                assistant_msg = msg_list.begin_assistant_message()
                                assistant_msg.append_text(content)
                                assistant_msg.finalize_text()
                                msg_list.end_assistant_message()
                        elif kind == "tool-call":
                            # Show tool calls in the most recent assistant message
                            tool_name = getattr(part, "tool_name", "unknown")
                            args = (
                                part.args_as_dict()
                                if hasattr(part, "args_as_dict")
                                else getattr(part, "args", {})
                            )
                            if not isinstance(args, dict):
                                args = {}
                            call_id = getattr(part, "tool_call_id", tool_name)
                            assistant_msg = msg_list.current_assistant
                            if assistant_msg is None:
                                assistant_msg = msg_list.begin_assistant_message()
                            assistant_msg.add_tool_call(tool_name, args, call_id)
                            if call_id not in completed_call_ids:
                                assistant_msg.complete_tool_call(call_id, "Interrupted", 0.0, True)
                        elif kind == "tool-return":
                            tool_name = getattr(part, "tool_name", "unknown")
                            call_id = getattr(part, "tool_call_id", tool_name)
                            content = str(getattr(part, "content", ""))
                            assistant_msg = msg_list.current_assistant
                            if assistant_msg is not None:
                                is_error = (
                                    "error" in content.lower()[:100]
                                    or "traceback" in content.lower()[:200]
                                )
                                assistant_msg.complete_tool_call(call_id, content, 0.0, is_error)

                # Finalize any open assistant message
                if msg_list.current_assistant is not None:
                    msg_list.current_assistant.finalize_text()
                    msg_list.end_assistant_message()

                # Show notification
                app.notify(
                    f"Loaded session: {len(history)} messages",
                    severity="information",
                )

                # Update status bar
                status = app.screen.query_one(StatusBar)
                status.message_count = len(history)

                # Scroll to bottom
                msg_list.scroll_end(animate=False)
            except Exception as e:
                app.notify(f"Failed to load session: {e}", severity="error")

        app.push_screen(SessionPickerModal(), _handle_load)

    elif cmd == "/improve":
        days = int(arg) if arg and arg.isdigit() else 7
        app.notify(f"Analyzing sessions from last {days} days...")

        async def _run_improve(days: int = days) -> None:
            try:
                from pathlib import Path

                from apps.cli.config import get_sessions_dir
                from apps.cli.keystore import load_keys
                from apps.cli.modals.improve_review import ImproveReviewModal
                from pydantic_deep.improve.analyzer import ImprovementAnalyzer

                # Ensure API keys are available (improve creates its own agents)
                load_keys()

                # Use the same model as the current agent
                model = app.model_name
                if not model or model in ("test", "preview"):
                    from apps.cli.config import load_config

                    model = load_config().model or "openrouter:anthropic/claude-sonnet-4"

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
                    if report.last_error:
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

        asyncio.ensure_future(_run_improve())

    elif cmd == "/help":
        from apps.cli.modals.help_view import HelpModal

        app.push_screen(HelpModal())

    elif cmd == "/provider":
        from apps.cli.screens.onboarding import _PROVIDERS, ApiKeyModal, ProviderPickerModal

        # Map provider_id to default model
        _PROVIDER_DEFAULT_MODELS = {
            "openrouter": "openrouter:anthropic/claude-sonnet-4",
            "anthropic": "anthropic:claude-sonnet-4-6",
            "openai": "openai:gpt-4.1",
            "google": "google-gla:gemini-2.5-pro",
        }

        async def _handle_provider(provider_id: str | None) -> None:
            if provider_id is None:
                return
            if provider_id == "ollama":
                app.reconfigure_agent(model="ollama:llama3.3")
                return
            # Find the provider info
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

    elif cmd == "/save":
        app.notify("Sessions are auto-saved after each turn")

    elif cmd == "/theme":
        from apps.cli.styles.themes import apply_theme, available_themes

        if arg:
            if apply_theme(app, arg):
                app.notify(f"Theme: {arg}")
                # Save to config
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

    elif cmd == "/config":
        from apps.cli.config import (
            format_config,
            load_config,
            set_config_value,
        )

        if arg.startswith("set "):
            # /config set key value
            set_parts = arg[4:].strip().split(maxsplit=1)
            if len(set_parts) < 2:
                app.notify("Usage: /config set <key> <value>", severity="warning")
                return
            key, val = set_parts[0], set_parts[1]
            try:
                from apps.cli.config import DEFAULT_CONFIG_PATH

                set_config_value(DEFAULT_CONFIG_PATH, key, val)
                app.notify(f"Set {key} = {val}")
                log.info("Config updated", key=key, value=val)
            except KeyError as exc:
                app.notify(str(exc), severity="error")
        else:
            # /config — show current config
            config = load_config()
            text = format_config(config)
            try:
                app.screen.add_system_message(  # type: ignore[attr-defined]
                    f"**Current config:**\n\n```toml\n{text}\n```"
                )
            except Exception:
                app.notify(text[:200])

    elif cmd == "/bug":
        import webbrowser

        webbrowser.open("https://github.com/vstorm-co/pydantic-deepagents/issues")
        app.notify("Opened GitHub issues in browser")

    else:
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
            # Post as user message
            from apps.cli.widgets.message_list import MessageList

            try:
                msg_list = app.screen.query_one(MessageList)
                msg_list.append_user_message(prompt)
                app.screen._run_agent(prompt)  # type: ignore[attr-defined]
            except Exception:
                app.notify(f"Failed to run skill: {skill_name}", severity="error")
        else:
            app.notify(f"Unknown command: {cmd}", severity="warning")
