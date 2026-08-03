"""Turn :class:`MCPServerConfig` declarations into live pydantic-ai toolsets.

The registry holds a set of server configs, resolves their auth secrets through
a pluggable resolver (env var by default; the CLI swaps in a keystore-backed
one), and builds connected MCP toolsets ready to attach to an agent. It also
exposes a connection probe used by the CLI's ``/mcp`` test action.

MCP support is optional — :func:`build_mcp_server` raises
:class:`MCPNotInstalledError` with an install hint if the ``mcp`` extra is
missing, so importing this module never hard-requires the dependency.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
import os
import re
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic_deep.mcp.config import _SECRET_AUTH_KINDS, MCPAuth, MCPServerConfig
from pydantic_deep.mcp.resources import create_mcp_resources_toolset


def _stdio_log_file(name: str) -> Path:
    """Path that a stdio MCP server's stderr is redirected to.

    By default fastmcp inherits the parent's ``sys.stderr``; under the TUI that
    means the server's logs (handshake, ``tools/list`` traffic, warnings) paint
    over the live screen. Redirecting to a per-server log file keeps the logs
    discoverable without corrupting the terminal.
    """
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", name) or "server"
    log_dir = Path(tempfile.gettempdir()) / "pydantic-deep" / "mcp"
    with contextlib.suppress(Exception):
        log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"{safe}.log"


if TYPE_CHECKING:
    import httpx
    from pydantic_ai._run_context import RunContext
    from pydantic_ai.toolsets import AbstractToolset
    from pydantic_ai.toolsets.abstract import ToolsetTool

logger = logging.getLogger("pydantic_deep.mcp")

__all__ = [
    "SecretResolver",
    "HttpClientFactory",
    "MCPRegistry",
    "MCPProbeResult",
    "MCPNotInstalledError",
    "MCP_INSTALL_HINT",
    "build_mcp_server",
    "make_resilient",
    "auth_satisfied",
]

SecretResolver = Callable[[str], "str | None"]
"""Resolves a secret key (e.g. ``"GITHUB_MCP_PAT"``) to its token, or ``None``."""

HttpClientFactory = Callable[[MCPServerConfig], "httpx.AsyncClient"]
"""Builds an ``httpx.AsyncClient`` for a server config (corporate proxy,
custom CA / OS trust store, mTLS, authenticated proxy headers, …).

