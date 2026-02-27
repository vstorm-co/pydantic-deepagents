"""CLI entry point for pydantic-deep.

Usage:
    pydantic-deep run "Create a Python script that..." [-m model] [-w dir] [-q]
    pydantic-deep chat [-m model] [-w dir]
    pydantic-deep skills list
    pydantic-deep config show
    pydantic-deep threads list
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import fields
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

app = typer.Typer(
    name="pydantic-deep",
    help="Deep Agent CLI — AI coding assistant powered by pydantic-ai.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


def _version_callback(value: bool) -> None:
    if value:
        from pydantic_deep import __version__

        typer.echo(f"pydantic-deep v{__version__}")
        raise typer.Exit()


def _setup_logfire() -> None:
    """Configure Logfire tracing for all pydantic-ai agents."""
    try:
        import logfire

        logfire.configure(
            token=os.environ.get("LOGFIRE_TOKEN"),
            send_to_logfire="if-token-present",
        )
        logfire.instrument_pydantic_ai()
    except ImportError:
        import sys

        print(
            "Logfire not installed. Run: pip install pydantic-deep[logfire]",
            file=sys.stderr,
        )
        raise SystemExit(2) from None


@app.callback()
def _main_callback(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-V",
            callback=_version_callback,
            is_eager=True,
            help="Show version and exit.",
        ),
    ] = None,
    logfire_enabled: Annotated[
        bool,
        typer.Option("--logfire/--no-logfire", help="Enable Logfire tracing"),
    ] = False,
) -> None:
    """Deep Agent CLI — AI coding assistant powered by pydantic-ai."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:  # pragma: no cover
        pass

    if not logfire_enabled:
        from cli.config import load_config

        config = load_config()
        logfire_enabled = config.logfire

    if logfire_enabled:
        _setup_logfire()


def _build_model_settings(
    model_settings_json: str | None,
    temperature: float | None,
    reasoning_effort: str | None,
    thinking: bool,
    thinking_budget: int | None,
) -> dict[str, Any] | None:
    """Build model settings dict from CLI flags."""
    settings: dict[str, Any] = {}
    if model_settings_json:
        settings = json.loads(model_settings_json)
    if temperature is not None:
        settings["temperature"] = temperature
    if reasoning_effort:
        settings["openai_reasoning_effort"] = reasoning_effort
    if thinking:
        if thinking_budget:
            settings["anthropic_thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
        else:
            settings["anthropic_thinking"] = {"type": "adaptive"}
    elif thinking_budget:
        settings["anthropic_thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
    return settings if settings else None


@app.command()
def init(
    directory: Annotated[
        str | None,
        typer.Option("--dir", "-d", help="Project directory (default: CWD)"),
    ] = None,
) -> None:
    """Initialize .pydantic-deep/ project directory with scaffolding."""
    from cli.init import init_project

    root = Path(directory) if directory else Path.cwd()
    init_project(root)


@app.command()
def run(
    prompt: Annotated[str, typer.Argument(help="Task to execute")],
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Model to use (default: from config)"),
    ] = None,
    working_dir: Annotated[
        str | None,
        typer.Option("--working-dir", "-w", help="Working directory"),
    ] = None,
    shell_allow_list: Annotated[
        list[str] | None,
        typer.Option("--shell-allow-list", help="Allowed shell commands"),
    ] = None,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="Suppress diagnostics")] = False,
    no_stream: Annotated[
        bool, typer.Option("--no-stream", help="Buffer output instead of streaming")
    ] = False,
    sandbox: Annotated[bool, typer.Option("--sandbox", help="Run in Docker sandbox")] = False,
    runtime: Annotated[
        str, typer.Option("--runtime", help="Sandbox runtime (e.g. python-minimal)")
    ] = "python-minimal",
    output_format: Annotated[
        str, typer.Option("--output-format", "-f", help="Output format: text, json, markdown")
    ] = "text",
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Enable verbose output")] = False,
    temperature: Annotated[
        float | None,
        typer.Option("--temperature", "-t", help="Model temperature (0.0 = deterministic)"),
    ] = None,
    reasoning_effort: Annotated[
        str | None,
        typer.Option("--reasoning-effort", help="Reasoning effort: low, medium, high"),
    ] = None,
    thinking: Annotated[
        bool,
        typer.Option("--thinking/--no-thinking", help="Enable extended thinking (Anthropic)"),
    ] = False,
    thinking_budget: Annotated[
        int | None,
        typer.Option("--thinking-budget", help="Thinking budget in tokens (Anthropic)"),
    ] = None,
    model_settings_json: Annotated[
        str | None,
        typer.Option("--model-settings", help="Model settings as JSON"),
    ] = None,
    lean: Annotated[
        bool,
        typer.Option("--lean", help="Use minimal system prompt (less noise for benchmarks)"),
    ] = False,
) -> None:
    """Run a task non-interactively (benchmark mode)."""
    from cli.init import ensure_initialized
    from cli.non_interactive import run_non_interactive

    ensure_initialized()

    settings = _build_model_settings(
        model_settings_json, temperature, reasoning_effort, thinking, thinking_budget
    )

    exit_code = asyncio.run(
        run_non_interactive(
            message=prompt,
            model=model,
            working_dir=working_dir,
            shell_allow_list=shell_allow_list,
            quiet=quiet,
            stream=not no_stream,
            sandbox=sandbox,
            runtime=runtime,
            output_format=output_format,
            verbose=verbose,
            model_settings=settings,
            lean=lean,
        )
    )
    raise typer.Exit(exit_code)


