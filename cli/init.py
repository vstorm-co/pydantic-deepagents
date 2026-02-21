"""Project initialization for pydantic-deep CLI.

Creates the ``.pydantic-deep/`` directory structure with scaffolding:
config, memory template, skills (copied from built-in), sessions dir.
"""

from __future__ import annotations

import shutil
from pathlib import Path


_AGENT_MD_TEMPLATE = """\
# Project Context

Describe your project here. This file is read by pydantic-deep at startup
to understand the project context.

## Tech Stack

- ...

## Key Files

- ...
"""

_MEMORY_MD_TEMPLATE = """\
# Agent Memory

This file is automatically maintained by pydantic-deep.
The agent reads and updates this file across sessions.
"""

_DEFAULT_CONFIG_TOML = """\
model = "openrouter:openai/gpt-4.1"
show_cost = true
show_tokens = true
"""


def init_project(root: Path | None = None, *, quiet: bool = False) -> Path:
    """Initialize ``.pydantic-deep/`` directory with scaffolding.

    Idempotent — safe to call multiple times. Existing files are not
    overwritten.

    Args:
        root: Project root directory. Defaults to CWD.
        quiet: Suppress output messages.

    Returns:
        Path to the ``.pydantic-deep/`` directory.
    """
    root = root or Path.cwd()
    pd_dir = root / ".pydantic-deep"

    # Create directory structure
    pd_dir.mkdir(exist_ok=True)
    (pd_dir / "skills").mkdir(exist_ok=True)
    (pd_dir / "sessions").mkdir(exist_ok=True)

    # Copy built-in skills (skip if already populated)
    _copy_builtin_skills(pd_dir / "skills", quiet=quiet)

    # Create memory template
    memory_dir = pd_dir / "main"
    memory_dir.mkdir(exist_ok=True)
    memory_file = memory_dir / "MEMORY.md"
    if not memory_file.exists():
        memory_file.write_text(_MEMORY_MD_TEMPLATE)
        if not quiet:
            _log(f"Created {memory_file.relative_to(root)}")

    # Create AGENT.md in project root (if doesn't exist)
    agent_md = root / "AGENT.md"
    if not agent_md.exists():
        agent_md.write_text(_AGENT_MD_TEMPLATE)
        if not quiet:
            _log(f"Created {agent_md.name}")

    # Create default config.toml (if doesn't exist)
    config_file = pd_dir / "config.toml"
    if not config_file.exists():
        config_file.write_text(_DEFAULT_CONFIG_TOML)
        if not quiet:
            _log(f"Created {config_file.relative_to(root)}")

    if not quiet:
        _log(f"Initialized {pd_dir.relative_to(root)}/")

    return pd_dir


def _copy_builtin_skills(target_dir: Path, *, quiet: bool = False) -> None:
    """Copy built-in skills from cli/skills/ to target directory.

    Only copies skills that don't already exist in the target.
    """
    builtin_dir = Path(__file__).parent / "skills"
    if not builtin_dir.is_dir():
        return

    for skill_dir in sorted(builtin_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            continue

        target_skill_dir = target_dir / skill_dir.name
        if target_skill_dir.exists():
            continue

        shutil.copytree(skill_dir, target_skill_dir)
        if not quiet:
            _log(f"  Copied skill: {skill_dir.name}")


def ensure_initialized(root: Path | None = None) -> Path:
    """Ensure ``.pydantic-deep/`` exists, creating it if needed.

    Lightweight wrapper — only runs ``init_project`` if the directory
    doesn't exist yet.

    Returns:
        Path to the ``.pydantic-deep/`` directory.
    """
    root = root or Path.cwd()
    pd_dir = root / ".pydantic-deep"
    if not pd_dir.exists():
        return init_project(root)
    return pd_dir


def _log(msg: str) -> None:
    """Print a message to stderr."""
    import sys

    print(msg, file=sys.stderr)


__all__ = ["ensure_initialized", "init_project"]
