# Browser

Give your agent a real headless browser. It can navigate, read rendered pages, click, fill forms, scroll, run JavaScript, and take screenshots — everything `WebFetch` can't do because the page needs a real browser to come alive.

`WebFetch` reads static HTML. The browser drives an actual Chromium instance through [Playwright](https://playwright.dev/python/), so the agent can reach pages behind logins, JavaScript-heavy single-page apps, and interactive multi-step flows.

## Install it

The browser ships as an optional extra. Install it, then download the Chromium binary:

```bash
pip install 'pydantic-deep[browser]'
playwright install chromium
```

!!! tip "Auto-install"
    Forget the second step? No problem. On the first browser call, the agent runs
    `playwright install chromium` for you (using your current interpreter, so
    virtualenvs are respected) and retries. Set `auto_install=False` to turn that off.

## Turn it on

The browser is a [capability](capabilities.md). Add one to your agent and the tools appear:

```python hl_lines="2 5"
from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend
from pydantic_deep.features.browser import BrowserCapability

agent = create_deep_agent(
    capabilities=[BrowserCapability()],
)

deps = DeepAgentDeps(backend=StateBackend())
```

## Run it

```python
result = await agent.run(
    "Go to https://example.com and tell me the page heading.",
    deps=deps,
)
print(result.output)
```

The agent calls `navigate`, reads the rendered page back as Markdown, and answers — all without a browser window popping up, because the browser runs **headless by default**.

!!! example "Check it"
    Pass `BrowserCapability(headless=False)` and run it again. This time Chromium
    opens a real window and you can watch the agent drive it.

## What just happened

`BrowserCapability` does two things:

- It registers the **browser toolset** — the nine tools below — on your agent.
- It manages the **browser lifecycle**. Chromium launches lazily on the *first* browser tool call and closes in a `finally` block when the run ends — on success, on error, or on cancellation. A run that never touches a browser tool pays zero Playwright overhead. No subprocess, no window.

A single tab is used throughout. If a link opens a popup or new tab, it's redirected back into the current tab.

## The tools

The agent gets nine tools. Page content comes back as Markdown, truncated to roughly `max_content_tokens` so a giant page can't blow your context.

| Tool | What it does |
|------|--------------|
| `navigate` | Go to a URL; returns title, URL, and page content as Markdown |
| `click` | Click a CSS selector (`button#submit`) or pixel coordinates (`'450,300'`) |
| `type_text` | Fill an input field (replaces its value) |
| `get_text` | Get full-page Markdown, or the text of one element by selector |
| `screenshot` | Capture the page as a base64 PNG (`full_page=True` for the whole scroll) |
| `scroll` | Scroll `up`, `down`, `left`, or `right` |
| `go_back` / `go_forward` | Move through browser history |
| `execute_js` | Run a JavaScript expression and get the result back |

!!! note "The agent already knows when to reach for it"
    `BrowserCapability` injects instructions telling the model to prefer the
    lightweight `web_search` / `web_fetch` tools for static lookups, and to use the
    browser only when a page needs login, JavaScript rendering, or interaction.

## Configure it

Every option is a constructor argument:

```python
BrowserCapability(
    headless=True,                 # no visible window (default)
    allowed_domains=None,          # None = every domain allowed
    screenshot_on_navigate=False,  # attach a screenshot to each navigate
    max_content_tokens=4000,       # truncate page content to ~this many tokens
    timeout_ms=30_000,             # navigation/interaction timeout
    auto_install=True,             # auto-run `playwright install chromium`
)
```

### Lock it down with a domain allowlist

Hand an agent a browser and it can go anywhere — unless you say otherwise. `allowed_domains` confines it:

```python hl_lines="2"
BrowserCapability(
    allowed_domains=["docs.python.org", "github.com"],
)
```

Subdomains come along for free — `github.com` also permits `api.github.com` and `gist.github.com`.

!!! info "Enforced at the network layer"
    The allowlist isn't just checked in the `navigate` tool. It's enforced on every
    top-level navigation request, so the agent can't slip past it by clicking a
    cross-domain link, setting `location.href` from `execute_js`, or following a
    popup. Off-limits pages never reach the model.

## From the CLI

The CLI bundles the browser too. It's **on by default** (and headless by default):

```bash
# Headless run with the browser available
pydantic-deep run "Go to example.com and summarize it"

# Watch it work in a real window
pydantic-deep run "Scrape the pricing table" --browser-headed

# Launch the TUI with a visible browser
pydantic-deep tui --browser-headed

# Turn the browser off entirely
pydantic-deep run "Fix the bug" --no-browser
```

Or set the defaults in your config file:

```toml
include_browser = true
browser_headless = true   # headless (default); set false to show the window
```

## Recap

- `BrowserCapability` gives the agent a real Chromium browser via Playwright — beyond what `WebFetch` can read.
- Install with `pip install 'pydantic-deep[browser]'` and `playwright install chromium` (or let `auto_install` handle the second step).
- Add `capabilities=[BrowserCapability()]` and nine tools appear: navigate, click, type, screenshot, get_text, scroll, go_back/forward, execute_js.
- Chromium launches lazily and is **headless by default**; runs that never use it pay nothing.
- `allowed_domains` locks the agent to specific domains, enforced at the network layer.
- The CLI ships it on by default — control it with `--browser` / `--no-browser` and `--browser-headed`.

Where to go next:

- [Web search & MCP](../learn/web-and-mcp.md) — the lightweight read-only web tools.
- [Capabilities & lifecycle](capabilities.md) — how capabilities like this one hook into a run.
- [Hooks](hooks.md) — intercept browser tool calls for logging or access control.
