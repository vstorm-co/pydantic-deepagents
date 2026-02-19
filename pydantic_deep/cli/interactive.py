"""Interactive chat mode for the CLI.

Provides a REPL-style chat loop with streaming responses, tool call
visibility, and TODO list display.

Uses ``agent.iter()`` + ``node.stream()`` (the same approach as
``examples/full_app/app.py``) for reliable, chunk-complete streaming.
"""

from __future__ import annotations

import sys
from typing import Any

from pydantic_ai import (
    Agent,
    FinalResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPartDelta,
)
from pydantic_ai._agent_graph import End, UserPromptNode
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessage,
)
from rich.console import Console

from pydantic_deep.cli.agent import create_cli_agent
from pydantic_deep.deps import DeepAgentDeps

console = Console()

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
        console.print(f"[red]Error: {msg}[/red]\n")
        console.print("[yellow]Hint:[/yellow] Set the API key for your provider, e.g.:")
        for prefix, var in _PROVIDER_ENV_VARS.items():
            console.print(f"  export {var}=sk-...   [dim]# for --model {prefix}:...[/dim]")
        console.print()
        console.print(
            "[yellow]Or switch providers:[/yellow]  "
            "pydantic-deep chat --model anthropic:claude-sonnet-4-20250514"
        )
    else:
        console.print(f"[red]Failed to create agent: {exc}[/red]")


def _truncate(text: str, max_len: int = 120) -> str:
    """Truncate text with ellipsis."""
    return text[: max_len - 3] + "..." if len(text) > max_len else text


def _write(text: str) -> None:
    """Write text to stdout and flush immediately."""
    sys.stdout.write(text)
    sys.stdout.flush()


# ANSI escape codes for styled output (avoids Rich buffering during streaming).
_CYAN_BOLD = "\033[1;36m"
_YELLOW = "\033[33m"
_DIM = "\033[2m"
_RESET = "\033[0m"


def _print_header() -> None:
    """Print the chat header."""
    console.print()
    console.print("[bold cyan]pydantic-deep Interactive Chat[/bold cyan]")
    console.print("[dim]Commands: /quit, /clear, /todos[/dim]")
    console.print()


def _print_todos(deps: DeepAgentDeps) -> None:
    """Print the current TODO list."""
    if not deps.todos:
        console.print("[dim]No TODOs[/dim]")
        return

    console.print()
    for todo in deps.todos:
        if todo.status == "completed":
            icon = "[green]\u2713[/green]"
        elif todo.status == "in_progress":
            icon = "[yellow]\u25cf[/yellow]"
        else:
            icon = "[dim]\u25cb[/dim]"
        console.print(f"  {icon} {todo.content}")
    console.print()


# ---------------------------------------------------------------------------
# Streaming via agent.iter() — same approach as examples/full_app/app.py
# ---------------------------------------------------------------------------


async def _stream_model_request(node: Any, ctx: Any) -> None:
    """Stream text from a ModelRequestNode using node.stream() + stream_text().

    Two phases:
      1. Iterate events for tool-call starts/deltas and the FinalResultEvent marker.
      2. After FinalResultEvent, call ``stream_text()`` which yields cumulative
         text — we compute deltas ourselves and write them immediately.
    """
    async with node.stream(ctx) as request_stream:
        final_result_found = False

        # Phase 1: events (tool call args, thinking, etc.)
        async for event in request_stream:
            if isinstance(event, PartStartEvent):
                if hasattr(event.part, "tool_name"):
                    tool_name = event.part.tool_name
                    _write(f"\n  {_YELLOW}\u26a1 {tool_name}{_RESET}\n")
            elif isinstance(event, PartDeltaEvent):
                if isinstance(event.delta, TextPartDelta):
                    _write(event.delta.content_delta)
            elif isinstance(event, FinalResultEvent):
                final_result_found = True
                break

        # Phase 2: authoritative cumulative text stream
        if final_result_found:
            previous_text = ""
            async for cumulative_text in request_stream.stream_text():
                delta = cumulative_text[len(previous_text) :]
                if delta:
                    _write(delta)
                previous_text = cumulative_text