Every HTTP-based connection goes through it — the MCP transport *and* each
step of the OAuth flow (discovery, registration, token exchange, refresh) —
and each call site closes the client it receives, so the factory must return
a **fresh client per call**, never a shared instance.
"""

MCP_INSTALL_HINT = (
    "MCP support requires the optional 'mcp' extra: "
    "pip install 'pydantic-deep[mcp]' (or 'pydantic-ai-slim[mcp]')."
)

MCPServerStatus = Literal["ready", "disabled", "needs_auth"]


class MCPNotInstalledError(ImportError):
    """Raised when building an MCP server but the optional dependency is absent."""


@dataclass
class MCPProbeResult:
    """Outcome of a connection probe against an MCP server."""

    ok: bool
    tool_count: int = 0
    tool_names: list[str] = field(default_factory=list)
    error: str | None = None


def _default_resolver(key: str) -> str | None:
    return os.environ.get(key)


def _load_mcp_classes() -> tuple[Any, Any, Any]:
    """Import the pydantic-ai/FastMCP classes lazily (isolated for testability)."""
    from fastmcp.client.transports import StdioTransport
    from pydantic_ai.mcp import MCPToolset
    from pydantic_ai.toolsets import PrefixedToolset

    return MCPToolset, PrefixedToolset, StdioTransport


def auth_satisfied(config: MCPServerConfig, resolver: SecretResolver | None = None) -> bool:
    """True when the server needs no pre-stored secret, or its secret resolves.

    ``oauth`` servers are always considered satisfied here — they authorize
    interactively at connect time, with no token to enter up front.
    """
    resolver = resolver or _default_resolver
    auth = config.auth
    if auth is None or auth.kind not in _SECRET_AUTH_KINDS:
        return True
    return bool(resolver(auth.secret_key))


def _adapt_http_client_factory(
    factory: HttpClientFactory, config: MCPServerConfig
) -> Callable[..., httpx.AsyncClient]:
    """Adapt a per-config client factory to the MCP SDK's factory protocol.

    FastMCP invokes the factory once per connection (transport traffic and each
    OAuth step) and closes every client it receives, so each call must produce
    a fresh client. The keyword arguments FastMCP passes are applied on top of
    the caller's client — ``auth`` in particular carries the OAuth object and
    dropping it would leave requests unauthenticated.
    """

    def make_client(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        client = factory(config)
        if headers:
            client.headers.update(headers)
        if timeout is not None:
            client.timeout = timeout
        if auth is not None:
            client.auth = auth
        return client

    return make_client


def _scoped_token_storage(storage: Any, scopes: Sequence[str]) -> Any:
    """Namespace an OAuth token store by the requested scope set.

    FastMCP keys cached tokens by server URL only, so after a config's
    ``scopes`` change the token minted under the old set would silently keep
    being used. Prefixing the store's keys with a scope-set hash forces a
    fresh authorization per scope set (switching back reuses the old token).
    """
    from key_value.aio.wrappers.prefix_keys import PrefixKeysWrapper

    digest = hashlib.sha256(",".join(sorted(scopes)).encode()).hexdigest()[:16]
    return PrefixKeysWrapper(key_value=storage, prefix=f"scopes-{digest}")


def _build_oauth(
    config: MCPServerConfig,
    auth: MCPAuth,
    *,
    oauth_token_storage: Any | None,
    client_factory: Callable[..., httpx.AsyncClient] | None,
) -> Any:
    """Construct the FastMCP ``OAuth`` object for an ``oauth``-kind config."""
    from fastmcp.client.auth.oauth import OAuth

    oauth_kwargs: dict[str, Any] = {"mcp_url": cast(str, config.url)}
    if oauth_token_storage is not None:
        storage = oauth_token_storage
        if auth.scopes:
            storage = _scoped_token_storage(storage, auth.scopes)
        oauth_kwargs["token_storage"] = storage
    if auth.client_name:
        oauth_kwargs["client_name"] = auth.client_name
    if auth.scopes:
        oauth_kwargs["scopes"] = list(auth.scopes)
    if auth.callback_port is not None:
        oauth_kwargs["callback_port"] = auth.callback_port
    if client_factory is not None:
        oauth_kwargs["httpx_client_factory"] = client_factory
    return OAuth(**oauth_kwargs)


def _build_http_transport(
    config: MCPServerConfig,
    client_factory: Callable[..., httpx.AsyncClient],
    *,
    headers: dict[str, str] | None = None,
    auth: Any | None = None,
) -> Any:
    """Build the FastMCP HTTP/SSE transport explicitly.

    ``MCPToolset(url, ...)`` offers no way to hand an ``httpx_client_factory``
    to the transport it builds internally, so a config with a client factory
    constructs the transport itself — chosen from ``config.transport`` rather
    than inferred from the URL — and passes it to the toolset.
    """
    from fastmcp.client.transports import SSETransport, StreamableHttpTransport

    transport_cls = SSETransport if config.transport == "sse" else StreamableHttpTransport
    return transport_cls(
        cast(str, config.url), headers=headers, auth=auth, httpx_client_factory=client_factory
    )


def _build_raw_mcp_toolset(
    config: MCPServerConfig,
    resolver: SecretResolver | None = None,
    *,
    oauth_token_storage: Any | None = None,
    http_client_factory: HttpClientFactory | None = None,
) -> AbstractToolset[Any]:
    """Build the bare ``MCPToolset`` for a config (before any prefix wrapping).

    Split out from :func:`build_mcp_server` so a resources toolset can bind to the
    same underlying ``MCPToolset`` instance and share its connection/cache.

    Raises:
        MCPNotInstalledError: if the ``mcp`` optional dependency is missing.
    """
    resolver = resolver or _default_resolver
    try:
        MCPToolset, _PrefixedToolset, StdioTransport = _load_mcp_classes()
    except ImportError as exc:
        raise MCPNotInstalledError(MCP_INSTALL_HINT) from exc

    headers = dict(config.headers)
    env = dict(config.env)

    extra: dict[str, Any] = {}
    if config.init_timeout is not None:
        extra["init_timeout"] = config.init_timeout

    auth = config.auth
    if auth is not None and auth.kind in _SECRET_AUTH_KINDS:
        token = resolver(auth.secret_key)
        if token:
            if auth.kind == "env":
                env[auth.env_var or auth.secret_key] = token
            else:  # bearer / header
                headers[auth.header] = auth.render_value(token)

    if config.transport == "stdio":
        command = cast(str, config.command)
        # Redirect the subprocess's stderr to a log file — otherwise it inherits
        # sys.stderr and the server's logs paint over the live TUI screen.
        transport = StdioTransport(
            command,
            list(config.args),
            env=env or None,
            log_file=_stdio_log_file(config.name),
        )
        toolset = MCPToolset(transport, id=config.name, **extra)
    elif auth is not None and auth.kind == "oauth":  # http/sse interactive OAuth
        url = cast(str, config.url)
        client_factory = (
            _adapt_http_client_factory(http_client_factory, config)
            if http_client_factory is not None
            else None
        )
        # Anything beyond the plain interactive flow — a persistent token store,
        # custom client name, explicit scopes / callback port, or a custom http
        # client — requires a real OAuth object; otherwise the lightweight
        # "oauth" string is enough.
        if (
            oauth_token_storage is not None
            or auth.client_name
            or auth.scopes
            or auth.callback_port is not None
            or client_factory is not None
        ):
            oauth = _build_oauth(
                config,
                auth,
                oauth_token_storage=oauth_token_storage,
                client_factory=client_factory,
            )
            if client_factory is not None:
                # The factory must reach both sides: the OAuth flow gets it via
                # _build_oauth, the transport's own connections get it here.
                transport = _build_http_transport(config, client_factory, auth=oauth)
                toolset = MCPToolset(transport, id=config.name, **extra)
            else:
                toolset = MCPToolset(url, auth=oauth, id=config.name, **extra)
        else:
            toolset = MCPToolset(url, auth="oauth", id=config.name, **extra)
    else:  # http / sse — FastMCP infers the transport from the URL
        url = cast(str, config.url)
        if http_client_factory is not None:
            transport = _build_http_transport(
                config,
                _adapt_http_client_factory(http_client_factory, config),
                headers=headers or None,
            )
            toolset = MCPToolset(transport, id=config.name, **extra)
        else:
            toolset = MCPToolset(url, headers=headers or None, id=config.name, **extra)

    return cast("AbstractToolset[Any]", toolset)


def _apply_tool_prefix(
    toolset: AbstractToolset[Any], config: MCPServerConfig
) -> AbstractToolset[Any]:
    """Wrap ``toolset`` in a ``PrefixedToolset`` when ``config.tool_prefix`` is set."""
    if not config.tool_prefix:
        return toolset
    _MCPToolset, PrefixedToolset, _StdioTransport = _load_mcp_classes()
    return cast("AbstractToolset[Any]", PrefixedToolset(toolset, config.tool_prefix))


def _resources_tool_prefix(config: MCPServerConfig) -> str:
    """Tool-name prefix for a server's resource tools.

    Every server's resources toolset registers the same four tool names, so two
    servers exposing their resources would collide and pydantic-ai fails the whole
    run on the duplicate. Prefixing with the server name (sanitised to what tool
    names allow) keeps them distinct and tells the model which server it is reading.
    """
    return config.tool_prefix or re.sub(r"[^A-Za-z0-9_-]", "_", config.name)


def build_mcp_server(
    config: MCPServerConfig,
    resolver: SecretResolver | None = None,
    *,
    oauth_token_storage: Any | None = None,
    http_client_factory: HttpClientFactory | None = None,
) -> AbstractToolset[Any]:
    """Build a connected pydantic-ai MCP toolset from a config.

    Resolves the auth secret (if any) and injects it as an HTTP header (for
    ``bearer``/``header`` auth) or a subprocess env var (for ``env`` auth).
    Wraps the toolset in a ``PrefixedToolset`` when ``tool_prefix`` is set.
    When ``config.init_timeout`` is set it is forwarded to the ``MCPToolset``,
    raising the connect/``initialize`` deadline above pydantic-ai's 5s default
    for servers that are slow to become ready.

    Only the server's *tools* are built here. To also expose its resources or
    ``skill://`` skills to the model, set ``include_resources`` / ``include_skills``
    on the config and build via :meth:`MCPRegistry.build_active`.

    For ``stdio`` servers, the subprocess receives ``config.env`` (plus any
    ``env``-kind auth var) layered on top of the MCP SDK's *safe default*
    environment (``PATH``, ``HOME``, …) — the parent process's full environment
    is intentionally **not** inherited, so secrets like API keys are never
    leaked to a third-party server. Add anything else a server needs (proxies,
    ``NODE_EXTRA_CA_CERTS``, …) explicitly via ``config.env``.

    Args:
        oauth_token_storage: A persistent ``AsyncKeyValue`` store for OAuth
            tokens (e.g. a disk-backed store). When provided for an ``oauth``
            server, the token survives restarts and is shared between the
            connection test and the agent (FastMCP keys tokens by server URL).
            When ``None``, FastMCP uses in-memory storage (token re-auth per
            client/restart). With ``auth.scopes`` set, the store is namespaced
            per scope set so a scope change forces a fresh authorization.
        http_client_factory: Escape hatch for network environments that env
            vars can't express (authenticated proxies, OS trust stores, mTLS).
            Applied to the server's HTTP transport *and* its OAuth flow, so a
            single factory covers discovery, token exchange, refresh and
            regular traffic. See :data:`HttpClientFactory` for the contract.
            Ignored for ``stdio`` servers.

    Raises:
        MCPNotInstalledError: if the ``mcp`` optional dependency is missing.
    """
    resolver = resolver or _default_resolver
    raw = _build_raw_mcp_toolset(
        config,
        resolver,
        oauth_token_storage=oauth_token_storage,
        http_client_factory=http_client_factory,
    )
    return _apply_tool_prefix(raw, config)


async def _connect_and_list(server: Any) -> list[str]:
    async with server:
        tools = await server.list_tools()
    return [getattr(t, "name", str(t)) for t in tools]


async def probe_mcp_server(server: Any, timeout: float = 10.0) -> MCPProbeResult:
    """Connect to a built MCP server and list its tools, with a timeout.

    Returns a :class:`MCPProbeResult` capturing success + tool names, or the
    error string on failure. Never raises.
    """
    try:
        names = await asyncio.wait_for(_connect_and_list(server), timeout)
    except Exception as exc:
        return MCPProbeResult(ok=False, error=str(exc) or type(exc).__name__)
    return MCPProbeResult(ok=True, tool_count=len(names), tool_names=names)


def _make_resilient_cls() -> type:  # noqa: C901
    """Build the resilient wrapper class lazily (needs pydantic-ai toolsets)."""
    from pydantic_ai.toolsets.wrapper import WrapperToolset

    @dataclass
    class _ResilientMCPToolset(WrapperToolset[Any]):
        """Wraps an MCP toolset so a server that won't connect degrades to zero
        tools instead of failing the whole agent run.

        A reachable server behaves exactly as the wrapped toolset. When the
        server can't be prepared/connected/listed, the failure is logged once and
        this toolset contributes no tools for that run. Connection is retried on
        the next run (state is reset in :meth:`for_run`).
        """

        server_name: str = "mcp"
        on_degraded: Callable[[str, str], None] | None = None
        _failed: bool = False
        _notified: bool = False

        def _degrade(self, reason: str) -> None:
            self._failed = True
            logger.warning("MCP server %r unavailable: %s", self.server_name, reason)
            # Notify the caller once per wrapper instance to avoid per-run spam.
            if self.on_degraded is not None and not self._notified:
                self._notified = True
                with contextlib.suppress(Exception):
                    self.on_degraded(self.server_name, reason)

        async def for_run(self, ctx: RunContext[Any]) -> AbstractToolset[Any]:
            self._failed = False
            try:
                return await super().for_run(ctx)
            except Exception as exc:
                self._degrade(str(exc) or type(exc).__name__)
                return self

        async def __aenter__(self) -> Any:
            if self._failed:
                return self
            try:
                await self.wrapped.__aenter__()
            except Exception as exc:
                self._degrade(str(exc) or type(exc).__name__)
            return self

        async def __aexit__(self, *args: Any) -> bool | None:
            if self._failed:
                return None
            try:
                return await self.wrapped.__aexit__(*args)
            except Exception:
                return None

        async def get_tools(self, ctx: RunContext[Any]) -> dict[str, ToolsetTool[Any]]:
            if self._failed:
                return {}
            try:
                return await self.wrapped.get_tools(ctx)
            except Exception as exc:
                self._degrade(str(exc) or type(exc).__name__)
                return {}

        async def get_instructions(self, ctx: RunContext[Any]) -> Any:
            if self._failed:
                return None
            try:
                return await self.wrapped.get_instructions(ctx)
            except Exception:
                return None

    return _ResilientMCPToolset


def make_resilient(
    toolset: AbstractToolset[Any],
    server_name: str,
    on_degraded: Callable[[str, str], None] | None = None,
) -> AbstractToolset[Any]:
    """Wrap an MCP toolset so an unreachable server can't break the agent run.

    Tools from a server that fails to connect simply don't appear; every other
    toolset (and the rest of the run) is unaffected. ``on_degraded(name, reason)``
    is invoked once (per wrapper) the first time the server fails, so callers can
    surface "server unavailable" to the user.
    """
    cls = _make_resilient_cls()
    return cast(
        "AbstractToolset[Any]",
        cls(wrapped=toolset, server_name=server_name, on_degraded=on_degraded),
    )


class MCPRegistry:
    """A mutable collection of MCP server configs with secret-aware building."""

    def __init__(
        self,
        configs: Sequence[MCPServerConfig] | None = None,
        resolver: SecretResolver | None = None,
        *,
        oauth_token_storage: Any | None = None,
        http_client_factory: HttpClientFactory | None = None,
    ) -> None:
        self._resolver: SecretResolver = resolver or _default_resolver
        self._oauth_token_storage = oauth_token_storage
        self._http_client_factory = http_client_factory
        self._configs: dict[str, MCPServerConfig] = {}
        for config in configs or []:
            self._configs[config.name] = config

    @property
    def resolver(self) -> SecretResolver:
        return self._resolver

    def list_servers(self) -> list[MCPServerConfig]:
        return list(self._configs.values())

    def get(self, name: str) -> MCPServerConfig | None:
        return self._configs.get(name)

    def add(self, config: MCPServerConfig) -> None:
        self._configs[config.name] = config

    def remove(self, name: str) -> bool:
        return self._configs.pop(name, None) is not None

    def set_enabled(self, name: str, enabled: bool) -> bool:
        config = self._configs.get(name)
        if config is None:
            return False
        config.enabled = enabled
        return True

    def auth_satisfied(self, config: MCPServerConfig) -> bool:
        return auth_satisfied(config, self._resolver)

    def status(self, config: MCPServerConfig) -> MCPServerStatus:
        if not config.enabled:
            return "disabled"
        if not self.auth_satisfied(config):
            return "needs_auth"
        return "ready"

    def build(self, config: MCPServerConfig) -> AbstractToolset[Any]:
        return build_mcp_server(
            config,
            self._resolver,
            oauth_token_storage=self._oauth_token_storage,
            http_client_factory=self._http_client_factory,
        )

    def build_active(
        self, on_degraded: Callable[[str, str], None] | None = None
    ) -> list[AbstractToolset[Any]]:
        """Build toolsets for every server that is enabled and authenticated.

        Each is wrapped via :func:`make_resilient` so that a configured server
        which turns out to be unreachable at runtime contributes no tools rather
        than failing the entire agent run. ``on_degraded(name, reason)`` is
        forwarded to each wrapper.

        A server with ``include_resources`` / ``include_skills`` set contributes a
        second toolset exposing its MCP resources (and ``skill://`` skills) to the
        model. It binds to the same underlying ``MCPToolset`` so tools and
        resources share one connection, and its tools are prefixed per server so
        several such servers can be active at once.
        """
        servers: list[AbstractToolset[Any]] = []
        for config in self._configs.values():
            if self.status(config) != "ready":
                continue
            raw = _build_raw_mcp_toolset(
                config,
                self._resolver,
                oauth_token_storage=self._oauth_token_storage,
                http_client_factory=self._http_client_factory,
            )
            servers.append(
                make_resilient(_apply_tool_prefix(raw, config), config.name, on_degraded)
            )
            if config.include_resources or config.include_skills:
                resources = create_mcp_resources_toolset(
                    cast("Any", raw),
                    server_name=config.name,
                    include_skills=config.include_skills,
                    tool_prefix=_resources_tool_prefix(config),
                )
                servers.append(make_resilient(resources, config.name, on_degraded))
        return servers
