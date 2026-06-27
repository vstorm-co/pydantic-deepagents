# Web search & MCP

A model's training data has a cutoff; the world doesn't. This page gives your agent the live web — and then connects it to whole catalogs of external tools through **MCP**.

Your agent can already search and fetch the web. You turned nothing on for that — it's a default. So let's start by *using* it, then wire up an external server.

```python
import asyncio

from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend


async def main():
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        instructions="You are a research assistant. Cite the pages you used.",
    )

    deps = DeepAgentDeps(backend=StateBackend())

    result = await agent.run(
        "What changed in the latest Python release? "
        "Check the official docs and summarize the top three points.",
        deps=deps,
    )
    print(result.output)


asyncio.run(main())
```

## Run it

Save it to `main.py` and run:

<div class="termy">

```console
$ python main.py
```

</div>

The agent searches the web, opens the pages it finds, reads them, and answers with up-to-date information — none of which was in its training data. You didn't register a search tool or write an HTTP client. It was already there.

!!! example "Check it"
    Ask it something that *must* be recent — "What's today's top story on the Python
    blog?" Then flip `web_search=False` (next section) and ask again. Without the web,
    the model can only guess from its training cutoff. The difference is the point.

## Step by step

### The web is on by default

`create_deep_agent()` enables two web capabilities for you:

```python
agent = create_deep_agent()  # web_search=True, web_fetch=True
```

- **`web_search`** — search the web and get back a list of results.
- **`web_fetch`** — open a specific URL and read its content as text.

They're independent, so you can turn either one off:

```python hl_lines="2 3"
agent = create_deep_agent(
    web_search=True,    # find pages
    web_fetch=False,    # but don't open them
)
```

Set both to `False` for a fully offline agent — handy when you want deterministic
runs or you're working in a sandbox with no network.

!!! note "It uses the model's native web tools when it can"
    Under the hood these are Pydantic AI's built-in `WebSearch` and `WebFetch`
    capabilities. When the model has native web tools (Anthropic's web tools,
    OpenAI's `web_search_preview`), they're used directly. Otherwise pydantic-deep
    falls back to a local implementation. Either way, the same code works across
    providers.

### Tightening the leash

The defaults are the easy path. When you need more control — restrict to certain
domains, cap how many searches a run can make — disable the default and pass your
own capability:

```python
from pydantic_ai.capabilities import WebSearch, WebFetch

agent = create_deep_agent(
    web_search=False,   # turn off the default…
    web_fetch=False,
    capabilities=[      # …and bring your own, configured
        WebSearch(allowed_domains=["docs.python.org"], max_uses=5),
        WebFetch(allowed_domains=["docs.python.org", "peps.python.org"]),
    ],
)
```

Now the agent can only look at the Python docs, and only a handful of times. See
[Web Tools](../learn/web-and-mcp.md) for every option.

## Connecting external tools with MCP

The web is one source of tools. The [Model Context Protocol](https://modelcontextprotocol.io/)
is the universal one. An **MCP server** exposes a bundle of tools — query GitHub,
look up a library's docs, read any public repo — and your agent picks them up as
native tools, sitting right next to the filesystem and the web.

MCP is an optional extra:

```bash
pip install 'pydantic-deep[mcp]'
```

Describe a server, then hand it to `mcp_servers=`:

```python hl_lines="9 12"
import asyncio

from pydantic_deep import create_deep_agent, build_mcp_server, MCPServerConfig


async def main():
    deepwiki = build_mcp_server(
        MCPServerConfig(
            name="deepwiki",
            transport="http",
            url="https://mcp.deepwiki.com/mcp",
        )
    )

    agent = create_deep_agent(mcp_servers=[deepwiki])

    async with agent:  # connects the MCP server for the duration of the block
        result = await agent.run("What does the pydantic/pydantic repo do?")
        print(result.output)


asyncio.run(main())
```

The agent now answers using DeepWiki's tools — which can read any public repo —
without you knowing the tool names. It just uses them.

!!! warning "Open the agent before you run it"
    MCP servers are live connections. Wrap your runs in `async with agent:` so the
    servers connect for the block and disconnect cleanly when it ends. Forget it,
    and the tools won't be there.

### Built-in servers

You don't have to type out a config for the popular ones.
[`builtin_mcp_servers()`][pydantic_deep.mcp.builtin_mcp_servers] ships curated
definitions — `github` (needs a token), `context7` (library docs), `deepwiki`
(ask any public repo), and the Figma servers. They're all disabled until you opt
in, which an [`MCPRegistry`][pydantic_deep.mcp.MCPRegistry] makes easy:

```python
from pydantic_deep import create_deep_agent, MCPRegistry, builtin_mcp_servers

registry = MCPRegistry(builtin_mcp_servers())
registry.set_enabled("deepwiki", True)

agent = create_deep_agent(mcp_servers=registry.build_active())
```

The registry builds only the servers that are both enabled *and* authenticated, so
you can keep a whole shelf of servers defined and switch them on as needed.

!!! tip "Auth without committing secrets"
    Servers that need a token take an [`MCPAuth`][pydantic_deep.mcp.MCPAuth] — e.g.
    `MCPAuth(secret_key="GITHUB_MCP_PAT", kind="bearer")`. The token is never stored
    in the config; it's resolved at build time from your environment (or the CLI's
    keystore). See [MCP Servers](../learn/web-and-mcp.md) for OAuth, stdio subprocesses,
    and importing servers from Claude Code.

## Recap

You gave your agent the world:

- **Web search and fetch are on by default.** `web_search=True`, `web_fetch=True` — flip either to `False` for offline or read-only runs.
- For domain limits and usage caps, disable the default and pass your own `WebSearch` / `WebFetch` via `capabilities=`.
- **MCP servers** add whole catalogs of external tools. Install the `[mcp]` extra, describe a server with `MCPServerConfig`, and attach it via `mcp_servers=`.
- Always run MCP-backed agents inside `async with agent:` so connections open and close cleanly.
- `builtin_mcp_servers()` + `MCPRegistry` give you curated servers (GitHub, Context7, DeepWiki, Figma) you can enable one line at a time.

That's the tutorial. From here, the real depth opens up — the capability lifecycle, hooks, cost budgets, agent teams, and more.

- [On to the Advanced User Guide →](../advanced/index.md)
