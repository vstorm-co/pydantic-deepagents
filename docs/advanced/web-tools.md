# Web Tools

Web tools give agents the ability to search the web and fetch pages. pydantic-deep uses pydantic-ai's built-in `WebSearch` and `WebFetch` capabilities, which leverage model-native web tools when available and fall back to local implementations otherwise.

## Quick Start

```python
from pydantic_deep import create_deep_agent

agent = create_deep_agent()  # web_search=True, web_fetch=True by default
```

Both are enabled by default and independently controllable:

```python
agent = create_deep_agent(web_search=True, web_fetch=False)   # Search only
agent = create_deep_agent(web_search=False, web_fetch=True)   # Fetch only
agent = create_deep_agent(web_search=False, web_fetch=False)  # Offline mode
```

For custom configuration (domain restrictions, custom implementations), disable the default and pass your own via `capabilities`:

```python
from pydantic_ai.capabilities import WebSearch

agent = create_deep_agent(
    web_search=False,  # Disable default
    capabilities=[WebSearch(allowed_domains=["docs.python.org"])],
)
```

This adds `WebSearch()` and `WebFetch()` capabilities to the agent. The capabilities automatically use the model's built-in web tools when supported (e.g. OpenAI's `web_search_preview`, Anthropic's web tools), falling back to local tool implementations when they are not.

## Capabilities

| Capability | Description |
|------------|-------------|
| `WebSearch` | Search the web. Uses model-native search when available, falls back to DuckDuckGo. |
| `WebFetch` | Fetch a URL and return its content. Uses model-native fetch when available. |

## Standalone Usage

You can use `WebSearch` and `WebFetch` directly with any pydantic-ai agent without `create_deep_agent`:

```python
from pydantic_ai import Agent
from pydantic_ai.capabilities import WebSearch, WebFetch

agent = Agent(
    "anthropic:claude-sonnet-4-6",
    capabilities=[WebSearch(), WebFetch()],
)
```

## WebSearch Configuration

`WebSearch` supports several configuration options:

```python
from pydantic_ai.capabilities import WebSearch

search = WebSearch(
    search_context_size="medium",  # "low", "medium", or "high"
    blocked_domains=["example.com"],
    allowed_domains=["docs.python.org"],
    max_uses=10,  # Max searches per run
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `builtin` | `bool \| WebSearchTool \| Callable` | `True` | Control built-in tool usage. `True` = auto-detect, `False` = local only. |
| `local` | `Tool \| Callable \| False \| None` | `None` | Custom local fallback tool. `None` = DuckDuckGo. `False` = no fallback. |
| `search_context_size` | `"low" \| "medium" \| "high" \| None` | `None` | How much context to retrieve. Builtin-only. |
| `user_location` | `WebSearchUserLocation \| None` | `None` | Localize results. Builtin-only. |
| `blocked_domains` | `list[str] \| None` | `None` | Exclude results from these domains. Requires builtin support. |
| `allowed_domains` | `list[str] \| None` | `None` | Only include results from these domains. Requires builtin support. |
| `max_uses` | `int \| None` | `None` | Max searches per run. Requires builtin support. |

## WebFetch Configuration

`WebFetch` fetches a URL and returns its content:

```python
from pydantic_ai.capabilities import WebFetch

fetch = WebFetch(
    allowed_domains=["docs.python.org", "github.com"],
    max_uses=20,
    max_content_tokens=5000,
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `builtin` | `bool \| WebFetchTool \| Callable` | `True` | Control built-in tool usage. `True` = auto-detect, `False` = local only. |
| `local` | `Tool \| Callable \| False \| None` | `None` | Custom local fallback tool. `None` = no default fallback. `False` = no fallback. |
| `allowed_domains` | `list[str] \| None` | `None` | Only fetch from these domains. Requires builtin support. |
| `blocked_domains` | `list[str] \| None` | `None` | Never fetch from these domains. Requires builtin support. |
| `max_uses` | `int \| None` | `None` | Max fetches per run. Requires builtin support. |
| `enable_citations` | `bool \| None` | `None` | Enable citations for fetched content. Builtin-only. |
| `max_content_tokens` | `int \| None` | `None` | Max content length in tokens. Builtin-only. |

## Builtin vs. Local Tools

Both `WebSearch` and `WebFetch` follow a **builtin-or-local** pattern:

1. If the model supports the capability natively (e.g. OpenAI models support `web_search_preview`), the builtin tool is used. This is typically faster and more integrated with the model.
2. If the model does not support the capability natively, a local tool function is registered instead. For `WebSearch`, the default local fallback uses DuckDuckGo (requires `duckduckgo-search` package). `WebFetch` has no default local fallback.

You can force local-only mode by setting `builtin=False`:

```python
from pydantic_ai.capabilities import WebSearch

# Always use local DuckDuckGo search, even if model supports builtin
search = WebSearch(builtin=False)
```

Or provide a custom local tool:

```python
from pydantic_ai.capabilities import WebSearch


async def my_search(query: str) -> str:
    # Your custom search implementation
    ...


search = WebSearch(local=my_search)
```

## Full Example

```python
from pydantic_ai import Agent
from pydantic_ai.capabilities import WebSearch, WebFetch

agent = Agent(
    "anthropic:claude-sonnet-4-6",
    capabilities=[
        WebSearch(
            search_context_size="high",
            max_uses=5,
        ),
        WebFetch(
            allowed_domains=["docs.python.org"],
            max_content_tokens=10000,
        ),
    ],
)

result = await agent.run("What's new in Python 3.13?")
print(result.output)
```

## Next Steps

- [Capabilities](middleware.md) -- Overview of the Capabilities API
- [Toolsets](../concepts/toolsets.md) -- Overview of all available toolsets
- [Cost Tracking](cost-tracking.md) -- Monitor token usage from web tool responses
