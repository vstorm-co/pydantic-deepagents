# Eviction

The eviction capability automatically saves large tool outputs to files and replaces them with a preview + file reference. This prevents context pollution from tools that return massive results (e.g., `grep` or `read_file` on large files).

## Quick Start

Eviction is **enabled by default** with a 20,000 token threshold:

```python
from pydantic_deep import create_deep_agent

agent = create_deep_agent()  # eviction_token_limit=20_000 by default

# Custom threshold
agent = create_deep_agent(eviction_token_limit=50_000)

# Disable
agent = create_deep_agent(eviction_token_limit=None)
```

## How It Works

The [`EvictionCapability`][pydantic_deep.features.eviction.EvictionCapability] uses the `after_tool_execute` hook to intercept large tool results **before** they enter the conversation history. This means the full output never bloats the message list in memory.

1. After each tool call, `after_tool_execute` checks the result size
2. If the result exceeds the token limit (chars / 4), it:
   - Saves the full output to a file in the backend (`/large_tool_results/{id}`)
   - Returns a preview showing head/tail lines + file path instead
3. The agent can then use `read_file` with `offset`/`limit` to access the full output

!!! tip "Why a capability hook?"
    [`EvictionCapability`][pydantic_deep.features.eviction.EvictionCapability] intercepts via `after_tool_execute`, so a large output is written to the backend and replaced with a preview **before** it ever enters the message history — the full content never sits in memory waiting for the next model call. It is the default used by `create_deep_agent`.

### Before Eviction

```
Tool result: [50,000 characters of grep output]
```

### After Eviction

```
Tool result too large, saved to: /large_tool_results/call_abc123

Read the result using read_file with offset and limit parameters.
Example: read_file(path="/large_tool_results/call_abc123", offset=0, limit=100)

Preview (head/tail):

[first 5 lines]

... [990 lines truncated] ...

[last 5 lines]
```

## Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `eviction_token_limit` | `int \| None` | `20_000` | Token threshold for eviction. `None` disables eviction. |

### Standalone Usage

To attach eviction to a plain `Agent` (outside `create_deep_agent`), add the
capability directly:

```python
from pydantic_ai import Agent
from pydantic_ai_backends import StateBackend, ensure_async
from pydantic_deep.features.eviction import EvictionCapability

agent = Agent(
    "anthropic:claude-sonnet-4-6",
    capabilities=[
        EvictionCapability(
            backend=ensure_async(StateBackend()),
            token_limit=20_000,
        )
    ],
)
```

!!! info "Multi-User Applications"
    Evicted files are written to the backend. In multi-user apps, use separate
    backends per user to avoid mixing evicted outputs. See [Multi-User Guide](multi-user.md).

## Runtime Backend Resolution

When used via `create_deep_agent()`, the processor resolves the backend from `ctx.deps.backend` at runtime. This ensures evicted files are written to the same backend that `read_file`, `grep`, and other console tools use. It falls back to the backend passed at initialization for standalone usage.

## Components

| Component | Description |
|-----------|-------------|
| [`EvictionCapability`][pydantic_deep.features.eviction.EvictionCapability] | Capability that intercepts large outputs via `after_tool_execute` (default) |
| [`create_content_preview`][pydantic_deep.features.eviction.create_content_preview] | Create head/tail preview |
| `DEFAULT_TOKEN_LIMIT` | Default threshold: 20,000 tokens |
| `DEFAULT_EVICTION_PATH` | Default path: `/large_tool_results` |

## Next Steps

- [History Processors](processors.md) — Summarization and sliding window
- [Cost Tracking](cost-tracking.md) — Token and cost monitoring
- [Agents](../concepts/agents.md) — Full agent configuration
