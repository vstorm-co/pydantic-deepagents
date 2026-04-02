# History Processors & Context Management

pydantic-deep uses a layered system for managing conversation context. Understanding how the layers work together is key to configuring long-running agents.

## How the Layers Work Together

```
Message history
    │
    ▼
┌─────────────────────────────┐
│  EvictionProcessor          │  Saves large tool outputs to files (default: on, 20K tokens)
│  (history_processors)       │
├─────────────────────────────┤
│  PatchToolCallsProcessor    │  Fixes orphaned tool calls (default: on)
│  (history_processors)       │
├─────────────────────────────┤
│  User history_processors    │  Custom: SlidingWindow, Summarization, etc.
│  (history_processors=[...]) │
├─────────────────────────────┤
│  ContextManagerCapability   │  Token tracking + auto-compression at 90% (default: on)
│  (context_manager=True)     │
└─────────────────────────────┘
    │
    ▼
  Model request
```

| Layer | Parameter | Default | Purpose |
|-------|-----------|---------|---------|
| **ContextManagerCapability** | `context_manager=True` | On | Token tracking + LLM-based auto-compression when reaching 90% of token budget |
| **EvictionProcessor** | `eviction_token_limit=20_000` | On (20K) | Saves oversized tool outputs to files, replaces with preview |
| **PatchToolCallsProcessor** | `patch_tool_calls=True` | On | Fixes orphaned tool calls from interrupted conversations |
| **Custom processors** | `history_processors=[...]` | None | User-provided: SlidingWindow, Summarization, custom |

**You don't need to configure anything for most use cases.** The defaults handle context management, large outputs, and interrupted sessions automatically.

