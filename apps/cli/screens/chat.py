"""Main chat screen — the primary interface."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from apps.cli.app import DeepApp

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import Screen

from apps.cli.messages import (
    AgentComplete,
    AgentError,
    AgentRunStarted,
    AgentTextComplete,
    AgentToken,
    ApprovalRequested,
    CommandSelected,
    CompressionComplete,
    CompressionStarted,
    ContextUpdated,
    CostUpdated,
    FileSelected,
    TodosUpdated,
    ToolCallCompleted,
    ToolCallStarted,
    UserSubmitted,
)
from apps.cli.text_heuristics import looks_like_error
from apps.cli.widgets.branch_panel import BranchPanelWidget
from apps.cli.widgets.fork_badge import ForkBadgeWidget
from apps.cli.widgets.fork_overview import ForkOverviewWidget
from apps.cli.widgets.fork_tabs import OVERVIEW_TAB_ID, ForkTabsWidget
from apps.cli.widgets.header import DeepHeader
from apps.cli.widgets.input_area import InputArea
from apps.cli.widgets.message_list import MessageList
from apps.cli.widgets.notification import notify_success, notify_warning
from apps.cli.widgets.queued_panel import QueuedWidget
from apps.cli.widgets.side_panel import SidePanel
from apps.cli.widgets.status_bar import StatusBar
from pydantic_deep.deps import DEFAULT_USAGE_LIMITS

_FORK_POLL_INTERVAL_S: float = 0.5


class ChatScreen(Screen):
    """The main chat interface with header, messages, status bar, and input."""

    @property
    def app(self) -> DeepApp:
        return super().app

    BINDINGS = [
        Binding("ctrl+j", "toggle_multiline", "Multiline", show=False),
        Binding("ctrl+k", "show_todos", "TODOs"),
        Binding("ctrl+l", "clear_screen", "Clear"),
        Binding("ctrl+r", "search_messages", "Search"),
        Binding("tab", "cycle_branch_tab", "Cycle branch", show=False),
        Binding("enter", "merge_focused_branch", "Merge focused branch", show=False),
        Binding("pageup", "scroll_up", "Scroll up", show=False),
        Binding("pagedown", "scroll_down", "Scroll down", show=False),
    ]

    _poll_timer: Any = None

    def compose(self) -> ComposeResult:
        yield DeepHeader()
        with Horizontal(id="main-layout"):
            with Vertical(id="messages-pane"):
                yield MessageList()
                yield ForkTabsWidget()
                with Vertical(id="fork-view-body"):
                    yield ForkOverviewWidget()
            yield SidePanel()
        yield StatusBar()
        yield InputArea()

    def on_mount(self) -> None:
        """Show welcome banner, init session, bootstrap context files, focus input."""
        self._init_session()
        self._bootstrap_context_files()
        self._init_side_panel()
        self.call_later(self._show_welcome)
        self.query_one(InputArea).focus_input()

    def on_resize(self, event: Any) -> None:
        """Keep side panel responsive to terminal width changes."""
        self.query_one(SidePanel).update_for_width(self.app.size.width)

    def _init_side_panel(self) -> None:
        """Show side panel and populate with default subagents."""
        side = self.query_one(SidePanel)
        side.update_for_width(self.app.size.width)

        from apps.cli.widgets.subagents_panel import SubagentsWidget

        sa_widget = side.query_one(SubagentsWidget)
        defaults = []
        # Show built-in subagents as available
        agent = getattr(self.app, "agent", None)
        if agent:
            # Extract subagent names from the task manager
            mgr = getattr(agent, "_task_manager", None)
            if mgr:
                for name in sorted(getattr(mgr, "_agents", {}).keys()):
                    defaults.append({"name": name, "status": "idle", "description": ""})
        if not defaults:
            # Fallback — show common built-ins
            defaults = [
                {"name": "planner", "status": "idle", "description": ""},
                {"name": "research", "status": "idle", "description": ""},
            ]
        sa_widget.agents = defaults

    def _bootstrap_context_files(self) -> None:
        """Create AGENTS.md, SOUL.md and MEMORY.md if they don't exist."""
        from pathlib import Path

        working_dir = Path(getattr(self.app, "working_dir", ".")).resolve()
        created: list[str] = []

        # AGENTS.md — project conventions (visible to agent + subagents)
        agents_path = working_dir / "AGENTS.md"
        if not agents_path.exists():
            try:
                from apps.cli.local_context import (
                    detect_language,
                    detect_package_manager,
                    detect_test_command,
                )

                lang = detect_language(working_dir) or "Unknown"
                pkg = detect_package_manager(working_dir) or ""
                test_cmd = detect_test_command(working_dir) or ""
            except Exception:
                lang, pkg, test_cmd = "Unknown", "", ""

            sections = [
                "# AGENTS.md",
                "",
                "Project conventions and context for the AI assistant.",
                "",
            ]
            sections.append("## Project")
            sections.append("")
            if lang:
                sections.append(f"- Language: {lang}")
            if pkg:
                sections.append(f"- Package manager: {pkg}")
            if test_cmd:
                sections.append(f"- Test command: `{test_cmd}`")
            sections.append("")
            sections.append("## Conventions")
            sections.append("")
            sections.append("<!-- Add your project conventions here -->")
            sections.append("")

            agents_path.write_text("\n".join(sections))
            created.append("AGENTS.md")

        # SOUL.md — user preferences (main agent only)
        soul_path = working_dir / "SOUL.md"
        if not soul_path.exists():
            soul_content = "\n".join(
                [
                    "# SOUL.md",
                    "",
                    "Agent personality and user preferences.",
                    "",
                    "## Communication Style",
                    "",
                    "- Be concise and direct",
                    "- Use the same language as the user",
                    "",
                    "## Preferences",
                    "",
                    "<!-- The /improve command will populate this over time -->",
                    "",
                ]
            )
            soul_path.write_text(soul_content)
            created.append("SOUL.md")

        # MEMORY.md — persistent memory
        memory_dir = working_dir / ".pydantic-deep" / "main"
        memory_path = memory_dir / "MEMORY.md"
        if not memory_path.exists():
            memory_dir.mkdir(parents=True, exist_ok=True)
            memory_content = "\n".join(
                [
                    "# Memory",
                    "",
                    "Persistent observations from past sessions.",
                    "",
                ]
            )
            memory_path.write_text(memory_content)
            created.append("MEMORY.md")

        if created:
            self._bootstrapped_files = created

    def _init_session(self) -> None:
        """Create a session directory for this conversation."""
        import uuid

        try:
            from apps.cli.config import get_sessions_dir

            self._session_id = uuid.uuid4().hex[:12]
            session_dir = get_sessions_dir() / self._session_id
            session_dir.mkdir(parents=True, exist_ok=True)
            self._session_dir = session_dir

            # Initialize per-session debug logger
            from apps.cli.debug_log import setup_logger

            setup_logger(self._session_id)
        except Exception:
            self._session_id = ""
            self._session_dir = None

    def _save_session(self) -> None:
        """Save current message history to session directory."""
        if not self._session_dir:
            return
        try:
            from pydantic_ai.messages import ModelMessagesTypeAdapter

            history = getattr(self.app, "message_history", [])
            if not history:
                return
            data = ModelMessagesTypeAdapter.dump_json(history, indent=2)
            messages_file = self._session_dir / "messages.json"
            messages_file.write_bytes(data)
        except Exception:
            pass  # Don't crash on save failure

    def _append_tool_log(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: str,
        elapsed: float,
        is_error: bool,
    ) -> None:
        """Append a structured tool call record to tool_log.jsonl.

        This provides richer execution traces for the /improve pipeline,
        following the Meta-Harness insight that raw traces >> summaries.
        """
        if not self._session_dir:
            return
        try:
            import json
            from datetime import datetime, timezone

            # Subagent outputs get full content; other tools get preview
            is_subagent = tool_name == "task"
            max_result = 20_000 if is_subagent else 2000
            record = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "tool": tool_name,
                "args": {k: str(v)[:500] for k, v in args.items()},
                "result_preview": result[:max_result],
                "result_length": len(result),
                "elapsed": round(elapsed, 3),
                "error": is_error,
            }
            log_file = self._session_dir / "tool_log.jsonl"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _sync_status_from_history(self) -> None:
        """Calculate cost and token usage from message_history and update status bar."""
        try:
            history = getattr(self.app, "message_history", [])
            status = self.query_one(StatusBar)
            status.message_count = len(history)

            # Sum tokens from all response messages
            total_input = 0
            total_output = 0
            for msg in history:
                usage = getattr(msg, "usage", None)
                if usage is None:
                    continue
                if hasattr(usage, "input_tokens"):
                    total_input += usage.input_tokens or 0
                if hasattr(usage, "output_tokens"):
                    total_output += usage.output_tokens or 0

            # Update token breakdown
            status.total_input_tokens = total_input
            status.total_output_tokens = total_output

            # Estimate cost (~$3/MTok input, ~$15/MTok output for Sonnet-class)
            estimated_cost = (total_input * 3.0 + total_output * 15.0) / 1_000_000
            status.total_cost = estimated_cost
            status.current_cost = estimated_cost

            # Context: use last known values from callbacks, or estimate from tokens
            if self.app.context_max > 0:  # type: ignore
                status.context_pct = self.app.context_pct  # type: ignore
                status.context_current = self.app.context_current  # type: ignore
                status.context_max = self.app.context_max  # type: ignore
            elif total_input > 0:
                # Rough estimate: latest input tokens vs 200K default
                max_tokens = 200_000
                status.context_current = total_input
                status.context_max = max_tokens
                status.context_pct = total_input / max_tokens
        except Exception:
            from apps.cli.debug_log import get_logger

            get_logger().error("_sync_status_from_history failed", exc_info=True)

    def add_system_message(self, text: str) -> None:
        """Add a synthetic assistant message to history and save.

        Use this for errors, shell outputs, and other non-agent messages
        that should persist across sessions.
        """
        from datetime import datetime, timezone

        from pydantic_ai.messages import ModelResponse, TextPart

        # Add to UI
        msg_list = self.query_one(MessageList)
        assistant = msg_list.begin_assistant_message()
        assistant.append_text(text)
        assistant.finalize_text()
        msg_list.end_assistant_message()

        # Add to message history so it persists
        try:
            synthetic = ModelResponse(
                parts=[TextPart(content=text)],
                timestamp=datetime.now(timezone.utc),
            )
            self.app.message_history.append(synthetic)  # type: ignore
            self._save_session()
        except Exception:
            pass

    def _show_welcome(self) -> None:
        """Display a welcome message with project context."""
        from pathlib import Path

        from apps.cli.widgets.message_list import MessageList

        msg_list = self.query_one(MessageList)

        working_dir = getattr(self.app, "working_dir", ".")
        root = Path(working_dir).resolve()
        lines: list[str] = []

        try:
            from apps.cli.local_context import (
                detect_language,
                detect_package_manager,
                detect_test_command,
            )

            lang = detect_language(root)
            pkg = detect_package_manager(root)
            test_cmd = detect_test_command(root)
            if lang:
                info = f"**{lang}**"
                if pkg:
                    info += f" · {pkg}"
                lines.append(info)
            if test_cmd:
                lines.append(f"Test: `{test_cmd}`")
        except Exception:
            pass

        # Show bootstrapped files
        bootstrapped = getattr(self, "_bootstrapped_files", [])
        if bootstrapped:
            lines.append(f"Created: {', '.join(bootstrapped)}")

        lines.append("")
        lines.append("Ready! Type a message, `/` for commands, `@` for files.")

        welcome = "\n".join(lines)
        assistant = msg_list.begin_assistant_message()
        assistant.append_text(welcome)
        assistant.finalize_text()
        msg_list.end_assistant_message()

    # ── User input handling ───────────────────────────────────────

    #: Slash commands allowed while a fork is active — everything else is blocked
    #: because a new ``agent.run()`` would overwrite ``deps.fork_coordinator``.
    _FORK_ALLOWED_COMMANDS = frozenset(
        {"/merge", "/help", "/cost", "/tokens", "/version", "/quit", "/exit", "/q", "/copy"}
    )

    @staticmethod
    def _is_fork_inspection(text: str) -> bool:
        """Return True for ``/fork diff`` and its argumented form.

        Inspection commands are allowed during an active fork —
        but only the ``diff`` sub-command of ``/fork``. ``/fork``
        without args would re-enter the picker modal and clobber state;
        ``/fork-config`` is similarly blocked.
        """
        stripped = text.strip()
        return stripped.startswith("/fork ") and stripped[6:].lstrip().startswith("diff")

    async def on_user_submitted(self, event: UserSubmitted) -> None:  # noqa: C901
        """Handle user submitting a prompt."""
        import re

        text = event.text

        app = self.app
        active_fork = app.active_fork

        if active_fork is not None:
            match = re.match(r"^>>(\w+)\s+(.*)", text)
            if match is not None:
                branch_id_or_label, msg = match.group(1), match.group(2).strip()
                if msg:
                    state = active_fork.branch_state(branch_id_or_label)
                    if state is None:
                        app.notify(
                            f"unknown branch `{branch_id_or_label}` — "
                            "use `>>{label} <msg>` with a live branch label.",
                            severity="warning",
                        )
                        return
                    if state != "running":
                        app.notify(
                            f"branch `{branch_id_or_label}` is {state} — cannot steer. "
                            "Use /merge to resolve the fork.",
                            severity="warning",
                        )
                        return
                    delivered = await active_fork.steer_branch(branch_id_or_label, msg)
                    if delivered:
                        preview = msg[:40] + ("…" if len(msg) > 40 else "")
                        app.notify(f"→ {branch_id_or_label}: {preview}")
                        return

            # ── Slash commands during fork — only inspection allow-list ──
            if text.startswith("/") and not text.startswith("//"):
                cmd = text.split(maxsplit=1)[0].lower()
                if cmd in self._FORK_ALLOWED_COMMANDS or self._is_fork_inspection(text):
                    app.handle_command(text)  # type: ignore[attr-defined]
                    return
                app.notify(
                    f"fork active — `{cmd}` is blocked. Use `>>{{label}} <msg>` to steer "
                    "a branch, or `/merge` to resolve.",
                    severity="warning",
                )
                return

            if not text.startswith("!"):
                app.notify(
                    "fork active — use `>>{label} <msg>` to steer a branch, "
                    "or `/merge` to resolve.",
                    severity="warning",
                )
                return

        queue = app.queue
        task = app.agent_task
        is_running = task is not None and not task.done()

        # Mid-run: route to queue. `>>` prefix = steering, plain text = follow-up.
        # `!` keeps meaning "shell command" regardless of agent state.
        if is_running and queue is not None and not text.startswith("!"):
            if text.startswith(">>"):
                steer_text = text[2:].strip()
                if steer_text:
                    await queue.steer(steer_text)
                    preview = steer_text[:40] + ("…" if len(steer_text) > 40 else "")
                    app.notify(f"steering queued: {preview}")
                    self._increment_queue_badge(steering=True)
            else:
                await queue.follow_up(text)
                app.notify("follow-up queued")
                self._increment_queue_badge(steering=False)
            return

        # Shell command
        if text.startswith("!"):
            app.run_shell_command(text[1:])  # type: ignore[attr-defined]
            return

        # Slash command (but not things like "I used /path/to/file")
        if text.startswith("/") and not text.startswith("//"):
            app.handle_command(text)  # type: ignore[attr-defined]
            return

        # User typed `>>foo` while idle — strip the steering prefix and run as a normal prompt
        if text.startswith(">>"):
            text = text[2:].lstrip()

        # Expand @file references — read files and append content to prompt
        text = self._expand_file_refs(text)

        # Regular prompt → add to message list and run agent
        msg_list = self.query_one(MessageList)
        msg_list.append_user_message(text)
        self._run_agent(text)

    def on_command_selected(self, event: CommandSelected) -> None:
        """Open the command picker or handle a selected command."""
        from apps.cli.modals.command_picker import CommandPickerModal

        async def _handle_result(result: str | None) -> None:
            if result:
                self.app.handle_command(result)  # type: ignore[attr-defined]

        self.app.push_screen(CommandPickerModal(), _handle_result)

    def on_file_selected(self, event: FileSelected) -> None:
        """Open the file picker."""
        from apps.cli.modals.file_picker import FilePickerModal

        working_dir = getattr(self.app, "working_dir", ".")

        async def _handle_result(result: str | None) -> None:
            if result:
                input_area = self.query_one(InputArea)
                prompt = input_area.query("PromptInput")
                if prompt:
                    prompt.first().value += f"@{result} "

        self.app.push_screen(FilePickerModal(working_dir), _handle_result)

    def _run_agent(self, text: str) -> None:
        """Run the agent and stream results directly to widgets."""
        import asyncio

        app = self.app
        if getattr(app, "agent", None) is None:
            app.notify("No agent configured — use /provider to set up", severity="error")  # type: ignore
            return

        header = self.query_one(DeepHeader)
        msg_list = self.query_one(MessageList)

        header.is_streaming = True
        self.query_one(InputArea).is_agent_running = True
        app.last_response = ""  # type: ignore
        assistant = msg_list.begin_assistant_message()

        task = asyncio.create_task(self._agent_stream_worker(text, assistant, msg_list, header))
        app.agent_task = task

        def _on_done(t: asyncio.Task[None]) -> None:
            app.agent_task = None
            exc = t.exception()
            if exc:
                app.notify(f"Agent error: {exc}", severity="error", timeout=10)  # type: ignore

        task.add_done_callback(_on_done)

    async def _agent_stream_worker(  # noqa: C901
        self, text: str, assistant: Any, msg_list: Any, header: Any
    ) -> None:
        """Async worker that streams agent output directly to widgets."""
        import asyncio
        import time as _time

        from pydantic_ai import Agent
        from pydantic_ai._agent_graph import End, UserPromptNode  # type: ignore[attr-defined]
        from pydantic_ai.messages import (
            FinalResultEvent,
            FunctionToolCallEvent,
            FunctionToolResultEvent,
            PartDeltaEvent,
            TextPartDelta,
            ThinkingPartDelta,
        )

        from apps.cli.debug_log import get_logger

        log = get_logger()

        app = self.app
        agent = app.agent  # type: ignore
        deps = app.deps  # type: ignore
        history = app.message_history  # type: ignore

        log.info("Agent run started", prompt_length=len(text), history_messages=len(history))

        _follow_up_scheduled = False
        pending: dict[str, tuple[dict[str, Any], float]] = {}
        _run_cancelled = False
        _TODO_TOOLS: frozenset[str] = frozenset()  # Show all tool calls in UI
        _TEAM_TOOLS = frozenset(
            {
                "spawn_team",
                "assign_task",
                "check_teammates",
                "message_teammate",
                "dissolve_team",
            }
        )
        _subagent_tasks: dict[str, dict[str, Any]] = {}  # task_id -> info

        def _parse_args(raw: Any) -> dict[str, Any]:
            if isinstance(raw, dict):
                return raw
            if isinstance(raw, str):
                import json

                try:
                    p = json.loads(raw)
                    return p if isinstance(p, dict) else {}
                except Exception:
                    pass
            return {}

        try:
            from pydantic_deep.processors.patch import patch_tool_calls_processor

            history = patch_tool_calls_processor(list(history))

            async with agent.iter(
                text, deps=deps, message_history=history, usage_limits=DEFAULT_USAGE_LIMITS
            ) as run:
                async for node in run:
                    if isinstance(node, UserPromptNode):
                        continue

                    elif Agent.is_model_request_node(node):
                        async with node.stream(run.ctx) as stream:
                            # Phase 1: consume events — stream text deltas + detect tool starts
                            final_found = False
                            async for event in stream:
                                if isinstance(event, PartDeltaEvent):
                                    if isinstance(event.delta, TextPartDelta):
                                        if header.is_thinking:
                                            header.is_thinking = False
                                            assistant.finalize_thinking()
                                        delta = event.delta.content_delta
                                        if delta:
                                            assistant.append_text(delta)
                                            app.last_response += delta  # type: ignore
                                            msg_list.scroll_end(animate=False)
                                    elif isinstance(event.delta, ThinkingPartDelta):
                                        if not header.is_thinking:
                                            header.is_thinking = True
                                        if event.delta.content_delta:
                                            assistant.append_thinking(event.delta.content_delta)
                                elif isinstance(event, FinalResultEvent):
                                    final_found = True
                                    if header.is_thinking:
                                        header.is_thinking = False
                                        assistant.finalize_thinking()
                                    break

                            # Phase 2: stream remaining text after FinalResultEvent
                            if final_found:
                                prev_len = 0
                                async for cumulative in stream.stream_text():
                                    if len(cumulative) > prev_len:
                                        delta = cumulative[prev_len:]
                                        assistant.append_text(delta)
                                        app.last_response += delta  # type: ignore
                                        prev_len = len(cumulative)
                                        msg_list.scroll_end(animate=False)

                    elif Agent.is_call_tools_node(node):
                        async with node.stream(run.ctx) as handle_stream:
                            async for event in handle_stream:
                                if isinstance(event, FunctionToolCallEvent):
                                    tool_name = event.part.tool_name
                                    args = _parse_args(event.part.args)
                                    call_id = getattr(event.part, "tool_call_id", tool_name)
                                    log.debug("Tool call started", tool=tool_name, call_id=call_id)
                                    if tool_name not in _TODO_TOOLS:
                                        assistant.add_tool_call(tool_name, args, call_id)
                                        msg_list.scroll_end(animate=False)
                                    pending[call_id] = (args, _time.monotonic())

                                    # Feature 8: Track subagent task launches
                                    if tool_name == "task":
                                        sa_name = args.get("subagent_type") or args.get(
                                            "name", "subagent"
                                        )
                                        sa_desc = args.get("description", "")
                                        _subagent_tasks[call_id] = {
                                            "name": sa_name,
                                            "description": sa_desc[:40],
                                            "status": "running",
                                        }
                                        self._update_subagents_panel(_subagent_tasks)

                                    # Feature 9: Track team tool events
                                    if tool_name in _TEAM_TOOLS:
                                        self._update_subagents_panel(
                                            _subagent_tasks,
                                            team_event=(tool_name, args),
                                        )

                                elif isinstance(event, FunctionToolResultEvent):
                                    tool_name = getattr(event.result, "tool_name", "unknown")
                                    call_id = getattr(event.result, "tool_call_id", tool_name)
                                    raw = str(event.result.content)
                                    elapsed = 0.0
                                    args = {}
                                    if call_id in pending:
                                        args, start = pending.pop(call_id)
                                        elapsed = _time.monotonic() - start
                                    is_error = looks_like_error(raw, check_exit_code=True)
                                    log_kwargs: dict[str, Any] = {
                                        "tool": tool_name,
                                        "call_id": call_id,
                                        "elapsed": f"{elapsed:.2f}s",
                                        "is_error": is_error,
                                        "output_length": len(raw),
                                    }
                                    if tool_name == "task":
                                        # Log full subagent output for debugging
                                        log_kwargs["output"] = raw[:5000]
                                    log.debug("Tool call completed", **log_kwargs)
                                    # Save structured tool trace for /improve
                                    self._append_tool_log(tool_name, args, raw, elapsed, is_error)
                                    if tool_name not in _TODO_TOOLS:
                                        assistant.complete_tool_call(
                                            call_id, raw, elapsed, is_error
                                        )

                                    # Feature 8: Update subagent status on completion
                                    if call_id in _subagent_tasks:
                                        _subagent_tasks[call_id]["status"] = (
                                            "error" if is_error else "completed"
                                        )
                                        self._update_subagents_panel(_subagent_tasks)

                    elif isinstance(node, End):
                        pass

                result = run.result

            assistant.finalize_text()

            if result is not None:
                # Show per-turn usage on the assistant message
                try:
                    usage = result.usage()
                    assistant.set_usage(
                        input_tokens=usage.request_tokens or 0,
                        output_tokens=usage.response_tokens or 0,
                        requests=usage.requests or 0,
                    )
                except Exception:
                    pass

                app.message_history = result.all_messages()  # type: ignore
                log.info(
                    "Agent run completed",
                    total_messages=len(app.message_history),  # type: ignore[arg-type]
                )

                # Calculate cost/tokens from message history (authoritative)
                self._sync_status_from_history()

                # Check for DeferredToolRequests (approval flow)
                from pydantic_ai.tools import DeferredToolRequests

                if isinstance(result.output, DeferredToolRequests):
                    from pydantic_ai.tools import (
                        DeferredToolResults,
                        ToolApproved,
                        ToolDenied,
                    )

                    approvals: dict[str, ToolApproved | ToolDenied] = {}

                    for call in result.output.approvals:
                        future: asyncio.Future[str] = asyncio.Future()
                        tool_args = call.args if isinstance(call.args, dict) else {}

                        # Show approval modal and wait for user decision
                        from apps.cli.modals.approval import ApprovalModal

                        self.app.push_screen(
                            ApprovalModal(call.tool_name, tool_args),
                            lambda decision, f=future: f.set_result(decision),  # type: ignore[misc]
                        )
                        decision = await future

                        if decision == "no":
                            approvals[call.tool_call_id] = ToolDenied(
                                message=f"User denied {call.tool_name}"
                            )
                            assistant_new = msg_list.begin_assistant_message()
                            assistant_new.append_text(
                                f"Tool `{call.tool_name}` was denied by user."
                            )
                            assistant_new.finalize_text()
                            msg_list.end_assistant_message()
                        else:
                            approvals[call.tool_call_id] = ToolApproved()

                    # Continue agent with approval decisions
                    header.is_streaming = True
                    assistant_cont = msg_list.begin_assistant_message()

                    async with agent.iter(
                        None,
                        deps=deps,
                        message_history=result.all_messages(),
                        deferred_tool_results=DeferredToolResults(approvals=approvals),
                        usage_limits=DEFAULT_USAGE_LIMITS,
                    ) as cont_run:
                        async for node in cont_run:
                            if isinstance(node, UserPromptNode):
                                continue
                            elif Agent.is_model_request_node(node):
                                async with node.stream(cont_run.ctx) as stream:
                                    final_found = False
                                    async for event in stream:
                                        if isinstance(event, PartDeltaEvent):
                                            if isinstance(event.delta, TextPartDelta):
                                                delta = event.delta.content_delta
                                                if delta:
                                                    assistant_cont.append_text(delta)
                                                    app.last_response += delta  # type: ignore
                                                    msg_list.scroll_end(animate=False)
                                        elif isinstance(event, FinalResultEvent):
                                            final_found = True
                                            break
                                    if final_found:
                                        prev_len = 0
                                        async for cumulative in stream.stream_text():
                                            if len(cumulative) > prev_len:
                                                delta = cumulative[prev_len:]
                                                assistant_cont.append_text(delta)
                                                app.last_response += delta  # type: ignore
                                                prev_len = len(cumulative)
                                                msg_list.scroll_end(animate=False)
                                    elif Agent.is_call_tools_node(node):
                                        async with node.stream(cont_run.ctx) as handle_stream:
                                            async for event in handle_stream:
                                                if isinstance(event, FunctionToolCallEvent):
                                                    tool_name = event.part.tool_name
                                                    t_args = _parse_args(event.part.args)
                                                    call_id = getattr(
                                                        event.part, "tool_call_id", tool_name
                                                    )
                                                    if tool_name not in _TODO_TOOLS:
                                                        assistant_cont.add_tool_call(
                                                            tool_name, t_args, call_id
                                                        )
                                                        msg_list.scroll_end(animate=False)
                                                elif isinstance(event, FunctionToolResultEvent):
                                                    tool_name = getattr(
                                                        event.result, "tool_name", "unknown"
                                                    )
                                                    call_id = getattr(
                                                        event.result, "tool_call_id", tool_name
                                                    )
                                                    raw = str(event.result.content)
                                                    assistant_cont.complete_tool_call(
                                                        call_id, raw, 0.0, False
                                                    )
                            elif isinstance(node, End):
                                pass

                        cont_result = cont_run.result

                    assistant_cont.finalize_text()
                    msg_list.end_assistant_message()

                    if cont_result is not None:
                        app.message_history = cont_result.all_messages()  # type: ignore
                        try:
                            status = self.query_one(StatusBar)
                            status.message_count = len(app.message_history)  # type: ignore
                        except Exception:
                            pass

                # Auto-save session
                self._save_session()

                # Drain follow-up queue and schedule next run if pending.
                _queue = app.queue
                if _queue is not None:
                    _follow_up_msgs = await _queue.drain_follow_up()
                    if _follow_up_msgs:
                        from pydantic_deep.capabilities.message_queue import (
                            format_follow_up as _fmt_fu,
                        )

                        _follow_up_text = _fmt_fu(_follow_up_msgs)
                        msg_list.append_user_message(_follow_up_text)
                        self._decrement_queue_badge(len(_follow_up_msgs))
                        _follow_up_scheduled = True
                        self.call_later(self._run_agent, _follow_up_text)

        except asyncio.CancelledError:
            _run_cancelled = True
            log.info("Agent run cancelled")
        except Exception as exc:
            log.error("Agent run failed", exc_info=True)
            assistant.append_text(f"\n\n**Error:** {exc}")
            assistant.finalize_text()
            with contextlib.suppress(Exception):
                app.notify(f"Agent error: {exc}", severity="error", timeout=10)  # type: ignore
        finally:
            from apps.cli.widgets.input_area import HintsBar

            for call_id, (_, start) in list(pending.items()):
                elapsed = _time.monotonic() - start
                if _run_cancelled:
                    assistant.complete_tool_call(call_id, "Interrupted", elapsed, True)
                else:
                    assistant.complete_tool_call(call_id, "", elapsed, False)
            pending.clear()

            msg_list.remove_last_if_empty()

            # Always save session — even after errors or cancellation
            self._save_session()
            app.is_streaming = False
            header.is_streaming = False
            header.is_thinking = False
            with contextlib.suppress(Exception):
                self.query_one(InputArea).is_agent_running = False
            msg_list.end_assistant_message()
            with contextlib.suppress(Exception):
                self.query_one(InputArea).focus_input()
            with contextlib.suppress(Exception):
                self.query_one(HintsBar).reset()
            with contextlib.suppress(Exception):
                msg_list.scroll_end(animate=False)
            _stale_queue = app.queue
            if _stale_queue is not None:
                stale = await _stale_queue.drain_steering()
                if stale:
                    n = len(stale)
                    label = "steering message" if n == 1 else "steering messages"
                    with contextlib.suppress(Exception):
                        app.notify(
                            f"{n} {label} not delivered — agent finished before next LLM call",
                            severity="warning",
                            timeout=6,
                        )
                # When the run was cancelled, follow-ups referring to the cancelled
                # task are likely stale too. Discard with a count-only notification.
                if _run_cancelled:
                    stale_fu = await _stale_queue.drain_follow_up()
                    if stale_fu:
                        n = len(stale_fu)
                        label = "follow-up" if n == 1 else "follow-ups"
                        with contextlib.suppress(Exception):
                            app.notify(
                                f"{n} {label} discarded — run cancelled",
                                severity="warning",
                                timeout=6,
                            )
            if not _follow_up_scheduled:
                self._reset_queue_badge()
            else:
                with contextlib.suppress(Exception):
                    self.query_one(QueuedWidget).clear_steering()

    def _increment_queue_badge(self, *, steering: bool) -> None:
        with contextlib.suppress(Exception):
            w = self.query_one(QueuedWidget)
            w.increment_steering() if steering else w.increment_follow_up()

    def _decrement_queue_badge(self, follow_up_count: int = 1) -> None:
        with contextlib.suppress(Exception):
            self.query_one(QueuedWidget).decrement_follow_up(follow_up_count)

    def _reset_queue_badge(self) -> None:
        with contextlib.suppress(Exception):
            self.query_one(QueuedWidget).reset()

    def _expand_file_refs(self, text: str) -> str:
        """Expand @file references in the prompt with file contents."""
        import re
        from pathlib import Path

        working_dir = Path(getattr(self.app, "working_dir", "."))

        def replace_ref(match: re.Match[str]) -> str:
            filepath = match.group(1)
            full_path = working_dir / filepath
            try:
                if full_path.is_file():
                    content = full_path.read_text()
                    # Truncate large files
                    if len(content) > 50_000:
                        content = content[:50_000] + "\n... (truncated)"
                    return f'\n\n<file path="{filepath}">\n{content}\n</file>\n'
            except Exception:
                pass
            return match.group(0)  # Leave as-is if can't read

        return re.sub(r"@([\w./\-]+)", replace_ref, text)

    # ── Agent event handling ──────────────────────────────────────

    def on_agent_run_started(self, _event: AgentRunStarted) -> None:
        header = self.query_one(DeepHeader)
        header.is_streaming = True
        self.app.last_response = ""  # type: ignore
        msg_list = self.query_one(MessageList)
        msg_list.begin_assistant_message()

    def on_agent_token(self, event: AgentToken) -> None:
        msg_list = self.query_one(MessageList)
        if msg_list.current_assistant:
            msg_list.current_assistant.append_text(event.text)
            # Auto-scroll (debounced — Textual coalesces scroll_end calls)
            msg_list.scroll_end(animate=False)
        # Track for /copy
        self.app.last_response = getattr(self.app, "last_response", "") + event.text  # type: ignore

    def on_agent_text_complete(self, _event: AgentTextComplete) -> None:
        msg_list = self.query_one(MessageList)
        if msg_list.current_assistant:
            msg_list.current_assistant.finalize_text()
            msg_list.scroll_end(animate=False)

    def on_tool_call_started(self, event: ToolCallStarted) -> None:
        msg_list = self.query_one(MessageList)
        if msg_list.current_assistant:
            msg_list.current_assistant.add_tool_call(event.tool_name, event.args, event.call_id)
            msg_list.scroll_end(animate=False)

    def on_tool_call_completed(self, event: ToolCallCompleted) -> None:
        msg_list = self.query_one(MessageList)
        if msg_list.current_assistant:
            msg_list.current_assistant.complete_tool_call(
                event.call_id, event.result, event.elapsed, event.error
            )

    def on_agent_complete(self, _event: AgentComplete) -> None:
        header = self.query_one(DeepHeader)
        header.is_streaming = False
        msg_list = self.query_one(MessageList)
        msg_list.end_assistant_message()
        self.query_one(InputArea).focus_input()

    def on_agent_error(self, event: AgentError) -> None:
        header = self.query_one(DeepHeader)
        header.is_streaming = False
        msg_list = self.query_one(MessageList)
        msg_list.end_assistant_message()
        from apps.cli.widgets.notification import notify_error

        notify_error(self.app, f"Error: {event.error}")
        self.query_one(InputArea).focus_input()

    # ── Approval handling ─────────────────────────────────────────

    def on_approval_requested(self, event: ApprovalRequested) -> None:
        from apps.cli.modals.approval import ApprovalModal

        async def _handle_result(result: str) -> None:
            event.future.set_result(result)

        self.app.push_screen(
            ApprovalModal(event.tool_name, event.args),
            _handle_result,
        )

    # ── Status updates ────────────────────────────────────────────

    def on_cost_updated(self, event: CostUpdated) -> None:
        status = self.query_one(StatusBar)
        header = self.query_one(DeepHeader)
        status.current_cost = event.run_cost
        status.total_cost = event.total_cost
        header.total_cost = event.total_cost
        if event.total_input_tokens > 0:
            status.total_input_tokens = event.total_input_tokens
            header.total_input_tokens = event.total_input_tokens
        if event.total_output_tokens > 0:
            status.total_output_tokens = event.total_output_tokens
            header.total_output_tokens = event.total_output_tokens

    def on_context_updated(self, event: ContextUpdated) -> None:
        status = self.query_one(StatusBar)
        status.context_pct = event.pct
        status.context_current = event.current
        status.context_max = event.maximum
        if event.pct >= 0.9:
            notify_warning(self.app, f"Context at {event.pct:.0%} — type /compact to summarize")

    def on_todos_updated(self, event: TodosUpdated) -> None:
        status = self.query_one(StatusBar)
        todos = event.todos
        status.total_todos = len(todos)
        status.active_todos = sum(1 for t in todos if getattr(t, "status", "") == "completed")
        # Update side panel
        side = self.query_one(SidePanel)
        todos_widget = side.query_one("TodosWidget")
        todos_widget.todos = todos  # type: ignore[attr-defined]
        side.show_if_needed(self.app.size.width, len(todos) > 0)

    def on_compression_started(self, _event: CompressionStarted) -> None:
        notify_warning(self.app, "Compacting context...")

    def on_compression_complete(self, _event: CompressionComplete) -> None:
        notify_success(self.app, "Context compacted")

    # ── Subagent / Team panel updates ────────────────────────────

    def _update_subagents_panel(
        self,
        subagent_tasks: dict[str, dict[str, Any]],
        team_event: tuple[str, dict[str, Any]] | None = None,
    ) -> None:
        """Update the SubagentsWidget in the side panel with current task info."""
        try:
            from apps.cli.widgets.subagents_panel import SubagentsWidget

            side = self.query_one(SidePanel)
            sa_widget = side.query_one(SubagentsWidget)

            agents_list: list[dict[str, Any]] = []

            # Add tracked subagent tasks
            for info in subagent_tasks.values():
                agents_list.append(info)

            # Add team event info if present
            if team_event:
                tool_name, args = team_event
                if tool_name == "spawn_team":
                    members = args.get("members", [])
                    for m in members[:5]:  # Limit display
                        name = m if isinstance(m, str) else m.get("name", "member")
                        agents_list.append(
                            {
                                "name": name,
                                "status": "running",
                                "description": "team member",
                            }
                        )
                elif tool_name == "assign_task":
                    assignee = args.get("assignee", "?")
                    desc = args.get("description", "")[:30]
                    agents_list.append(
                        {
                            "name": assignee,
                            "status": "running",
                            "description": desc,
                        }
                    )

            sa_widget.agents = agents_list

            # Show the side panel if we have subagent/team content
            if agents_list:
                side.show_if_needed(self.app.size.width, True)
        except Exception:
            pass  # Side panel may not be mounted yet

    # ── Actions ───────────────────────────────────────────────────

    def action_show_todos(self) -> None:
        self.app.handle_command("/todos")  # type: ignore[attr-defined]

    def action_clear_screen(self) -> None:
        self.query_one(MessageList).clear_messages()

    def action_scroll_up(self) -> None:
        self.query_one(MessageList).scroll_page_up()

    def action_scroll_down(self) -> None:
        self.query_one(MessageList).scroll_page_down()

    def action_focus_input(self) -> None:
        """Esc returns focus to the input."""
        self.query_one(InputArea).focus_input()

    def enter_fork_view(self, session: Any) -> None:
        """Swap the main message pane to fork view and start polling.

        Called by ``DeepApp.watch_active_fork`` when a fork starts.
        """
        with contextlib.suppress(NoMatches):
            self.query_one(MessageList).display = False
        tabs = self.query_one(ForkTabsWidget)
        tabs.add_class("active")
        body = self.query_one("#fork-view-body", Vertical)
        body.display = True
        overview = self.query_one(ForkOverviewWidget)
        overview.set_active(True)

        coordinator = session.coordinator
        parent_model = getattr(self.app, "model_name", None) or None
        branch_models: dict[str, str] = {}
        for branch_id in session.handle.branches:
            runtime = coordinator.branches[branch_id]
            effective_model = runtime.spec.model or parent_model
            if effective_model:
                branch_models[branch_id] = effective_model
            panel = BranchPanelWidget(
                branch_id=branch_id,
                label=runtime.spec.label,
                model=effective_model,
            )
            body.mount(panel)
            self._attach_branch_done_callback(panel, runtime)
        with contextlib.suppress(NoMatches):
            overview.set_models(branch_models)

        with contextlib.suppress(NoMatches):
            self.query_one(ForkBadgeWidget).show()

        self._poll_timer = self.set_interval(_FORK_POLL_INTERVAL_S, self._poll_fork_state)

        self._poll_fork_state()

    def exit_fork_view(self) -> None:
        """Tear down fork widgets and resume normal chat. Called on /merge or abort."""
        if self._poll_timer is not None:
            # Timer.stop() can raise during app teardown (loop closing); broader catch.
            with contextlib.suppress(Exception):
                self._poll_timer.stop()
            self._poll_timer = None

        # panel.remove() schedules async removal — broader catch covers teardown races.
        with contextlib.suppress(Exception):
            for panel in list(self.query(BranchPanelWidget)):
                panel.remove()

        with contextlib.suppress(NoMatches):
            tabs = self.query_one(ForkTabsWidget)
            tabs.statuses = []
            tabs.active_id = OVERVIEW_TAB_ID
            tabs.remove_class("active")
        with contextlib.suppress(NoMatches):
            body = self.query_one("#fork-view-body", Vertical)
            body.display = False
        with contextlib.suppress(NoMatches):
            self.query_one(ForkOverviewWidget).set_active(False)
        with contextlib.suppress(NoMatches):
            self.query_one(ForkBadgeWidget).hide()
        with contextlib.suppress(NoMatches):
            self.query_one(MessageList).display = True

    def _attach_branch_done_callback(self, panel: BranchPanelWidget, runtime: Any) -> None:
        """Hook the branch's task so panel renders final messages on completion."""
        import asyncio

        task: asyncio.Task[Any] = runtime.task
        app = self.app

        _BUDGET_STATES = ("budget_exhausted", "aggregate_budget_exhausted")

        def _replay_partial(state: str) -> None:
            """Apply a budget-terminal state plus the partial history snapshot.

            Even when a branch was cancelled or BudgetExceededError-raised
            by the budget watcher, the agent typically produced meaningful
            output before the cap kicked in (tool calls, write_file
            results, intermediate assistant text — all snapshot by
            :meth:`LiveForkCapability.before_model_request`). Render that
            snapshot so the user sees the work even on a budget cut-off,
            mirroring the merge-resolver's partial-history fallback.
            """
            panel.mark_status(state, reason=getattr(runtime.status, "error", None))
            partial = list(getattr(runtime, "partial_history", None) or [])
            if partial:
                with contextlib.suppress(Exception):  # pragma: no cover - defensive
                    panel.replay_messages(partial)

        def _on_done(t: asyncio.Task[Any]) -> None:
            def _apply() -> None:
                coord_state = getattr(runtime.status, "state", None)
                if t.cancelled():
                    if coord_state in _BUDGET_STATES:
                        _replay_partial(coord_state)
                    else:
                        panel.mark_status("terminated")
                    return
                exc = t.exception()
                if exc is not None:
                    if coord_state in _BUDGET_STATES:
                        _replay_partial(coord_state)
                        return
                    panel.mark_status("failed")

                    import traceback as _tb

                    from apps.cli.debug_log import get_logger as _gl

                    _log = _gl()
                    tb_str = "".join(_tb.format_exception(type(exc), exc, exc.__traceback__))
                    _log.error(f"Branch {panel.label} failed:\n{tb_str}")
                    with contextlib.suppress(Exception):
                        msg = str(exc) or type(exc).__name__
                        app.notify(
                            f"Branch {panel.label} failed: {msg[:120]}",
                            severity="error",
                            timeout=10,
                        )
                    return
                result = t.result()
                panel.mark_status("done")
                with contextlib.suppress(Exception):  # pragma: no cover - defensive
                    panel.replay_messages(list(result.all_messages()))

            try:
                app.call_from_thread(_apply)
            except RuntimeError:  # pragma: no cover - falling back when not on a worker
                _apply()

        task.add_done_callback(_on_done)

    def _poll_fork_state(self) -> None:
        """Refresh tab badges, overview rows, and the side-panel cost chip.

        Reads :meth:`ForkCoordinator.fork_cost` once per tick so the chip
        and the per-branch tabs see a coherent snapshot. The fork's status
        timer already runs at ~1 Hz; we piggyback rather than add a timer.
        """
        app = self.app
        session = app.active_fork
        if session is None:  # pragma: no cover - timer should be stopped before this
            return
        statuses = session.inspect()
        summary = None
        with contextlib.suppress(Exception):
            summary = session.coordinator.fork_cost()
        per_branch_costs = dict(summary.per_branch) if summary is not None else {}
        with contextlib.suppress(Exception):
            tabs = self.query_one(ForkTabsWidget)
            tabs.statuses = statuses
            tabs.branch_costs = per_branch_costs
        with contextlib.suppress(Exception):
            overview = self.query_one(ForkOverviewWidget)
            overview.statuses = statuses
        with contextlib.suppress(Exception):
            badge = self.query_one(ForkBadgeWidget)
            agg_usd = summary.aggregate_usd if summary is not None else None
            agg_budget = summary.aggregate_budget_usd if summary is not None else None
            badge.update_from_statuses(
                list(statuses),
                aggregate_usd=agg_usd,
                aggregate_budget_usd=agg_budget,
            )
        for panel in self.query(BranchPanelWidget):
            cost = per_branch_costs.get(panel.branch_id)
            panel.cost_usd = cost.cumulative_usd if cost is not None else None

    def focus_branch_tab(self, branch_id: str) -> None:
        """Show one branch panel and hide the others (or show overview if ``OVERVIEW_TAB_ID``)."""
        with contextlib.suppress(Exception):
            overview = self.query_one(ForkOverviewWidget)
            overview.set_active(branch_id == OVERVIEW_TAB_ID)
        for panel in self.query(BranchPanelWidget):
            panel.set_active(panel.branch_id == branch_id)
            if panel.branch_id == branch_id:
                with contextlib.suppress(Exception):
                    panel.focus()
        if branch_id == OVERVIEW_TAB_ID:
            with contextlib.suppress(Exception):
                self.query_one(ForkOverviewWidget).focus()

    def on_fork_tabs_widget_branch_tab_selected(
        self, event: ForkTabsWidget.BranchTabSelected
    ) -> None:
        """React to programmatic tab cycling — show the corresponding panel."""
        self.focus_branch_tab(event.branch_id)

    def action_cycle_branch_tab(self) -> None:
        """Tab keybinding — cycle through overview + each branch panel."""
        if self.app.active_fork is None:
            return
        with contextlib.suppress(Exception):
            tabs = self.query_one(ForkTabsWidget)
            tabs.cycle_focus()

    async def action_merge_focused_branch(self) -> None:
        """Enter keybinding — pick the currently-focused branch as the merge winner.

        Only fires when:
        - a fork is active
        - the focused tab is a branch panel (not the overview)
        - the branch has finished (``state == "done"``)

        Otherwise it's a no-op so the keypress can bubble up (e.g. to the chat input).
        """
        app = self.app
        session = app.active_fork
        if session is None:
            return
        try:
            tabs = self.query_one(ForkTabsWidget)
        except Exception:  # pragma: no cover - defensive
            return
        branch_id = tabs.active_id
        if branch_id == OVERVIEW_TAB_ID:
            return
        runtime = session.coordinator.branches.get(branch_id)
        if runtime is None or runtime.status.state != "done":
            if runtime is not None:
                app.notify(
                    f"branch `{runtime.spec.label}` is {runtime.status.state} — "
                    "wait for `done` before merging.",
                    severity="warning",
                )
            return
        try:
            result = await session.merge(branch_id)
        except Exception as e:  # pragma: no cover - defensive
            from apps.cli.debug_log import get_logger

            get_logger().error("Merge failed", exc_info=True)
            app.notify(f"Merge failed: {e}", severity="error")
            return

        from pydantic_deep.processors.patch import patch_tool_calls_processor

        app.message_history = patch_tool_calls_processor(list(result.history_after_merge))
        label = runtime.spec.label
        app.active_fork = None
        app.notify(f"Merged: kept branch {label}", severity="information")

    async def fork_action_escape(self) -> bool:
        """Handle Esc while a fork is active. Returns True if Esc was consumed.

        Called from :meth:`DeepApp.action_escape_key` before the default
        agent-interrupt behaviour, so branch-tab Esc and overview Esc reach
        the user's confirm prompt instead of cancelling an unrelated task.
        """
        from apps.cli.modals.confirm import ConfirmModal

        app = self.app
        session = app.active_fork
        if session is None:
            return False

        try:
            tabs = self.query_one(ForkTabsWidget)
        except Exception:  # pragma: no cover - defensive
            return False
        active = tabs.active_id

        if active == OVERVIEW_TAB_ID:

            async def _on_abort(decision: bool | None) -> None:
                if decision:
                    await session.abort()
                    app.active_fork = None
                    app.notify("Fork aborted")

            app.push_screen(ConfirmModal("Abort the entire fork?"), _on_abort)
            return True

        runtime = session.coordinator.branches.get(active)
        label = runtime.spec.label if runtime else active

        if runtime is not None and runtime.status.state != "running":
            state = runtime.status.state
            if state == "done":
                app.notify(
                    f"branch `{label}` is done — press Enter to merge it, "
                    "or /merge for the picker.",
                    severity="information",
                )
            else:
                app.notify(
                    f"branch `{label}` is {state} — nothing to terminate.",
                    severity="information",
                )
            return True

        async def _on_terminate(decision: bool | None) -> None:
            if decision:
                await session.terminate_branch(active)
                app.notify(f"Branch {label} terminated")

        app.push_screen(ConfirmModal(f"Terminate branch '{label}'?"), _on_terminate)
        return True

    def action_toggle_multiline(self) -> None:
        self.query_one(InputArea).toggle_multiline()

    def action_search_messages(self) -> None:
        """Open search modal to find messages in the conversation."""
        from apps.cli.modals.search import SearchModal

        def _handle_result(result: str | None) -> None:
            if result is not None and result.isdigit():
                child_idx = int(result)
                msg_list = self.query_one(MessageList)
                children = list(msg_list.children)
                if 0 <= child_idx < len(children):
                    children[child_idx].scroll_visible(animate=True)

        self.app.push_screen(SearchModal(), _handle_result)

    # on_resize is defined near on_mount — handles side panel visibility
