"""Lightweight skill discovery for the gateway.

Mirrors the CLI's skill discovery (bundled + user + project dirs) without
importing the Textual UI, so the gateway stays light.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _skill_dirs() -> list[Path]:
    bundled = Path(__file__).resolve().parent.parent / "cli" / "skills"
    user = Path.home() / ".pydantic-deep" / "skills"
    project = Path.cwd() / ".pydantic-deep" / "skills"
    return [bundled, user, project]


def _description(skill_md: Path) -> str:
    try:
        text = skill_md.read_text()
    except OSError:
        return ""
    in_frontmatter = False
    for line in text.splitlines():
        if line.strip() == "---":
            if in_frontmatter:
                break
            in_frontmatter = True
            continue
        if in_frontmatter and line.startswith("description:"):
            return line.split(":", 1)[1].strip().strip("\"'")
    return ""


def discover_skills() -> list[dict[str, Any]]:
    """Return ``[{name, description}]`` for every discoverable skill."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for directory in _skill_dirs():
        if not directory.is_dir():
            continue
        for folder in sorted(directory.iterdir()):
            skill_md = folder / "SKILL.md"
            if not folder.is_dir() or not skill_md.exists() or folder.name in seen:
                continue
            seen.add(folder.name)
            out.append({"name": folder.name, "description": _description(skill_md)})
    return out


def _slug(name: str) -> str:
    out = "".join(c if c.isalnum() or c in "-_" else "-" for c in name.strip().lower())
    return "-".join(filter(None, out.split("-"))) or "skill"


def create_skill(name: str, description: str, content: str) -> dict[str, Any]:
    """Write a new project skill to ``.pydantic-deep/skills/<slug>/SKILL.md``."""
    slug = _slug(name)
    skill_dir = Path.cwd() / ".pydantic-deep" / "skills" / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    desc = description.replace('"', "'")
    body = f'---\nname: {name}\ndescription: "{desc}"\n---\n\n{content}\n'
    (skill_dir / "SKILL.md").write_text(body)
    return {"name": slug, "description": description}


def read_skill(name: str) -> str | None:
    """Return a skill's ``SKILL.md`` content, or ``None`` if not found."""
    safe = Path(name).name
    for directory in _skill_dirs():
        skill_md = directory / safe / "SKILL.md"
        if skill_md.exists():
            return skill_md.read_text()
    return None


__all__ = ["create_skill", "discover_skills", "read_skill"]
