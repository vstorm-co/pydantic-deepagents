"""Interactive MCP server manager — the `/mcp` command.

Lists configured MCP servers (built-in + user), and lets the user enable /
disable them, log in (store an auth token), test the connection, add custom
servers, and remove them. Changes persist to ``mcp.json`` / the keystore and
trigger an agent reconfigure on close.
"""

from __future__ import annotations

import shlex

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from apps.cli.mcp_store import (
    import_claude_code_servers,
    load_mcp_registry,
    mcp_login,
    mcp_logout,
    save_mcp_registry,
)
from pydantic_deep.mcp import (
    MCPAuth,
    MCPNotInstalledError,
    MCPProbeResult,
    MCPServerConfig,
    probe_mcp_server,
)

_STATUS_GLYPH = {
    "ready": "[green]●[/green]",
    "disabled": "[dim]○[/dim]",
    "needs_auth": "[yellow]⚠[/yellow]",
}
# "enabled" rather than "ready": the server is active and attached to the agent,
# but actual reachability is only confirmed by the `t` test action — a local
# server (e.g. figma) can be enabled yet unreachable.
_STATUS_LABEL = {
    "ready": "[green]enabled[/green]",
    "disabled": "[dim]disabled[/dim]",
    "needs_auth": "[yellow]needs login[/yellow]",
}


