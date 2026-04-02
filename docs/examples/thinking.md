# Thinking Example

This example demonstrates the thinking/reasoning capability for different complexity levels.

## Source Code

:material-file-code: `examples/thinking.py`

## Overview

The `thinking` parameter controls how much reasoning effort the model uses before responding. Higher effort produces better results for complex tasks but uses more tokens.

## Effort Levels

| Level | Best For |
|-------|----------|
| `False` | Disable thinking entirely |
| `True` | Provider's default effort |
| `"minimal"` | Trivial tasks |
| `"low"` | Simple tasks |
| `"medium"` | Moderate complexity |
| `"high"` | Complex reasoning (default) |
| `"xhigh"` | Maximum reasoning |

## Examples

### Default (high)

```python
from pydantic_deep import create_deep_agent

# Default: thinking="high"
agent = create_deep_agent()
```

### Quick Tasks

```python
agent = create_deep_agent(thinking="low")
```

### Maximum Reasoning

```python
agent = create_deep_agent(thinking="xhigh")
```

### Disable Thinking

```python
agent = create_deep_agent(thinking=False)
```

### CLI Configuration

```bash
# Via /config command
/config set thinking_effort medium

# Or in .pydantic-deep/config.toml
thinking_effort = "high"
```

## How It Works

The `thinking` parameter creates a pydantic-ai [`Thinking`](https://ai.pydantic.dev/thinking/) capability. This works across providers:

- **Anthropic**: Maps to extended thinking mode
- **OpenAI**: Maps to reasoning effort parameter
- **Other providers**: Silently ignored if unsupported

Subagents have `thinking=False` by default to save tokens — they focus on execution, not deep reasoning.

## Next Steps

- [Web Tools](web-tools.md) -- Web search and fetch
- [MCP Servers](mcp.md) -- External tool integration
- [Subagents](subagents.md) -- Task delegation
