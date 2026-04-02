# Web Tools Example

This example demonstrates web search and fetch capabilities with independent control.

## Source Code

:material-file-code: `examples/web_tools.py`

## Overview

pydantic-deep provides two web capabilities, each independently controllable:

| Parameter | Capability | Default | What it does |
|-----------|-----------|---------|--------------|
| `web_search` | `WebSearch` | `True` | Search the web for information |
| `web_fetch` | `WebFetch` | `True` | Fetch and parse web pages as markdown |

## Examples

### Both Enabled (Default)

```python
from pydantic_deep import create_deep_agent

agent = create_deep_agent()  # web_search=True, web_fetch=True
```

### Search Only

```python
agent = create_deep_agent(
    web_search=True,
    web_fetch=False,
)
```

### Fetch Only

```python
agent = create_deep_agent(
    web_search=False,
    web_fetch=True,
)
```

### Neither (Offline Mode)

```python
agent = create_deep_agent(
    web_search=False,
    web_fetch=False,
)
```

### Custom Configuration via Capabilities

For advanced control (domain restrictions, custom implementations), disable the defaults and pass your own:

```python
from pydantic_ai.capabilities import WebFetch, WebSearch

agent = create_deep_agent(
    web_search=False,
    web_fetch=False,
    capabilities=[
        WebSearch(allowed_domains=["docs.python.org"]),
        WebFetch(allowed_domains=["docs.python.org", "peps.python.org"]),
    ],
)
```

## CLI Configuration

```bash
# Via /config command
/config set web_search true
/config set web_fetch false

# Or in .pydantic-deep/config.toml
web_search = true
web_fetch = true
```

## Next Steps

- [MCP Servers](mcp.md) -- External tool integration
- [Thinking](thinking.md) -- Reasoning effort levels
- [Subagents](subagents.md) -- Task delegation
