"""Non-interactive execution mode for benchmarks.

Runs a single task against the agent, streams results to stdout, and exits.
Diagnostic output (tool calls, cost) goes to stderr when not in quiet mode.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic_ai import (
    AgentRunResultEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
)
from rich.console import Console

from cli.agent import create_cli_agent
from cli.display import (
    format_cost_line,
    print_error,
    print_warning,
    render_markdown,
)
from cli.theme import get_glyphs, get_theme
from cli.tool_display import render_tool_call, render_tool_result

_PROVIDER_ENV_VARS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
}


def _is_api_key_error(exc: Exception) -> bool:
    """Check if the exception is an API key error."""
    msg = str(exc).lower()
    return "api_key" in msg or "api key" in msg


def _print_api_error(exc: Exception, err_console: Console) -> None:
    """Print a friendly error when the model provider fails."""
    msg = str(exc)
    if _is_api_key_error(exc):
        hint_lines = ["Set the API key for your provider, e.g.:"]
        for prefix, var in _PROVIDER_ENV_VARS.items():
            hint_lines.append(f"  export {var}=sk-...   # for --model {prefix}:...")
        print_error(err_console, msg, hint="\n".join(hint_lines))
    else:
        print_error(err_console, f"{type(exc).__name__}: {exc}")


def _truncate(text: str, max_len: int = 120) -> str:
    """Truncate text with ellipsis."""
    glyphs = get_glyphs()
    if len(text) > max_len:
        return text[: max_len - len(glyphs.ellipsis)] + glyphs.ellipsis
    return text


def _print_diagnostics(
    err_console: Console,
    model: str | None,
    working_dir: str | None,
    sandbox: bool,
    runtime: str,
    quiet: bool,
) -> None:
    """Print startup diagnostics to stderr."""
    if quiet:
        return
    err_console.print("[dim]Running task non-interactively...[/dim]")
    if model:
        err_console.print(f"[dim]Model: {model}[/dim]")
    if working_dir:
        err_console.print(f"[dim]Dir: {working_dir}[/dim]")
    if sandbox:
        err_console.print(f"[dim]Sandbox: {runtime}[/dim]")
    err_console.print()


async def run_non_interactive(
    message: str,
    model: str | None = None,
    working_dir: str | None = None,
    shell_allow_list: list[str] | None = None,
    quiet: bool = False,
    stream: bool = True,
    sandbox: bool = False,
    runtime: str = "python-minimal",
    output_format: str = "text",
    verbose: bool = False,
    model_settings: dict[str, Any] | None = None,
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
        output_format: Output format — ``text``, ``json``, or ``markdown``.
        verbose: Enable verbose tool call logging.

    Returns:
        Exit code: 0 for success, 1 for error, 2 for API key error, 130 for interrupt.
    """
    theme = get_theme()
    glyphs = get_glyphs()
    err_console = Console(stderr=True)
    out_console = Console()
    effective_quiet = quiet and not verbose

    _print_diagnostics(err_console, model, working_dir, sandbox, runtime, effective_quiet)

    def _on_cost(cost_info: Any) -> None:
        if not effective_quiet:
            run_cost = getattr(cost_info, "run_cost_usd", None)
            total = getattr(cost_info, "cumulative_cost_usd", None)
            if isinstance(run_cost, (int, float)):
                total_f = total if isinstance(total, (int, float)) else None
                line = format_cost_line(run_cost=run_cost, total_cost=total_f)
                if line:
                    err_console.print(line)

    sandbox_instance: Any = None

    try:
        backend = None
        if sandbox:
            backend = _create_sandbox(runtime, err_console)
            if backend is None:
                return 1

            sandbox_instance = backend

        agent, deps = create_cli_agent(
            model=model,
            working_dir=working_dir,
            shell_allow_list=shell_allow_list,
            on_cost_update=_on_cost,
            backend=backend,
            non_interactive=True,
            model_settings=model_settings,
        )

        show_tools = not effective_quiet or verbose
        if stream:
            response_text = await _stream_execution(
                agent,
                message,
                deps,
                err_console,
                quiet=not show_tools,
                glyphs=glyphs,
                verbose=verbose,
            )
        else:
            if not effective_quiet:
                spinner = err_console.status(
                    f"[dim]{glyphs.lightning} Running...[/dim]", spinner="dots"
                )
                spinner.start()
            try:
                result = await agent.run(message, deps=deps)
                response_text = str(result.output)
            finally:
                if not effective_quiet:
                    spinner.stop()

        if response_text:
            _write_output(out_console, response_text, output_format)

        if not effective_quiet:
            err_console.print()
            err_console.print(f"[{theme.success}]{glyphs.success} Task completed[/{theme.success}]")

        return 0

    except KeyboardInterrupt:
        err_console.print(f"\n[{theme.warning}]Interrupted[/{theme.warning}]")
        return 130
    except Exception as e:
        _print_api_error(e, err_console)
        return 2 if _is_api_key_error(e) else 1
    finally:
        if sandbox_instance is not None:
            _stop_sandbox(sandbox_instance, err_console)


