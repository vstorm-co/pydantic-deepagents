# Web Tools

Web tools give agents the ability to search the web, fetch pages, and make HTTP requests. All three tools are optional and require the `web-tools` extra.

## Installation

```bash
pip install 'pydantic-deep[web-tools]'
```

For web search, you also need a [Tavily](https://tavily.com/) API key:

```bash
export TAVILY_API_KEY=tvly-...
```

## Quick Start

```python
from pydantic_deep import create_deep_agent

agent = create_deep_agent(include_web=True)
```

The agent gets three web tools:

| Tool | Description |
|------|-------------|
| `web_search` | Search the web via Tavily (requires `TAVILY_API_KEY`) |
| `fetch_url` | Fetch a URL and convert HTML to markdown |
| `http_request` | Make raw HTTP requests to APIs |

Each tool has a clear "When to use / When NOT to use" section in its description, so the agent knows which tool to pick:

- **Need information?** &rarr; `web_search`
- **Have a URL?** &rarr; `fetch_url`
- **Calling an API?** &rarr; `http_request`

## Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `include_web` | `bool` | `False` | Enable web tools |
| `web_search_provider` | `SearchProvider` | `TavilySearchProvider` | Custom search provider |

## Search Providers

The default search provider uses [Tavily](https://tavily.com/), but you can swap it for any service by implementing the [`SearchProvider`][pydantic_deep.toolsets.web.SearchProvider] protocol.

### Default: Tavily

```python
agent = create_deep_agent(include_web=True)
# Uses TavilySearchProvider with TAVILY_API_KEY env var
```

If `TAVILY_API_KEY` is not set, `web_search` returns a helpful error message instead of crashing.

### Custom Search Provider

Implement the [`SearchProvider`][pydantic_deep.toolsets.web.SearchProvider] protocol:

```python
from pydantic_deep.toolsets.web import SearchProvider, SearchResult


class BraveSearchProvider:
    """Example: Use Brave Search API instead of Tavily."""

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def search(
        self,
        query: str,
        max_results: int = 5,
        topic: str = "general",
    ) -> list[SearchResult]:
        import requests

        response = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": self.api_key},
            params={"q": query, "count": max_results},
        )
        data = response.json()
        return [
            SearchResult(
                title=r["title"],
                url=r["url"],
                content=r.get("description", ""),
                score=1.0,
            )
            for r in data.get("web", {}).get("results", [])
        ]


agent = create_deep_agent(
    include_web=True,
    web_search_provider=BraveSearchProvider(api_key="..."),
)
```

## Standalone Usage

You can use the web toolset without `create_deep_agent`:

```python
from pydantic_ai import Agent
from pydantic_deep.toolsets.web import create_web_toolset

web_toolset = create_web_toolset(
    require_approval=False,  # No approval prompts
    include_http=False,      # Only search and fetch
)

agent = Agent("openai:gpt-4.1", toolsets=[web_toolset])
```

### Factory Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `id` | `str` | `"deep-web"` | Toolset identifier |
| `search_provider` | `SearchProvider` | `TavilySearchProvider` | Search provider instance |
| `include_search` | `bool` | `True` | Include `web_search` tool |
| `include_fetch` | `bool` | `True` | Include `fetch_url` tool |
| `include_http` | `bool` | `True` | Include `http_request` tool |
| `require_approval` | `bool` | `True` | Require user approval for web requests |
| `user_agent` | `str` | `"Mozilla/5.0 (...)"` | User-Agent header for HTTP requests |
| `descriptions` | `dict[str, str] \| None` | `None` | Custom tool descriptions (keys: `web_search`, `fetch_url`, `http_request`) |

### Custom Tool Descriptions

Override the default tool descriptions with the `descriptions` parameter:

```python
from pydantic_deep.toolsets.web import create_web_toolset

web_toolset = create_web_toolset(
    descriptions={
        "web_search": "Search the internet for up-to-date information",
        "fetch_url": "Download and read the contents of a web page",
    },
)
```

Only the keys you provide are overridden; any missing keys fall back to the built-in descriptions. Supported keys: `web_search`, `fetch_url`, `http_request`.

## Error Handling

All web tools return error messages as strings instead of raising exceptions. This lets the agent handle errors gracefully:

- **Missing package**: `"Error: Required package not installed. Install with: pip install 'pydantic-deep[web-tools]'"`
- **Missing API key**: `"Error: TAVILY_API_KEY environment variable is not set."`
- **Timeout**: `"Error: Request timed out after 30s for https://..."`
- **HTTP error**: `"Error fetching https://...: 404 Not Found"`

## Components

| Component | Description |
|-----------|-------------|
| [`create_web_toolset`][pydantic_deep.toolsets.web.create_web_toolset] | Factory function for web tools |
| [`SearchProvider`][pydantic_deep.toolsets.web.SearchProvider] | Protocol for pluggable search providers |
| [`TavilySearchProvider`][pydantic_deep.toolsets.web.TavilySearchProvider] | Default Tavily-based search |
| [`SearchResult`][pydantic_deep.toolsets.web.SearchResult] | TypedDict for search results |

## Next Steps

- [Toolsets](../concepts/toolsets.md) &mdash; Overview of all available toolsets
- [Human-in-the-Loop](human-in-the-loop.md) &mdash; Approval gates for tool calls
- [Cost Tracking](cost-tracking.md) &mdash; Monitor token usage from web tool responses
