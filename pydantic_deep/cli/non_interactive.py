"""Non-interactive execution mode for benchmarks.

Runs a single task against the agent, streams results to stdout, and exits.
Diagnostic output (tool calls, cost) goes to stderr when not in quiet mode.
"""

from __future__ import annotations

import sys
from typing import Any

from pydantic_ai import (
    AgentRunResultEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
)
from rich.console import Console

from pydantic_deep.cli.agent import create_cli_agent

# Map provider prefixes to their required environment variables.
_PROVIDER_ENV_VARS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
}


def _truncate(text: str, max_len: int = 120) -> str:
    """Truncate text with ellipsis."""
    return text[: max_len - 3] + "..." if len(text) > max_len else text


async def run_non_interactive(
    message: str,
    model: str | None = None,
    working_dir: str | None = None,
    shell_allow_list: list[str] | None = None,
    quiet: bool = False,
    stream: bool = True,
    sandbox: bool = False,
    runtime: str = "python-minimal",
) -> int:
    """Run a single task non-interactively and exit.

    In non-interactive mode, all tool calls are auto-approved (no HITL).
    Response text goes to stdout. Diagnostics go to stderr.

    Args:
        message: The task to execute.
        model: Model to use.
        working_dir: Filesystem root directory.
        shell_allow_list: Allowed shell command prefixes.
        quiet: Suppress all diagnostic output.
        stream: Stream response text as it arrives.
        sandbox: Run in Docker sandbox.
        runtime: Sandbox runtime name.

    Returns:
        Exit code: 0 for success, 1 for error, 130 for keyboard interrupt.
    """
    # Diagnostics always go to stderr so stdout is clean for response text
    console = Console(stderr=True)

    if not quiet:
        console.print("[dim]Running task non-interactively...[/dim]")
        if model:
            console.print(f"[dim]Model: {model}[/dim]")
        if working_dir:
            console.print(f"[dim]Working dir: {working_dir}[/dim]")
        if sandbox:
            console.print(f"[dim]Sandbox: {runtime}[/dim]")
        console.print()

    def _on_cost(cost_info: Any) -> None:
        if not quiet:
            run_cost = getattr(cost_info, "run_cost_usd", None)
            if run_cost is not None:
                console.print(f"[dim]Cost: ${run_cost:.4f}[/dim]")

    sandbox_instance: Any = None

    try:
        backend = None
        if sandbox:
            backend = _create_sandbox(runtime, console)
            if backend is None:
                return 1

            sandbox_instance = backend

        agent, deps = create_cli_agent(
            model=model,
            working_dir=working_dir,
            shell_allow_list=shell_allow_list,
            on_cost_update=_on_cost,
            backend=backend,
        )

        if stream:
            response_text = await _stream_execution(agent, message, deps, console, quiet=quiet)
        else:
            result = await agent.run(message, deps=deps)
            response_text = str(result.output)

        # Write final response to stdout
        if response_text:
            sys.stdout.write(response_text)
            if not response_text.endswith("\n"):
                sys.stdout.write("\n")
            sys.stdout.flush()

        if not quiet:
            console.print()
            console.print("[green]Task completed[/green]")

        return 0

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
        return 130
    except Exception as e:
        msg = str(e)
        if "api_key" in msg.lower() or "api key" in msg.lower():
            console.print(f"\n[red]Error: {msg}[/red]\n")
            console.print("[yellow]Hint:[/yellow] Set the API key for your provider, e.g.:")
            for prefix, var in _PROVIDER_ENV_VARS.items():
                console.print(f"  export {var}=sk-...   [dim]# for --model {prefix}:...[/dim]")
            console.print()
            console.print(
                "[yellow]Or switch providers:[/yellow]  "
                "pydantic-deep run \"task\" --model anthropic:claude-sonnet-4-20250514"
            )
        else:
            console.print(f"\n[red]Error ({type(e).__name__}): {e}[/red]")
        return 1
    finally:
        if sandbox_instance is not None:
            _stop_sandbox(sandbox_instance, console)


def _create_sandbox(runtime: str, console: Console) -> Any | None:
    """Create a DockerSandbox instance.

    Returns:
        The sandbox instance, or None if Docker support is not installed.
    """
    try:
        from pydantic_ai_backends import DockerSandbox
    except ImportError:
        console.print(
            "[red]Docker support not installed. "
            "Run: pip install pydantic-deep[sandbox][/red]"
        )
        return None
    return DockerSandbox(runtime=runtime)


def _stop_sandbox(sandbox: Any, console: Console) -> None:
    """Safely stop a sandbox instance."""
    try:
        sandbox.stop()
    except Exception as e:  # noqa: BLE001
        console.print(f"[yellow]Warning: sandbox cleanup failed: {e}[/yellow]")


async def _stream_execution(
    agent: Any,
    message: str,
    deps: Any,
    console: Console,
    *,
    quiet: bool = False,
) -> str:
    """Execute with streaming — write text to stdout, tools to stderr.

    Args:
        agent: The configured agent.
        message: User task message.
        deps: Agent dependencies.
        console: Rich console for stderr output.
        quiet: Suppress tool call diagnostics.

    Returns:
        Full response text.
    """
    response_parts: list[str] = []

    async for event in agent.run_stream_events(message, deps=deps):
        if isinstance(event, PartDeltaEvent):
            if hasattr(event.delta, "content_delta"):
                chunk = event.delta.content_delta
                if chunk:
                    response_parts.append(chunk)
                # Don't write to stdout during streaming — collect and write at end
                # This avoids interleaving with potential stderr output

        elif isinstance(event, FunctionToolCallEvent):
            if not quiet:
                tool_name = event.part.tool_name
                args_preview = _truncate(str(event.part.args), 100)
                console.print(f"[dim]  {tool_name}({args_preview})[/dim]")

        elif isinstance(event, FunctionToolResultEvent):
            if not quiet:
                result_preview = _truncate(str(event.result.content).replace("\n", " "), 80)
                console.print(f"[dim]  -> {result_preview}[/dim]")

        elif isinstance(event, AgentRunResultEvent):
            # Final result — use this as the canonical output
            return str(event.result.output)

    return "".join(response_parts)


__all__ = ["run_non_interactive"]
