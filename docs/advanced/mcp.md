# MCP Servers

pydantic-deep has first-class support for [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)
servers — connect your agent to GitHub, Figma, documentation lookups, or any
custom server, with auth handled for you. MCP tools appear as native tools
alongside the filesystem, web, and other deep-agent tools.

MCP support is an optional extra:

```bash
pip install 'pydantic-deep[mcp]'
```

## Quick start

Build a server config, turn it into a toolset, and attach it:

```python
from pydantic_deep import create_deep_agent, build_mcp_server, MCPServerConfig

deepwiki = build_mcp_server(
    MCPServerConfig(
        name="deepwiki",
        transport="http",
        url="https://mcp.deepwiki.com/mcp",
    )
)

agent = create_deep_agent(mcp_servers=[deepwiki])


async def main():
    async with agent:  # connects MCP servers for the duration of the block
        result = await agent.run("What does the pydantic/pydantic repo do?")
        print(result.output)
```

`mcp_servers` accepts any pydantic-ai toolset, so you can also pass
`pydantic_ai.mcp.MCPToolset(...)` instances directly.

## Declaring servers

[`MCPServerConfig`][pydantic_deep.mcp.MCPServerConfig] describes how to connect
and [`MCPAuth`][pydantic_deep.mcp.MCPAuth] describes how to authenticate:

```python
from pydantic_deep import MCPServerConfig, MCPAuth

# Remote HTTP server with a bearer token
github = MCPServerConfig(
    name="github",
    transport="http",
    url="https://api.githubcopilot.com/mcp/",
    auth=MCPAuth(secret_key="GITHUB_MCP_PAT", kind="bearer"),
)

# Local stdio server (subprocess) with a token passed via env var
local = MCPServerConfig(
    name="my-tool",
    transport="stdio",
    command="npx",
    args=["-y", "@scope/my-mcp-server"],
    auth=MCPAuth(secret_key="MY_TOKEN", kind="env", env_var="API_TOKEN"),
)
```

Auth `kind` options:

| kind     | effect                                                          |
|----------|-----------------------------------------------------------------|
| `bearer` | adds `Authorization: Bearer <token>` (the default)              |
| `header` | adds a custom header (`header=` + `value_template=`)            |
| `env`    | sets an env var on the stdio subprocess (`env_var=`)           |
| `oauth`  | interactive OAuth at connect time (no stored token); hosted servers like Figma |
| `none`   | no auth                                                         |

`oauth` servers (e.g. the hosted Figma server `https://mcp.figma.com/mcp`) need no
pre-stored secret — the client opens a browser to sign in on first connect. In
the CLI, press `t` in `/mcp` to trigger the sign-in; the token is cached
persistently under `~/.pydantic-deep/mcp-oauth` (via `mcp_oauth_storage()`) and
keyed by server URL, so authorizing once works for the agent too and survives
restarts. Pass `oauth_token_storage=` to
[`build_mcp_server`][pydantic_deep.mcp.build_mcp_server] / `MCPRegistry` to
control where tokens are stored.

The token itself is never stored in the config — it is resolved at build time
through a **secret resolver** (`os.environ` by default; the CLI uses its
keystore). This keeps secrets out of any file you might commit.

## Registry

[`MCPRegistry`][pydantic_deep.mcp.MCPRegistry] manages a set of servers and
builds only those that are enabled and authenticated:

```python
from pydantic_deep import MCPRegistry, builtin_mcp_servers

registry = MCPRegistry(builtin_mcp_servers(), resolver=lambda key: my_secrets.get(key))
registry.set_enabled("deepwiki", True)

agent = create_deep_agent(mcp_servers=registry.build_active())
```

[`builtin_mcp_servers()`][pydantic_deep.mcp.builtin_mcp_servers] ships curated
definitions: `github` (hosted MCP, needs a PAT), `figma` (hosted MCP, OAuth),
`figma-local` (Dev Mode desktop server), `context7` (library docs), and
`deepwiki` (ask any public repo). All are disabled by default.

!!! warning "Figma's hosted server is allowlisted during beta"
    Figma's hosted MCP (`https://mcp.figma.com/mcp`) allowlists OAuth clients by
    name during its beta, so generic clients get **`403 Registration failed`** at
    sign-in (it only works in clients with a pre-registered ID, like Claude's
    own CLI). Until Figma opens this up, use the **`figma-local`** built-in (the
    Dev Mode desktop server, no OAuth) — Figma's own recommended workaround. If
    you know an allowlisted client name, set `MCPAuth(kind="oauth",
    client_name="…")` to advertise it.

## Testing a connection

[`probe_mcp_server`][pydantic_deep.mcp.probe_mcp_server] connects to a server
and lists its tools, returning an [`MCPProbeResult`][pydantic_deep.mcp.MCPProbeResult]
without raising:

```python
from pydantic_deep import probe_mcp_server

result = await probe_mcp_server(registry.build(github))
if result.ok:
    print(f"connected — {result.tool_count} tools")
else:
    print(f"failed: {result.error}")
```

## Import from Claude Code

If you already use [Claude Code](https://code.claude.com/docs/en/mcp) and have
MCP servers configured there, press `i` in `/mcp` (or call
[`parse_mcp_servers`][pydantic_deep.mcp.parse_mcp_servers] /
`apps.cli.mcp_store.import_claude_code_servers`) to import them. We read the
same standard `mcpServers` JSON shape Claude Code writes, merging its three
scopes with the same precedence (local > project > user):

- **project** — `.mcp.json` in the project root
- **user** — top-level `mcpServers` in `~/.claude.json`
- **local** — this project's entry under `projects[<path>].mcpServers` in `~/.claude.json`

`${VAR}` / `${VAR:-default}` references are expanded, and tokens already present
in `env`/`headers` carry over — so imported servers work immediately. Built-in
server names are never overwritten by an import.

!!! note
    This imports **file-configured** servers (those added with `claude mcp add`).
    It does **not** import [claude.ai connectors](https://claude.ai/customize/connectors)
    — those live in your Anthropic account, not in a local config file, and are
    fetched by Claude Code at runtime rather than stored as `mcpServers`.

## CLI: the `/mcp` command

In the terminal app, type `/mcp` to open the interactive manager:

- **list** every server with its status — `●` ready, `○` disabled, `⚠` needs login
- **enable / disable** with `e`
- **log in** with `l` — paste a token, stored in the git-ignored keystore (`keys.toml`)
- **log out** with `o` — revoke a stored token (removes it from the keystore and the live environment)
- **test** the connection with `t`
- **add** a custom server with `a`, **import** from Claude Code with `i`, or **remove** one with `d`

User servers and per-builtin state persist to `.pydantic-deep/mcp.json`; tokens
live in `.pydantic-deep/keys.toml`. Enabled + authenticated servers are wired
into the agent automatically.

## Without the extra installed

If the `mcp` extra is missing, building a server raises
[`MCPNotInstalledError`][pydantic_deep.mcp.MCPNotInstalledError]. The CLI
degrades gracefully — the agent still starts, just without MCP tools.

## Alternative: the `MCP` capability

pydantic-ai also ships a lower-level `MCP` capability you can pass via
`capabilities=[...]` for a single HTTP server. The `mcp_servers` +
`MCPRegistry` API above is preferred — it adds stdio support, declarative auth
with a pluggable secret store, built-in servers, and connection probing.

## Learn more

- [pydantic-ai MCP client docs](https://ai.pydantic.dev/mcp/client/)
- [Model Context Protocol](https://modelcontextprotocol.io/)
