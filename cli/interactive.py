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

from cli.agent import create_cli_agent
from cli.display import (
    format_cost_line,
    install_prettier_code_blocks,
    print_error,
    print_warning,
    print_welcome_banner,
)
from cli.theme import get_glyphs, get_theme
from cli.tool_display import render_tool_call, render_tool_result
from pydantic_deep.deps import DeepAgentDeps

console = Console()


def _get_history_config() -> tuple[Path, int]:
    """Return (history_file_path, max_lines) from CLI config."""
    from cli.config import load_config

    config = load_config()
    return Path(config.history_file), config.max_history


def _setup_readline() -> None:
    """Configure readline with persistent history."""
    history_file, max_lines = _get_history_config()
    with contextlib.suppress(OSError):
        history_file.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        readline.read_history_file(str(history_file))
    readline.set_history_length(max_lines)


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
        console.print(f"[dim]Reason: {reason}[/dim]")

    try:
        answer = input("[Y]es / [N]o / [A]uto-approve all: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False

    if answer in ("a", "auto"):
        _SAFE_TOOLS_MUTABLE.add(tool_name)
        return True
    return answer in ("y", "yes", "")


_SAFE_TOOLS_MUTABLE: set[str] = set()


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
    """Print the current TODO list."""
    glyphs = get_glyphs()
    theme = get_theme()

    if not deps.todos:
        console.print("[dim]No TODOs[/dim]")
        return

    console.print()
    for todo in deps.todos:
        if todo.status == "completed":
            icon = f"[{theme.success}]{glyphs.success}[/{theme.success}]"
        elif todo.status == "in_progress":
            icon = f"[{theme.warning}]{glyphs.active}[/{theme.warning}]"
        else:
            icon = f"[dim]{glyphs.pending}[/dim]"
        console.print(f"  {icon} {todo.content}")
    console.print()


def _is_tty() -> bool:
    """Check if stdout is a terminal (for Rich Markdown vs raw output)."""
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


async def _stream_model_request(node: Any, ctx: Any) -> str:
    """Stream text from a ModelRequestNode using node.stream() + stream_text().

    When stdout is a TTY, renders output as Rich Markdown using ``Live``.
    When piped, writes raw text to stdout.

    Returns:
        The full response text from this model request.
    """
    theme = get_theme()
    glyphs = get_glyphs()
    use_rich = _is_tty()
    accumulated_text = ""

    async with node.stream(ctx) as request_stream:
        final_result_found = False

        # Phase 1: events (tool call args, thinking, etc.)
        async for event in request_stream:
            if isinstance(event, PartStartEvent):
                if hasattr(event.part, "tool_name"):
                    tool_name = event.part.tool_name
                    console.print(
                        f"\n  [{theme.warning}]{glyphs.lightning} {tool_name}[/{theme.warning}]"
                    )
            elif isinstance(event, PartDeltaEvent):
                if isinstance(event.delta, TextPartDelta) and not use_rich:
                    # In raw mode, write deltas immediately
                    sys.stdout.write(event.delta.content_delta)
                    sys.stdout.flush()
            elif isinstance(event, FinalResultEvent):
                final_result_found = True
                break

        # Phase 2: authoritative cumulative text stream
        if final_result_found:
            if use_rich:
                install_prettier_code_blocks()
                with Live(
                    Markdown(""),
                    console=console,
                    vertical_overflow="visible",
                    refresh_per_second=8,
                ) as live:
                    async for cumulative_text in request_stream.stream_text():
                        accumulated_text = cumulative_text
                        live.update(Markdown(accumulated_text))
            else:
                previous_text = ""
                async for cumulative_text in request_stream.stream_text():
                    delta = cumulative_text[len(previous_text) :]
                    if delta:
                        sys.stdout.write(delta)
                        sys.stdout.flush()
                    previous_text = cumulative_text
                    accumulated_text = cumulative_text

    return accumulated_text


async def _stream_tool_calls(node: Any, ctx: Any) -> None:
    """Stream tool-call results from a CallToolsNode."""
    async with node.stream(ctx) as handle_stream:
        async for event in handle_stream:
            if isinstance(event, FunctionToolCallEvent):
                args = event.part.args if isinstance(event.part.args, dict) else {}
                console.print(render_tool_call(event.part.tool_name, args))
            elif isinstance(event, FunctionToolResultEvent):
                tool_name = getattr(event.result, "tool_name", "unknown")
                console.print(render_tool_result(tool_name, event.result.content))


async def _process_stream(
    agent: Agent[DeepAgentDeps, str],
    user_input: str,
    deps: DeepAgentDeps,
    message_history: list[ModelMessage],
) -> list[ModelMessage]:
    """Run the agent using ``agent.iter()`` and stream output to the terminal.

    Returns:
        Updated message history.
    """
    theme = get_theme()
    glyphs = get_glyphs()

    spinner = console.status(
        f"[{theme.muted}]Thinking...[/{theme.muted}]",
        spinner="dots",
    )
    spinner_active = False
    if _is_tty():
        spinner.start()
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
                    spinner.stop()
                    spinner_active = False
                console.print(f"[bold {theme.accent}]AI:[/bold {theme.accent}] ", end="")
                await _stream_model_request(node, run.ctx)
            elif Agent.is_call_tools_node(node):
                if spinner_active:
                    spinner.update(
                        f"[{theme.muted}]{glyphs.lightning} Running tools...[/{theme.muted}]"
                    )
                await _stream_tool_calls(node, run.ctx)
                if _is_tty() and not spinner_active:
                    spinner.update(f"[{theme.muted}]Thinking...[/{theme.muted}]")
                    spinner.start()
                    spinner_active = True
            elif isinstance(node, End):
                pass

        result = run.result

    if spinner_active:
        spinner.stop()

    console.print()
    if result is None:
        return list(message_history)
    return result.all_messages()


def _cmd_save(arg: str, history: list[ModelMessage]) -> list[ModelMessage]:
    """Handle /save command."""
    import asyncio

    from cli.config import DEFAULT_THREADS_DIR
    from pydantic_deep.toolsets.checkpointing import FileCheckpointStore, _make_checkpoint

    label = arg or "manual-save"
    store = FileCheckpointStore(DEFAULT_THREADS_DIR)
    cp = _make_checkpoint(label=label, turn=len(history), messages=history)
    asyncio.get_event_loop().run_until_complete(store.save(cp))
    console.print(f"[dim]Saved checkpoint: {cp.id[:8]} ({label})[/dim]")
    return history


def _cmd_load(arg: str, history: list[ModelMessage]) -> list[ModelMessage]:
    """Handle /load command."""
    import asyncio

    from cli.config import DEFAULT_THREADS_DIR
    from pydantic_deep.toolsets.checkpointing import FileCheckpointStore

    if not arg:
        console.print("[dim]Usage: /load <thread-id>[/dim]")
        return history
    store = FileCheckpointStore(DEFAULT_THREADS_DIR)
    checkpoints = asyncio.get_event_loop().run_until_complete(store.list_all())
    match = next((cp for cp in checkpoints if cp.id.startswith(arg)), None)
    if match is None:
        console.print(f"[dim]Thread '{arg}' not found.[/dim]")
        return history
    loaded = asyncio.get_event_loop().run_until_complete(store.get(match.id))
    if loaded and loaded.messages:
        history = list(loaded.messages)
        console.print(
            f"[dim]Loaded checkpoint: {match.id[:8]} ({match.label}), {len(history)} messages[/dim]"
        )
    else:
        console.print("[dim]Checkpoint has no messages.[/dim]")
    return history


def _cmd_help() -> None:
    """Handle /help command."""
    theme = get_theme()
    console.print()
    console.print(f"[bold {theme.primary}]Available commands:[/bold {theme.primary}]")
    console.print("  [dim]/help[/dim]           Show this help message")
    console.print("  [dim]/quit[/dim]           Exit the chat")
    console.print("  [dim]/clear[/dim]          Clear conversation history")
    console.print("  [dim]/compact[/dim]        Trim history to last 10 messages")
    console.print("  [dim]/todos[/dim]          Show current TODO list")
    console.print("  [dim]/cost[/dim]           Show accumulated cost")
    console.print("  [dim]/tokens[/dim]         Show message/token stats")
    console.print("  [dim]/model[/dim] [name]   Show or change model")
    console.print("  [dim]/save[/dim] [label]   Save conversation checkpoint")
    console.print("  [dim]/load[/dim] <id>      Load a saved checkpoint")
    console.print("  [dim]/skills[/dim]         List available skills")
    console.print()
    console.print("[dim]Tip: Use @filepath to include file contents in your message[/dim]")
    console.print()


def _cmd_cost(cumulative_cost: float | None) -> None:
    """Handle /cost command."""
    if cumulative_cost is not None and cumulative_cost > 0:
        line = format_cost_line(total_cost=cumulative_cost)
        console.print(line or "[dim]No cost data[/dim]")
    else:
        console.print("[dim]No cost data yet.[/dim]")


def _cmd_compact(history: list[ModelMessage]) -> list[ModelMessage]:
    """Handle /compact command."""
    keep = 10
    if len(history) > keep:
        history = history[-keep:]
        console.print(f"[dim]Compacted to last {keep} messages.[/dim]")
    else:
        console.print("[dim]History is already compact.[/dim]")
    return history


def _cmd_model(
    arg: str,
    current_model: str | None,
    on_change: Any | None,
) -> None:
    """Handle /model command."""
    if arg:
        if on_change:
            on_change(arg)
        console.print(f"[dim]Model changed to: {arg}[/dim]")
    else:
        console.print(f"[dim]Current model: {current_model or 'default'}[/dim]")


def _cmd_tokens(history: list[ModelMessage]) -> None:
    """Handle /tokens command."""
    count = sum(len(str(getattr(m, "parts", ""))) for m in history)
    console.print(f"[dim]Messages: {len(history)}, ~{count} chars in history[/dim]")


def _cmd_skills() -> None:
    """Handle /skills command."""
    from cli.main import _discover_all_skills

    skills = _discover_all_skills()
    if not skills:
        console.print("[dim]No skills available.[/dim]")
    else:
        for s in skills:
            source_tag = f"[dim]({s['source']})[/dim]"
            console.print(f"  {s['name']}: {s['description']} {source_tag}")


def _handle_command(
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
        console.print("\n[dim]Goodbye![/dim]")
        return True, history

    if cmd_name == "/clear":
        history = []
        deps.todos = []
        console.print("[dim]Conversation cleared.[/dim]\n")
        return False, history

    if cmd_name == "/todos":
        _print_todos(deps)
    elif cmd_name == "/cost":
        _cmd_cost(cumulative_cost)
    elif cmd_name == "/compact":
        history = _cmd_compact(history)
    elif cmd_name == "/model":
        _cmd_model(cmd_arg, current_model, on_model_change)
    elif cmd_name == "/tokens":
        _cmd_tokens(history)
    elif cmd_name == "/save":
        history = _cmd_save(cmd_arg, history)
    elif cmd_name == "/load":
        history = _cmd_load(cmd_arg, history)
    elif cmd_name == "/skills":
        _cmd_skills()
    elif cmd_name == "/help":
        _cmd_help()
    else:
        console.print(f"[dim]Unknown command: {cmd_name}. Type /help for available commands.[/dim]")

    return False, history


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


def _read_user_input() -> str:
    """Read user input, supporting multiline blocks with triple-quotes.

    If the user starts a line with ``\"\"\"``, subsequent lines are collected
    until a closing ``\"\"\"`` is entered.
    """
    first_line = input("\033[1m\033[32mYou:\033[0m ").strip()
    if not first_line.startswith('"""'):
        return first_line

    lines = [first_line.removeprefix('"""')]
    console.print('[dim]  ... (multiline mode, close with """)[/dim]')
    while True:
        try:
            line = input("  ... ")
        except EOFError:
            break
        if line.strip().endswith('"""'):
            lines.append(line.rstrip().removesuffix('"""'))
            break
        lines.append(line)
    return "\n".join(lines).strip()


async def _chat_loop(
    agent: Agent[DeepAgentDeps, str],
    deps: DeepAgentDeps,
    message_history: list[ModelMessage],
    working_dir: str | None,
    *,
    get_cost: Any,
    get_model: Any,
    on_model_change: Any,
) -> None:
    """Run the main REPL loop for interactive chat."""
    while True:
        try:
            user_input = _read_user_input()

            if not user_input:
                continue

            if user_input.startswith("/"):
                should_break, message_history[:] = _handle_command(
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

            expanded = _expand_file_mentions(user_input, working_dir)

            print()
            message_history[:] = await _process_stream(agent, expanded, deps, message_history)

            if deps.todos:
                _print_todos(deps)

            print()

        except KeyboardInterrupt:
            console.print("\n\n[dim]Interrupted. Type /quit to exit.[/dim]\n")
        except EOFError:
            console.print("\n[dim]Goodbye![/dim]")
            break
        except Exception as e:
            console.print(f"\n[red]Error: {e}[/red]\n")


async def run_interactive(
    model: str | None = None,
    working_dir: str | None = None,
    sandbox: bool = False,
    runtime: str = "python-minimal",
    resume: str | None = None,
    auto_approve: bool = False,
) -> None:
    """Run the interactive chat loop.

    Args:
        model: Model to use.
        working_dir: Filesystem root directory.
        sandbox: Run in Docker sandbox.
        runtime: Sandbox runtime name.
        resume: Thread ID to resume (prefix match). Empty string means latest.
        auto_approve: Skip HITL approval prompts.
    """
    sandbox_instance: Any = None
    cumulative_cost: float = 0.0
    current_model = model

    _setup_readline()

    def _on_model_change(new_model: str) -> None:
        nonlocal current_model
        current_model = new_model

    def _on_cost(cost_info: Any) -> None:
        nonlocal cumulative_cost
        run_cost = getattr(cost_info, "run_cost_usd", None)
        total = getattr(cost_info, "cumulative_cost_usd", None)
        if isinstance(total, (int, float)):
            cumulative_cost = total
        if isinstance(run_cost, (int, float)):
            total_f = total if isinstance(total, (int, float)) else None
            line = format_cost_line(run_cost=run_cost, total_cost=total_f)
            if line:
                console.print(line)

    handler = None if auto_approve else _interactive_permission_handler

    try:
        backend = None
        if sandbox:
            sandbox_instance = _create_sandbox_backend(runtime)
            if sandbox_instance is None:
                return
            backend = sandbox_instance
            console.print(f"[dim]Sandbox: {runtime}[/dim]\n")

        try:
            agent, deps = create_cli_agent(
                model=model,
                working_dir=working_dir,
                on_cost_update=_on_cost,
                backend=backend,
                permission_handler=handler,
            )
        except Exception as e:
            _print_model_error(e)
            return

        print_welcome_banner(console, model=model, working_dir=working_dir)

        message_history: list[ModelMessage] = []
        if resume is not None:
            message_history = _load_thread(resume)

        await _chat_loop(
            agent,
            deps,
            message_history,
            working_dir,
            get_cost=lambda: cumulative_cost,
            get_model=lambda: current_model,
            on_model_change=_on_model_change,
        )
    finally:
        _save_readline_history()
        if sandbox_instance is not None:
            _stop_sandbox(sandbox_instance)


def _load_thread(thread_id: str) -> list[ModelMessage]:
    """Load a thread's message history for resuming.

    Args:
        thread_id: Thread ID prefix to match. Empty string means latest.

    Returns:
        Message history from the checkpoint, or empty list if not found.
    """
    import asyncio

    from cli.config import DEFAULT_THREADS_DIR
    from pydantic_deep.toolsets.checkpointing import FileCheckpointStore

    if not DEFAULT_THREADS_DIR.exists():
        console.print("[dim]No saved threads found.[/dim]")
        return []

    store = FileCheckpointStore(DEFAULT_THREADS_DIR)
    checkpoints = asyncio.get_event_loop().run_until_complete(store.list_all())

    if not checkpoints:
        console.print("[dim]No saved threads found.[/dim]")
        return []

    from pydantic_deep.toolsets.checkpointing import Checkpoint

    match_cp: Checkpoint | None
    if thread_id == "":
        match_cp = checkpoints[-1]
    else:
        match_cp = next((cp for cp in checkpoints if cp.id.startswith(thread_id)), None)

    if match_cp is None:
        console.print(f"[dim]Thread '{thread_id}' not found.[/dim]")
        return []

    loaded = asyncio.get_event_loop().run_until_complete(store.get(match_cp.id))
    if loaded and loaded.messages:
        console.print(
            f"[dim]Resumed thread: {match_cp.id[:8]} ({match_cp.label}), "
            f"{len(loaded.messages)} messages[/dim]"
        )
        return list(loaded.messages)

    console.print("[dim]Checkpoint has no messages.[/dim]")
    return []


__all__ = ["run_interactive"]
