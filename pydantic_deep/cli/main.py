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
from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(
    name="pydantic-deep",
    help="Deep Agent CLI — AI coding assistant powered by pydantic-ai.",
    no_args_is_help=True,
)


# ---------------------------------------------------------------------------
# Core commands: run + chat
# ---------------------------------------------------------------------------


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
    sandbox: Annotated[
        bool, typer.Option("--sandbox", help="Run in Docker sandbox")
    ] = False,
    runtime: Annotated[
        str, typer.Option("--runtime", help="Sandbox runtime (e.g. python-minimal)")
    ] = "python-minimal",
) -> None:
    """Run a task non-interactively (benchmark mode)."""
    from pydantic_deep.cli.non_interactive import run_non_interactive

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
    sandbox: Annotated[
        bool, typer.Option("--sandbox", help="Run in Docker sandbox")
    ] = False,
    runtime: Annotated[
        str, typer.Option("--runtime", help="Sandbox runtime (e.g. python-minimal)")
    ] = "python-minimal",
) -> None:
    """Start an interactive chat session."""
    from pydantic_deep.cli.interactive import run_interactive

    asyncio.run(
        run_interactive(
            model=model,
            working_dir=working_dir,
            sandbox=sandbox,
            runtime=runtime,
        )
    )


# ---------------------------------------------------------------------------
# Config sub-app
# ---------------------------------------------------------------------------

config_app = typer.Typer(name="config", help="Manage configuration.", no_args_is_help=True)
app.add_typer(config_app)


@config_app.command("show")
def config_show() -> None:
    """Show current configuration."""
    from pydantic_deep.cli.config import format_config, load_config

    config = load_config()
    typer.echo(format_config(config))


@config_app.command("set")
def config_set(
    key: Annotated[str, typer.Argument(help="Config key to set")],
    value: Annotated[str, typer.Argument(help="Value to set")],
) -> None:
    """Set a configuration value."""
    from pydantic_deep.cli.config import DEFAULT_CONFIG_PATH, set_config_value

    try:
        set_config_value(DEFAULT_CONFIG_PATH, key, value)
    except KeyError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from None
    typer.echo(f"Set {key} = {value}")


# ---------------------------------------------------------------------------
# Skills sub-app
# ---------------------------------------------------------------------------

skills_app = typer.Typer(name="skills", help="Manage skills.", no_args_is_help=True)
app.add_typer(skills_app)


def _get_builtin_skills_dir() -> Path:
    """Return the path to the built-in skills directory."""
    return Path(__file__).parent / "skills"


def _discover_all_skills(user_dir: str | None = None) -> list[dict[str, str]]:
    """Discover all skills (built-in + user) and return name/description pairs."""
    skills: list[dict[str, str]] = []

    # Built-in skills — read frontmatter from SKILL.md files
    builtin_dir = _get_builtin_skills_dir()
    if builtin_dir.is_dir():
        for skill_dir in sorted(builtin_dir.iterdir()):
            skill_file = skill_dir / "SKILL.md"
            if skill_file.is_file():
                name, desc = _parse_skill_frontmatter(skill_file)
                skills.append({"name": name, "description": desc, "path": str(skill_file), "source": "built-in"})

    # User skills
    if user_dir:
        user_path = Path(user_dir)
        if user_path.is_dir():
            for skill_dir in sorted(user_path.iterdir()):
                skill_file = skill_dir / "SKILL.md"
                if skill_file.is_file():
                    name, desc = _parse_skill_frontmatter(skill_file)
                    skills.append({"name": name, "description": desc, "path": str(skill_file), "source": "user"})

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

    current_source = ""
    for s in skills:
        if s["source"] != current_source:
            if current_source:
                typer.echo()
            current_source = s["source"]
            typer.echo(f"{current_source.title()} skills:")
        typer.echo(f"  {s['name']:25s} {s['description']}")


@skills_app.command("info")
def skills_info(
    name: Annotated[str, typer.Argument(help="Skill name")],
) -> None:
    """Show details for a specific skill."""
    skills = _discover_all_skills()
    for s in skills:
        if s["name"] == name:
            typer.echo(f"Name: {s['name']}")
            typer.echo(f"Description: {s['description']}")
            typer.echo(f"Path: {s['path']}")
            typer.echo()
            # Print the full content
            content = Path(s["path"]).read_text()
            typer.echo(content)
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


# ---------------------------------------------------------------------------
# Threads sub-app
# ---------------------------------------------------------------------------

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
    from pydantic_deep.cli.config import DEFAULT_THREADS_DIR
    from pydantic_deep.toolsets.checkpointing import FileCheckpointStore

    store_path = Path(directory) if directory else DEFAULT_THREADS_DIR
    if not store_path.exists():
        typer.echo("No threads found.")
        return

    store = FileCheckpointStore(store_path)
    checkpoints = asyncio.run(store.list_all())
    if not checkpoints:
        typer.echo("No threads found.")
        return

    for cp in checkpoints:
        short_id = cp.id[:8]
        typer.echo(f"  {short_id}  {cp.label:30s}  {cp.message_count} msgs")


@threads_app.command("delete")
def threads_delete(
    thread_id: Annotated[str, typer.Argument(help="Thread ID (or prefix)")],
    directory: Annotated[
        str | None,
        typer.Option("--dir", "-d", help="Threads directory"),
    ] = None,
) -> None:
    """Delete a conversation thread."""
    from pydantic_deep.cli.config import DEFAULT_THREADS_DIR
    from pydantic_deep.toolsets.checkpointing import FileCheckpointStore

    store_path = Path(directory) if directory else DEFAULT_THREADS_DIR
    if not store_path.exists():
        typer.echo("No threads found.", err=True)
        raise typer.Exit(1)

    store = FileCheckpointStore(store_path)
    checkpoints = asyncio.run(store.list_all())
    match = next((cp for cp in checkpoints if cp.id.startswith(thread_id)), None)
    if match is None:
        typer.echo(f"Thread '{thread_id}' not found.", err=True)
        raise typer.Exit(1)

    asyncio.run(store.remove(match.id))
    typer.echo(f"Deleted thread {match.id[:8]} ({match.label})")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    """Entry point for the CLI."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
