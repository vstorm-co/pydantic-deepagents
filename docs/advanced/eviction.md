# Eviction Processor

The eviction processor automatically saves large tool outputs to files and replaces them with a preview + file reference. This prevents context pollution from tools that return massive results (e.g., `grep` or `read_file` on large files).

## Quick Start

```python
from pydantic_deep import create_deep_agent

agent = create_deep_agent(
    eviction_token_limit=20000,  # Evict outputs > 20K tokens
)
```

## How It Works

1. Before each model call, the processor scans `ToolReturnPart` messages
2. If a tool output exceeds the token limit (chars / 4), it:
   - Saves the full output to a file in the backend (`/large_tool_results/{id}`)
   - Replaces the message with a preview showing head/tail lines + file path
3. The agent can then use `read_file` with `offset`/`limit` to access the full output

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
| `eviction_token_limit` | `int \| None` | `None` | Token threshold for eviction. `None` disables eviction. |

### Standalone Usage

For custom agent setups, use `EvictionProcessor` directly:

```python
from pydantic_ai import Agent
from pydantic_ai_backends import StateBackend
from pydantic_deep.processors.eviction import EvictionProcessor

processor = EvictionProcessor(
    backend=StateBackend(),
    token_limit=20000,
    eviction_path="/large_tool_results",
    head_lines=5,
    tail_lines=5,
)

agent = Agent("openai:gpt-4.1", history_processors=[processor])
```

### Factory Function

```python
from pydantic_ai_backends import StateBackend
from pydantic_deep import create_eviction_processor

processor = create_eviction_processor(
    backend=StateBackend(),
    token_limit=20000,
    eviction_path="/large_tool_results",
    head_lines=10,
    tail_lines=10,
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
| [`EvictionProcessor`][pydantic_deep.processors.eviction.EvictionProcessor] | History processor that evicts large outputs |
| [`create_eviction_processor`][pydantic_deep.processors.eviction.create_eviction_processor] | Factory function |
| [`create_content_preview`][pydantic_deep.processors.eviction.create_content_preview] | Create head/tail preview |
| `DEFAULT_TOKEN_LIMIT` | Default threshold: 20,000 tokens |
| `DEFAULT_EVICTION_PATH` | Default path: `/large_tool_results` |

## Next Steps

- [History Processors](processors.md) — Summarization and sliding window
- [Cost Tracking](cost-tracking.md) — Token and cost monitoring
- [Agents](../concepts/agents.md) — Full agent configuration
