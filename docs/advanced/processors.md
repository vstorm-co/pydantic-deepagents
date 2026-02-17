# History Processors

pydantic-deep supports history processors for managing conversation context. These processors are powered by [summarization-pydantic-ai](https://github.com/vstorm-co/summarization-pydantic-ai) and provide two strategies:

- **SummarizationProcessor** - Intelligent LLM-based summarization
- **SlidingWindowProcessor** - Zero-cost message trimming

!!! info "Coming to pydantic-ai"
    This feature will be added to pydantic-ai core in late January 2025 ([pydantic-ai#3780](https://github.com/pydantic/pydantic-ai/pull/3780)). Once available, we will migrate to use the upstream implementation. The API will remain compatible.

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
    model="openai:gpt-4.1",
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

The `EvictionProcessor` saves large tool outputs to files, replacing them with a preview and file reference. See [Eviction](eviction.md) for full details.

```python
agent = create_deep_agent(eviction_token_limit=20000)
```

## Patch Tool Calls Processor

The `patch_tool_calls_processor` fixes orphaned tool calls in message history — useful when resuming interrupted conversations.

```python
agent = create_deep_agent(patch_tool_calls=True)
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
