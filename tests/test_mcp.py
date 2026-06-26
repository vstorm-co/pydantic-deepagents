"""Tests for pydantic_deep.mcp — config, builtins, registry, build, probe."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pydantic_deep.mcp import (
    BUILTIN_MCP_NAMES,
    MCPAuth,
    MCPConfigError,
    MCPNotInstalledError,
    MCPProbeResult,
    MCPRegistry,
    MCPServerConfig,
    auth_satisfied,
    build_mcp_server,
    builtin_mcp_servers,
    probe_mcp_server,
)
from pydantic_deep.mcp import registry as registry_mod


def _transport(toolset: Any) -> Any:
    """FastMCP transport of a built MCP toolset (typed Any for test access)."""
    return toolset.client.transport


# ── config: MCPAuth ──────────────────────────────────────────────────────


def test_mcpauth_render_and_roundtrip() -> None:
    auth = MCPAuth(secret_key="K", kind="bearer", instructions="get a token")
    assert auth.render_value("abc") == "Bearer abc"
    d = auth.to_dict()
    back = MCPAuth.from_dict(d)
    assert back == auth


def test_mcpauth_from_dict_defaults() -> None:
    auth = MCPAuth.from_dict({"secret_key": "K"})
    assert auth.kind == "bearer"
    assert auth.header == "Authorization"
    assert auth.value_template == "Bearer {token}"


def test_mcpauth_custom_header_template() -> None:
    auth = MCPAuth(
        secret_key="FIGMA", kind="header", header="X-Figma-Token", value_template="{token}"
    )
    assert auth.render_value("t") == "t"


# ── config: MCPServerConfig validation ──────────────────────────────────


def test_config_stdio_requires_command() -> None:
    with pytest.raises(MCPConfigError):
        MCPServerConfig(name="x", transport="stdio")


def test_config_http_requires_url() -> None:
    with pytest.raises(MCPConfigError):
        MCPServerConfig(name="x", transport="http")


def test_config_sse_requires_url() -> None:
    with pytest.raises(MCPConfigError):
        MCPServerConfig(name="x", transport="sse")


def test_config_requires_name() -> None:
    with pytest.raises(MCPConfigError):
        MCPServerConfig(name="", transport="stdio", command="x")


def test_mcpauth_secret_kind_requires_secret_key() -> None:
    with pytest.raises(MCPConfigError):
        MCPAuth(kind="bearer")  # no secret_key
    with pytest.raises(MCPConfigError):
        MCPAuth(kind="env", secret_key="")
    # oauth / none don't need a secret_key.
    assert MCPAuth(kind="oauth").secret_key == ""
    assert MCPAuth(kind="none").secret_key == ""


def test_mcpauth_rejects_invalid_value_template() -> None:
    # A template with an extra placeholder or unbalanced braces would raise at
    # render_value time; __post_init__ rejects it up front (B13).
    with pytest.raises(MCPConfigError):
        MCPAuth(kind="none", value_template="Bearer {token} {extra}")
    with pytest.raises(MCPConfigError):
        MCPAuth(kind="none", value_template="Bearer {token")
    # A valid template (and a literal-brace one using `{{`) is accepted.
    assert MCPAuth(kind="none", value_template="token={token}").render_value("x") == "token=x"
    assert MCPAuth(kind="none", value_template="{{literal}} {token}").render_value("x") == (
        "{literal} x"
    )


def test_stdio_server_redirects_stderr_to_log_file() -> None:
    """A stdio MCP server's stderr must go to a log file, not the terminal —
    otherwise the server's logs (tools/list traffic, etc.) paint over the TUI."""
    import tempfile

    from pydantic_deep.mcp.registry import _stdio_log_file

    path = _stdio_log_file("my/server name")
    assert str(path).startswith(tempfile.gettempdir())
    assert path.name == "my_server_name.log"  # sanitised, not the raw name
    # Building a stdio server with the redirect must not raise.
    cfg = MCPServerConfig(name="demo", transport="stdio", command="echo", args=["hi"])
    assert build_mcp_server(cfg) is not None


def test_oauth_auth_does_not_require_secret() -> None:
    cfg = MCPServerConfig(
        name="figma", transport="http", url="https://mcp.figma.com/mcp", auth=MCPAuth(kind="oauth")
    )
    assert cfg.requires_auth is False
    assert auth_satisfied(cfg, lambda k: None) is True


