"""Skills list modal — /skills command. Shows actual loaded skills."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static


def _discover_skills() -> list[tuple[str, str]]:
    """Discover skills from known directories."""
    skills: list[tuple[str, str]] = []
    seen: set[str] = set()

    # Bundled skills
    bundled = Path(__file__).resolve().parent.parent.parent / "cli" / "skills"
    # User skills
    user_skills = Path.home() / ".pydantic-deep" / "skills"
    # Project skills
    project_skills = Path.cwd() / ".pydantic-deep" / "skills"

    for skills_dir in [bundled, user_skills, project_skills]:
        if not skills_dir.is_dir():
            continue
        for skill_folder in sorted(skills_dir.iterdir()):
            if not skill_folder.is_dir():
                continue
            skill_md = skill_folder / "SKILL.md"
            if not skill_md.exists():
                continue

            name = skill_folder.name
            if name in seen:
                continue
            seen.add(name)

            # Read description from frontmatter
            desc = ""
            try:
                text = skill_md.read_text()
                in_frontmatter = False
                for line in text.splitlines():
                    if line.strip() == "---":
                        if in_frontmatter:
                            break
                        in_frontmatter = True
                        continue
                    if in_frontmatter and line.startswith("description:"):
                        desc = line.split(":", 1)[1].strip().strip("\"'")
                        break
            except Exception:
                pass

            skills.append((name, desc))

    return skills


class SkillsViewModal(ModalScreen[None]):
    """Lists available skills with descriptions."""

    DEFAULT_CSS = """
    SkillsViewModal {
        align: center middle;
    }
    SkillsViewModal > #skills-container {
        width: 75;
        max-height: 28;
        border: tall $primary;
        background: $surface;
        padding: 1 2;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        skills = _discover_skills()

        with VerticalScroll(id="skills-container"):
            yield Static(f"[bold]Available Skills[/bold]  ({len(skills)} found)\n")

            if not skills:
                yield Static("[dim]No skills found.[/dim]")
            else:
                lines: list[str] = []
                for name, desc in skills:
                    if desc:
                        lines.append(f"  [bold]{name}[/bold]  [dim]{desc}[/dim]")
                    else:
                        lines.append(f"  [bold]{name}[/bold]")
                yield Static("\n".join(lines))

            yield Static("\n[dim]Esc or q to close[/dim]")

    def action_dismiss(self, result: object = None) -> None:
        self.dismiss(None)
