"""Interactive chat mode for the CLI.

Provides a REPL-style chat loop with streaming responses, tool call
visibility, and TODO list display.

Uses ``agent.iter()`` + ``node.stream()`` (the same approach as
``examples/full_app/app.py``) for reliable, chunk-complete streaming.
"""

from __future__ import annotations

import contextlib
import os
import readline
import sys
import time
from pathlib import Path
from typing import Any

from pydantic_ai import (
    Agent,
    FinalResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPartDelta,
)
from pydantic_ai._agent_graph import End, UserPromptNode  # type: ignore[attr-defined]
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessage,
)
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.text import Text

from cli.agent import create_cli_agent
from cli.display import (
    format_cost_line,
    format_tokens,
    install_prettier_code_blocks,
    print_error,
    print_warning,
    print_welcome_banner,
)
from cli.theme import Glyphs, Theme, get_glyphs, get_theme
from cli.tool_display import render_tool_call, render_tool_result
from pydantic_deep.deps import DeepAgentDeps

console = Console()

# Bold emerald prompt using RGB ANSI escapes (works on modern terminals)
_USER_PROMPT = "\033[1m\033[38;2;16;185;129m> \033[0m"

# TODO tool names — these are suppressed from the stream and shown as a checklist
_TODO_TOOLS: frozenset[str] = frozenset(
    {
        "write_todos",
        "read_todos",
        "add_todo",
        "update_todo_status",
        "remove_todo",
        "add_subtask",
        "set_dependency",
        "get_available_tasks",
    }
)

# Markers inserted by Ctrl+V readline binding — we detect these after input()
_PASTE_MARKER = "\x16"  # Ctrl+V literal character

# Module-level image list populated by _read_user_input, consumed by _chat_loop
_pending_images: list[Any] = []

# Counter for pasted text blocks
_paste_text_counter = 0


def _get_history_config() -> tuple[Path, int]:
    """Return (history_file_path, max_lines) from CLI config."""
    from cli.config import get_history_path, load_config

    config = load_config()
    history_path = Path(config.history_file) if config.history_file else get_history_path()
    return history_path, config.max_history


_SLASH_COMMANDS = [
    "/help",
    "/clear",
    "/compact",
    "/context",
    "/undo",
    "/copy",
    "/todos",
    "/cost",
    "/tokens",
    "/model",
    "/save",
    "/load",
    "/remember",
    "/skills",
    "/diff",
    "/version",
    "/bug",
    "/quit",
    "/exit",
]


def _get_all_slash_commands() -> list[str]:
    """Merge built-in slash commands with discovered custom commands."""
    from cli.commands import discover_commands

    all_cmds = list(_SLASH_COMMANDS)
    for cmd in discover_commands():
        slash = f"/{cmd.name}"
        if slash not in all_cmds:
            all_cmds.append(slash)
    return all_cmds


def _try_custom_command(user_input: str) -> str | None:
    """Check if user_input matches a custom command. Returns prompt or None."""
    from cli.commands import invoke_command, load_command

    parts = user_input.strip().split(maxsplit=1)
    cmd_name = parts[0].lstrip("/")
    cmd_arg = parts[1].strip() if len(parts) > 1 else ""
    cmd = load_command(cmd_name)
    if cmd is None:
        return None
    return invoke_command(cmd, cmd_arg)


def _slash_completer(text: str, state: int) -> str | None:
    """Readline completer for slash commands and @file mentions."""
    if text.startswith("/"):
        all_cmds = _get_all_slash_commands()
        matches = [c for c in all_cmds if c.startswith(text)]
    elif text.startswith("@"):
        # Complete file paths after @
        import glob as _glob

        prefix = text[1:]  # strip the @
        matches = [f"@{p}" for p in _glob.glob(prefix + "*")]
    else:
        return None
    if state < len(matches):
        return matches[state]
    return None


def _setup_readline() -> None:
    """Configure readline with persistent history, tab-completion, and Ctrl+V image paste."""
    history_file, max_lines = _get_history_config()
    with contextlib.suppress(OSError):
        history_file.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        readline.read_history_file(str(history_file))
    readline.set_history_length(max_lines)

    # Tab-completion for /commands and @files
    readline.set_completer(_slash_completer)
    readline.set_completer_delims(" \t\n")
    with contextlib.suppress(Exception):
        if "libedit" in (readline.__doc__ or ""):
            # libedit needs both forms for different macOS versions
            readline.parse_and_bind("bind ^I rl_complete")
            readline.parse_and_bind("bind '\\t' rl_complete")
        else:
            readline.parse_and_bind("tab: complete")

    # Rebind Ctrl+V: instead of quoted-insert, insert the literal \x16
    # character so we can detect it and grab the clipboard image.
    with contextlib.suppress(Exception):
        if "libedit" in (readline.__doc__ or ""):
            # macOS libedit
            readline.parse_and_bind('"\\C-v": ed-insert')
        else:
            # GNU readline
            readline.parse_and_bind(r'"\C-v": self-insert')


def _save_readline_history() -> None:
    """Save readline history to disk."""
    history_file, _ = _get_history_config()
    with contextlib.suppress(OSError):
        readline.write_history_file(str(history_file))


def _expand_file_mentions(text: str, working_dir: str | None = None) -> str:
    """Expand @filepath mentions by inlining file contents.

    Supports @path/to/file syntax. The file content is appended after
    the user message in a clearly delimited block.
    """
    import re

    pattern = re.compile(r"@([\w./~\-]+(?:\.\w+)?)")
    matches = pattern.findall(text)
    if not matches:
        return text

    root = Path(working_dir) if working_dir else Path.cwd()
    appended: list[str] = []
    for match in matches:
        filepath = Path(os.path.expanduser(match))
        if not filepath.is_absolute():
            filepath = root / filepath
        if filepath.is_file():
            try:
                content = filepath.read_text(errors="replace")
                appended.append(f'\n\n<file path="{filepath}">\n{content}\n</file>')
            except OSError:
                pass

    if appended:
        return text + "".join(appended)
    return text


_SAFE_TOOLS = frozenset(
    {
        "read_file",
        "read_todos",
        "ls",
        "glob",
        "grep",
        "web_search",
        "list_checkpoints",
        "read_memory",
    }
)


async def _interactive_permission_handler(
    tool_name: str,
    tool_args: dict[str, Any],
    reason: str,
) -> bool:
    """Prompt the user to approve or deny a tool call."""
    from cli.tool_display import format_tool_call

    if tool_name in _SAFE_TOOLS:
        return True

    theme = get_theme()
    formatted = format_tool_call(tool_name, tool_args)
    console.print(f"\n[bold {theme.warning}]Approval required:[/bold {theme.warning}] {formatted}")
    if reason:
        console.print(f"[{theme.muted}]Reason: {reason}[/{theme.muted}]")

    # Rich context for file operations
    from cli.diff_display import render_edit_approval, render_write_approval

    if tool_name == "edit_file":
        old_s = tool_args.get("old_string", "")
        new_s = tool_args.get("new_string", "")
        if old_s or new_s:
            console.print(render_edit_approval(tool_args.get("path", ""), old_s, new_s))
    elif tool_name == "write_file":
        content = tool_args.get("content", "")
        if content:
            console.print(render_write_approval(tool_args.get("path", ""), content))

    try:
        answer = input("[Y]es / [N]o / [A]uto-approve all: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False

    if answer in ("a", "auto"):
        _SAFE_TOOLS_MUTABLE.add(tool_name)
        _auto_approve_state["active"] = True
        return True
    return answer in ("y", "yes", "")


_SAFE_TOOLS_MUTABLE: set[str] = set()
_auto_approve_state: dict[str, bool] = {"active": False}


# Map provider prefixes to their required environment variables.
_PROVIDER_ENV_VARS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
}


def _print_model_error(exc: Exception) -> None:
    """Print a friendly error when the model provider fails to initialise."""
    msg = str(exc)
    if "api_key" in msg.lower() or "api key" in msg.lower():
        hint_lines = ["Set the API key for your provider, e.g.:"]
        for prefix, var in _PROVIDER_ENV_VARS.items():
            hint_lines.append(f"  export {var}=sk-...   # for --model {prefix}:...")
        print_error(console, msg, hint="\n".join(hint_lines))
    else:
        print_error(console, f"Failed to create agent: {exc}")


def _truncate(text: str, max_len: int = 120) -> str:
    """Truncate text with ellipsis."""
    glyphs = get_glyphs()
    if len(text) > max_len:
        return text[: max_len - len(glyphs.ellipsis)] + glyphs.ellipsis
    return text


def _print_todos(deps: DeepAgentDeps) -> None:
    """Print the current TODO list with stats header."""
    glyphs = get_glyphs()
    theme = get_theme()

    if not deps.todos:
        return

    # Count statuses
    active = sum(1 for t in deps.todos if t.status == "in_progress")
    pending = sum(1 for t in deps.todos if t.status == "pending")
    done = sum(1 for t in deps.todos if t.status == "completed")

    # Stats header
    stats_parts: list[str] = []
    if active:
        stats_parts.append(f"[{theme.warning}]{active} active[/{theme.warning}]")
    if pending:
        stats_parts.append(f"[{theme.muted}]{pending} pending[/{theme.muted}]")
    if done:
        stats_parts.append(f"[{theme.success}]{done} done[/{theme.success}]")
    stats = f" [{theme.muted}]{glyphs.bullet}[/{theme.muted}] ".join(stats_parts)

    console.print(f"\n  [{theme.muted}]TODOs[/{theme.muted}]  {stats}")

    for todo in deps.todos:
        if todo.status == "completed":
            icon = f"[{theme.success}]{glyphs.success}[/{theme.success}]"
            label = f"[{theme.muted}]{todo.content}[/{theme.muted}]"
        elif todo.status == "in_progress":
            icon = f"[{theme.warning}]{glyphs.active}[/{theme.warning}]"
            label = todo.content
        else:
            icon = f"[{theme.muted}]{glyphs.pending}[/{theme.muted}]"
            label = todo.content
        console.print(f"  {icon} {label}")