def test_build_oauth_server() -> None:
    cfg = MCPServerConfig(
        name="figma", transport="http", url="https://mcp.figma.com/mcp", auth=MCPAuth(kind="oauth")
    )
    ts = build_mcp_server(cfg, lambda k: None)
    assert _transport(ts).url == "https://mcp.figma.com/mcp"
    # OAuth is wired onto the transport (not a static header).
    assert getattr(_transport(ts), "auth", None) is not None


def test_build_oauth_server_with_persistent_storage(tmp_path: Path) -> None:
    from key_value.aio.stores.disk import DiskStore

    cfg = MCPServerConfig(
        name="figma", transport="http", url="https://mcp.figma.com/mcp", auth=MCPAuth(kind="oauth")
    )
    store = DiskStore(directory=str(tmp_path / "oauth"))
    ts = build_mcp_server(cfg, lambda k: None, oauth_token_storage=store)
    assert _transport(ts).url == "https://mcp.figma.com/mcp"
    assert getattr(_transport(ts), "auth", None) is not None


def test_build_oauth_with_client_name() -> None:
    # A custom client_name forces a real OAuth object even without storage
    # (some servers, e.g. Figma's beta, allowlist the client name).
    cfg = MCPServerConfig(
        name="figma",
        transport="http",
        url="https://mcp.figma.com/mcp",
        auth=MCPAuth(kind="oauth", client_name="My Client"),
    )
    ts = build_mcp_server(cfg, lambda k: None)
    assert getattr(_transport(ts), "auth", None) is not None


def test_registry_threads_oauth_storage(tmp_path: Path) -> None:
    from key_value.aio.stores.disk import DiskStore

    store = DiskStore(directory=str(tmp_path / "oauth"))
    reg = MCPRegistry(resolver=lambda k: None, oauth_token_storage=store)
    cfg = MCPServerConfig(
        name="figma", transport="http", url="https://mcp.figma.com/mcp", auth=MCPAuth(kind="oauth")
    )
    reg.add(cfg)
    ts = reg.build(cfg)
    assert _transport(ts).url == "https://mcp.figma.com/mcp"


def test_config_requires_auth_property() -> None:
    no_auth = MCPServerConfig(name="a", transport="http", url="http://x")
    assert no_auth.requires_auth is False
    none_auth = MCPServerConfig(
        name="b", transport="http", url="http://x", auth=MCPAuth(secret_key="K", kind="none")
    )
    assert none_auth.requires_auth is False
    with_auth = MCPServerConfig(
        name="c", transport="http", url="http://x", auth=MCPAuth(secret_key="K")
    )
    assert with_auth.requires_auth is True


def test_config_roundtrip_stdio_and_http() -> None:
    stdio = MCPServerConfig(
        name="s",
        transport="stdio",
        command="npx",
        args=["-y", "pkg"],
        env={"A": "B"},
        tool_prefix="s",
        auth=MCPAuth(secret_key="K", kind="env", env_var="TOKEN"),
    )
    assert MCPServerConfig.from_dict(stdio.to_dict()) == stdio

    http = MCPServerConfig(
        name="h",
        transport="http",
        url="http://x/mcp",
        headers={"X": "1"},
        description="d",
        builtin=True,
    )
    assert MCPServerConfig.from_dict(http.to_dict()) == http


# ── builtins ─────────────────────────────────────────────────────────────


def test_builtins_names_and_freshness() -> None:
    a = builtin_mcp_servers()
    b = builtin_mcp_servers()
    assert [c.name for c in a] == list(BUILTIN_MCP_NAMES)
    # Fresh copies: mutating one batch doesn't affect the next.
    a[0].enabled = True
    assert b[0].enabled is False
    # github needs a bearer token; figma uses OAuth (no pre-stored secret).
    gh = next(c for c in a if c.name == "github")
    assert gh.requires_auth is True
    figma = next(c for c in a if c.name == "figma")
    assert figma.auth is not None and figma.auth.kind == "oauth"
    assert figma.requires_auth is False
    assert figma.url == "https://mcp.figma.com/mcp"
    # The local Dev Mode server is offered separately.
    local = next(c for c in a if c.name == "figma-local")
    assert local.url == "http://127.0.0.1:3845/mcp"


# ── auth_satisfied ───────────────────────────────────────────────────────


def test_auth_satisfied_variants() -> None:
    no_auth = MCPServerConfig(name="a", transport="http", url="http://x")
    assert auth_satisfied(no_auth) is True

    none_auth = MCPServerConfig(
        name="b", transport="http", url="http://x", auth=MCPAuth(secret_key="K", kind="none")
    )
    assert auth_satisfied(none_auth) is True

    needs = MCPServerConfig(
        name="c", transport="http", url="http://x", auth=MCPAuth(secret_key="K")
    )
    assert auth_satisfied(needs, lambda k: None) is False
    assert auth_satisfied(needs, lambda k: "tok") is True


