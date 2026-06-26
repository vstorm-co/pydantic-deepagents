"""Left sidebar — what the system wires into the agent.

Lists the live capability surface: the model-callable tools, the higher-level
extensions (memory, skills, plan, …), the storage backend, any MCP servers,
and the project context docs. Read from the CLI config and the runtime deps,
so it reflects what is actually plugged in. Purely informational.

Session (provider · model · thinking) and workspace (path · branch) live in
the footer under the input, not here — see `SessionFooter`.
"""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

# Project docs surfaced under "context", in priority order.
_CONTEXT_FILES = ("DEEP.md", "AGENTS.md", "CLAUDE.md", "SOUL.md")

_BACKEND_LABELS = {
    "LocalBackend": "local filesystem",
    "StateBackend": "in-memory",
    "DockerSandbox": "docker sandbox",
    "CompositeBackend": "composite",
}


def _header(text: str) -> str:
    return f"[$text-muted b]{text}[/]"


def _bullet(text: str) -> str:
    return f"[$accent]•[/] [$foreground]{text}[/]"


class SessionSidebar(Widget):
    """Left-docked panel listing the agent's wired capabilities."""

    DEFAULT_CSS = """
    SessionSidebar {
        width: 30;
        padding: 1 2 0 2;
        border-right: tall $panel;
        background: $surface;
    }
    SessionSidebar.hidden {
        display: none;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static(id="sidebar-content")

    def on_mount(self) -> None:
        self.refresh_session()

    def refresh_session(self) -> None:
        """Re-read config + deps and repaint the capability list."""
        try:
            content = self.query_one("#sidebar-content", Static)
        except Exception:
            return

        cfg = self._config()
        lines: list[str] = []

        lines.append(_header("tools"))
        lines += [_bullet(t) for t in self._tools(cfg)]

        extensions = self._extensions(cfg)
        if extensions:
            lines += ["", _header("extensions")]
            lines += [_bullet(e) for e in extensions]

        backend = self._backend_label() or self._backend_from_config(cfg)
        if backend:
            lines += ["", _header("backend"), f"[$foreground]{backend}[/]"]

        mcp = self._mcp_servers()
        if mcp:
            lines += ["", _header("mcp")]
            lines += [_bullet(name) for name in mcp]

        context = self._context_files()
        if context:
            lines += ["", _header("context")]
            lines += [_bullet(name) for name in context]

        content.update("\n".join(lines))

    # ── data sources ────────────────────────────────────────────────

    @staticmethod
    def _config() -> object | None:
        try:
            from apps.cli.config import load_config

            return load_config()
        except Exception:
            return None

    @staticmethod
    def _tools(cfg: object | None) -> list[str]:
        # Filesystem + exec tools are always wired in the CLI.
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

    @staticmethod
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
        # Always-on context engine features.
        ext += ["checkpoints", "history search"]
        return ext

    def _backend_label(self) -> str:
        deps = getattr(self.app, "deps", None)
        if deps is None:
            return ""
        try:
            from pydantic_deep.deps import unwrap_backend

            name = type(unwrap_backend(deps.backend)).__name__
            return _BACKEND_LABELS.get(name, name)
        except Exception:
            return ""

    @staticmethod
    def _backend_from_config(cfg: object | None) -> str:
        sandbox = str(getattr(cfg, "sandbox", "") or "")
        return {"local": "local filesystem", "docker": "docker sandbox"}.get(sandbox, sandbox)

    @staticmethod
    def _mcp_servers() -> list[str]:
        try:
            from apps.cli.mcp_store import load_mcp_registry

            registry = load_mcp_registry()
            servers = registry.list_servers()
            names = [
                s.name for s in servers if getattr(s, "enabled", True) and getattr(s, "name", None)
            ]
            return names[:6]
        except Exception:
            return []

    def _context_files(self) -> list[str]:
        root = Path(str(getattr(self.app, "working_dir", ".")))
        found: list[str] = []
        for name in _CONTEXT_FILES:
            try:
                if (root / name).is_file():
                    found.append(name)
            except Exception:
                pass
        return found


__all__ = ["SessionSidebar"]