@app.command()
def chat(
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Model to use (default: from config)"),
    ] = None,
    working_dir: Annotated[
        str | None,
        typer.Option("--working-dir", "-w", help="Working directory"),
    ] = None,
    sandbox: Annotated[bool, typer.Option("--sandbox", help="Run in Docker sandbox")] = False,
    runtime: Annotated[
        str, typer.Option("--runtime", help="Sandbox runtime (e.g. python-minimal)")
    ] = "python-minimal",
    resume: Annotated[
        str | None,
        typer.Option("--resume", "-r", help="Resume a session by ID"),
    ] = None,
    sessions: Annotated[
        bool,
        typer.Option("--sessions", "-s", help="Pick a previous session to resume"),
    ] = False,
    auto_approve: Annotated[
        bool,
        typer.Option("--auto-approve", help="Auto-approve all tool calls (skip HITL)"),
    ] = False,
    temperature: Annotated[
        float | None,
        typer.Option("--temperature", "-t", help="Model temperature (0.0 = deterministic)"),
    ] = None,
    reasoning_effort: Annotated[
        str | None,
        typer.Option("--reasoning-effort", help="Reasoning effort: low, medium, high"),
    ] = None,
    thinking: Annotated[
        bool,
        typer.Option("--thinking/--no-thinking", help="Enable extended thinking (Anthropic)"),
    ] = False,
    thinking_budget: Annotated[
        int | None,
        typer.Option("--thinking-budget", help="Thinking budget in tokens (Anthropic)"),
    ] = None,
    model_settings_json: Annotated[
        str | None,
        typer.Option("--model-settings", help="Model settings as JSON"),
    ] = None,
    fork: Annotated[
        bool,
        typer.Option("--fork", help="Fork from a resumed session (new session, same history)"),
    ] = False,
) -> None:
    """Start an interactive chat session."""
    from cli.init import ensure_initialized
    from cli.interactive import run_interactive

    ensure_initialized()

    settings = _build_model_settings(
        model_settings_json, temperature, reasoning_effort, thinking, thinking_budget
    )

    # --sessions flag triggers interactive picker (resume="")
    effective_resume = "" if sessions else resume

    asyncio.run(
        run_interactive(
            model=model,
            working_dir=working_dir,
            sandbox=sandbox,
            runtime=runtime,
            resume=effective_resume,
            auto_approve=auto_approve,
            model_settings=settings,
            fork_session=fork,
        )
    )


config_app = typer.Typer(name="config", help="Manage configuration.", no_args_is_help=True)
app.add_typer(config_app)