!!! info "Coming to pydantic-ai"
    History processors will be added to pydantic-ai core ([pydantic-ai#3780](https://github.com/pydantic/pydantic-ai/pull/3780)). Once available, we will migrate to use the upstream implementation. The API will remain compatible.

## Context Manager vs History Processors

These are **complementary, not alternatives**:

- **`context_manager`** is a **Capability** (pydantic-ai native). It tracks token usage across the conversation, reports it via `on_context_update` callback, and triggers LLM-based summarization when approaching the token budget. It's the **smart, high-level** layer.

- **`history_processors`** are **low-level transformations** applied to the message list before each model request. They don't track tokens or make decisions — they just transform. The built-in ones (eviction, patching) run automatically; you add custom ones for special needs.

Both run simultaneously. The context manager handles the "are we running out of space?" question; processors handle "clean up the data before sending."

## Summarization Processor

The `SummarizationProcessor` monitors conversation length and automatically summarizes older messages when thresholds are reached. This provides intelligent compression that preserves important context.

### Basic Usage

```python
from pydantic_deep import create_deep_agent, create_summarization_processor

# Create a summarization processor
processor = create_summarization_processor(
    trigger=("tokens", 100000),  # Summarize when reaching 100k tokens
    keep=("messages", 20),       # Keep last 20 messages after summarization
)

# Create agent with the processor
agent = create_deep_agent(
    history_processors=[processor],
)
```

### Trigger Conditions

You can trigger summarization based on different criteria:

```python
from pydantic_deep import create_summarization_processor

# Trigger when message count exceeds threshold
processor = create_summarization_processor(
    trigger=("messages", 50),
)

# Trigger when token count exceeds threshold
processor = create_summarization_processor(
    trigger=("tokens", 100000),
)

# Trigger at fraction of max input tokens
processor = create_summarization_processor(
    trigger=("fraction", 0.8),  # 80% of max tokens
    max_input_tokens=200000,    # Required for fraction triggers
)

# Multiple trigger conditions (any condition triggers)
processor = create_summarization_processor(
    trigger=[
        ("messages", 100),
        ("tokens", 150000),
    ],
)
```

### Retention Configuration

Control how much context to keep after summarization:

```python
from pydantic_deep import create_summarization_processor

# Keep last N messages
processor = create_summarization_processor(
    trigger=("tokens", 100000),
    keep=("messages", 20),
)

# Keep last N tokens worth of messages
processor = create_summarization_processor(
    trigger=("tokens", 100000),
    keep=("tokens", 10000),
)

# Keep fraction of max tokens
processor = create_summarization_processor(
    trigger=("fraction", 0.8),
    keep=("fraction", 0.1),
    max_input_tokens=200000,
)
```

### Custom Token Counter

By default, the processor uses a simple character-based estimation (~4 characters per token). For more accurate counting, provide a custom token counter:

```python
from pydantic_ai.messages import ModelMessage
from pydantic_deep import create_summarization_processor

def count_tokens(messages: list[ModelMessage]) -> int:
    """Custom token counter using tiktoken or similar."""
    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")

    total = 0
    for msg in messages:
        # Extract text from message and count tokens
        # Implementation depends on your needs
        pass
    return total

processor = create_summarization_processor(
    trigger=("tokens", 100000),
    token_counter=count_tokens,
)
```

### Custom Summary Prompt

Customize how the summarization is performed:

```python
from pydantic_deep import create_summarization_processor

custom_prompt = """
Extract the key information from this conversation.
Focus on:
- User requirements and goals
- Important decisions made
- Current state of the task

Messages:
{messages}

Provide a concise summary.
"""

processor = create_summarization_processor(
    trigger=("tokens", 100000),
    summary_prompt=custom_prompt,
)
```

## Sliding Window Processor

The `SlidingWindowProcessor` provides a zero-cost alternative that simply discards old messages without LLM calls. This is useful when you don't need to preserve historical context.

### Basic Usage

```python
from pydantic_deep import create_deep_agent, create_sliding_window_processor

# Create a sliding window processor
processor = create_sliding_window_processor(
    trigger=("messages", 100),  # Trim when reaching 100 messages
    keep=("messages", 50),      # Keep last 50 messages
)

# Create agent with the processor
agent = create_deep_agent(
    history_processors=[processor],
)
```

### When to Use Sliding Window

Choose `SlidingWindowProcessor` when:

- **Cost matters**: No LLM calls for processing
- **Speed matters**: Instant trimming without API latency
- **Recent context is sufficient**: Tasks don't need historical information
- **Conversations are long**: High-volume chat applications

Choose `SummarizationProcessor` when:

- **Context preservation matters**: Need to remember earlier decisions
- **Tasks span multiple topics**: Important details scattered throughout
- **Quality over speed**: Willing to trade latency for better context

### Configuration Examples

```python
from pydantic_deep import create_sliding_window_processor

# Message-based window
processor = create_sliding_window_processor(
    trigger=("messages", 100),
    keep=("messages", 50),
)

# Token-based window
processor = create_sliding_window_processor(
    trigger=("tokens", 100000),
    keep=("tokens", 50000),
)

# Fraction-based window
processor = create_sliding_window_processor(
    trigger=("fraction", 0.8),
    keep=("fraction", 0.4),
    max_input_tokens=200000,
)
```

## Using Processor Classes Directly

For more control, use the processor classes directly:

```python
from pydantic_deep import SummarizationProcessor, SlidingWindowProcessor

# Summarization processor
summarizer = SummarizationProcessor(
    model="anthropic:claude-sonnet-4-6",
    trigger=("tokens", 100000),
    keep=("messages", 20),
    max_input_tokens=None,
    trim_tokens_to_summarize=4000,  # Limit summary input size
)

# Sliding window processor
window = SlidingWindowProcessor(
    trigger=("tokens", 100000),
    keep=("messages", 50),
)
```

## How It Works

### Summarization Processor

1. **Before each model call**, the processor checks if any trigger condition is met
2. If triggered, it finds a safe cutoff point that doesn't split tool call/response pairs
3. Older messages are summarized using a lightweight LLM call
4. The summary replaces the old messages, preserving recent context
5. The agent continues with the compressed history

### Sliding Window Processor

1. **Before each model call**, the processor checks if any trigger condition is met
2. If triggered, it finds a safe cutoff point that doesn't split tool call/response pairs
3. Older messages are discarded (no LLM call)
4. The agent continues with only recent messages

### Tool Call Safety

Both processors ensure tool calls and their responses stay together:

```
Messages: [User, AI+ToolCall, ToolResponse, User, AI+ToolCall, ToolResponse, User]
                                           ↑ Safe cutoff point (between complete pairs)
```

## Multiple Processors

You can chain multiple history processors:

```python
from pydantic_deep import (
    create_deep_agent,
    create_summarization_processor,
    create_sliding_window_processor,
)

# Multiple processors are applied in order
agent = create_deep_agent(
    history_processors=[
        create_summarization_processor(trigger=("tokens", 100000)),
        create_sliding_window_processor(trigger=("messages", 200)),
    ],
)
```

## Context Manager Middleware

The `ContextManagerMiddleware` from [summarization-pydantic-ai](https://github.com/vstorm-co/summarization-pydantic-ai) is a **dual-protocol** component that acts as both a history processor and an `AgentMiddleware`. It provides token tracking and automatic compression.

!!! tip "Enabled by default"
    Context manager is **enabled by default** in `create_deep_agent()` via `context_manager=True`.

### Basic Usage

```python
from pydantic_deep import create_deep_agent

# Default: enabled with 200K token budget
agent = create_deep_agent()

# Custom configuration
agent = create_deep_agent(
    context_manager=True,
    context_manager_max_tokens=128_000,
    on_context_update=lambda pct, cur, mx: print(f"Context: {pct:.0%}"),
)

# Disable
agent = create_deep_agent(context_manager=False)
```

### How It Works

1. **Before each model call**, the middleware counts tokens in the message history
2. **Calls `on_context_update`** with `(percentage, current_tokens, max_tokens)`
3. **If usage exceeds `compress_threshold`** (default 0.9 = 90%), triggers LLM-based summarization
4. **As middleware**, can also truncate overly large tool outputs

### Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `context_manager` | `bool` | `True` | Enable/disable |
| `context_manager_max_tokens` | `int` | `200,000` | Token budget |
| `on_context_update` | `Callable` | `None` | Callback: `(float, int, int) -> Any` |

### Standalone Usage

```python
from pydantic_ai_summarization import create_context_manager_middleware

middleware = create_context_manager_middleware(
    max_tokens=200_000,
    compress_threshold=0.9,
    keep=("messages", 20),
    on_usage_update=lambda pct, cur, mx: print(f"{pct:.0%}"),
)
```

## Eviction Processor

The `EvictionProcessor` saves large tool outputs to files, replacing them with a preview and file reference. **Enabled by default** with a 20,000 token threshold. See [Eviction](eviction.md) for full details.

```python
# Default: enabled at 20K tokens
agent = create_deep_agent()

# Custom threshold
agent = create_deep_agent(eviction_token_limit=50_000)

# Disable
agent = create_deep_agent(eviction_token_limit=None)
```

## Patch Tool Calls Processor

The `patch_tool_calls_processor` fixes orphaned tool calls in message history. **Enabled by default.** Essential for resuming interrupted conversations where tool calls were sent but responses never received.

```python
# Default: enabled
agent = create_deep_agent()

# Disable
agent = create_deep_agent(patch_tool_calls=False)
```

## Best Practices

1. **Choose appropriate thresholds**: Set trigger thresholds below your model's context limit to leave room for the response

2. **Keep enough context**: Retain sufficient recent messages for the agent to understand the current task

3. **Monitor summarization quality**: Check that summaries preserve important context for your use case

4. **Use fraction-based triggers for portability**: When switching between models with different context limits

5. **Consider hybrid approaches**: Use summarization for important conversations and sliding window for casual chat

## Next Steps

- [Structured Output](structured-output.md) - Type-safe responses with Pydantic models
- [Streaming](streaming.md) - Real-time response handling
- [Human-in-the-Loop](human-in-the-loop.md) - Approval workflows