async def _stream_tool_calls(node: Any, ctx: Any) -> None:
    """Stream tool-call results from a CallToolsNode."""
    async with node.stream(ctx) as handle_stream:
        async for event in handle_stream:
            if isinstance(event, FunctionToolCallEvent):
                tool_name = event.part.tool_name
                args_preview = _truncate(str(event.part.args), 100)
                _write(f"  {_YELLOW}\u26a1 {tool_name}{_RESET}{_DIM}({args_preview}){_RESET}\n")
            elif isinstance(event, FunctionToolResultEvent):
                result_preview = _truncate(
                    str(event.result.content).replace("\n", " "), 80
                )
                _write(f"    {_DIM}\u2192 {result_preview}{_RESET}\n")


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
    _write(f"{_CYAN_BOLD}AI:{_RESET} ")

    async with agent.iter(
        user_input,
        deps=deps,
        message_history=message_history,
    ) as run:
        async for node in run:
            if isinstance(node, UserPromptNode):
                pass  # nothing to display
            elif Agent.is_model_request_node(node):
                await _stream_model_request(node, run.ctx)
            elif Agent.is_call_tools_node(node):
                await _stream_tool_calls(node, run.ctx)
            elif isinstance(node, End):
                pass

        result = run.result

    _write("\n")
    return result.all_messages()


def _handle_command(
    cmd: str,
    deps: DeepAgentDeps,
    history: list[ModelMessage],
) -> tuple[bool, list[ModelMessage]]:
    """Handle slash commands.

    Returns:
        Tuple of (should_break, updated_history).
    """
    cmd_lower = cmd.lower()

    if cmd_lower in ("/quit", "/exit"):
        console.print("\n[dim]Goodbye![/dim]")
        return True, history

    if cmd_lower == "/clear":
        history = []
        deps.todos = []
        console.print("[dim]Conversation cleared.[/dim]\n")
        return False, history

    if cmd_lower == "/todos":
        _print_todos(deps)
        return False, history

    return False, history


async def run_interactive(
    model: str | None = None,
    working_dir: str | None = None,
    sandbox: bool = False,
    runtime: str = "python-minimal",
) -> None:
    """Run the interactive chat loop.

    Args:
        model: Model to use.
        working_dir: Filesystem root directory.
        sandbox: Run in Docker sandbox.
        runtime: Sandbox runtime name.
    """
    _print_header()

    sandbox_instance: Any = None

    def _on_cost(cost_info: Any) -> None:
        run_cost = getattr(cost_info, "run_cost_usd", None)
        total = getattr(cost_info, "cumulative_cost_usd", None)
        if run_cost is not None:
            console.print(f"[dim]  Cost: ${run_cost:.4f} (total: ${total:.4f})[/dim]")

    try:
        backend = None
        if sandbox:
            try:
                from pydantic_ai_backends import DockerSandbox
            except ImportError:
                console.print(
                    "[red]Docker support not installed. "
                    "Run: pip install pydantic-deep[sandbox][/red]"
                )
                return

            sandbox_instance = DockerSandbox(runtime=runtime)
            backend = sandbox_instance
            console.print(f"[dim]Sandbox: {runtime}[/dim]\n")

        try:
            agent, deps = create_cli_agent(
                model=model,
                working_dir=working_dir,
                on_cost_update=_on_cost,
                backend=backend,
            )
        except Exception as e:
            _print_model_error(e)
            return

        message_history: list[ModelMessage] = []

        while True:
            try:
                user_input = input("\033[1m\033[32mYou:\033[0m ").strip()

                if not user_input:
                    continue

                if user_input.startswith("/"):
                    should_break, message_history = _handle_command(user_input, deps, message_history)
                    if should_break:
                        break
                    continue

                print()
                message_history = await _process_stream(agent, user_input, deps, message_history)

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
    finally:
        if sandbox_instance is not None:
            try:
                sandbox_instance.stop()
            except Exception as e:  # noqa: BLE001
                console.print(f"[yellow]Warning: sandbox cleanup failed: {e}[/yellow]")


__all__ = ["run_interactive"]