def test_auth_satisfied_default_resolver_uses_env(monkeypatch: pytest.MonkeyPatch) -> None:
    needs = MCPServerConfig(
        name="c", transport="http", url="http://x", auth=MCPAuth(secret_key="MY_ENV_KEY")
    )
    monkeypatch.delenv("MY_ENV_KEY", raising=False)
    assert auth_satisfied(needs) is False
    monkeypatch.setenv("MY_ENV_KEY", "v")
    assert auth_satisfied(needs) is True


# ── build_mcp_server ─────────────────────────────────────────────────────


def test_build_http_with_bearer() -> None:
    cfg = MCPServerConfig(
        name="gh", transport="http", url="http://x/mcp", auth=MCPAuth(secret_key="K")
    )
    ts = build_mcp_server(cfg, lambda k: "tok")
    assert _transport(ts).url == "http://x/mcp"
    assert _transport(ts).headers["Authorization"] == "Bearer tok"


def test_build_http_header_kind() -> None:
    cfg = MCPServerConfig(
        name="figma",
        transport="http",
        url="http://x/mcp",
        auth=MCPAuth(secret_key="K", kind="header", header="X-Token", value_template="{token}"),
    )
    ts = build_mcp_server(cfg, lambda k: "raw")
    assert _transport(ts).headers["X-Token"] == "raw"


def test_build_http_no_token_leaves_headers() -> None:
    cfg = MCPServerConfig(
        name="x", transport="http", url="http://x/mcp", auth=MCPAuth(secret_key="K")
    )
    ts = build_mcp_server(cfg, lambda k: None)
    assert "Authorization" not in (_transport(ts).headers or {})


def test_build_stdio_with_env_auth_explicit_var() -> None:
    cfg = MCPServerConfig(
        name="s",
        transport="stdio",
        command="npx",
        args=["-y", "pkg"],
        auth=MCPAuth(secret_key="K", kind="env", env_var="GH_TOKEN"),
    )
    ts = build_mcp_server(cfg, lambda k: "tok")
    assert _transport(ts).command == "npx"
    assert _transport(ts).args == ["-y", "pkg"]
    assert _transport(ts).env["GH_TOKEN"] == "tok"


def test_build_stdio_env_auth_defaults_to_secret_key() -> None:
    cfg = MCPServerConfig(
        name="s",
        transport="stdio",
        command="run",
        auth=MCPAuth(secret_key="MY_KEY", kind="env"),
    )
    ts = build_mcp_server(cfg, lambda k: "tok")
    assert _transport(ts).env["MY_KEY"] == "tok"


def test_build_with_tool_prefix_wraps() -> None:
    cfg = MCPServerConfig(name="p", transport="http", url="http://x/mcp", tool_prefix="pp")
    ts = build_mcp_server(cfg, lambda k: None)
    assert type(ts).__name__ == "PrefixedToolset"