class MCPLoginModal(ModalScreen[str | None]):
    """Token entry for an MCP server that requires authentication."""

    DEFAULT_CSS = """
    MCPLoginModal { align: center middle; }
    MCPLoginModal > #mcp-login { width: 70; height: auto; border: tall $primary;
        background: $surface; padding: 1 2; }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, server_name: str, auth: MCPAuth) -> None:
        super().__init__()
        self._server_name = server_name
        self._auth = auth

    def compose(self) -> ComposeResult:
        with Vertical(id="mcp-login"):
            yield Static(f"[bold]Log in to '{self._server_name}'[/bold]")
            if self._auth.instructions:
                yield Static(f"[dim]{self._auth.instructions}[/dim]\n")
            yield Static(f"Token is stored as [bold]{self._auth.secret_key}[/bold].\n")
            yield Input(password=True, placeholder="Paste token…", id="mcp-token")
            yield Static("\n[dim]Enter to save  ·  Esc to cancel[/dim]")

    def on_mount(self) -> None:
        self.query_one("#mcp-token", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        token = event.value.strip()
        self.dismiss(token or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class MCPAddModal(ModalScreen["MCPServerConfig | None"]):
    """Minimal form to add a custom MCP server.

    A target starting with ``http`` becomes an HTTP server (url); anything else
    is treated as a stdio command (split on spaces). An optional secret key adds
    bearer auth.
    """

    DEFAULT_CSS = """
    MCPAddModal { align: center middle; }
    MCPAddModal > #mcp-add { width: 74; height: auto; border: tall $primary;
        background: $surface; padding: 1 2; }
    MCPAddModal Input { margin: 0 0 1 0; }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="mcp-add"):
            yield Static("[bold]Add MCP server[/bold]\n")
            yield Input(placeholder="name (e.g. my-server)", id="mcp-name")
            yield Input(
                placeholder="URL (https://…/mcp) or command (npx -y pkg)",
                id="mcp-target",
            )
            yield Input(placeholder="auth secret key (optional, e.g. MY_TOKEN)", id="mcp-secret")
            yield Static("[dim]Enter in the last field to add  ·  Esc to cancel[/dim]")

    def on_mount(self) -> None:
        self.query_one("#mcp-name", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        name = self.query_one("#mcp-name", Input).value.strip()
        target = self.query_one("#mcp-target", Input).value.strip()
        secret = self.query_one("#mcp-secret", Input).value.strip()
        if not name or not target:
            self.app.notify("Name and URL/command are required", severity="warning")
            return
        auth = MCPAuth(secret_key=secret) if secret else None
        try:
            if target.startswith(("http://", "https://")):
                config = MCPServerConfig(
                    name=name, transport="http", url=target, enabled=True, auth=auth
                )
            else:
                # shlex handles quoted args and paths with spaces correctly.
                parts = shlex.split(target)
                if not parts:
                    self.app.notify("Command is empty", severity="warning")
                    return
                config = MCPServerConfig(
                    name=name,
                    transport="stdio",
                    command=parts[0],
                    args=parts[1:],
                    enabled=True,
                    auth=auth,
                )
        except Exception as exc:
            self.app.notify(f"Invalid server: {exc}", severity="error")
            return
        self.dismiss(config)

    def action_cancel(self) -> None:
        self.dismiss(None)


class MCPViewModal(ModalScreen[None]):
    """Manage MCP servers: enable/disable, login, test, add, remove."""

    DEFAULT_CSS = """
    MCPViewModal { align: center middle; }
    MCPViewModal > #mcp-container { width: 86; max-height: 30; border: tall $primary;
        background: $surface; padding: 1 2; }
    """

    BINDINGS = [
        Binding("up", "move(-1)", "Up", show=False),
        Binding("down", "move(1)", "Down", show=False),
        Binding("e", "toggle", "Enable/Disable"),
        Binding("space", "toggle", "Enable/Disable", show=False),
        Binding("l", "login", "Login"),
        Binding("o", "logout", "Logout"),
        Binding("t", "test", "Test"),
        Binding("a", "add", "Add"),
        Binding("i", "import_claude_code", "Import from Claude Code"),
        Binding("d", "delete", "Remove"),
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._registry = load_mcp_registry()
        self._index = 0
        self._dirty = False
        # Inline connection-test result per server name (avoids toast pile-up).
        self._test_status: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="mcp-container"):
            yield Static(self._list_text(), id="mcp-list")
            yield Static(
                "\n[dim]↑↓ select · e enable/disable · l login · o logout · "
                "t test · a add · i import (Claude Code) · d remove · Esc close[/dim]",
                id="mcp-help",
            )

    # rendering

    def _servers(self) -> list[MCPServerConfig]:
        return self._registry.list_servers()

    def _list_text(self) -> str:
        servers = self._servers()
        if servers:
            self._index = max(0, min(self._index, len(servers) - 1))
        lines = ["[bold]MCP Servers[/bold]\n"]
        if not servers:
            lines.append("[dim]No MCP servers configured. Press 'a' to add one.[/dim]")
        for i, config in enumerate(servers):
            status = self._registry.status(config)
            marker = "[reverse]▶[/reverse]" if i == self._index else " "
            tag = "[dim](builtin)[/dim]" if config.builtin else "[cyan](custom)[/cyan]"
            test = self._test_status.get(config.name, "")
            test_suffix = f"  {test}" if test else ""
            lines.append(
                f"{marker} {_STATUS_GLYPH[status]} [bold]{config.name}[/bold] "
                f"{tag}  {_STATUS_LABEL[status]}{test_suffix}"
            )
            target = config.url or config.command or ""
            lines.append(f"     [dim]{config.transport} · {target}[/dim]")
            if config.description:
                lines.append(f"     [dim]{config.description}[/dim]")
        return "\n".join(lines)

    def _refresh_list(self) -> None:
        self.query_one("#mcp-list", Static).update(self._list_text())

    def _selected(self) -> MCPServerConfig | None:
        servers = self._servers()
        if not servers:
            return None
        return servers[self._index]

    # actions

    def action_move(self, delta: int) -> None:
        servers = self._servers()
        if servers:
            self._index = (self._index + delta) % len(servers)
            self._refresh_list()

    def action_toggle(self) -> None:
        config = self._selected()
        if config is None:
            return
        self._registry.set_enabled(config.name, not config.enabled)
        self._test_status.pop(config.name, None)  # stale once state changes
        save_mcp_registry(self._registry)
        self._dirty = True
        self._refresh_list()

    def action_login(self) -> None:
        config = self._selected()
        if config is None:
            return
        if config.auth is None:
            self.app.notify(f"'{config.name}' needs no login", severity="information")
            return
        auth = config.auth
        if auth.kind == "oauth":
            self.app.notify(
                f"'{config.name}' uses OAuth — press 't' to sign in via your browser.",
                severity="information",
            )
            return

        def _on_token(token: str | None) -> None:
            if token:
                mcp_login(auth.secret_key, token)
                self._test_status.pop(config.name, None)
                self._dirty = True
                self.app.notify(f"Saved token for '{config.name}'")
                self._refresh_list()

        self.app.push_screen(MCPLoginModal(config.name, auth), _on_token)

    def action_logout(self) -> None:
        config = self._selected()
        if config is None:
            return
        if config.auth is None:
            self.app.notify(f"'{config.name}' has no stored token", severity="information")
            return
        mcp_logout(config.auth.secret_key)
        self._test_status.pop(config.name, None)
        self._dirty = True
        self.app.notify(f"Removed token for '{config.name}'")
        self._refresh_list()

    def action_add(self) -> None:
        def _on_add(config: MCPServerConfig | None) -> None:
            if config is None:
                return
            existing = self._registry.get(config.name)
            if existing is not None and existing.builtin:
                self.app.notify(
                    f"'{config.name}' is a built-in server name; choose another.",
                    severity="warning",
                )
                return
            self._registry.add(config)
            save_mcp_registry(self._registry)
            self._dirty = True
            self.app.notify(f"Added '{config.name}'")
            self._refresh_list()

        self.app.push_screen(MCPAddModal(), _on_add)

    def action_import_claude_code(self) -> None:
        """Import MCP servers already configured in Claude Code (.mcp.json / ~/.claude.json).

        Existing custom servers with the same name are overwritten (tokens in
        env/headers carry over, so imported servers work right away). Built-in
        names are skipped to avoid clobbering curated defaults.
        """
        try:
            imported = import_claude_code_servers()
        except Exception as exc:
            self.app.notify(f"Import failed: {exc}", severity="error")
            return
        if not imported:
            self.app.notify(
                "No MCP servers found in Claude Code config (.mcp.json / ~/.claude.json).",
                severity="information",
            )
            return
        added = 0
        skipped = []
        for config in imported:
            existing = self._registry.get(config.name)
            if existing is not None and existing.builtin:
                skipped.append(config.name)
                continue
            self._registry.add(config)
            added += 1
        if added:
            save_mcp_registry(self._registry)
            self._dirty = True
            self._refresh_list()
        msg = f"Imported {added} server(s) from Claude Code"
        if skipped:
            msg += f" (skipped built-in name(s): {', '.join(skipped)})"
        self.app.notify(msg)

    def action_delete(self) -> None:
        config = self._selected()
        if config is None:
            return
        if config.builtin:
            self.app.notify(
                "Built-in servers can't be removed (disable instead)", severity="warning"
            )
            return
        self._registry.remove(config.name)
        # Keep the selection in range after removing the last item.
        self._index = max(0, min(self._index, len(self._servers()) - 1))
        save_mcp_registry(self._registry)
        self._dirty = True
        self.app.notify(f"Removed '{config.name}'")
        self._refresh_list()

    def action_test(self) -> None:
        config = self._selected()
        if config is None:
            return
        # Inline status in the list rather than stacking toasts on repeat tests.
        self._test_status[config.name] = "[dim]· testing…[/dim]"
        self._refresh_list()
        self.run_worker(self._probe(config), exclusive=True)

    def _set_test_status(self, name: str, text: str) -> None:
        self._test_status[name] = text
        self._refresh_list()

    async def _probe(self, config: MCPServerConfig) -> None:
        try:
            server = self._registry.build(config)
        except MCPNotInstalledError as exc:
            self._set_test_status(config.name, "[red]· mcp extra not installed[/red]")
            self.app.notify(str(exc), severity="error", timeout=8)
            return
        except Exception as exc:
            self._set_test_status(config.name, f"[red]· build error: {exc}[/red]")
            return
        # OAuth servers open a browser and wait for the user to authorize, so
        # give the probe much longer than the default.
        is_oauth = config.auth is not None and config.auth.kind == "oauth"
        timeout = 180.0 if is_oauth else 10.0
        result: MCPProbeResult = await probe_mcp_server(server, timeout=timeout)
        if result.ok:
            self._set_test_status(config.name, f"[green]· ✓ {result.tool_count} tools[/green]")
        else:
            err = (result.error or "failed").splitlines()[0][:50]
            self._set_test_status(config.name, f"[red]· ✗ {err}[/red]")

    def action_close(self) -> None:
        if self._dirty:
            reconfigure = getattr(self.app, "reconfigure_agent", None)
            if reconfigure is not None:
                reconfigure()
        self.dismiss(None)