@config_app.command("show")
def config_show() -> None:
    """Show current configuration."""
    from cli.config import CliConfig, load_config

    config = load_config()
    console = Console()
    table = Table(show_header=True, header_style="bold", show_lines=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value")

    for f in fields(CliConfig):
        value = getattr(config, f.name)
        if isinstance(value, bool):
            style = "green" if value else "red"
            table.add_row(f.name, Text(str(value), style=style))
        elif value is None:
            table.add_row(f.name, Text("None", style="dim"))
        else:
            table.add_row(f.name, str(value))

    console.print(table)


@config_app.command("set")
def config_set(
    key: Annotated[str, typer.Argument(help="Config key to set")],
    value: Annotated[str, typer.Argument(help="Value to set")],
) -> None:
    """Set a configuration value."""
    from cli.config import get_config_path, set_config_value

    try:
        set_config_value(get_config_path(), key, value)
    except KeyError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from None
    typer.echo(f"Set {key} = {value}")


skills_app = typer.Typer(name="skills", help="Manage skills.", no_args_is_help=True)
app.add_typer(skills_app)


def _get_builtin_skills_dir() -> Path:
    """Return the path to the built-in skills directory."""
    return Path(__file__).parent / "skills"


def _discover_all_skills(user_dir: str | None = None) -> list[dict[str, str]]:
    """Discover all skills (built-in + user) and return name/description pairs."""
    skills: list[dict[str, str]] = []

    builtin_dir = _get_builtin_skills_dir()
    if builtin_dir.is_dir():
        for skill_dir in sorted(builtin_dir.iterdir()):
            skill_file = skill_dir / "SKILL.md"
            if skill_file.is_file():
                name, desc = _parse_skill_frontmatter(skill_file)
                skills.append(
                    {
                        "name": name,
                        "description": desc,
                        "path": str(skill_file),
                        "source": "built-in",
                    }
                )

    if user_dir:
        user_path = Path(user_dir)
        if user_path.is_dir():
            for skill_dir in sorted(user_path.iterdir()):
                skill_file = skill_dir / "SKILL.md"
                if skill_file.is_file():
                    name, desc = _parse_skill_frontmatter(skill_file)
                    skills.append(
                        {
                            "name": name,
                            "description": desc,
                            "path": str(skill_file),
                            "source": "user",
                        }
                    )

    return skills


def _parse_skill_frontmatter(path: Path) -> tuple[str, str]:
    """Parse name and description from SKILL.md YAML frontmatter."""
    content = path.read_text()
    name = path.parent.name
    description = ""

    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().splitlines():
                line = line.strip()
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("description:"):
                    description = line.split(":", 1)[1].strip().strip('"').strip("'")

    return name, description


@skills_app.command("list")
def skills_list(
    directory: Annotated[
        str | None,
        typer.Option("--dir", "-d", help="Additional skills directory"),
    ] = None,
) -> None:
    """List available skills (built-in + user)."""
    skills = _discover_all_skills(directory)

    if not skills:
        typer.echo("No skills found.")
        return

    console = Console()
    table = Table(show_header=True, header_style="bold")
    table.add_column("Name", style="cyan")
    table.add_column("Description")
    table.add_column("Source", style="dim")

    for s in skills:
        table.add_row(s["name"], s["description"], s["source"])

    console.print(table)


@skills_app.command("info")
def skills_info(
    name: Annotated[str, typer.Argument(help="Skill name")],
) -> None:
    """Show details for a specific skill."""
    from rich.markdown import Markdown
    from rich.panel import Panel

    skills = _discover_all_skills()
    for s in skills:
        if s["name"] == name:
            info_console = Console()
            content = Path(s["path"]).read_text()

            body_text = content
            if content.startswith("---"):
                fm_parts = content.split("---", 2)
                if len(fm_parts) >= 3:
                    body_text = fm_parts[2].strip()

            header = (
                f"[dim]Description:[/dim] {s['description']}\n"
                f"[dim]Source:[/dim]      {s['source']}\n"
                f"[dim]Path:[/dim]        {s['path']}"
            )
            info_console.print()
            info_console.print(
                Panel(header, title=f"[bold cyan]{s['name']}[/bold cyan]", padding=(0, 1))
            )
            if body_text:
                info_console.print()
                info_console.print(Markdown(body_text))
            return

    typer.echo(f"Skill '{name}' not found.", err=True)
    raise typer.Exit(1)


@skills_app.command("create")
def skills_create(
    name: Annotated[str, typer.Argument(help="Skill name (lowercase, hyphens)")],
    directory: Annotated[str, typer.Option("--dir", "-d", help="Output directory")] = "./skills",
) -> None:
    """Create a new skill scaffold."""
    skill_dir = Path(directory) / name
    skill_file = skill_dir / "SKILL.md"
    if skill_file.exists():
        typer.echo(f"Skill already exists at {skill_file}", err=True)
        raise typer.Exit(1)

    skill_dir.mkdir(parents=True, exist_ok=True)
    template = f"""---
name: {name}
description: ""
---

# {name}

Instructions for this skill go here.
"""
    skill_file.write_text(template)
    typer.echo(f"Created skill scaffold at {skill_dir}/")


from apps.swebench_agent.cli import swebench_app  # noqa: E402

app.add_typer(swebench_app)

providers_app = typer.Typer(
    name="providers", help="Model provider information.", no_args_is_help=True
)
app.add_typer(providers_app)


@providers_app.command("list")
def providers_list() -> None:
    """List all supported model providers."""
    from cli.providers import PROVIDERS, validate_provider_env

    console = Console()
    table = Table(show_header=True, header_style="bold", show_lines=False)
    table.add_column("Provider", style="cyan")
    table.add_column("Name")
    table.add_column("Description")
    table.add_column("Env Var(s)")
    table.add_column("Status")

    for prefix, info in sorted(PROVIDERS.items()):
        missing = validate_provider_env(prefix)
        if not info.env_vars:
            status = Text("ready", style="green")
        elif missing:
            status = Text("missing key", style="red")
        else:
            status = Text("ready", style="green")

        env_str = ", ".join(info.env_vars) if info.env_vars else "-"
        table.add_row(prefix, info.name, info.description, env_str, status)

    console.print(table)
    console.print(
        '\n[dim]Usage: pydantic-deep run "task" --model provider:model-name[/dim]',
    )
    console.print(
        "[dim]Example: pydantic-deep chat --model openrouter:openai/gpt-5.2-codex[/dim]",
    )


@providers_app.command("check")
def providers_check(
    model: Annotated[
        str, typer.Argument(help="Model string to check (e.g. openrouter:openai/gpt-5)")
    ],
) -> None:
    """Check if a model provider is properly configured."""
    from cli.providers import format_provider_error, parse_model_string

    error = format_provider_error(model)
    console = Console()
    if error:
        console.print(f"[red]{error}[/red]")
        raise typer.Exit(1)

    provider, model_name = parse_model_string(model)
    console.print(f"[green]Provider '{provider}' is ready.[/green] Model: {model_name}")


threads_app = typer.Typer(name="threads", help="Manage conversation threads.", no_args_is_help=True)
app.add_typer(threads_app)


@threads_app.command("list")
def threads_list(
    directory: Annotated[
        str | None,
        typer.Option("--dir", "-d", help="Threads directory"),
    ] = None,
) -> None:
    """List saved conversation threads."""
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    from cli.config import get_sessions_dir

    store_path = Path(directory) if directory else get_sessions_dir()
    if not store_path.exists():
        typer.echo("No threads found.")
        return

    # Each session is a subdirectory with messages.json
    sessions: list[tuple[str, int]] = []
    for session_dir in sorted(store_path.iterdir()):
        if not session_dir.is_dir():
            continue
        messages_file = session_dir / "messages.json"
        if messages_file.exists():
            try:
                raw = messages_file.read_bytes()
                if raw:
                    messages = ModelMessagesTypeAdapter.validate_json(raw)
                    sessions.append((session_dir.name, len(messages)))
            except Exception:
                pass

    if not sessions:
        typer.echo("No threads found.")
        return

    console = Console()
    table = Table(show_header=True, header_style="bold")
    table.add_column("Session ID", style="cyan", width=14)
    table.add_column("Messages", justify="right")

    for sid, msg_count in sessions:
        table.add_row(sid, str(msg_count))

    console.print(table)


@threads_app.command("delete")
def threads_delete(
    thread_id: Annotated[str, typer.Argument(help="Thread ID (or prefix)")],
    directory: Annotated[
        str | None,
        typer.Option("--dir", "-d", help="Threads directory"),
    ] = None,
) -> None:
    """Delete a conversation thread."""
    import shutil

    from cli.config import get_sessions_dir

    store_path = Path(directory) if directory else get_sessions_dir()
    if not store_path.exists():
        typer.echo("No threads found.", err=True)
        raise typer.Exit(1)

    # Find session directory by prefix match
    match_dir = None
    for session_dir in store_path.iterdir():
        if session_dir.is_dir() and session_dir.name.startswith(thread_id):
            match_dir = session_dir
            break

    if match_dir is None:
        typer.echo(f"Thread '{thread_id}' not found.", err=True)
        raise typer.Exit(1)

    shutil.rmtree(match_dir)
    typer.echo(f"Deleted thread {match_dir.name}")


@threads_app.command("export")
def threads_export(
    thread_id: Annotated[str, typer.Argument(help="Thread ID (or prefix)")],
    directory: Annotated[
        str | None,
        typer.Option("--dir", "-d", help="Threads directory"),
    ] = None,
    output_format: Annotated[
        str, typer.Option("--format", "-f", help="Export format: json or markdown")
    ] = "markdown",
) -> None:
    """Export a conversation thread."""
    import json

    from pydantic_ai.messages import ModelMessagesTypeAdapter

    from cli.config import get_sessions_dir

    store_path = Path(directory) if directory else get_sessions_dir()
    if not store_path.exists():
        typer.echo("No threads found.", err=True)
        raise typer.Exit(1)

    # Find session directory by prefix match
    session_dir = None
    for d in store_path.iterdir():
        if d.is_dir() and d.name.startswith(thread_id):
            session_dir = d
            break

    if session_dir is None:
        typer.echo(f"Thread '{thread_id}' not found.", err=True)
        raise typer.Exit(1)

    messages_file = session_dir / "messages.json"
    if not messages_file.exists():
        typer.echo("Thread has no history.", err=True)
        raise typer.Exit(1)

    raw = messages_file.read_bytes()
    messages = list(ModelMessagesTypeAdapter.validate_json(raw))

    if output_format == "json":
        data = {
            "id": session_dir.name,
            "message_count": len(messages),
            "messages": [str(m) for m in messages],
        }
        typer.echo(json.dumps(data, indent=2, default=str))
    else:
        typer.echo(f"# Thread: {session_dir.name}")
        typer.echo(f"\nMessages: {len(messages)}")
        typer.echo()
        for msg in messages:
            typer.echo(f"---\n{msg}\n")


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
