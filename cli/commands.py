"""Custom command discovery, loading, and invocation.

Commands are ``.md`` files with YAML frontmatter that act as prompt
templates.  The user types ``/command-name args`` in interactive chat,
and the body (with ``$ARGUMENTS`` substituted) is sent to the agent as
a user prompt.

Discovery scopes (project wins):
1. Built-in  → ``cli/commands/*.md``
2. User      → ``~/.pydantic-deep/commands/*.md``
3. Project   → ``.pydantic-deep/commands/*.md``
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Command:
    """A loaded custom command."""

    name: str
    description: str
    argument_hint: str
    body: str
    source: str  # "built-in" | "user" | "project"


def _builtin_dir() -> Path:
    return Path(__file__).parent / "commands"


def _user_dir() -> Path:
    return Path.home() / ".pydantic-deep" / "commands"


def _project_dir() -> Path | None:
    project = Path.cwd() / ".pydantic-deep" / "commands"
    return project if project.is_dir() else None


def _parse_command(path: Path, source: str) -> Command:
    """Parse a command ``.md`` file into a Command."""
    content = path.read_text()
    name = path.stem
    description = ""
    argument_hint = ""
    body = content

    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].strip().splitlines():
                line = line.strip()
                if line.startswith("description:"):
                    description = line.split(":", 1)[1].strip().strip("\"'")
                elif line.startswith("argument-hint:"):
                    argument_hint = line.split(":", 1)[1].strip().strip("\"'")
            body = parts[2].strip()

    return Command(
        name=name,
        description=description,
        argument_hint=argument_hint,
        body=body,
        source=source,
    )


def _scan_dir(directory: Path, source: str) -> dict[str, Command]:
    """Scan a directory for ``.md`` command files."""
    commands: dict[str, Command] = {}
    if not directory.is_dir():
        return commands
    for path in sorted(directory.iterdir()):
        if path.suffix == ".md" and path.is_file():
            cmd = _parse_command(path, source)
            commands[cmd.name] = cmd
    return commands


def discover_commands() -> list[Command]:
    """Discover all custom commands across all scopes.

    Returns deduplicated list — project overrides user overrides built-in.
    """
    merged: dict[str, Command] = {}

    # 1. Built-in (lowest priority)
    merged.update(_scan_dir(_builtin_dir(), "built-in"))

    # 2. User
    merged.update(_scan_dir(_user_dir(), "user"))

    # 3. Project (highest priority)
    proj = _project_dir()
    if proj:
        merged.update(_scan_dir(proj, "project"))

    return sorted(merged.values(), key=lambda c: c.name)


def load_command(name: str) -> Command | None:
    """Load a single command by name.  Project > user > built-in."""
    proj = _project_dir()
    if proj:
        path = proj / f"{name}.md"
        if path.is_file():
            return _parse_command(path, "project")

    user = _user_dir() / f"{name}.md"
    if user.is_file():
        return _parse_command(user, "user")

    builtin = _builtin_dir() / f"{name}.md"
    if builtin.is_file():
        return _parse_command(builtin, "built-in")

    return None


def invoke_command(cmd: Command, arguments: str) -> str:
    """Substitute ``$ARGUMENTS`` and return the final prompt."""
    return cmd.body.replace("$ARGUMENTS", arguments)


__all__ = [
    "Command",
    "discover_commands",
    "invoke_command",
    "load_command",
]