def test_build_default_resolver(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = MCPServerConfig(name="x", transport="http", url="http://x/mcp")
    ts = build_mcp_server(cfg)  # no resolver -> env-based default
    assert _transport(ts).url == "http://x/mcp"
    monkeypatch.setenv("UNUSED", "1")


def test_build_raises_when_mcp_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom() -> tuple[Any, ...]:
        raise ImportError("no mcp")

    monkeypatch.setattr(registry_mod, "_load_mcp_classes", _boom)
    cfg = MCPServerConfig(name="x", transport="http", url="http://x/mcp")
    with pytest.raises(MCPNotInstalledError):
        build_mcp_server(cfg)


# ── MCPRegistry ──────────────────────────────────────────────────────────


def test_registry_crud_and_status() -> None:
    reg = MCPRegistry(builtin_mcp_servers(), resolver=lambda k: None)
    assert {c.name for c in reg.list_servers()} == set(BUILTIN_MCP_NAMES)
    assert reg.get("missing") is None

    gh = reg.get("github")
    assert gh is not None
    assert reg.status(gh) == "disabled"  # builtins disabled by default
    reg.set_enabled("github", True)
    assert reg.status(gh) == "needs_auth"  # enabled but no token

    assert reg.set_enabled("nope", True) is False

    custom = MCPServerConfig(name="custom", transport="http", url="http://x/mcp")
    reg.add(custom)
    assert reg.status(custom) == "ready"  # enabled, no auth needed
    assert reg.remove("custom") is True
    assert reg.remove("custom") is False


def test_registry_build_active_filters() -> None:
    reg = MCPRegistry(resolver=lambda k: "tok")
    reg.add(MCPServerConfig(name="on", transport="http", url="http://a/mcp"))
    reg.add(MCPServerConfig(name="off", transport="http", url="http://b/mcp", enabled=False))
    reg.add(
        MCPServerConfig(
            name="auth_on",
            transport="http",
            url="http://c/mcp",
            auth=MCPAuth(secret_key="K"),
        )
    )
    reg.add(
        MCPServerConfig(
            name="auth_missing",
            transport="http",
            url="http://d/mcp",
            auth=MCPAuth(secret_key="K"),
        )
    )
    # Resolver returns "tok" for all -> auth_missing is actually satisfied here.
    active = reg.build_active()
    # on + auth_on + auth_missing = 3 ready; off disabled.
    assert len(active) == 3


def test_registry_build_active_skips_needs_auth() -> None:
    reg = MCPRegistry(resolver=lambda k: None)
    reg.add(MCPServerConfig(name="plain", transport="http", url="http://a/mcp"))
    reg.add(
        MCPServerConfig(
            name="needs", transport="http", url="http://b/mcp", auth=MCPAuth(secret_key="K")
        )
    )
    active = reg.build_active()
    assert len(active) == 1  # only the no-auth one


def test_registry_build_delegates() -> None:
    resolver = lambda k: "t"  # noqa: E731
    reg = MCPRegistry(resolver=resolver)
    assert reg.resolver is resolver
    cfg = MCPServerConfig(
        name="x", transport="http", url="http://x/mcp", auth=MCPAuth(secret_key="K")
    )
    reg.add(cfg)
    ts = reg.build(cfg)
    assert _transport(ts).headers["Authorization"] == "Bearer t"


# ── probe_mcp_server ─────────────────────────────────────────────────────


class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name


class _FakeServer:
    def __init__(self, tools: list[str], fail: bool = False) -> None:
        self._tools = tools
        self._fail = fail

    async def __aenter__(self) -> _FakeServer:
        if self._fail:
            raise RuntimeError("connection refused")
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def list_tools(self) -> list[_FakeTool]:
        return [_FakeTool(n) for n in self._tools]


async def test_probe_success() -> None:
    result = await probe_mcp_server(_FakeServer(["a", "b"]))
    assert isinstance(result, MCPProbeResult)
    assert result.ok is True
    assert result.tool_count == 2
    assert result.tool_names == ["a", "b"]


async def test_probe_failure() -> None:
    result = await probe_mcp_server(_FakeServer([], fail=True))
    assert result.ok is False
    assert "connection refused" in (result.error or "")


# ── create_deep_agent integration ───────────────────────────────────────


def test_create_deep_agent_attaches_mcp_servers() -> None:
    from pydantic_ai.models.test import TestModel

    from pydantic_deep import create_deep_agent

    server = build_mcp_server(
        MCPServerConfig(name="deepwiki", transport="http", url="https://mcp.deepwiki.com/mcp"),
        lambda k: None,
    )
    agent = create_deep_agent(
        model=TestModel(call_tools=[]),
        mcp_servers=[server],
        include_skills=False,
        include_plan=False,
        include_memory=False,
        include_subagents=False,
        include_teams=False,
        include_todo=False,
        include_filesystem=False,
        include_execute=False,
        web_search=False,
        web_fetch=False,
        cost_tracking=False,
        context_manager=False,
        stuck_loop_detection=False,
        context_discovery=False,
    )
    flat = repr(getattr(agent, "toolsets", []))
    assert "deepwiki" in flat or "MCPToolset" in flat


# ── resilient wrapper ────────────────────────────────────────────────────


class _FakeWrapped:
    """Minimal AbstractToolset-shaped stand-in whose methods can be made to fail."""

    def __init__(self, fail: set[str] | None = None) -> None:
        self.fail = fail or set()
        self.entered = False
        self.exited = False

    @property
    def id(self) -> None:
        return None

    @property
    def label(self) -> str:
        return "fake"

    async def for_run(self, ctx: object) -> _FakeWrapped:
        if "for_run" in self.fail:
            raise RuntimeError("for_run boom")
        return self

    async def for_run_step(self, ctx: object) -> _FakeWrapped:
        return self

    async def __aenter__(self) -> _FakeWrapped:
        if "aenter" in self.fail:
            raise RuntimeError("connect boom")
        self.entered = True
        return self

    async def __aexit__(self, *args: object) -> None:
        if "aexit" in self.fail:
            raise RuntimeError("exit boom")
        self.exited = True
        return None

    async def get_tools(self, ctx: object) -> dict[str, object]:
        if "get_tools" in self.fail:
            raise RuntimeError("tools boom")
        return {"t": object()}

    async def get_instructions(self, ctx: object) -> str:
        if "instr" in self.fail:
            raise RuntimeError("instr boom")
        return "instructions"

    def apply(self, visitor: object) -> None:
        pass

    def visit_and_replace(self, visitor: object) -> _FakeWrapped:
        return self


async def test_resilient_passthrough_when_healthy() -> None:
    from pydantic_deep.mcp import make_resilient

    fake = _FakeWrapped()
    w = make_resilient(fake, "srv")
    ctx = object()
    prepared = await w.for_run(ctx)
    assert prepared is w  # wrapped unchanged -> same wrapper instance
    await w.__aenter__()
    assert fake.entered is True
    tools = await w.get_tools(ctx)
    assert "t" in tools
    instr = await w.get_instructions(ctx)
    assert instr == "instructions"
    assert await w.__aexit__(None, None, None) is None
    assert fake.exited is True


async def test_resilient_degrades_on_connect_failure() -> None:
    from pydantic_deep.mcp import make_resilient

    fake = _FakeWrapped(fail={"aenter"})
    w = make_resilient(fake, "srv")
    ctx = object()
    await w.for_run(ctx)
    await w.__aenter__()  # swallows connect failure
    # Degraded: no tools, no instructions, aexit is a no-op.
    assert await w.get_tools(ctx) == {}
    assert await w.get_instructions(ctx) is None
    assert await w.__aexit__(None, None, None) is None
    # Entering again while degraded short-circuits.
    assert await w.__aenter__() is w


async def test_resilient_degrades_on_for_run_failure() -> None:
    from pydantic_deep.mcp import make_resilient

    fake = _FakeWrapped(fail={"for_run"})
    w = make_resilient(fake, "srv")
    ctx = object()
    prepared = await w.for_run(ctx)
    assert prepared is w
    # for_run failed -> __aenter__ skips the wrapped, tools empty.
    await w.__aenter__()
    assert fake.entered is False
    assert await w.get_tools(ctx) == {}


async def test_resilient_degrades_on_get_tools_failure() -> None:
    from pydantic_deep.mcp import make_resilient

    fake = _FakeWrapped(fail={"get_tools"})
    w = make_resilient(fake, "srv")
    ctx = object()
    await w.for_run(ctx)
    await w.__aenter__()
    assert await w.get_tools(ctx) == {}
    # Now flagged failed -> instructions also degrade.
    assert await w.get_instructions(ctx) is None


async def test_resilient_on_degraded_fires_once() -> None:
    from pydantic_deep.mcp import make_resilient

    calls: list[tuple[str, str]] = []
    fake = _FakeWrapped(fail={"aenter"})
    w = make_resilient(fake, "srv", on_degraded=lambda n, r: calls.append((n, r)))
    ctx = object()
    # Two runs, both fail to connect — callback fires only once.
    await w.for_run(ctx)
    await w.__aenter__()
    await w.for_run(ctx)
    await w.__aenter__()
    assert len(calls) == 1
    assert calls[0][0] == "srv"


async def test_resilient_on_degraded_exception_suppressed() -> None:
    from pydantic_deep.mcp import make_resilient

    def _boom(name: str, reason: str) -> None:
        raise RuntimeError("callback boom")

    fake = _FakeWrapped(fail={"aenter"})
    w = make_resilient(fake, "srv", on_degraded=_boom)
    ctx = object()
    await w.for_run(ctx)
    await w.__aenter__()  # callback raises internally -> suppressed
    assert await w.get_tools(ctx) == {}


def test_build_active_forwards_on_degraded() -> None:
    from pydantic_deep.mcp import MCPRegistry

    reg = MCPRegistry(resolver=lambda k: None)
    reg.add(MCPServerConfig(name="x", transport="http", url="http://x/mcp"))
    active = reg.build_active(on_degraded=lambda n, r: None)
    assert len(active) == 1


async def test_resilient_instructions_and_exit_failures_swallowed() -> None:
    from pydantic_deep.mcp import make_resilient

    fake = _FakeWrapped(fail={"instr", "aexit"})
    w = make_resilient(fake, "srv")
    ctx = object()
    await w.for_run(ctx)
    await w.__aenter__()
    # get_instructions raises internally -> None (not flagged failed by instr path)
    assert await w.get_instructions(ctx) is None
    # __aexit__ raises internally -> swallowed to None
    assert await w.__aexit__(None, None, None) is None
