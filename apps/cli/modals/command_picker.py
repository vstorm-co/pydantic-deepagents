"""Command picker modal — opened by typing /."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from apps.cli.modals._filter_input import FilterInput as _FilterInput

# Built-in commands with descriptions
COMMANDS: list[tuple[str, str]] = [
    ("/bug", "Open the GitHub issues page"),
    ("/clear", "Clear conversation history"),
    ("/compact", "Compress context (LLM summarization)"),
    ("/context", "Show context window usage"),
    ("/copy", "Copy last response to clipboard"),
    ("/copy-all", "Copy entire conversation to clipboard"),
    ("/cost", "Show accumulated cost"),
    ("/diff", "Show git diff"),
    ("/export", "Export the conversation to a Markdown file (/export [path])"),
    ("/fork", "Spawn parallel branches from current state"),
    ("/fork diff", "Pick file + branches to open in external diff tool (PyCharm/VS Code)"),
    ("/fork-config", "Configure /fork branches, models, and budgets (persisted)"),
    ("/goal", "Keep working toward a condition (/goal <condition>, /goal clear)"),
    ("/help", "Show commands and shortcuts"),
    ("/improve", "Analyze sessions and self-improve"),
    ("/info", "Show what's wired into the agent (tools, backend, MCP, context)"),
    ("/load", "Load a saved session"),
    ("/mcp", "Manage MCP servers (connect, login, test)"),
    ("/merge", "Resolve active fork — pick a winning branch"),
    ("/model", "Change model"),
    ("/paste", "Attach an image from the clipboard (also Ctrl+V)"),
    ("/provider", "Configure AI provider"),
    ("/quit", "Exit pydantic-deep"),
    ("/remember", "Add note to persistent memory"),
    ("/remind", "Switch periodic reminder mode"),
    ("/retry", "Re-run the last prompt (drops the previous turn)"),
    ("/save", "Save current session"),
    ("/screenshot", "Export the current screen as an SVG image"),
    ("/settings", "Change settings (toggle features, model, theme)"),
    ("/shells", "List background shells (run_in_background processes)"),
    ("/skills", "List available skills"),
    ("/theme", "Switch color theme"),
    ("/todos", "Show todo list"),
    ("/tokens", "Show token count"),
    ("/undo", "Undo last turn"),
    ("/version", "Show version"),
]


def _discover_skill_commands() -> list[tuple[str, str]]:
    """Discover available skills and return as /skill-name command entries."""
    skills: list[tuple[str, str]] = []
    seen: set[str] = set()

    bundled = Path(__file__).resolve().parent.parent.parent / "cli" / "skills"
    user_skills = Path.home() / ".pydantic-deep" / "skills"
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

            skills.append((f"/{name}", f"Skill: {desc}" if desc else "Skill"))

    return skills


class CommandPickerModal(ModalScreen[str | None]):
    """Floating command picker with real-time fuzzy filtering.

    ↑/↓ navigate the list while typing in the filter input.
    """

    DEFAULT_CSS = """
    CommandPickerModal {
        align: center middle;
    }
    CommandPickerModal > #picker-container {
        width: 60;
        max-height: 24;
        border: tall $primary;
        background: $surface;
        padding: 1;
    }
    CommandPickerModal > #picker-container > #picker-title {
        height: 1;
        margin: 0 0 1 0;
    }
    CommandPickerModal > #picker-container > #picker-filter {
        height: 1;
        margin: 0 0 1 0;
        border: none;
    }
    CommandPickerModal > #picker-container > #picker-list {
        height: auto;
        max-height: 16;
    }
    CommandPickerModal > #picker-container > #picker-hint {
        height: 1;
        color: $text-disabled;
        margin: 1 0 0 0;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._all_commands = list(COMMANDS)
        self._skill_commands = _discover_skill_commands()

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-container"):
            yield Static("[bold]Commands[/bold]", id="picker-title")
            yield _FilterInput(
                placeholder="Type to filter...",
                id="picker-filter",
                list_id="picker-list",
                enter_selects=True,
            )
            options = self._make_options(self._all_commands)
            if self._skill_commands:
                options.append(Option("[dim]── Skills ──[/dim]", disabled=True))
                options.extend(self._make_options(self._skill_commands))
            yield OptionList(*options, id="picker-list")
            yield Static(
                "[dim]↑↓ navigate  Enter select  Esc cancel[/dim]",
                id="picker-hint",
            )

    def _make_options(self, commands: list[tuple[str, str]]) -> list[Option]:
        return [Option(f"{cmd}  [dim]{desc}[/dim]", id=cmd) for cmd, desc in commands]

    def on_mount(self) -> None:
        self.query_one("#picker-filter", _FilterInput).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        from apps.cli.fuzzy import fuzzy_filter

        # Match against "cmd desc" so a query can hit either the command name or
        # its description, then rank best matches first.
        def _key(item: tuple[str, str]) -> str:
            return f"{item[0]} {item[1]}"

        filtered_cmds = fuzzy_filter(event.value, self._all_commands, key=_key)
        filtered_skills = fuzzy_filter(event.value, self._skill_commands, key=_key)

        option_list = self.query_one("#picker-list", OptionList)
        option_list.clear_options()
        for opt in self._make_options(filtered_cmds):
            option_list.add_option(opt)
        if filtered_skills:
            option_list.add_option(Option("[dim]── Skills ──[/dim]", disabled=True))
            for opt in self._make_options(filtered_skills):
                option_list.add_option(opt)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        cmd = str(event.option.id) if event.option.id else ""
        self.dismiss(cmd)

    def action_cancel(self) -> None:
        self.dismiss(None)
