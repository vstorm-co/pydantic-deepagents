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

    # Non-blocking update notification (uses 24-hour file cache)
    from apps.cli.update import check_for_update

    _upd = check_for_update()
    if _upd:
        Console().print(
            f"[yellow]Update available:[/yellow] "
            f"v{_upd.current} → [bold]v{_upd.latest}[/bold]  "
            f"Run: [cyan]pydantic-deep update[/cyan]"
        )

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
    sandbox: Annotated[
        str | None,
        typer.Option("--sandbox", "-s", help="Sandbox backend: local or docker (from config)"),
    ] = None,
    workspace: Annotated[
        str | None,
        typer.Option(
            "--workspace",
            help=(
                "Named Docker workspace shared across threads. "
                "Packages and state persist between sessions. "
                "Implies --sandbox docker."
            ),
        ),
    ] = None,
) -> None:
    """Launch the Textual-based TUI (rich interactive interface)."""
    from apps.cli.init import ensure_initialized
    from apps.cli.tui import run_tui

    # --workspace implies --sandbox docker
    if workspace and not sandbox:
        sandbox = "docker"

    ensure_initialized()
    run_tui(
        model=model,
        working_dir=working_dir or os.getcwd(),
        sandbox=sandbox,
        workspace=workspace,
    )


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
    sandbox: Annotated[
        str | None,
        typer.Option("--sandbox", "-s", help="Sandbox backend: local or docker (from config)"),
    ] = None,
    workspace: Annotated[
        str | None,
        typer.Option(
            "--workspace",
            help=(
                "Named Docker workspace shared across threads. "
                "Packages and state persist between sessions. "
                "Implies --sandbox docker."
            ),
        ),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Stream progress to stderr"),
    ] = False,
    include_browser: Annotated[
        bool | None,
        typer.Option(
            "--browser/--no-browser",
            help="Enable Playwright browser automation (requires pydantic-deep[browser])",
        ),
    ] = None,
    browser_headless: Annotated[
        bool | None,
        typer.Option(
            "--browser-headless/--browser-headed",
            help="Browser window mode: headless (hidden) or headed (visible, default)",
        ),
    ] = None,
    include_liteparse: Annotated[
        bool | None,
        typer.Option(
            "--liteparse/--no-liteparse",
            help="Enable LiteParse document parsing (requires pydantic-deep[liteparse] + Node.js)",
        ),
    ] = None,
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
        pydantic-deep run "Analyze data" --sandbox docker
        pydantic-deep run "Train model" --workspace ml-env
    """
    from apps.cli.run import execute_headless

    # --workspace implies --sandbox docker
    if workspace and not sandbox:
        sandbox = "docker"

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
            sandbox=sandbox,
            workspace=workspace,
            verbose=verbose,
            include_browser=include_browser,
            browser_headless=browser_headless,
            include_liteparse=include_liteparse,
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


# ── Sandbox subcommands ────────────────────────────────────────

sandbox_app = typer.Typer(
    name="sandbox", help="Manage Docker sandbox workspaces.", no_args_is_help=True
)
app.add_typer(sandbox_app)


def _get_project_container_prefix() -> str:
    """Return the Docker container name prefix for the current project."""
    import hashlib

    dir_hash = hashlib.md5(str(Path.cwd().resolve()).encode()).hexdigest()[:8]
    return f"pydantic-deep-{dir_hash}-"


@sandbox_app.command("list")
def sandbox_list() -> None:
    """List Docker sandbox workspaces for this project."""
    try:
        import docker
    except ImportError:
        typer.echo(
            "Docker package not installed. Install with: pip install pydantic-ai-backend[docker]",
            err=True,
        )
        raise typer.Exit(1) from None

    prefix = _get_project_container_prefix()
    client = docker.from_env()

    containers = [c for c in client.containers.list(all=True) if c.name.startswith(prefix)]

    if not containers:
        typer.echo("No sandbox workspaces found for this project.")
        return

    console = Console()
    table = Table(show_header=True, header_style="bold")
    table.add_column("Workspace", style="cyan")
    table.add_column("Status")
    table.add_column("Image", style="dim")
    table.add_column("Created", style="dim")

    for c in sorted(containers, key=lambda x: x.name):
        # Strip project prefix to show short workspace name
        workspace_name = c.name[len(prefix) :]
        status_style = "green" if c.status == "running" else "yellow"
        table.add_row(
            workspace_name,
            Text(c.status, style=status_style),
            c.image.tags[0] if c.image.tags else str(c.image.short_id),
            c.attrs.get("Created", "")[:19],
        )

    console.print(table)
    typer.echo(f"\nProject: {Path.cwd()}")
    typer.echo(f"Prefix:  {prefix}*")


@sandbox_app.command("stop")
def sandbox_stop(
    name: Annotated[
        str | None,
        typer.Argument(help="Workspace name to stop (or 'all')"),
    ] = None,
    remove: Annotated[
        bool,
        typer.Option("--rm", help="Remove workspace container after stopping"),
    ] = False,
) -> None:
    """Stop sandbox workspaces for this project.

    Examples:
        pydantic-deep sandbox stop ml-env     # Stop one workspace
        pydantic-deep sandbox stop all        # Stop all for this project
        pydantic-deep sandbox stop all --rm   # Stop and remove all
    """
    try:
        import docker
    except ImportError:
        typer.echo(
            "Docker package not installed. Install with: pip install pydantic-ai-backend[docker]",
            err=True,
        )
        raise typer.Exit(1) from None

    if name is None:
        typer.echo("Provide a workspace name or 'all'.", err=True)
        raise typer.Exit(1)

    prefix = _get_project_container_prefix()
    client = docker.from_env()

    if name == "all":
        targets = [c for c in client.containers.list(all=True) if c.name.startswith(prefix)]
    else:
        full_name = f"{prefix}{name}"
        try:
            targets = [client.containers.get(full_name)]
        except docker.errors.NotFound:
            typer.echo(f"Workspace '{name}' not found.", err=True)
            raise typer.Exit(1) from None

    for c in targets:
        short = c.name[len(prefix) :]
        if c.status == "running":
            c.stop()
            typer.echo(f"Stopped: {short}")
        if remove:
            c.remove()
            typer.echo(f"Removed: {short}")
        elif c.status != "running":
            typer.echo(f"Already stopped: {short}")

    if not targets:
        typer.echo("No containers to stop.")


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


@app.command()
def update() -> None:
    """Update pydantic-deep to the latest version."""
    from apps.cli.update import run_update

    Console().print("Updating pydantic-deep...")
    raise typer.Exit(run_update())


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