def _is_tty() -> bool:
    """Check if stdout is a terminal (for Rich Markdown vs raw output)."""
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


# ---------------------------------------------------------------------------
# Braille spinner with elapsed time
# ---------------------------------------------------------------------------


class BrailleSpinner:
    """Custom spinner renderable with braille animation and elapsed time."""

    def __init__(self, glyphs: Glyphs, theme: Theme) -> None:
        self._frames = glyphs.spinner_frames
        self._pos = 0
        self._start = time.monotonic()
        self._theme = theme
        self._status = "Thinking"

    def update_status(self, status: str) -> None:
        self._status = status

    def __rich__(self) -> Text:
        frame = self._frames[self._pos % len(self._frames)]
        self._pos += 1
        elapsed = int(time.monotonic() - self._start)
        return Text.from_markup(
            f"[bold {self._theme.accent}]{frame} {self._status}"
            f"\u2026[/bold {self._theme.accent}] "
            f"[{self._theme.muted}]({elapsed}s)[/{self._theme.muted}]"
        )


# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------


async def _stream_text_rich(request_stream: Any, live: Live) -> str:
    """Stream text into an existing Live context (spinner → Markdown)."""
    install_prettier_code_blocks()
    live.update(Markdown(""))
    text = ""
    async for cumulative in request_stream.stream_text():
        text = cumulative
        live.update(Markdown(text))
    live.stop()
    return text


async def _stream_text_rich_new(request_stream: Any) -> str:
    """Stream text via a fresh Live context (after tool calls stopped it)."""
    install_prettier_code_blocks()
    text = ""
    with Live(
        Markdown(""),
        console=console,
        vertical_overflow="visible",
        refresh_per_second=10,
    ) as live:
        async for cumulative in request_stream.stream_text():
            text = cumulative
            live.update(Markdown(text))
    return text


async def _stream_text_pipe(request_stream: Any) -> str:
    """Stream text to stdout in non-TTY (piped) mode."""
    previous = ""
    text = ""
    async for cumulative in request_stream.stream_text():
        delta = cumulative[len(previous) :]
        if delta:
            sys.stdout.write(delta)
            sys.stdout.flush()
        previous = cumulative
        text = cumulative
    return text


async def _stream_model_request(node: Any, ctx: Any) -> str:
    """Stream text from a ModelRequestNode using node.stream() + stream_text().

    When stdout is a TTY, renders output as Rich Markdown using ``Live``.
    When piped, writes raw text to stdout.

    Uses a single ``Live`` context that starts as a spinner and seamlessly
    transitions to Markdown rendering when text begins — no visual gap.

    Returns:
        The full response text from this model request.
    """
    use_rich = _is_tty()
    theme = get_theme()
    glyphs = get_glyphs()

    # Single Live context — starts as spinner, transitions to Markdown
    live: Live | None = None
    if use_rich:
        live = Live(
            BrailleSpinner(glyphs, theme),
            console=console,
            refresh_per_second=10,
            vertical_overflow="visible",
        )
        live.start()

    def _stop_live() -> None:
        nonlocal live
        if live is not None:
            live.stop()
            live = None

    async with node.stream(ctx) as request_stream:
        final_result_found = False

        # Event phase: spinner is visible, waiting for FinalResultEvent
        async for event in request_stream:
            if isinstance(event, PartStartEvent):
                if hasattr(event.part, "tool_name"):
                    _stop_live()
            elif isinstance(event, PartDeltaEvent):
                if isinstance(event.delta, TextPartDelta) and not use_rich:
                    _stop_live()
                    sys.stdout.write(event.delta.content_delta)
                    sys.stdout.flush()
            elif isinstance(event, FinalResultEvent):
                final_result_found = True
                break

        # Text streaming phase
        if not final_result_found:
            _stop_live()
            return ""

        if use_rich and live is not None:
            return await _stream_text_rich(request_stream, live)
        if use_rich:
            return await _stream_text_rich_new(request_stream)
        return await _stream_text_pipe(request_stream)


def _parse_tool_args(raw_args: Any) -> dict[str, Any]:
    """Parse tool call args, handling both dict and JSON string formats."""
    if isinstance(raw_args, dict):
        return raw_args
    if isinstance(raw_args, str) and raw_args:
        import json

        with contextlib.suppress(json.JSONDecodeError, ValueError):
            parsed = json.loads(raw_args)
            if isinstance(parsed, dict):
                return parsed
    return {}


async def _stream_tool_calls(node: Any, ctx: Any) -> None:
    """Stream tool-call results from a CallToolsNode."""
    from cli.diff_display import render_inline_change
    from cli.tool_display import render_tool_call_error, render_tool_call_success

    # Track pending calls for elapsed time
    pending: dict[str, tuple[dict[str, Any], float]] = {}

    async with node.stream(ctx) as handle_stream:
        async for event in handle_stream:
            if isinstance(event, FunctionToolCallEvent):
                tool_name = event.part.tool_name
                if tool_name in _TODO_TOOLS:
                    continue
                args = _parse_tool_args(event.part.args)
                console.print(render_tool_call(tool_name, args))
                pending[tool_name] = (args, time.monotonic())
            elif isinstance(event, FunctionToolResultEvent):
                tool_name = getattr(event.result, "tool_name", "unknown")
                if tool_name in _TODO_TOOLS:
                    continue
                # Calculate elapsed
                elapsed = None
                args: dict[str, Any] = {}
                if tool_name in pending:
                    args, start = pending.pop(tool_name)
                    elapsed = time.monotonic() - start
                # Detect error
                raw = str(event.result.content)
                is_error = (
                    "error" in raw.lower()[:100]
                    or "exit code 1" in raw.lower()
                    or "traceback" in raw.lower()[:200]
                )
                # Show status transition
                if is_error:
                    console.print(render_tool_call_error(tool_name, args))
                else:
                    console.print(render_tool_call_success(tool_name, args, elapsed))
                    # Inline diff/preview for file-modifying tools
                    change_preview = render_inline_change(tool_name, args)
                    if change_preview:
                        console.print(change_preview)
                console.print(render_tool_result(tool_name, event.result.content, error=is_error))


async def _process_stream(
    agent: Agent[DeepAgentDeps, str],
    user_input: str | list[Any],
    deps: DeepAgentDeps,
    message_history: list[ModelMessage],
) -> list[ModelMessage]:
    """Run the agent using ``agent.iter()`` and stream output to the terminal.

    Args:
        user_input: Plain text string **or** multimodal list
            (``[text, BinaryContent, ...]``).

    Returns:
        Updated message history.
    """
    theme = get_theme()
    glyphs = get_glyphs()

    spinner_obj = BrailleSpinner(glyphs, theme)
    spinner_live = Live(
        spinner_obj,
        console=console,
        refresh_per_second=10,
        transient=True,
    )
    spinner_active = False
    if _is_tty():
        spinner_live.start()
        spinner_active = True

    async with agent.iter(
        user_input,
        deps=deps,
        message_history=message_history,
    ) as run:
        async for node in run:
            if isinstance(node, UserPromptNode):
                pass
            elif Agent.is_model_request_node(node):
                if spinner_active:
                    spinner_live.stop()
                    spinner_active = False
                console.print()
                await _stream_model_request(node, run.ctx)
            elif Agent.is_call_tools_node(node):
                if spinner_active:
                    spinner_obj.update_status("Running tools")
                await _stream_tool_calls(node, run.ctx)
                if _is_tty() and not spinner_active:
                    spinner_obj = BrailleSpinner(glyphs, theme)
                    spinner_live = Live(
                        spinner_obj,
                        console=console,
                        refresh_per_second=10,
                        transient=True,
                    )
                    spinner_live.start()
                    spinner_active = True
            elif isinstance(node, End):
                pass

        result = run.result

    if spinner_active:
        spinner_live.stop()

    console.print()
    if result is None:
        return list(message_history)
    return result.all_messages()


def _cmd_save(arg: str, history: list[ModelMessage]) -> list[ModelMessage]:
    """Handle /save command — sessions auto-save every turn via middleware."""
    theme = get_theme()
    console.print(f"[{theme.muted}]Sessions are auto-saved after each turn.[/{theme.muted}]")
    console.print(f"[{theme.muted}]Messages in current session: {len(history)}[/{theme.muted}]")
    return history


async def _cmd_load(arg: str, history: list[ModelMessage]) -> list[ModelMessage]:
    """Handle /load command — show session picker or load by ID."""
    loaded = await _load_thread(arg)  # empty string -> picker
    if loaded:
        history = loaded
        _display_loaded_session(history)
    return history


def _cmd_version() -> None:
    """Handle /version command."""
    from pydantic_deep import __version__

    theme = get_theme()
    console.print(f"[{theme.primary}]pydantic-deep[/{theme.primary}] v{__version__}")


