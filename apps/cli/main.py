"""CLI entry point for pydantic-deep.

Usage:
    pydantic-deep                           # Launch TUI (default)
    pydantic-deep tui [-m model] [-w dir]   # Launch TUI
    pydantic-deep run "task description"    # Headless non-interactive run
    pydantic-deep init                      # Initialize project
    pydantic-deep config show               # Show configuration
    pydantic-deep skills list               # List available skills
    pydantic-deep threads list              # List saved threads
"""

from __future__ import annotations

import json
import os
from dataclasses import fields
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

app = typer.Typer(
    name="pydantic-deep",
    help="Deep Agent CLI — AI coding assistant powered by pydantic-ai.",
    invoke_without_command=True,
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


@app.callback(invoke_without_command=True)
def _main_callback(
    ctx: typer.Context,
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

        load_dotenv(Path.home() / ".pydantic-deep" / ".env", override=False)
        load_dotenv(Path.cwd() / ".pydantic-deep" / ".env", override=True)
        load_dotenv()
    except ImportError:  # pragma: no cover
        pass

    if not logfire_enabled:
        from apps.cli.config import load_config

        config = load_config()
        logfire_enabled = config.logfire

    if logfire_enabled:
        _setup_logfire()

    # Default: launch TUI when no subcommand is given
    if ctx.invoked_subcommand is None:
        from apps.cli.init import ensure_initialized
        from apps.cli.tui import run_tui

        ensure_initialized()
        run_tui(working_dir=os.getcwd())


@app.command()
def tui(
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Model to use (default: from config)"),
    ] = None,
    working_dir: Annotated[
        str | None,
        typer.Option("--working-dir", "-w", help="Working directory"),
    ] = None,
) -> None:
    """Launch the Textual-based TUI (rich interactive interface)."""
    from apps.cli.init import ensure_initialized
    from apps.cli.tui import run_tui

    ensure_initialized()
    run_tui(model=model, working_dir=working_dir or os.getcwd())


@app.command()
def run(
    task: Annotated[
        str | None,
        typer.Argument(help="Task description (or use --task-file)"),
    ] = None,
    task_file: Annotated[
        Path | None,
        typer.Option("--task-file", "-f", help="Read task from file"),
    ] = None,
    working_dir: Annotated[
        str | None,
        typer.Option("--working-dir", "-w", help="Working directory"),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Model to use (default: from config)"),
    ] = None,
    output_json: Annotated[
        bool,
        typer.Option("--json", help="Output result as JSON"),
    ] = False,
    max_turns: Annotated[
        int | None,
        typer.Option("--max-turns", help="Maximum number of agent turns"),
    ] = None,
    timeout: Annotated[
        int | None,
        typer.Option("--timeout", help="Timeout in seconds"),
    ] = None,
    # Feature flags — None means "use config.toml default" (same as TUI)
    web_search: Annotated[
        bool | None,
        typer.Option("--web-search/--no-web-search", help="Enable web search (from config)"),
    ] = None,
    web_fetch: Annotated[
        bool | None,
        typer.Option("--web-fetch/--no-web-fetch", help="Enable web fetch (default: from config)"),
    ] = None,
    thinking: Annotated[
        str | None,
        typer.Option("--thinking", help="Thinking effort: minimal/low/medium/high/xhigh or false"),
    ] = None,
    include_todo: Annotated[
        bool | None,
        typer.Option("--todo/--no-todo", help="Enable task planning (default: from config)"),
    ] = None,
    include_subagents: Annotated[
        bool | None,
        typer.Option(
            "--subagents/--no-subagents", help="Enable subagent delegation (default: from config)"
        ),
    ] = None,
    include_skills: Annotated[
        bool | None,
        typer.Option("--skills/--no-skills", help="Enable skills (default: from config)"),
    ] = None,
    include_plan: Annotated[
        bool | None,
        typer.Option("--plan/--no-plan", help="Enable plan mode (default: from config)"),
    ] = None,
    include_memory: Annotated[
        bool | None,
        typer.Option("--memory/--no-memory", help="Enable persistent memory (from config)"),
    ] = None,
    include_teams: Annotated[
        bool | None,
        typer.Option("--teams/--no-teams", help="Enable agent teams (from config)"),
    ] = None,
    context_discovery: Annotated[
        bool | None,
        typer.Option("--context/--no-context", help="Auto-discover AGENTS.md (from config)"),
    ] = None,
    temperature: Annotated[
        float | None,
        typer.Option("--temperature", help="Sampling temperature (default: 0.0)"),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Stream progress to stderr"),
    ] = False,
) -> None:
    """Run a task non-interactively (headless mode).

    Executes a single task and prints the result to stdout.
    Designed for benchmarks, CI/CD pipelines, and scripted automation.

    All feature flags default to the same values as the TUI (from
    .pydantic-deep/config.toml). Use --no-web-search, --no-thinking,
    etc. to override specific features.

    Examples:
        pydantic-deep run "Fix the failing test in test_auth.py"
        pydantic-deep run --task-file task.md --json
        pydantic-deep run "Refactor utils.py" --max-turns 50 --timeout 300
        pydantic-deep run "Research X" --web-search --web-fetch
        pydantic-deep run "Fix bug" --no-web-search --no-web-fetch --thinking false
    """
    from apps.cli.run import execute_headless

    if task is None and task_file is None:
        typer.echo("Error: provide a task argument or --task-file", err=True)
        raise typer.Exit(1)

    if task_file is not None:
        if not task_file.exists():
            typer.echo(f"Error: task file not found: {task_file}", err=True)
            raise typer.Exit(1)
        task_text = task_file.read_text().strip()
    else:
        assert task is not None
        task_text = task

    if not task_text:
        typer.echo("Error: task is empty", err=True)
        raise typer.Exit(1)

    import asyncio

    result = asyncio.run(
        execute_headless(
            task=task_text,
            working_dir=working_dir or os.getcwd(),
            model=model,
            output_json=output_json,
            max_turns=max_turns,
            timeout=timeout,
            web_search=web_search,
            web_fetch=web_fetch,
            thinking=thinking,
            include_todo=include_todo,
            include_subagents=include_subagents,
            include_skills=include_skills,
            include_plan=include_plan,
            include_memory=include_memory,
            include_teams=include_teams,
            context_discovery=context_discovery,
            temperature=temperature,
            verbose=verbose,
        )
    )
    raise typer.Exit(result)


@app.command()
def init(
    directory: Annotated[
        str | None,
        typer.Option("--dir", "-d", help="Project directory (default: CWD)"),
    ] = None,
) -> None:
    """Initialize .pydantic-deep/ project directory with scaffolding."""
    from apps.cli.init import init_project

    root = Path(directory) if directory else Path.cwd()
    init_project(root)


# ── Config subcommands ──────────────────────────────────────────

config_app = typer.Typer(name="config", help="Manage configuration.", no_args_is_help=True)
app.add_typer(config_app)


@config_app.command("show")
def config_show() -> None:
    """Show current configuration."""
    from apps.cli.config import CliConfig, load_config

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
    from apps.cli.config import get_config_path, set_config_value

    try:
        set_config_value(get_config_path(), key, value)
    except KeyError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from None
    typer.echo(f"Set {key} = {value}")


# ── Skills subcommands ──────────────────────────────────────────

skills_app = typer.Typer(name="skills", help="Manage skills.", no_args_is_help=True)
app.add_typer(skills_app)


def _get_builtin_skills_dir() -> Path:
    return Path(__file__).parent / "skills"


def _discover_all_skills(user_dir: str | None = None) -> list[dict[str, str]]:
    """Discover all skills from all sources."""
    seen_names: set[str] = set()
    skills: list[dict[str, str]] = []

    def _scan_dir(directory: Path, source: str) -> None:
        if not directory.is_dir():
            return
        for skill_dir in sorted(directory.iterdir()):
            skill_file = skill_dir / "SKILL.md"
            if skill_file.is_file():
                name, desc = _parse_skill_frontmatter(skill_file)
                if name in seen_names:
                    skills[:] = [s for s in skills if s["name"] != name]
                seen_names.add(name)
                skills.append(
                    {"name": name, "description": desc, "path": str(skill_file), "source": source}
                )

    _scan_dir(_get_builtin_skills_dir(), "built-in")
    _scan_dir(Path.home() / ".pydantic-deep" / "skills", "user")
    _scan_dir(Path.cwd() / ".pydantic-deep" / "skills", "project")
    if user_dir:
        _scan_dir(Path(user_dir), "custom")
    return skills


def _parse_skill_frontmatter(path: Path) -> tuple[str, str]:
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
def skills_list(directory: Annotated[str | None, typer.Option("--dir", "-d")] = None) -> None:
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
def skills_info(name: Annotated[str, typer.Argument(help="Skill name")]) -> None:
    """Show details for a specific skill."""
    from rich.markdown import Markdown
    from rich.panel import Panel

    skills = _discover_all_skills()
    for s in skills:
        if s["name"] == name:
            console = Console()
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
            console.print()
            console.print(
                Panel(header, title=f"[bold cyan]{s['name']}[/bold cyan]", padding=(0, 1))
            )
            if body_text:
                console.print()
                console.print(Markdown(body_text))
            return
    typer.echo(f"Skill '{name}' not found.", err=True)
    raise typer.Exit(1)


@skills_app.command("create")
def skills_create(
    name: Annotated[str, typer.Argument(help="Skill name")],
    directory: Annotated[str, typer.Option("--dir", "-d")] = "./skills",
) -> None:
    """Create a new skill scaffold."""
    skill_dir = Path(directory) / name
    skill_file = skill_dir / "SKILL.md"
    if skill_file.exists():
        typer.echo(f"Skill already exists at {skill_file}", err=True)
        raise typer.Exit(1)
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file.write_text(
        f"---\nname: {name}\n"
        f'description: ""\n'
        f"---\n\n# {name}\n\n"
        f"Instructions for this skill go here.\n"
    )
    typer.echo(f"Created skill scaffold at {skill_dir}/")


# ── Threads subcommands ─────────────────────────────────────────

threads_app = typer.Typer(name="threads", help="Manage conversation threads.", no_args_is_help=True)
app.add_typer(threads_app)


@threads_app.command("list")
def threads_list(directory: Annotated[str | None, typer.Option("--dir", "-d")] = None) -> None:
    """List saved conversation threads."""
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    from apps.cli.config import get_sessions_dir

    store_path = Path(directory) if directory else get_sessions_dir()
    if not store_path.exists():
        typer.echo("No threads found.")
        return
    sessions: list[tuple[str, int]] = []
    for session_dir in sorted(store_path.iterdir()):
        if not session_dir.is_dir():
            continue
        mf = session_dir / "messages.json"
        if mf.exists():
            try:
                raw = mf.read_bytes()
                if raw:
                    sessions.append(
                        (session_dir.name, len(ModelMessagesTypeAdapter.validate_json(raw)))
                    )
            except Exception:
                pass
    if not sessions:
        typer.echo("No threads found.")
        return
    console = Console()
    table = Table(show_header=True, header_style="bold")
    table.add_column("Session ID", style="cyan", width=14)
    table.add_column("Messages", justify="right")
    for sid, mc in sessions:
        table.add_row(sid, str(mc))
    console.print(table)


@threads_app.command("delete")
def threads_delete(
    thread_id: Annotated[str, typer.Argument(help="Thread ID (or prefix)")],
    directory: Annotated[str | None, typer.Option("--dir", "-d")] = None,
) -> None:
    """Delete a conversation thread."""
    import shutil

    from apps.cli.config import get_sessions_dir

    store_path = Path(directory) if directory else get_sessions_dir()
    if not store_path.exists():
        typer.echo("No threads found.", err=True)
        raise typer.Exit(1)
    match_dir = None
    for sd in store_path.iterdir():
        if sd.is_dir() and sd.name.startswith(thread_id):
            match_dir = sd
            break
    if match_dir is None:
        typer.echo(f"Thread '{thread_id}' not found.", err=True)
        raise typer.Exit(1)
    shutil.rmtree(match_dir)
    typer.echo(f"Deleted thread {match_dir.name}")


@threads_app.command("export")
def threads_export(
    thread_id: Annotated[str, typer.Argument(help="Thread ID (or prefix)")],
    directory: Annotated[str | None, typer.Option("--dir", "-d")] = None,
    output_format: Annotated[str, typer.Option("--format", "-f")] = "markdown",
) -> None:
    """Export a conversation thread."""
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    from apps.cli.config import get_sessions_dir

    store_path = Path(directory) if directory else get_sessions_dir()
    if not store_path.exists():
        typer.echo("No threads found.", err=True)
        raise typer.Exit(1)
    session_dir = None
    for d in store_path.iterdir():
        if d.is_dir() and d.name.startswith(thread_id):
            session_dir = d
            break
    if session_dir is None:
        typer.echo(f"Thread '{thread_id}' not found.", err=True)
        raise typer.Exit(1)
    mf = session_dir / "messages.json"
    if not mf.exists():
        typer.echo("Thread has no history.", err=True)
        raise typer.Exit(1)
    messages = list(ModelMessagesTypeAdapter.validate_json(mf.read_bytes()))
    if output_format == "json":
        typer.echo(
            json.dumps(
                {
                    "id": session_dir.name,
                    "message_count": len(messages),
                    "messages": [str(m) for m in messages],
                },
                indent=2,
                default=str,
            )
        )
    else:
        typer.echo(f"# Thread: {session_dir.name}\n\nMessages: {len(messages)}\n")
        for msg in messages:
            typer.echo(f"---\n{msg}\n")


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
