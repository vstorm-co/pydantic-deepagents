"""Tests for the CLI MCP integration: store, agent wiring, and the /mcp modal."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from apps.cli import mcp_store
from apps.cli.keystore import get_stored_keys
from apps.cli.modals.mcp_view import MCPViewModal
from apps.cli.screens.chat import ChatScreen
from pydantic_deep.mcp import MCPProbeResult, MCPServerConfig


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the project dir (mcp.json + keys.toml) to a temp location."""
    monkeypatch.setattr(mcp_store, "get_project_dir", lambda: tmp_path)
    from apps.cli import keystore

    monkeypatch.setattr(keystore, "get_project_dir", lambda: tmp_path)
    return tmp_path


# ── store ────────────────────────────────────────────────────────────────


def test_load_default_registry_has_builtins(project_dir: Path) -> None:
    reg = mcp_store.load_mcp_registry(resolver=lambda k: None)
    names = {c.name for c in reg.list_servers()}
    assert "github" in names and "deepwiki" in names
    # All builtins disabled by default.
    assert all(not c.enabled for c in reg.list_servers())


def test_save_and_reload_roundtrip(project_dir: Path) -> None:
    reg = mcp_store.load_mcp_registry(resolver=lambda k: None)
    reg.set_enabled("deepwiki", True)
    reg.add(MCPServerConfig(name="mine", transport="http", url="http://x/mcp", enabled=True))
    mcp_store.save_mcp_registry(reg)

    assert mcp_store.mcp_config_path().exists()

    reloaded = mcp_store.load_mcp_registry(resolver=lambda k: None)
    deepwiki = reloaded.get("deepwiki")
    assert deepwiki is not None and deepwiki.enabled is True
    mine = reloaded.get("mine")
    assert mine is not None and mine.url == "http://x/mcp"


def test_load_skips_malformed_user_entry(project_dir: Path) -> None:
    path = mcp_store.mcp_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # 'bad' has no command/url -> from_dict raises -> skipped; 'good' kept.
    path.write_text(
        '{"user_servers": ['
        '{"name": "bad", "transport": "stdio"},'
        '{"name": "good", "transport": "http", "url": "http://y/mcp"}'
        "]}"
    )
    reg = mcp_store.load_mcp_registry(resolver=lambda k: None)
    names = {c.name for c in reg.list_servers()}
    assert "good" in names
    assert "bad" not in names


