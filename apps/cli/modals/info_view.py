"""Info modal — /info command.

Shows what the system wires into the agent: the model-callable tools, the
higher-level extensions (memory, skills, plan, …), the storage backend, any
MCP servers, and the project context docs. Read from the CLI config and the
runtime deps, so it reflects what is actually plugged in.

This is the on-demand replacement for the old always-on left sidebar: the
capability surface is reference information, not something to keep on screen.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

# Project docs surfaced under "context", in priority order.
_CONTEXT_FILES = ("DEEP.md", "AGENTS.md", "CLAUDE.md", "SOUL.md")

_BACKEND_LABELS = {
    "LocalBackend": "local filesystem",
    "StateBackend": "in-memory",
    "DockerSandbox": "docker sandbox",
    "CompositeBackend": "composite",
}


def _config() -> object | None:
    try:
        from apps.cli.config import load_config

        return load_config()
    except Exception:
        return None


def _tools(cfg: object | None) -> list[str]:
    tools = ["read", "write", "edit", "grep", "glob", "bash"]
    if getattr(cfg, "web_search", True):
        tools.append("web_search")
    if getattr(cfg, "web_fetch", True):
        tools.append("web_fetch")
    if getattr(cfg, "include_todo", True):
        tools.append("todos")
    if getattr(cfg, "include_subagents", True):
        tools.append("task")
    if getattr(cfg, "include_liteparse", True):
        tools.append("parse_document")
    return tools


def _extensions(cfg: object | None) -> list[str]:
    ext: list[str] = []
    if getattr(cfg, "include_memory", True):
        ext.append("memory")
    if getattr(cfg, "include_skills", True):
        ext.append("skills")
    if getattr(cfg, "include_plan", True):
        ext.append("plan")
    if getattr(cfg, "include_subagents", True):
        ext.append("subagents")
    if getattr(cfg, "include_teams", False):
        ext.append("teams")
    if getattr(cfg, "include_browser", True):
        ext.append("browser")
    ext += ["checkpoints", "history search"]
    return ext


def _backend_label(app: object) -> str:
    deps = getattr(app, "deps", None)
    if deps is None:
        return ""
    try:
        from pydantic_deep.deps import unwrap_backend

        name = type(unwrap_backend(deps.backend)).__name__
        return _BACKEND_LABELS.get(name, name)
    except Exception:
        return ""


def _backend_from_config(cfg: object | None) -> str:
    sandbox = str(getattr(cfg, "sandbox", "") or "")
    return {"local": "local filesystem", "docker": "docker sandbox"}.get(sandbox, sandbox)


def _mcp_servers() -> list[str]:
    try:
        from apps.cli.mcp_store import load_mcp_registry

        servers = load_mcp_registry().list_servers()
        return [
            s.name for s in servers if getattr(s, "enabled", True) and getattr(s, "name", None)
        ][:8]
    except Exception:
        return []


def _context_files(app: object) -> list[str]:
    root = Path(str(getattr(app, "working_dir", ".")))
    found: list[str] = []
    for name in _CONTEXT_FILES:
        try:
            if (root / name).is_file():
                found.append(name)
        except Exception:
            pass
    return found


def build_info_markup(app: object) -> str:
    """Build the capability-surface markup for the /info modal."""
    cfg = _config()
    sections: list[tuple[str, str]] = []

    sections.append(("tools", "  ".join(_tools(cfg))))

    extensions = _extensions(cfg)
    if extensions:
        sections.append(("extensions", "  ".join(extensions)))

    backend = _backend_label(app) or _backend_from_config(cfg)
    if backend:
        sections.append(("backend", backend))

    mcp = _mcp_servers()
    if mcp:
        sections.append(("mcp", "  ".join(mcp)))

    context = _context_files(app)
    if context:
        sections.append(("context", "  ".join(context)))

    blocks: list[str] = []
    for title, body in sections:
        blocks.append(f"[$accent b]{title}[/]\n[$foreground]{body}[/]")
    return "\n\n".join(blocks)


class InfoModal(ModalScreen[None]):
    """Overlay listing the agent's wired capability surface."""

    DEFAULT_CSS = """
    InfoModal {
        align: center middle;
    }
    InfoModal > #info-container {
        width: 64;
        max-height: 85%;
        border: tall $accent;
        background: $surface;
        padding: 1 2;
    }
    InfoModal #info-heading {
        text-style: bold;
        color: $foreground;
        padding: 0 0 1 0;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="info-container"):
            yield Static("◆ wired into this agent", id="info-heading")
            yield Static(build_info_markup(self.app))
            yield Static("\n[$text-muted]Esc or q to close[/]")

    def action_dismiss(self, result: object = None) -> None:
        self.dismiss(None)