def _cmd_bug() -> None:
    """Handle /bug command — open GitHub issues."""
    import webbrowser

    theme = get_theme()
    url = "https://github.com/vstorm-co/pydantic-deep/issues"
    console.print(f"[{theme.muted}]Opening: {url}[/{theme.muted}]")
    try:
        webbrowser.open(url)
    except Exception:  # pragma: no cover
        console.print(f"[{theme.muted}]Open manually: {url}[/{theme.muted}]")


def _cmd_copy(history: list[ModelMessage]) -> None:
    """Handle /copy command — copy last AI response to clipboard."""
    import subprocess

    theme = get_theme()

    # Find last text response
    for msg in reversed(history):
        if getattr(msg, "kind", None) != "response":
            continue
        for part in getattr(msg, "parts", []):
            if getattr(part, "part_kind", "") == "text":
                content = getattr(part, "content", "")
                if not isinstance(content, str) or not content.strip():
                    continue
                # Try pbcopy (macOS) then xclip (Linux)
                for cmd in (["pbcopy"], ["xclip", "-selection", "clipboard"]):
                    try:
                        proc = subprocess.run(cmd, input=content, text=True, timeout=5)
                        if proc.returncode == 0:
                            lines = content.strip().count("\n") + 1
                            console.print(
                                f"[{theme.success}]Copied to clipboard "
                                f"({lines} lines).[/{theme.success}]"
                            )
                            return
                    except (FileNotFoundError, subprocess.TimeoutExpired):
                        continue
                console.print(f"[{theme.error}]Clipboard not available.[/{theme.error}]")
                return

    console.print(f"[{theme.muted}]No response to copy.[/{theme.muted}]")


def _cmd_undo(history: list[ModelMessage]) -> list[ModelMessage]:
    """Handle /undo command — remove the last user+AI turn from history."""
    theme = get_theme()
    if len(history) < 2:
        console.print(f"[{theme.muted}]Nothing to undo.[/{theme.muted}]")
        return history

    # Remove the last response and the last request
    # Messages alternate: request, response, request, response, ...
    removed = 0
    while history and removed < 2:
        msg = history[-1]
        kind = getattr(msg, "kind", None)
        history = history[:-1]
        if kind in ("request", "response"):
            removed += 1

    console.print(f"[{theme.muted}]Undone last turn. Messages: {len(history)}[/{theme.muted}]")
    return history


