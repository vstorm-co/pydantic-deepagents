"""Declarative configuration for MCP (Model Context Protocol) servers.

These dataclasses describe *how to connect* to an MCP server and *how to
authenticate*, decoupled from pydantic-ai's concrete server classes and from
any particular secret store. :mod:`pydantic_deep.mcp.registry` turns a
``MCPServerConfig`` into a live pydantic-ai toolset, resolving secrets through
a caller-supplied resolver (the CLI backs this with its keystore).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

__all__ = [
    "MCPAuth",
    "MCPServerConfig",
    "MCPConfigError",
    "MCPTransport",
    "MCPAuthKind",
]

MCPTransport = Literal["stdio", "http", "sse"]
"""Supported MCP transports: local subprocess (`stdio`) or remote (`http`/`sse`)."""

MCPAuthKind = Literal["none", "bearer", "header", "env", "oauth"]
"""How a connection is authenticated.

- `none`: no authentication.
- `bearer`/`header`: inject an HTTP header from a stored secret (bearer is a
  header with a `Bearer {token}` template).
- `env`: set an environment variable on a stdio subprocess from a stored secret.
- `oauth`: interactive OAuth flow handled by the client at connect time (no
  stored secret); used by hosted servers like Figma's `https://mcp.figma.com/mcp`.
"""

# Auth kinds that resolve a pre-stored secret (so the CLI needs a login/token).
_SECRET_AUTH_KINDS = ("bearer", "header", "env")


class MCPConfigError(ValueError):
    """Raised when an :class:`MCPServerConfig` is structurally invalid."""


@dataclass
class MCPAuth:
    """Describes how to authenticate to an MCP server using a stored secret.

    Args:
        secret_key: Name under which the token is stored (keystore / env var),
            e.g. ``"GITHUB_MCP_PAT"``. Not required for ``oauth``/``none``.
        kind: How auth is performed (see :data:`MCPAuthKind`).
        header: Header name for ``bearer``/``header`` auth.
        env_var: Environment variable name for ``env`` auth (defaults to
            ``secret_key`` when omitted).
        value_template: Template formatted with ``token=<secret>`` to produce
            the header/env value. Defaults to ``"Bearer {token}"``.
        instructions: Human-readable hint on how to obtain the token, shown in
            the CLI login flow.
        client_name: OAuth client name advertised during dynamic client
            registration (``oauth`` only). Some servers (e.g. Figma's hosted MCP
            during beta) allowlist this; leave ``None`` to use the default.
    """

    secret_key: str = ""
    kind: MCPAuthKind = "bearer"
    header: str = "Authorization"
    env_var: str | None = None
    value_template: str = "Bearer {token}"
    instructions: str = ""
    client_name: str | None = None

    def __post_init__(self) -> None:
        if self.kind in _SECRET_AUTH_KINDS and not self.secret_key:
            raise MCPConfigError(f"{self.kind} MCP auth requires a non-empty secret_key")
        # Fail fast on a template that would raise at `render_value` time —
        # extra placeholders (`{foo}`) or unbalanced literal braces (B13).
        try:
            self.value_template.format(token="")
        except (KeyError, IndexError, ValueError) as exc:
            raise MCPConfigError(f"invalid value_template {self.value_template!r}: {exc}") from exc

    def render_value(self, token: str) -> str:
        """Format `value_template` with the resolved token."""
        return self.value_template.format(token=token)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MCPAuth:
        return cls(
            secret_key=data.get("secret_key", ""),
            kind=data.get("kind", "bearer"),
            header=data.get("header", "Authorization"),
            env_var=data.get("env_var"),
            value_template=data.get("value_template", "Bearer {token}"),
            instructions=data.get("instructions", ""),
            client_name=data.get("client_name"),
        )


@dataclass
class MCPServerConfig:
    """Connection + auth description for a single MCP server.

    A `stdio` server requires `command`; `http`/`sse` servers require `url`.
    """

    name: str
    transport: MCPTransport = "stdio"
    # stdio transport
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    # http / sse transport
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    # common
    tool_prefix: str | None = None
    enabled: bool = True
    description: str = ""
    builtin: bool = False
    auth: MCPAuth | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise MCPConfigError("MCP server config requires a non-empty name")
        if self.transport == "stdio":
            if not self.command:
                raise MCPConfigError(f"stdio MCP server '{self.name}' requires a command")
        elif self.transport in ("http", "sse"):
            if not self.url:
                raise MCPConfigError(f"{self.transport} MCP server '{self.name}' requires a url")
        else:  # pragma: no cover - guarded by the Literal type, defensive only
            raise MCPConfigError(f"unknown transport '{self.transport}' for '{self.name}'")

    @property
    def requires_auth(self) -> bool:
        """True when a pre-stored secret must be provided before use.

        ``oauth`` returns False: there's no token to enter up front — the client
        runs the OAuth flow interactively at connect time.
        """
        return self.auth is not None and self.auth.kind in _SECRET_AUTH_KINDS

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MCPServerConfig:
        auth_data = data.get("auth")
        return cls(
            name=data["name"],
            transport=data.get("transport", "stdio"),
            command=data.get("command"),
            args=list(data.get("args", [])),
            env=dict(data.get("env", {})),
            url=data.get("url"),
            headers=dict(data.get("headers", {})),
            tool_prefix=data.get("tool_prefix"),
            enabled=data.get("enabled", True),
            description=data.get("description", ""),
            builtin=data.get("builtin", False),
            auth=MCPAuth.from_dict(auth_data) if auth_data is not None else None,
        )
