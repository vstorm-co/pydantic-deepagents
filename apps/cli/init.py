"""Project initialization for pydantic-deep CLI.

Creates the `.pydantic-deep/` directory structure with scaffolding: config,
skills (copied from built-in), sessions dir. Context files (AGENTS.md, SOUL.md,
MEMORY.md) are intentionally NOT scaffolded — the agent creates them when it
decides to, via `/init`, or the user makes them by hand.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

# No `model` line here on purpose: the model is a user-level choice made during
# onboarding and stored in ~/.pydantic-deep/config.toml. Its absence from a fresh
# project config is what triggers first-run onboarding.
_DEFAULT_CONFIG_TOML = """\
show_cost = true
show_tokens = true

# Tools that require user approval before execution
# Edit this list directly, or change other settings with /settings in the CLI
approve_tools = ["execute"]
"""


def init_project(root: Path | None = None, *, quiet: bool = False) -> Path:
    """Initialize `.pydantic-deep/` directory with scaffolding.

    Idempotent — safe to call multiple times. Existing files are not
    overwritten.

    Args:
        root: Project root directory. Defaults to CWD.
        quiet: Suppress output messages.

    Returns:
        Path to the `.pydantic-deep/` directory.
    """
    root = root or Path.cwd()
    pd_dir = root / ".pydantic-deep"

    # Create directory structure
    pd_dir.mkdir(exist_ok=True)
    (pd_dir / "skills").mkdir(exist_ok=True)
    (pd_dir / "sessions").mkdir(exist_ok=True)

    # Copy built-in skills (skip if already populated)
    _copy_builtin_skills(pd_dir / "skills", quiet=quiet)

    # Memory dir exists so the agent can write MEMORY.md there on demand, but the
    # file itself is NOT scaffolded. AGENTS.md / SOUL.md / MEMORY.md are created
    # by the agent when it decides to (write_memory / write_file), by `/init`, or
    # by the user — never auto-generated on launch.
    (pd_dir / "main").mkdir(exist_ok=True)

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
    """Ensure `.pydantic-deep/` exists with all scaffolding.

    Idempotent — calls `init_project` which only creates missing
    files and directories, never overwrites existing ones.

    Returns:
        Path to the `.pydantic-deep/` directory.
    """
    root = root or Path.cwd()
    return init_project(root, quiet=True)


def _log(msg: str) -> None:
    """Print a message to stderr."""

    print(msg, file=sys.stderr)


__all__ = ["ensure_initialized", "init_project"]