def _cmd_diff() -> None:
    """Handle /diff command — show git diff of uncommitted changes."""
    import subprocess

    theme = get_theme()
    try:
        result = subprocess.run(
            ["git", "diff", "--stat"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            console.print(f"[{theme.muted}]Not in a git repository.[/{theme.muted}]")
            return

        if not result.stdout.strip():
            console.print(f"[{theme.muted}]No uncommitted changes.[/{theme.muted}]")
            return

        console.print(f"\n[bold {theme.primary}]Uncommitted changes:[/bold {theme.primary}]")
        for line in result.stdout.strip().splitlines():
            if "|" in line:
                parts = line.split("|", 1)
                filename = parts[0].strip()
                stats = parts[1].strip()
                console.print(f"  [{theme.accent}]{filename}[/{theme.accent}]  {stats}")
            else:
                console.print(f"  {line}")

        # Show full diff summary
        full = subprocess.run(
            ["git", "diff", "--shortstat"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if full.stdout.strip():
            console.print(f"\n  [{theme.muted}]{full.stdout.strip()}[/{theme.muted}]")
        console.print()

    except (FileNotFoundError, subprocess.TimeoutExpired):
        console.print(f"[{theme.muted}]git not available.[/{theme.muted}]")


async def _cmd_remember(arg: str, deps: DeepAgentDeps) -> None:
    """Handle /remember command — append text to persistent memory."""
    theme = get_theme()

    if not arg:
        # Show current memory content
        memory_path = Path.cwd() / ".pydantic-deep" / "main" / "MEMORY.md"
        if memory_path.exists():
            content = memory_path.read_text()
            lines = content.strip().splitlines()
            header = f"[bold {theme.primary}]Memory[/bold {theme.primary}]"
            console.print(f"\n{header} ({len(lines)} lines)")
            for line in lines[:20]:
                console.print(f"  [{theme.muted}]{line}[/{theme.muted}]")
            if len(lines) > 20:
                glyphs = get_glyphs()
                extra = len(lines) - 20
                msg = f"{glyphs.ellipsis} ({extra} more lines)"
                console.print(f"  [{theme.muted}]{msg}[/{theme.muted}]")
            console.print()
        else:
            console.print(f"[{theme.muted}]No memory file found.[/{theme.muted}]")
        return

    # Append to memory
    memory_path = Path.cwd() / ".pydantic-deep" / "main" / "MEMORY.md"
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    with open(memory_path, "a") as f:
        f.write(f"\n- {arg}\n")
    console.print(f"[{theme.success}]Saved to memory.[/{theme.success}]")


_COMMAND_DESCRIPTIONS: dict[str, str] = {
    "/help": "Show all commands and shortcuts",
    "/clear": "Clear conversation history",
    "/compact": "Trim history to last 10 messages",
    "/undo": "Remove last turn from history",
    "/copy": "Copy last response to clipboard",
    "/todos": "Show current TODO list",
    "/cost": "Show accumulated cost",
    "/tokens": "Show message/token stats",
    "/model": "Switch model or show picker",
    "/save": "Session auto-save info",
    "/load": "Browse & resume a previous session",
    "/remember": "View or save to persistent memory",
    "/skills": "List available skills",
    "/diff": "Show git diff of uncommitted changes",
    "/version": "Show version",
    "/bug": "Report a bug (opens GitHub)",
    "/quit": "Exit the chat",
    "/exit": "Exit the chat",
}


def _get_custom_command_descriptions() -> dict[str, str]:
    """Build description map for discovered custom commands."""
    from cli.commands import discover_commands

    return {f"/{cmd.name}": cmd.description for cmd in discover_commands()}


def _command_picker(subset: list[str] | None = None) -> str | None:
    """Show interactive arrow-key picker for slash commands.

    Args:
        subset: If given, only show these commands. Otherwise show all.

    Returns:
        The selected command string, or None if cancelled.
    """
    from cli.picker import PickerItem, interactive_select

    commands = subset if subset else _get_all_slash_commands()
    # Don't show /exit (duplicate of /quit)
    commands = [c for c in commands if c != "/exit"]

    # Merge built-in and custom command descriptions
    all_descriptions = {**_COMMAND_DESCRIPTIONS, **_get_custom_command_descriptions()}

    items = [
        PickerItem(
            label=cmd,
            value=cmd,
            description=all_descriptions.get(cmd, ""),
        )
        for cmd in commands
    ]

    selected = interactive_select(
        items,
        title="Commands",
        empty_message="No matching commands.",
        console=console,
    )

    if selected is None:
        return None
    return selected.value


def _file_picker(working_dir: str | None = None) -> str | None:
    """Show interactive file picker for @ mentions.

    Scans the working directory for files (excluding hidden dirs, common
    noise like ``__pycache__``, ``.git``, ``node_modules``, etc.) and
    presents an arrow-key navigable list.

    Returns:
        Relative file path, or None if cancelled.
    """
    from cli.picker import PickerItem, interactive_select

    root = Path(working_dir) if working_dir else Path.cwd()

    # Collect files, skipping noise
    _SKIP_DIRS = {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        "dist",
        "build",
        ".egg-info",
        ".eggs",
        "htmlcov",
    }

    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune hidden and noisy directories
        dirnames[:] = [
            d
            for d in dirnames
            if not d.startswith(".") and d not in _SKIP_DIRS and not d.endswith(".egg-info")
        ]
        dirnames.sort()

        rel_dir = os.path.relpath(dirpath, root)
        for fname in sorted(filenames):
            if fname.startswith("."):
                continue
            rel_path = fname if rel_dir == "." else os.path.join(rel_dir, fname)
            files.append(rel_path)

        # Limit to avoid overwhelming the picker
        if len(files) > 200:
            break

    if not files:
        theme = get_theme()
        console.print(f"[{theme.muted}]No files found.[/{theme.muted}]")
        return None

    items = [PickerItem(label=f, value=f, description="") for f in files]

    sys.stdout.write("\n")
    sys.stdout.flush()

    selected = interactive_select(
        items,
        title="Select File",
        empty_message="No files found.",
        console=console,
        max_visible=15,
    )

    if selected is None:
        return None
    return selected.value


def _cmd_model_picker(
    current_model: str | None,
    on_change: Any | None,
) -> None:
    """Show interactive model picker."""
    from cli.picker import PickerItem, interactive_select

    theme = get_theme()

    # Build model list from known providers
    items: list[PickerItem] = []
    popular_models = [
        ("openrouter:openai/gpt-4.1", "OpenAI GPT-4.1 via OpenRouter"),
        ("openrouter:anthropic/claude-sonnet-4", "Anthropic Claude Sonnet 4"),
        ("openrouter:anthropic/claude-opus-4", "Anthropic Claude Opus 4"),
        ("openrouter:google/gemini-2.5-pro", "Google Gemini 2.5 Pro"),
        ("openai:gpt-4.1", "OpenAI GPT-4.1 (direct)"),
        ("anthropic:claude-sonnet-4-5", "Anthropic Claude Sonnet 4.5 (direct)"),
        ("google:gemini-2.5-pro", "Google Gemini 2.5 Pro (direct)"),
    ]

    for model_id, desc in popular_models:
        marker = " [current]" if model_id == current_model else ""
        items.append(PickerItem(label=f"{model_id}{marker}", value=model_id, description=desc))

    selected = interactive_select(
        items,
        title="Select Model",
        empty_message="No models available.",
        console=console,
    )

    if selected is None:
        return

    if on_change:
        on_change(selected.value)
    console.print(f"[{theme.muted}]Model changed to: {selected.value}[/{theme.muted}]")


def _run_bash_command(command: str) -> None:
    """Execute a shell command directly and display output."""
    import subprocess

    theme = get_theme()
    glyphs = get_glyphs()

    console.print(
        f"[bold {theme.warning}]{glyphs.tool_prefix} "
        f"execute({_truncate(command, 100)})[/bold {theme.warning}]"
    )

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.stdout:
            for line in result.stdout.splitlines()[:30]:
                console.print(f"[{theme.muted}]{glyphs.output_prefix} {line}[/{theme.muted}]")
            total_lines = result.stdout.count("\n") + 1
            if total_lines > 30:
                console.print(
                    f"[{theme.muted}]  {glyphs.ellipsis} "
                    f"({total_lines - 30} more lines)[/{theme.muted}]"
                )
        if result.stderr:
            for line in result.stderr.splitlines()[:10]:
                console.print(f"[{theme.error}]{glyphs.output_prefix} {line}[/{theme.error}]")
        if result.returncode != 0:
            console.print(
                f"[{theme.error}]{glyphs.output_prefix} "
                f"exit code {result.returncode}[/{theme.error}]"
            )
    except subprocess.TimeoutExpired:
        console.print(f"[{theme.error}]Command timed out (60s limit).[/{theme.error}]")
    except Exception as e:
        console.print(f"[{theme.error}]Error: {e}[/{theme.error}]")


def _cmd_help() -> None:
    """Handle /help command."""
    theme = get_theme()
    console.print()
    console.print(f"[bold {theme.primary}]Commands[/bold {theme.primary}]")
    cmds = [
        ("/help", "Show this help message"),
        ("/clear", "Clear conversation history"),
        ("/compact [focus]", "Summarize history (optional focus instruction)"),
        ("/context", "Show context usage breakdown"),
        ("/undo", "Remove last turn from history"),
        ("/copy", "Copy last response to clipboard"),
        ("/todos", "Show current TODO list"),
        ("/cost", "Show accumulated cost"),
        ("/tokens", "Show message/token stats"),
        ("/model [name]", "Show picker or switch model"),
        ("/save", "Session auto-save info"),
        ("/load [id]", "Browse & resume a previous session"),
        ("/remember [text]", "View or save to persistent memory"),
        ("/skills", "List available skills"),
        ("/diff", "Show git diff of uncommitted changes"),
        ("/version", "Show version"),
        ("/bug", "Report a bug (opens GitHub)"),
    ]
    for cmd, desc in cmds:
        console.print(f"  [{theme.muted}]{cmd}[/{theme.muted}]  {desc}")

    # Custom commands
    from cli.commands import discover_commands

    custom = discover_commands()
    if custom:
        console.print()
        console.print(f"[bold {theme.primary}]Custom Commands[/bold {theme.primary}]")
        for c in custom:
            hint = f" {c.argument_hint}" if c.argument_hint else ""
            source = f"[{theme.muted}]({c.source})[/{theme.muted}]"
            console.print(
                f"  [{theme.muted}]/{c.name}{hint}[/{theme.muted}]  {c.description} {source}"
            )

    console.print()
    console.print(f"[bold {theme.primary}]Keyboard Shortcuts[/bold {theme.primary}]")
    shortcuts = [
        ("Ctrl+C", "Interrupt (press twice to quit)"),
        ("Ctrl+D", "Exit immediately"),
        ("Ctrl+V", "Paste image from clipboard"),
        ("Ctrl+L", "Clear screen"),
    ]
    for key, desc in shortcuts:
        console.print(f"  [{theme.muted}]{key}[/{theme.muted}]      {desc}")
    console.print()
    console.print(f"[bold {theme.primary}]Tips[/bold {theme.primary}]")
    console.print(
        f"  [{theme.muted}]@filepath[/{theme.muted}]     Include file contents in your message"
    )
    console.print(
        f"  [{theme.muted}]!command[/{theme.muted}]      "
        f"Run a shell command directly (e.g. !ls -la)"
    )
    console.print(f'  [{theme.muted}]"""..."""[/{theme.muted}]     Multi-line input mode')
    console.print()


def _cmd_cost(cumulative_cost: float | None) -> None:
    """Handle /cost command."""
    if cumulative_cost is not None and cumulative_cost > 0:
        line = format_cost_line(total_cost=cumulative_cost)
        theme = get_theme()
        console.print(line or f"[{theme.muted}]No cost data[/{theme.muted}]")
    else:
        theme = get_theme()
        console.print(f"[{theme.muted}]No cost data yet.[/{theme.muted}]")


async def _cmd_compact(
    history: list[ModelMessage],
    deps: DeepAgentDeps,
    focus: str | None = None,
) -> list[ModelMessage]:
    """Handle /compact [focus] command.

    Uses LLM summarization via ContextManagerMiddleware when available,
    falls back to naive truncation otherwise.
    """
    theme = get_theme()
    glyphs = get_glyphs()
    old_count = len(history)

    ctx_mw = deps.context_middleware
    if ctx_mw is not None and hasattr(ctx_mw, "compact"):
        if old_count <= 2:
            msg = f"History is already compact ({old_count} messages)."
            console.print(f"[{theme.muted}]{msg}[/{theme.muted}]")
            return history

        focus_msg = f' (focus: "{focus}")' if focus else ""
        msg = f"Compacting {old_count} messages{focus_msg}..."
        console.print(f"[{theme.muted}]{msg}[/{theme.muted}]")

        history = await ctx_mw.compact(history, focus=focus)
        new_count = len(history)
        line_char = glyphs.separator
        console.print(
            f"\n[{theme.muted}] {line_char}{line_char}{line_char}[/{theme.muted}] "
            f"[{theme.accent}]{glyphs.success} Compacted: "
            f"{old_count} \u2192 {new_count} messages (LLM summary)[/{theme.accent}] "
            f"[{theme.muted}]{line_char}{line_char}{line_char}[/{theme.muted}]\n"
        )
    else:
        # Fallback: naive truncation
        keep = 10
        if old_count > keep:
            history = history[-keep:]
            line_char = glyphs.separator
            console.print(
                f"\n[{theme.muted}] {line_char}{line_char}{line_char}[/{theme.muted}] "
                f"[{theme.accent}]{glyphs.success} Compacted: "
                f"{old_count} \u2192 {keep} messages[/{theme.accent}] "
                f"[{theme.muted}]{line_char}{line_char}{line_char}[/{theme.muted}]\n"
            )
        else:
            msg = f"History is already compact ({old_count} messages)."
            console.print(f"[{theme.muted}]{msg}[/{theme.muted}]")
    return history


async def _cmd_context(deps: DeepAgentDeps, history: list[ModelMessage]) -> None:
    """Handle /context command — show context usage breakdown."""
    theme = get_theme()
    ctx_mw = deps.context_middleware

    console.print()
    console.print(f"[bold {theme.primary}]Context Usage[/bold {theme.primary}]")

    if ctx_mw is not None:
        max_tokens = getattr(ctx_mw, "max_tokens", 0)
        token_counter = getattr(ctx_mw, "token_counter", None)
        compress_threshold = getattr(ctx_mw, "compress_threshold", 0.9)
        compression_count = getattr(ctx_mw, "_compression_count", 0)

        if token_counter and history:
            import inspect as _inspect

            result = token_counter(history)
            current_tokens = await result if _inspect.isawaitable(result) else result
        else:
            current_tokens = 0
        pct = current_tokens / max_tokens if max_tokens > 0 else 0.0
        threshold_tokens = int(max_tokens * compress_threshold)

        # Usage bar
        bar_width = 30
        filled = int(bar_width * pct)
        filled_bar = f"[{theme.accent}]{'█' * filled}[/{theme.accent}]"
        empty_bar = f"[{theme.muted}]{'░' * (bar_width - filled)}[/{theme.muted}]"
        bar = f"{filled_bar}{empty_bar}"

        console.print(f"  {bar}  {pct:.0%}")
        tok_label = f"[{theme.muted}]Tokens:[/{theme.muted}]"
        console.print(f"  {tok_label}       {current_tokens:,} / {max_tokens:,}")
        thr_label = f"[{theme.muted}]Threshold:[/{theme.muted}]"
        thr_val = f"{compress_threshold:.0%} ({threshold_tokens:,} tokens)"
        console.print(f"  {thr_label}    {thr_val}")
        console.print(f"  [{theme.muted}]Messages:[/{theme.muted}]     {len(history)}")
        console.print(f"  [{theme.muted}]Compressions:[/{theme.muted}] {compression_count}")

        messages_path = getattr(ctx_mw, "messages_path", None)
        if messages_path:
            from pathlib import Path as _P

            p = _P(messages_path)
            if p.exists():
                size_kb = p.stat().st_size / 1024
                hf_label = f"[{theme.muted}]History file:[/{theme.muted}]"
                console.print(f"  {hf_label}  {messages_path} ({size_kb:.1f} KB)")
            else:
                hf_label = f"[{theme.muted}]History file:[/{theme.muted}]"
                console.print(f"  {hf_label}  {messages_path} (not yet created)")
    else:
        console.print(f"  [{theme.muted}]Context manager not available.[/{theme.muted}]")
        console.print(f"  [{theme.muted}]Messages:[/{theme.muted}] {len(history)}")

    console.print()


def _cmd_model(
    arg: str,
    current_model: str | None,
    on_change: Any | None,
) -> None:
    """Handle /model command."""
    theme = get_theme()
    if arg:
        if on_change:
            on_change(arg)
        console.print(f"[{theme.muted}]Model changed to: {arg}[/{theme.muted}]")
    else:
        console.print(f"[{theme.muted}]Current model: {current_model or 'default'}[/{theme.muted}]")


def _cmd_tokens(history: list[ModelMessage]) -> None:
    """Handle /tokens command."""
    theme = get_theme()
    count = sum(len(str(getattr(m, "parts", ""))) for m in history)
    console.print(
        f"[{theme.muted}]Messages: {len(history)}, ~{count} chars in history[/{theme.muted}]"
    )


def _cmd_skills() -> None:
    """Handle /skills command."""
    theme = get_theme()
    from cli.main import _discover_all_skills

    skills = _discover_all_skills()
    if not skills:
        console.print(f"[{theme.muted}]No skills available.[/{theme.muted}]")
    else:
        for s in skills:
            source_tag = f"[{theme.muted}]({s['source']})[/{theme.muted}]"
            console.print(f"  {s['name']}: {s['description']} {source_tag}")


async def _handle_command(  # noqa: C901
    cmd: str,
    deps: DeepAgentDeps,
    history: list[ModelMessage],
    *,
    cumulative_cost: float | None = None,
    current_model: str | None = None,
    on_model_change: Any | None = None,
) -> tuple[bool, list[ModelMessage]]:
    """Handle slash commands.

    Returns:
        Tuple of (should_break, updated_history).
    """
    parts = cmd.strip().split(maxsplit=1)
    cmd_name = parts[0].lower()
    cmd_arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd_name in ("/quit", "/exit"):
        theme = get_theme()
        console.print(f"\n[{theme.muted}]Goodbye![/{theme.muted}]")
        return True, history

    if cmd_name == "/clear":
        theme = get_theme()
        history = []
        deps.todos = []
        console.print(f"[{theme.muted}]Conversation cleared.[/{theme.muted}]\n")
        return False, history

    if cmd_name == "/todos":
        _print_todos(deps)
    elif cmd_name == "/cost":
        _cmd_cost(cumulative_cost)
    elif cmd_name == "/compact":
        history = await _cmd_compact(history, deps, focus=cmd_arg or None)
    elif cmd_name == "/context":
        await _cmd_context(deps, history)
    elif cmd_name == "/model":
        if cmd_arg:
            _cmd_model(cmd_arg, current_model, on_model_change)
        else:
            _cmd_model_picker(current_model, on_model_change)
    elif cmd_name == "/tokens":
        _cmd_tokens(history)
    elif cmd_name == "/save":
        history = _cmd_save(cmd_arg, history)
    elif cmd_name == "/load":
        history = await _cmd_load(cmd_arg, history)
    elif cmd_name == "/skills":
        _cmd_skills()
    elif cmd_name == "/undo":
        history = _cmd_undo(history)
    elif cmd_name == "/diff":
        _cmd_diff()
    elif cmd_name == "/remember":
        await _cmd_remember(cmd_arg, deps)
    elif cmd_name == "/version":
        _cmd_version()
    elif cmd_name == "/bug":
        _cmd_bug()
    elif cmd_name == "/copy":
        _cmd_copy(history)
    elif cmd_name == "/help":
        _cmd_help()
    else:
        theme = get_theme()
        # Show interactive picker for "/" or partial matches
        all_cmds = _get_all_slash_commands()
        matches = [c for c in all_cmds if c.startswith(cmd_name)]
        if cmd_name == "/" or matches:
            picked = _command_picker(matches if matches else None)
            if picked:
                # Recurse to execute the picked command
                return await _handle_command(
                    picked,
                    deps,
                    history,
                    cumulative_cost=cumulative_cost,
                    current_model=current_model,
                    on_model_change=on_model_change,
                )
        else:
            console.print(
                f"[{theme.muted}]Unknown command: {cmd_name}. "
                f"Type / for command list.[/{theme.muted}]"
            )

    return False, history


def _create_agent_with_retry(
    model: str | None = None,
    **kwargs: Any,
) -> tuple[Any, DeepAgentDeps] | tuple[None, None]:
    """Try to create the CLI agent, prompting for a model if it fails.

    Returns (agent, deps) on success, or (None, None) if the user quits.
    """
    effective_model = model
    while True:
        try:
            agent, deps = create_cli_agent(model=effective_model, **kwargs)
            return agent, deps
        except Exception as e:
            _print_model_error(e)
            theme = get_theme()
            console.print(
                f"\n[{theme.muted}]Enter a model "
                f"(e.g. openrouter:openai/gpt-4.1) or 'q' to quit:[/{theme.muted}]"
            )
            try:
                choice = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                return None, None
            if choice.lower() in ("q", "quit", "exit", ""):
                return None, None
            effective_model = choice


def _create_sandbox_backend(runtime: str) -> Any | None:
    """Create a Docker sandbox backend, or None if unavailable."""
    try:
        from pydantic_ai_backends import DockerSandbox
    except ImportError:
        print_error(
            console,
            "Docker support not installed.",
            hint="Run: pip install pydantic-deep[sandbox]",
        )
        return None
    return DockerSandbox(runtime=runtime)


def _stop_sandbox(sandbox: Any) -> None:
    """Safely stop a sandbox instance."""
    try:
        sandbox.stop()
    except Exception as e:
        print_warning(console, f"Sandbox cleanup failed: {e}")


def _read_raw_key() -> str:
    """Read a single keypress in raw mode, returning a key name or character."""
    import select as _sel
    import termios

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        new = termios.tcgetattr(fd)
        new[3] = new[3] & ~(termios.ICANON | termios.ECHO)
        new[6][termios.VMIN] = 1
        new[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSADRAIN, new)

        ch = os.read(fd, 1).decode("utf-8", errors="replace")
        if ch == "\x1b":
            if _sel.select([fd], [], [], 0.05)[0]:
                ch2 = os.read(fd, 1).decode("utf-8", errors="replace")
                if ch2 == "[":
                    ch3 = os.read(fd, 1).decode("utf-8", errors="replace")
                    return {"A": "up", "B": "down", "C": "right", "D": "left"}.get(ch3, "unknown")
                return "unknown"
            return "escape"
        if ch in ("\r", "\n"):
            return "enter"
        if ch in ("\x7f", "\x08"):
            return "backspace"
        if ch == "\x03":
            return "interrupt"
        if ch == "\x04":
            return "eof"
        if ch == "\x16":
            return "paste"
        if ch == "\x01":
            return "home"  # Ctrl+A
        if ch == "\x05":
            return "end"  # Ctrl+E
        if ch == "\x15":
            return "clear_line"  # Ctrl+U
        if ch == "\x17":
            return "del_word"  # Ctrl+W
        if ch == "\x0c":
            return "clear_screen"  # Ctrl+L
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _raw_line_edit() -> str:  # noqa: C901
    """Raw line editor with instant ``/`` and ``@`` triggers.

    Reads keystrokes one by one in raw mode, providing:
    - ``/`` as first character → instant command picker
    - ``@`` anywhere → instant file picker (result inserted inline)
    - Ctrl+V → clipboard image paste
    - Up/Down → readline history navigation
    - Backspace, Ctrl+U (clear line), Ctrl+W (delete word)
    - Enter to submit, Ctrl+C to interrupt, Ctrl+D to EOF

    Returns:
        The user's input line.
    """
    buf = ""
    history_len = readline.get_current_history_length()
    history_pos = history_len + 1  # past the end = current input
    saved_buf = ""  # saved current input when navigating history

    def _redraw() -> None:
        """Redraw the prompt and buffer."""
        sys.stdout.write(f"\r\x1b[K{_USER_PROMPT}{buf}")
        sys.stdout.flush()

    sys.stdout.write(_USER_PROMPT)
    sys.stdout.flush()

    while True:
        key = _read_raw_key()

        # --- "/" as first character → command picker ---
        if key == "/" and not buf:
            sys.stdout.write("/\n")
            sys.stdout.flush()
            picked = _command_picker()
            return picked or ""

        # --- "@" anywhere → file picker ---
        if key == "@":
            sys.stdout.write("@")
            sys.stdout.flush()
            picked_file = _file_picker()
            if picked_file:
                mention = f"@{picked_file} "
                buf += mention
                _redraw()
            else:
                # Cancelled — just continue without @
                _redraw()
            continue

        # --- Ctrl+V → clipboard image paste ---
        if key == "paste":
            from cli.clipboard import get_clipboard_image

            theme = get_theme()
            image = get_clipboard_image()
            if image:
                _pending_images.append(image)
                n = len(_pending_images)
                tag = f"[image {n}]"
                buf += tag
                size_kb = len(image.data) / 1024
                # Show tag inline + confirmation below
                sys.stdout.write("\n")
                console.print(
                    f"[{theme.accent}]  \u2022 Image pasted from clipboard "
                    f"({size_kb:.0f} KB)[/{theme.accent}]"
                )
                _redraw()
            else:
                sys.stdout.write("\n")
                console.print(f"[{theme.muted}]  No image in clipboard.[/{theme.muted}]")
                _redraw()
            continue

        # --- Enter → submit ---
        if key == "enter":
            sys.stdout.write("\n")
            sys.stdout.flush()
            if buf.strip():
                readline.add_history(buf)
            return buf

        # --- Ctrl+C → interrupt ---
        if key == "interrupt":
            sys.stdout.write("\n")
            sys.stdout.flush()
            raise KeyboardInterrupt

        # --- Ctrl+D → EOF (only on empty line) ---
        if key == "eof":
            if not buf:
                sys.stdout.write("\n")
                sys.stdout.flush()
                raise EOFError
            continue

        # --- Backspace ---
        if key == "backspace":
            if buf:
                buf = buf[:-1]
                _redraw()
            continue

        # --- Ctrl+U → clear entire line ---
        if key == "clear_line":
            buf = ""
            _redraw()
            continue

        # --- Ctrl+W → delete last word ---
        if key == "del_word":
            stripped = buf.rstrip()
            last_space = stripped.rfind(" ")
            buf = stripped[: last_space + 1] if last_space >= 0 else ""
            _redraw()
            continue

        # --- Ctrl+L → clear screen and redraw ---
        if key == "clear_screen":
            sys.stdout.write("\x1b[2J\x1b[H")
            _redraw()
            continue

        # --- Up arrow → previous history ---
        if key == "up":
            if history_pos > 1:
                if history_pos == history_len + 1:
                    saved_buf = buf
                history_pos -= 1
                buf = readline.get_history_item(history_pos) or ""
                _redraw()
            continue

        # --- Down arrow → next history ---
        if key == "down":
            if history_pos <= history_len:
                history_pos += 1
                if history_pos == history_len + 1:
                    buf = saved_buf
                else:
                    buf = readline.get_history_item(history_pos) or ""
                _redraw()
            continue

        # --- Printable character ---
        if len(key) == 1 and key.isprintable():
            buf += key
            sys.stdout.write(key)
            sys.stdout.flush()
            continue


def _read_user_input() -> str:
    """Read user input with instant triggers, multiline, and paste detection.

    Features:
    - ``/`` as first char → instant command picker (no Enter needed).
    - ``@`` anywhere → instant file picker with fuzzy search.
    - Ctrl+V → clipboard image paste.
    - Up/Down → history navigation.
    - ``\"\"\"…\"\"\"`` for explicit multiline mode.
    - Multi-line paste detection (non-TTY falls back to ``input()``).
    """
    # TTY mode: use custom raw line editor for instant triggers
    # Non-TTY fallback (tests, pipes) — standard input()
    first_line = _raw_line_edit().strip() if sys.stdin.isatty() else input(_USER_PROMPT).strip()

    # Handle Ctrl+V image paste markers
    first_line = _process_paste_markers(first_line)

    # Explicit multiline mode
    if first_line.startswith('"""'):
        theme = get_theme()
        lines = [first_line.removeprefix('"""')]
        console.print(f'[{theme.muted}]  ... (multiline mode, close with """)[/{theme.muted}]')
        while True:
            try:
                line = input("  ... ")
            except EOFError:
                break
            line = _process_paste_markers(line)
            if line.strip().endswith('"""'):
                lines.append(line.rstrip().removesuffix('"""'))
                break
            lines.append(line)
        return "\n".join(lines).strip()

    # Skip paste detection for commands and bang-commands
    if first_line.startswith("/") or first_line.startswith("!"):
        return first_line

    # Paste detection: consume any remaining lines sitting in stdin buffer
    extra_lines = _drain_paste_buffer()
    if extra_lines:
        all_lines = [first_line, *extra_lines]
        full_text = "\n".join(all_lines)
        _collapse_pasted_display(all_lines)
        return full_text

    # Single long line (e.g. pasted JSON blob)
    if len(first_line) > 300:
        _collapse_long_line(first_line)

    return first_line


def _process_paste_markers(text: str) -> str:
    """Detect Ctrl+V paste markers and grab clipboard images."""
    if _PASTE_MARKER not in text:
        return text

    from cli.clipboard import get_clipboard_image

    theme = get_theme()
    image = get_clipboard_image()
    if image:
        _pending_images.append(image)
        n = len(_pending_images)
        text = text.replace(_PASTE_MARKER, f"[image {n}]")
        size_kb = len(image.data) / 1024
        console.print(
            f"[{theme.accent}]  \u2022 Image pasted from clipboard "
            f"({size_kb:.0f} KB)[/{theme.accent}]"
        )
    else:
        text = text.replace(_PASTE_MARKER, "")
        console.print(f"[{theme.muted}]  No image in clipboard.[/{theme.muted}]")

    return text


def _drain_paste_buffer() -> list[str]:
    """Consume any lines sitting in stdin from a multi-line paste.

    After ``input()`` returns, pasted text beyond the first newline is
    queued in the OS stdin buffer.  We sleep briefly to let the full paste
    arrive, then do a **non-blocking** ``os.read`` to grab everything at
    once.  Using ``os.read`` instead of ``sys.stdin.readline`` prevents
    blocking on partial data (e.g. terminal escape sequences without a
    trailing newline).
    """
    import os as _os
    import select as _sel

    lines: list[str] = []
    try:
        fd = sys.stdin.fileno()
        # Brief pause so the full paste lands in the kernel buffer
        time.sleep(0.03)
        # Non-blocking check — timeout=0 means instant
        if not _sel.select([fd], [], [], 0)[0]:
            return lines
        # Read all available bytes at once
        data = b""
        while _sel.select([fd], [], [], 0)[0]:
            chunk = _os.read(fd, 65536)
            if not chunk:
                break
            data += chunk
        if data:
            text = data.decode("utf-8", errors="replace")
            for raw_line in text.splitlines():
                cleaned = _process_paste_markers(raw_line)
                lines.append(cleaned)
    except (OSError, ValueError):
        pass
    return lines


def _terminal_rows(lines: list[str], prompt_width: int = 2) -> int:
    """Estimate how many terminal rows *lines* occupied on screen."""
    import shutil

    cols = shutil.get_terminal_size().columns or 80
    rows = 0
    for i, line in enumerate(lines):
        w = len(line) + (prompt_width if i == 0 else 0)
        rows += max(1, -(-w // cols))  # ceiling division
    return rows


def _erase_rows(n: int) -> None:
    """Move cursor up *n* rows and clear to end of screen."""
    if n > 0:
        sys.stdout.write(f"\x1b[{n}A\x1b[J")
        sys.stdout.flush()


def _collapse_pasted_display(lines: list[str]) -> None:
    """Erase the raw pasted text and print a compact indicator."""
    global _paste_text_counter
    _paste_text_counter += 1

    theme = get_theme()
    rows = _terminal_rows(lines)
    _erase_rows(rows)

    first = lines[0][:60]
    if len(lines[0]) > 60:
        glyphs = get_glyphs()
        first += glyphs.ellipsis
    extra = len(lines) - 1

    from rich.markup import escape

    console.print(
        f"[bold {theme.primary}]> [/bold {theme.primary}]"
        f"{escape(first)}  "
        f"[{theme.muted}]\\[Pasted text #{_paste_text_counter} "
        f"+{extra} lines][/{theme.muted}]"
    )


def _collapse_long_line(text: str) -> None:
    """Erase a long single-line paste and print a compact indicator."""
    global _paste_text_counter
    _paste_text_counter += 1

    theme = get_theme()
    rows = _terminal_rows([text])
    _erase_rows(rows)

    preview = text[:60]
    glyphs = get_glyphs()
    preview += glyphs.ellipsis
    chars = len(text)

    from rich.markup import escape

    console.print(
        f"[bold {theme.primary}]> [/bold {theme.primary}]"
        f"{escape(preview)}  "
        f"[{theme.muted}]\\[Pasted text #{_paste_text_counter} "
        f"+{chars} chars][/{theme.muted}]"
    )


def _extract_option_label(opt: Any) -> str:
    """Extract the display label from an option dict or string.

    LLMs use inconsistent key names, so we try several variants.
    """
    if isinstance(opt, str):
        return opt
    if isinstance(opt, dict):
        # Try common key names in priority order
        for key in ("label", "name", "text", "title", "option", "value"):
            val = opt.get(key)
            if val and isinstance(val, str):
                return val
        # Last resort: join all string values
        vals = [v for v in opt.values() if isinstance(v, str) and v.strip()]
        if vals:
            return vals[0]
    return str(opt)


def _extract_option_description(opt: Any) -> str:
    """Extract description from an option dict."""
    if isinstance(opt, dict):
        for key in ("description", "desc", "detail", "details", "info", "explanation"):
            val = opt.get(key)
            if val and isinstance(val, str):
                return val
    return ""


def _is_option_recommended(opt: Any) -> bool:
    """Check if an option is marked as recommended."""
    if isinstance(opt, dict):
        val = opt.get("recommended", "")
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in ("true", "yes", "1")
    return False


async def _interactive_ask_user(
    question: str,
    options: list[Any],
) -> str:
    """Interactive callback for the plan agent's ``ask_user`` tool.

    Shows the question with an arrow-key picker for the provided options.
    Supports a custom text answer via an "Other" option.

    Args:
        question: The question from the planner.
        options: List of option dicts or strings.

    Returns:
        The selected option label or custom text.
    """
    from cli.picker import PickerItem, interactive_select

    theme = get_theme()

    # Print the question
    console.print(f"\n[bold {theme.primary}]  ? {question}[/bold {theme.primary}]\n")

    # No options → direct text input
    if not options:
        console.print(f"[{theme.muted}]Type your answer:[/{theme.muted}]")
        try:
            custom = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            return ""
        return custom

    # Convert options to PickerItem list, skipping empty/malformed entries
    items: list[PickerItem] = []
    for opt in options:
        # Skip empty dicts, empty strings, None
        if not opt or (isinstance(opt, dict) and not opt):
            continue
        label = _extract_option_label(opt)
        # Skip if label is just a repr of an empty container
        if not label or label in ("{}", "[]", "None", "''", '""'):
            continue
        desc = _extract_option_description(opt)
        recommended = _is_option_recommended(opt)
        display_label = f"{label} (recommended)" if recommended else label
        items.append(PickerItem(label=display_label, value=label, description=desc))

    # If no valid options survived filtering, fall back to text input
    if not items:
        console.print(f"[{theme.muted}]Type your answer:[/{theme.muted}]")
        try:
            custom = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            return ""
        return custom

    # Add "Other" option for custom text
    items.append(
        PickerItem(
            label="Other",
            value="__other__",
            description="Type a custom answer",
        )
    )

    selected = interactive_select(
        items,
        title="Options",
        empty_message="No options provided.",
        console=console,
    )

    if selected is None:
        # Cancelled — return first option
        first = _extract_option_label(options[0]) if options else ""
        return first

    if selected.value == "__other__":
        # Custom text input
        console.print(f"[{theme.muted}]Type your answer:[/{theme.muted}]")
        try:
            custom = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            return _extract_option_label(options[0]) if options else ""
        return custom or (_extract_option_label(options[0]) if options else "")

    return selected.value


def _show_compression_notice(
    old_pct: float,
    new_pct: float,
    cur: int,
    mx: int,
) -> None:
    """Print a notice when context auto-compression occurs."""
    theme = get_theme()
    glyphs = get_glyphs()
    line_char = glyphs.separator

    old_str = f"{old_pct:.0%}"
    new_str = f"{new_pct:.0%}"
    tok_str = f"{format_tokens(cur)}/{format_tokens(mx)}"

    console.print(
        f"\n[{theme.muted}] {line_char}{line_char}{line_char}[/{theme.muted}] "
        f"[{theme.accent}]{glyphs.success} Context compacted: "
        f"{old_str} \u2192 {new_str}[/{theme.accent}] "
        f"[{theme.muted}]({tok_str})[/{theme.muted}] "
        f"[{theme.muted}]{line_char}{line_char}{line_char}[/{theme.muted}]\n"
    )


def _format_status_bar(
    deps: DeepAgentDeps,
    *,
    cost: float | None = None,
    model: str | None = None,
    context_pct: float = 0.0,
    context_current: int = 0,
    context_max: int = 0,
    message_count: int = 0,
    auto_approve: bool = False,
) -> str:
    """Build the status bar string shown before each prompt.

    Returns Rich markup string, or empty string if no data.
    """
    theme = get_theme()
    glyphs = get_glyphs()
    segments: list[str] = []

    # Auto-approve indicator
    if auto_approve or _auto_approve_state["active"]:
        segments.append(f"[bold {theme.success}]auto[/bold {theme.success}]")
    else:
        segments.append(f"[{theme.warning}]manual[/{theme.warning}]")

    # Todos: completed/total
    if deps.todos:
        completed = sum(1 for t in deps.todos if t.status == "completed")
        total = len(deps.todos)
        segments.append(f"[{theme.accent}]{completed}/{total}[/{theme.accent}] todos")

    # Cost
    if cost and cost > 0:
        segments.append(f"[{theme.accent}]${cost:.4f}[/{theme.accent}]")

    # Context: visual progress bar + percentage
    if context_pct > 0:
        bar_width = 10
        filled = int(bar_width * min(context_pct, 1.0))
        empty = bar_width - filled

        if context_pct >= 0.85:
            bar_color = theme.error
        elif context_pct >= 0.60:
            bar_color = theme.warning
        else:
            bar_color = theme.success

        pct_str = f"{context_pct:.0%}" if context_pct >= 0.01 else "<1%"
        bar = (
            f"[{bar_color}]{glyphs.progress_filled * filled}[/{bar_color}]"
            f"[{theme.muted}]{glyphs.progress_empty * empty}[/{theme.muted}]"
        )
        ctx_seg = f"{bar} [{bar_color}]{pct_str}[/{bar_color}]"
        if context_current > 0 and context_max > 0:
            ctx_seg += (
                f" [{theme.muted}]({format_tokens(context_current)}"
                f"/{format_tokens(context_max)})[/{theme.muted}]"
            )
        segments.append(ctx_seg)

    # Message count
    if message_count > 0:
        segments.append(f"[{theme.muted}]{message_count} msgs[/{theme.muted}]")

    # Model name
    if model:
        segments.append(f"[{theme.muted}]{model}[/{theme.muted}]")

    if not segments:
        return ""

    sep = f" [{theme.muted}]{glyphs.bullet}[/{theme.muted}] "
    inner = sep.join(segments)
    line_char = glyphs.separator
    border = f"[{theme.muted}] {line_char}{line_char}{line_char}[/{theme.muted}]"
    return f"{border} {inner} {border}"


async def _chat_loop(  # noqa: C901
    agent: Agent[DeepAgentDeps, str],
    deps: DeepAgentDeps,
    message_history: list[ModelMessage],
    working_dir: str | None,
    *,
    get_cost: Any,
    get_model: Any,
    on_model_change: Any,
    get_context_pct: Any = None,
    get_context_current: Any = None,
    get_context_max: Any = None,
) -> None:
    """Run the main REPL loop for interactive chat."""
    theme = get_theme()
    last_interrupt = 0.0

    while True:
        try:
            # Status bar before prompt
            bar = _format_status_bar(
                deps,
                cost=get_cost(),
                model=get_model(),
                context_pct=get_context_pct() if get_context_pct else 0.0,
                context_current=get_context_current() if get_context_current else 0,
                context_max=get_context_max() if get_context_max else 0,
                message_count=len(message_history),
            )
            if bar:
                console.print()
                console.print(bar)

            user_input = _read_user_input()

            if not user_input:
                continue

            if user_input.startswith("/"):
                # Try custom commands first (they need agent access)
                custom_prompt = _try_custom_command(user_input)
                if custom_prompt is not None:
                    print()
                    message_history[:] = await _process_stream(
                        agent, custom_prompt, deps, message_history
                    )
                    if deps.todos:
                        _print_todos(deps)
                    continue

                should_break, message_history[:] = await _handle_command(
                    user_input,
                    deps,
                    message_history,
                    cumulative_cost=get_cost(),
                    current_model=get_model(),
                    on_model_change=on_model_change,
                )
                if should_break:
                    break
                continue

            if user_input.startswith("!"):
                cmd = user_input[1:].strip()
                if cmd:
                    _run_bash_command(cmd)
                continue

            expanded = _expand_file_mentions(user_input, working_dir)

            # Build multimodal content if images were pasted via Ctrl+V
            prompt: str | list[Any] = expanded
            if _pending_images:
                prompt = [expanded] + [img.to_binary_content() for img in _pending_images]
                _pending_images.clear()

            print()
            message_history[:] = await _process_stream(agent, prompt, deps, message_history)

            if deps.todos:
                _print_todos(deps)

        except KeyboardInterrupt:
            now = time.monotonic()
            if now - last_interrupt < 3.0:
                console.print(f"\n[{theme.muted}]Goodbye![/{theme.muted}]")
                break
            last_interrupt = now
            console.print(
                f"\n[{theme.muted}]Press Ctrl+C again to quit, or Ctrl+D.[/{theme.muted}]\n"
            )
        except EOFError:
            console.print(f"\n[{theme.muted}]Goodbye![/{theme.muted}]")
            break
        except Exception as e:
            import traceback

            console.print(f"\n[{theme.error}]Error: {e}[/{theme.error}]")
            console.print(f"[{theme.muted}]{traceback.format_exc()}[/{theme.muted}]\n")


async def run_interactive(  # noqa: C901
    model: str | None = None,
    working_dir: str | None = None,
    sandbox: bool = False,
    runtime: str = "python-minimal",
    resume: str | None = None,
    auto_approve: bool = False,
    model_settings: dict[str, Any] | None = None,
    fork_session: bool = False,
) -> None:
    """Run the interactive chat loop.

    Args:
        model: Model to use.
        working_dir: Filesystem root directory.
        sandbox: Run in Docker sandbox.
        runtime: Sandbox runtime name.
        resume: Thread ID to resume (prefix match). Empty string means latest.
        auto_approve: Skip HITL approval prompts.
        model_settings: Model settings overrides.
        fork_session: When True with --resume, create a new session ID but
            copy conversation history from the resumed session.
    """
    import uuid

    sandbox_instance: Any = None
    cumulative_cost: float = 0.0
    current_model = model
    context_pct: float = 0.0
    context_current: int = 0
    context_max: int = 0
    prev_context_pct: float = 0.0
    new_session_id = uuid.uuid4().hex[:12]
    session_id = new_session_id  # May be replaced by resumed session's ID

    _setup_readline()

    def _on_model_change(new_model: str) -> None:
        nonlocal current_model
        current_model = new_model

    def _on_cost(cost_info: Any) -> None:
        nonlocal cumulative_cost
        run_cost = getattr(cost_info, "run_cost_usd", None)
        total = getattr(cost_info, "total_cost_usd", None)
        if isinstance(total, (int, float)):
            cumulative_cost = total
        if isinstance(run_cost, (int, float)):
            total_f = total if isinstance(total, (int, float)) else None
            line = format_cost_line(run_cost=run_cost, total_cost=total_f)
            if line:
                console.print(line)

    def _on_context(pct: float, cur: int, mx: int) -> None:
        nonlocal context_pct, context_current, context_max, prev_context_pct
        # Detect compression: pct dropped significantly (>10%)
        if prev_context_pct > 0 and pct < prev_context_pct - 0.1:
            _show_compression_notice(prev_context_pct, pct, cur, mx)
        prev_context_pct = pct
        context_pct = pct
        context_current = cur
        context_max = mx

    handler = None if auto_approve else _interactive_permission_handler
    _auto_approve_state["active"] = auto_approve

    try:
        backend = None
        if sandbox:
            sandbox_instance = _create_sandbox_backend(runtime)
            if sandbox_instance is None:
                return
            backend = sandbox_instance
            theme = get_theme()
            console.print(f"[{theme.muted}]Sandbox: {runtime}[/{theme.muted}]\n")

        # Resolve session_id before creating agent — resume reuses old ID,
        # fork always gets a fresh one.
        message_history: list[ModelMessage] = []
        if resume is not None:
            message_history, resumed_id = await _load_thread(resume)
            if message_history and resumed_id and not fork_session:
                # Continue: reuse old session_id
                session_id = resumed_id

        result = _create_agent_with_retry(
            model=model,
            working_dir=working_dir,
            on_cost_update=_on_cost,
            on_context_update=_on_context,
            backend=backend,
            permission_handler=handler,
            model_settings=model_settings,
            session_id=session_id,
        )
        if result[0] is None:
            return
        agent, deps = result

        # Wire interactive ask_user callback for plan agent
        if not auto_approve:
            deps.ask_user = _interactive_ask_user

        print_welcome_banner(console, model=model, working_dir=working_dir)

        if message_history:
            if fork_session and resume is not None:
                theme = get_theme()
                console.print(
                    f"[{theme.muted}]Forked from session "
                    f"\u2192 new session {session_id}[/{theme.muted}]"
                )
            _display_loaded_session(message_history)

        await _chat_loop(
            agent,
            deps,
            message_history,
            working_dir,
            get_cost=lambda: cumulative_cost,
            get_model=lambda: current_model,
            on_model_change=_on_model_change,
            get_context_pct=lambda: context_pct,
            get_context_current=lambda: context_current,
            get_context_max=lambda: context_max,
        )
    finally:
        _save_readline_history()
        if sandbox_instance is not None:
            _stop_sandbox(sandbox_instance)


async def _get_session_info(session_dir: Path) -> dict[str, Any] | None:
    """Get session info from a session directory.

    Reads from messages.json (the persistent conversation history written
    by ContextManagerMiddleware).

    Returns dict with id, messages, message_count, last_user_msg, date — or None.
    """
    from datetime import datetime, timezone

    messages_file = session_dir / "messages.json"
    if not messages_file.exists():
        return None

    try:
        from pydantic_ai.messages import ModelMessagesTypeAdapter

        raw = messages_file.read_bytes()
        if not raw:
            return None
        messages = list(ModelMessagesTypeAdapter.validate_json(raw))
    except Exception:
        return None

    if not messages:
        return None

    # Extract last user message (most useful for "where did I leave off?")
    last_user_msg = ""
    for msg in reversed(messages):
        if getattr(msg, "kind", None) == "request":
            for part in getattr(msg, "parts", []):
                content = getattr(part, "content", None)
                if isinstance(content, str) and content.strip():
                    last_user_msg = content.strip()
                    break
            if last_user_msg:
                break

    # Get date from file mtime
    mtime = messages_file.stat().st_mtime
    date = datetime.fromtimestamp(mtime, tz=timezone.utc)

    return {
        "id": session_dir.name,
        "messages": messages,
        "message_count": len(messages),
        "last_user_msg": last_user_msg,
        "date": date,
    }


async def _pick_session_interactive() -> list[ModelMessage]:
    """Show interactive session picker with arrow-key navigation."""
    from cli.config import get_sessions_dir
    from cli.picker import PickerItem, interactive_select

    sessions_dir = get_sessions_dir()
    if not sessions_dir.exists():
        theme = get_theme()
        console.print(f"[{theme.muted}]No saved sessions.[/{theme.muted}]")
        return []

    # Collect session info, sorted by date (newest first)
    session_dirs = sorted(
        (d for d in sessions_dir.iterdir() if d.is_dir()),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )

    sessions: list[dict[str, Any]] = []
    for d in session_dirs:
        info = await _get_session_info(d)
        if info:
            sessions.append(info)

    if not sessions:
        theme = get_theme()
        console.print(f"[{theme.muted}]No saved sessions.[/{theme.muted}]")
        return []

    # Build picker items
    items: list[PickerItem] = []
    for s in sessions:
        date_str = s["date"].astimezone().strftime("%b %d, %H:%M")
        label = f"{date_str}  \u2022  {s['message_count']} msgs  \u2022  {s['id']}"
        description = _truncate(s["last_user_msg"], 70) if s["last_user_msg"] else ""
        items.append(PickerItem(label=label, value=s, description=description))

    selected = interactive_select(
        items,
        title="Previous Sessions",
        empty_message="No saved sessions.",
        console=console,
    )

    if selected is None:
        return []

    return list(selected.value["messages"])


def _display_loaded_session(messages: list[ModelMessage]) -> None:
    """Render loaded message history exactly as it appears during live chat.

    Replays user prompts, tool calls, tool results, and AI text responses
    using the same rendering functions as the streaming display.
    """
    theme = get_theme()
    glyphs = get_glyphs()

    sep = glyphs.separator * 50
    console.print(f"\n[{theme.muted}]{sep}[/{theme.muted}]")
    console.print(
        f" [bold]Restored session[/bold] [{theme.muted}]({len(messages)} messages)[/{theme.muted}]"
    )
    console.print(f"[{theme.muted}]{sep}[/{theme.muted}]\n")

    for msg in messages:
        kind = getattr(msg, "kind", None)
        parts = getattr(msg, "parts", [])

        if kind == "request":
            for part in parts:
                pk = getattr(part, "part_kind", "")
                if pk == "user-prompt":
                    content = getattr(part, "content", "")
                    if isinstance(content, str) and content.strip():
                        console.print(
                            f"[bold {theme.primary}]>[/bold {theme.primary}] {content.strip()}"
                        )
                        console.print()
                elif pk == "tool-return":
                    tool_name = getattr(part, "tool_name", "")
                    content = getattr(part, "content", "")
                    console.print(render_tool_result(tool_name, content))

        elif kind == "response":
            for part in parts:
                pk = getattr(part, "part_kind", "")
                if pk == "tool-call":
                    tool_name = getattr(part, "tool_name", "?")
                    args = getattr(part, "args", {})
                    if not isinstance(args, dict):
                        args = {}
                    console.print(render_tool_call(tool_name, args))
                elif pk == "text":
                    content = getattr(part, "content", "")
                    if isinstance(content, str) and content.strip():
                        install_prettier_code_blocks()
                        console.print(Markdown(content.strip()))
                        console.print()

    console.print(f"[{theme.muted}]{sep}[/{theme.muted}]\n")


async def _load_thread(thread_id: str) -> tuple[list[ModelMessage], str | None]:
    """Load a thread's message history for resuming.

    Reads from messages.json (the persistent conversation history written
    by ContextManagerMiddleware).

    Args:
        thread_id: Thread ID prefix to match. Empty string triggers interactive picker.

    Returns:
        Tuple of (message_history, matched_session_id). Session ID is None
        if the thread was loaded via the interactive picker.
    """
    if not thread_id:
        return await _pick_session_interactive(), None

    from cli.config import get_sessions_dir

    sessions_dir = get_sessions_dir()
    if not sessions_dir.exists():
        theme = get_theme()
        console.print(f"[{theme.muted}]No saved sessions.[/{theme.muted}]")
        return [], None

    match_dir = next(
        (d for d in sessions_dir.iterdir() if d.is_dir() and d.name.startswith(thread_id)),
        None,
    )

    if match_dir is None:
        theme = get_theme()
        console.print(f"[{theme.muted}]Session '{thread_id}' not found.[/{theme.muted}]")
        return [], None

    messages_file = match_dir / "messages.json"
    if not messages_file.exists():
        theme = get_theme()
        console.print(f"[{theme.muted}]Session has no history.[/{theme.muted}]")
        return [], None

    try:
        from pydantic_ai.messages import ModelMessagesTypeAdapter

        raw = messages_file.read_bytes()
        if not raw:
            return [], match_dir.name
        messages = list(ModelMessagesTypeAdapter.validate_json(raw))
        if messages:
            return messages, match_dir.name
    except Exception:
        theme = get_theme()
        console.print(f"[{theme.muted}]Failed to load session history.[/{theme.muted}]")

    return [], None


__all__ = ["run_interactive"]