def test_read_config_handles_garbage(project_dir: Path) -> None:
    path = mcp_store.mcp_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json{{{")
    reg = mcp_store.load_mcp_registry(resolver=lambda k: None)
    # Falls back to builtins only.
    assert {c.name for c in reg.list_servers()} >= {"github", "deepwiki"}


def test_keystore_escapes_special_characters(project_dir: Path) -> None:
    """A token with quotes/backslashes/newlines must not corrupt keys.toml."""
    from apps.cli import keystore

    nasty = 'ab"cd\\ef\ngh'
    keystore.save_key("SAFE_KEY", "plain-123")
    keystore.save_key("NASTY_KEY", nasty)
    # Re-read from disk (not the live env) — proves the file is valid TOML.
    stored = keystore.get_stored_keys()
    assert stored["SAFE_KEY"] == "plain-123"
    assert stored["NASTY_KEY"] == nasty


def test_mcp_logout_removes_token(project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOGOUT_KEY", raising=False)
    mcp_store.mcp_login("LOGOUT_KEY", "secret")
    import os

    assert os.environ.get("LOGOUT_KEY") == "secret"
    assert "LOGOUT_KEY" in get_stored_keys()

    mcp_store.mcp_logout("LOGOUT_KEY")
    assert os.environ.get("LOGOUT_KEY") is None
    assert "LOGOUT_KEY" not in get_stored_keys()


def test_secret_resolver_env_and_keystore(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    resolver = mcp_store.mcp_secret_resolver()
    monkeypatch.setenv("ENV_ONLY_KEY", "from-env")
    assert resolver("ENV_ONLY_KEY") == "from-env"

    monkeypatch.delenv("STORED_KEY", raising=False)
    mcp_store.mcp_login("STORED_KEY", "from-keystore")
    assert resolver("STORED_KEY") == "from-keystore"


def test_build_servers_for_agent(project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reg = mcp_store.load_mcp_registry(resolver=lambda k: None)
    reg.set_enabled("deepwiki", True)  # no-auth -> ready
    reg.set_enabled("github", True)  # needs auth, no token -> not ready
    mcp_store.save_mcp_registry(reg)

    servers = mcp_store.build_mcp_servers_for_agent()
    # Only deepwiki is ready (github needs a token).
    assert len(servers) == 1


def test_build_servers_for_agent_handles_missing_dep(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pydantic_deep.mcp import MCPNotInstalledError

    reg = mcp_store.load_mcp_registry(resolver=lambda k: None)
    reg.set_enabled("deepwiki", True)
    mcp_store.save_mcp_registry(reg)

    def _boom(self: object, **kwargs: object) -> list[Any]:
        raise MCPNotInstalledError("nope")

    monkeypatch.setattr("pydantic_deep.mcp.registry.MCPRegistry.build_active", _boom)
    assert mcp_store.build_mcp_servers_for_agent() == []


def test_mcp_oauth_storage_persistent(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    store = mcp_store.mcp_oauth_storage()
    assert store is not None  # disk extra installed in dev env
    assert (home / ".pydantic-deep" / "mcp-oauth").exists()


def test_mcp_oauth_storage_missing_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    import builtins

    real_import = builtins.__import__

    def _fake_import(name: str, *args: object, **kwargs: object) -> Any:
        if name == "key_value.aio.stores.disk":
            raise ImportError("no disk backend")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    assert mcp_store.mcp_oauth_storage() is None


# ── import from Claude Code ──────────────────────────────────────────────


def test_import_claude_code_merges_scopes(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import json

    proj = tmp_path / "proj"
    proj.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))

    # user scope + this project's local scope in ~/.claude.json
    (home / ".claude.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "userserver": {"type": "http", "url": "https://u/mcp"},
                    "shared": {"type": "http", "url": "https://user-version/mcp"},
                },
                "projects": {
                    str(proj.resolve()): {
                        "mcpServers": {
                            "localserver": {"command": "npx", "args": ["-y", "x"]},
                            "shared": {"type": "http", "url": "https://local-version/mcp"},
                        }
                    }
                },
            }
        )
    )
    # project scope .mcp.json
    (proj / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"projserver": {"type": "http", "url": "https://p/mcp"}}})
    )

    imported = mcp_store.import_claude_code_servers(project_dir=proj)
    by_name = {s.name: s for s in imported}
    assert set(by_name) == {"userserver", "localserver", "shared", "projserver"}
    # local scope wins over user scope for the duplicate name.
    assert by_name["shared"].url == "https://local-version/mcp"


def test_import_claude_code_empty(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    proj = tmp_path / "proj"
    proj.mkdir()
    assert mcp_store.import_claude_code_servers(project_dir=proj) == []


def test_claude_code_config_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    paths = mcp_store.claude_code_config_paths(project_dir=tmp_path)
    assert paths[0] == tmp_path / ".mcp.json"
    assert paths[1] == home / ".claude.json"


# ── /mcp modal ─────────────────────────────────────────────────────────────


async def test_mcp_modal_opens_and_navigates(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The modal loads the registry via mcp_store; point it at our temp dir.
    monkeypatch.setattr(
        "apps.cli.modals.mcp_view.load_mcp_registry",
        lambda: mcp_store.load_mcp_registry(resolver=lambda k: None),
    )
    from apps.cli.app import DeepApp

    app = DeepApp(model="test", version="0.0.0")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app.push_screen(MCPViewModal())
        await pilot.pause()
        modal = cast(MCPViewModal, app.screen)
        assert isinstance(modal, MCPViewModal)
        start = modal._index
        modal.action_move(1)
        assert modal._index == (start + 1) % len(modal._servers())
        # Toggle the selected server's enabled state and confirm it persisted.
        selected = modal._selected()
        assert selected is not None
        before = selected.enabled
        modal.action_toggle()
        sel = modal._selected()
        assert sel is not None and sel.enabled is not before
        assert modal._dirty is True


async def test_mcp_modal_inline_test_status(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Connection test shows inline status per server (no stacking toasts)."""
    monkeypatch.setattr(
        "apps.cli.modals.mcp_view.load_mcp_registry",
        lambda: mcp_store.load_mcp_registry(resolver=lambda k: None),
    )
    from apps.cli.app import DeepApp
    from pydantic_deep.mcp import MCPProbeResult

    app = DeepApp(model="test", version="0.0.0")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app.push_screen(MCPViewModal())
        await pilot.pause()
        modal = cast(MCPViewModal, app.screen)

        # Stub build (no real connection) + probe result.
        monkeypatch.setattr(modal._registry, "build", lambda c: object())

        async def _ok(server: object, timeout: float = 10.0) -> MCPProbeResult:
            return MCPProbeResult(ok=True, tool_count=4, tool_names=["a", "b", "c", "d"])

        monkeypatch.setattr("apps.cli.modals.mcp_view.probe_mcp_server", _ok)

        sel = modal._selected()
        assert sel is not None
        name = sel.name
        modal.action_test()
        assert modal._test_status[name] == "[dim]· testing…[/dim]"
        # Drive the worker to completion.
        await modal.workers.wait_for_complete()
        await pilot.pause()
        assert "✓ 4 tools" in modal._test_status[name]

        # Toggling clears the stale test status.
        modal.action_toggle()
        assert name not in modal._test_status


async def test_mcp_modal_inline_test_failure(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "apps.cli.modals.mcp_view.load_mcp_registry",
        lambda: mcp_store.load_mcp_registry(resolver=lambda k: None),
    )
    from apps.cli.app import DeepApp
    from pydantic_deep.mcp import MCPProbeResult

    app = DeepApp(model="test", version="0.0.0")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app.push_screen(MCPViewModal())
        await pilot.pause()
        modal = cast(MCPViewModal, app.screen)
        monkeypatch.setattr(modal._registry, "build", lambda c: object())

        async def _fail(server: object, timeout: float = 10.0) -> MCPProbeResult:
            return MCPProbeResult(ok=False, error="Client failed to connect")

        monkeypatch.setattr("apps.cli.modals.mcp_view.probe_mcp_server", _fail)
        sel = modal._selected()
        assert sel is not None
        name = sel.name
        modal.action_test()
        await modal.workers.wait_for_complete()
        await pilot.pause()
        assert "✗" in modal._test_status[name]


async def test_notify_degraded_mcp_once(project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.cli.app import DeepApp

    app = DeepApp(model="test", version="0.0.0")
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        screen = cast(ChatScreen, app.screen)
        msgs: list[str] = []
        monkeypatch.setattr(app, "notify", lambda m, **k: msgs.append(m))

        class _Deps:
            mcp_degraded = {"figma"}

        app.deps = _Deps()

        screen._notify_degraded_mcp()
        screen._notify_degraded_mcp()  # second call: already notified, no new toast
        assert sum("figma" in m for m in msgs) == 1

        # A newly-degraded server notifies again.
        app.deps.mcp_degraded = {"figma", "context7"}
        screen._notify_degraded_mcp()
        assert any("context7" in m for m in msgs)


async def test_notify_degraded_mcp_empty(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.cli.app import DeepApp

    app = DeepApp(model="test", version="0.0.0")
    async with app.run_test(size=(120, 35)) as pilot:
        await pilot.pause()
        screen = cast(ChatScreen, app.screen)
        msgs: list[str] = []
        monkeypatch.setattr(app, "notify", lambda m, **k: msgs.append(m))
        # No deps / empty set -> no notification, no crash.
        screen._notify_degraded_mcp()

        class _Deps:
            mcp_degraded: set[str] = set()

        app.deps = _Deps()
        screen._notify_degraded_mcp()
        assert msgs == []


async def test_mcp_modal_add_and_remove(project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "apps.cli.modals.mcp_view.load_mcp_registry",
        lambda: mcp_store.load_mcp_registry(resolver=lambda k: None),
    )
    from apps.cli.app import DeepApp

    app = DeepApp(model="test", version="0.0.0")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        await app.push_screen(MCPViewModal())
        await pilot.pause()
        modal = cast(MCPViewModal, app.screen)
        n0 = len(modal._servers())
        modal._registry.add(
            MCPServerConfig(name="zzz", transport="http", url="http://z/mcp", enabled=True)
        )
        modal._refresh_list()
        # Select the custom server and remove it.
        modal._index = len(modal._servers()) - 1
        sel = modal._selected()
        assert sel is not None and sel.name == "zzz"
        modal.action_delete()
        assert len(modal._servers()) == n0


async def test_mcp_modal_import_claude_code(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "apps.cli.modals.mcp_view.load_mcp_registry",
        lambda: mcp_store.load_mcp_registry(resolver=lambda k: None),
    )
    # Stub the importer: one new custom server + one that collides with a builtin.
    monkeypatch.setattr(
        "apps.cli.modals.mcp_view.import_claude_code_servers",
        lambda: [
            MCPServerConfig(name="my-cc-server", transport="http", url="https://cc/mcp"),
            MCPServerConfig(name="github", transport="http", url="https://collide/mcp"),
        ],
    )
    from apps.cli.app import DeepApp

    app = DeepApp(model="test", version="0.0.0")
    msgs: list[str] = []
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        monkeypatch.setattr(app, "notify", lambda m, **k: msgs.append(m))
        await app.push_screen(MCPViewModal())
        await pilot.pause()
        modal = cast(MCPViewModal, app.screen)
        modal.action_import_claude_code()
        names = {s.name for s in modal._servers()}
        assert "my-cc-server" in names  # new custom server imported
        # builtin 'github' was not overwritten by the import.
        gh = modal._registry.get("github")
        assert gh is not None
        assert gh.builtin is True and gh.url == "https://api.githubcopilot.com/mcp/"
        assert any("Imported 1" in m for m in msgs)


async def test_mcp_modal_import_empty(project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "apps.cli.modals.mcp_view.load_mcp_registry",
        lambda: mcp_store.load_mcp_registry(resolver=lambda k: None),
    )
    monkeypatch.setattr("apps.cli.modals.mcp_view.import_claude_code_servers", lambda: [])
    from apps.cli.app import DeepApp

    app = DeepApp(model="test", version="0.0.0")
    msgs: list[str] = []
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        monkeypatch.setattr(app, "notify", lambda m, **k: msgs.append(m))
        await app.push_screen(MCPViewModal())
        await pilot.pause()
        cast(MCPViewModal, app.screen).action_import_claude_code()
        assert any("No MCP servers found" in m for m in msgs)


async def test_mcp_modal_import_error(project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "apps.cli.modals.mcp_view.load_mcp_registry",
        lambda: mcp_store.load_mcp_registry(resolver=lambda k: None),
    )

    def _boom() -> list[Any]:
        raise RuntimeError("disk on fire")

    monkeypatch.setattr("apps.cli.modals.mcp_view.import_claude_code_servers", _boom)
    from apps.cli.app import DeepApp

    app = DeepApp(model="test", version="0.0.0")
    msgs: list[str] = []
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        monkeypatch.setattr(app, "notify", lambda m, **k: msgs.append(m))
        await app.push_screen(MCPViewModal())
        await pilot.pause()
        cast(MCPViewModal, app.screen).action_import_claude_code()
        assert any("Import failed" in m for m in msgs)