def _write_output(console: Console, text: str, fmt: str) -> None:
    """Write the final response in the requested format."""
    if fmt == "json":
        console.print_json(json.dumps({"response": text}))
    elif fmt == "markdown":
        from rich.markdown import Markdown

        console.print(Markdown(text))
    else:
        render_markdown(console, text)


def _create_sandbox(runtime: str, console: Console) -> Any | None:
    """Create a DockerSandbox instance.

    Returns:
        The sandbox instance, or None if Docker support is not installed.
    """
    try:
        from pydantic_ai_backends import DockerSandbox
    except ImportError:
        console.print(
            "[red]Docker support not installed. Run: pip install pydantic-deep[sandbox][/red]"
        )
        return None
    return DockerSandbox(runtime=runtime)


def _stop_sandbox(sandbox: Any, console: Console) -> None:
    """Safely stop a sandbox instance."""
    try:
        sandbox.stop()
    except Exception as e:
        print_warning(console, f"Sandbox cleanup failed: {e}")


async def _stream_execution(
    agent: Any,
    message: str,
    deps: Any,
    console: Console,
    *,
    quiet: bool = False,
    glyphs: Any = None,
    verbose: bool = False,
) -> str:
    """Execute with streaming — write text to stdout, tools to stderr.

    Args:
        agent: The configured agent.
        message: User task message.
        deps: Agent dependencies.
        console: Rich console for stderr output.
        quiet: Suppress tool call diagnostics.
        glyphs: Glyph set for display.
        verbose: Show full tool arguments and results.

    Returns:
        Full response text.
    """
    if glyphs is None:
        glyphs = get_glyphs()

    response_parts: list[str] = []

    async for event in agent.run_stream_events(message, deps=deps):
        if isinstance(event, PartDeltaEvent):
            if hasattr(event.delta, "content_delta"):
                chunk = event.delta.content_delta
                if chunk:
                    response_parts.append(chunk)

        elif isinstance(event, FunctionToolCallEvent):
            if not quiet:
                args = event.part.args if isinstance(event.part.args, dict) else {}
                console.print(render_tool_call(event.part.tool_name, args))
                if verbose:
                    console.print(f"    [dim]args: {args}[/dim]")

        elif isinstance(event, FunctionToolResultEvent):
            if not quiet:
                tool_name = getattr(event.result, "tool_name", "unknown")
                console.print(render_tool_result(tool_name, event.result.content))
                if verbose:
                    raw = str(event.result.content)
                    if len(raw) > 500:
                        raw = raw[:500] + "..."
                    console.print(f"    [dim]result: {raw}[/dim]")

        elif isinstance(event, AgentRunResultEvent):
            return str(event.result.output)

    return "".join(response_parts)


__all__ = ["run_non_interactive"]
