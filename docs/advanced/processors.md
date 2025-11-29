# History Processors

pydantic-deep supports history processors for managing conversation context. The most common use case is automatic summarization to handle long conversations without exceeding token limits.

## Summarization Processor

The `SummarizationProcessor` monitors conversation length and automatically summarizes older messages when thresholds are reached.

### Basic Usage

```python
from pydantic_deep import create_deep_agent
from pydantic_deep.processors import create_summarization_processor

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
def count_tokens(messages):
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

## Using the Processor Class Directly

For more control, use `SummarizationProcessor` directly:

```python
from pydantic_deep.processors import SummarizationProcessor

processor = SummarizationProcessor(
    model="openai:gpt-4.1",
    trigger=("tokens", 100000),
    keep=("messages", 20),
    max_input_tokens=None,
    trim_tokens_to_summarize=4000,  # Limit summary input size
)
```

## How It Works

1. **Before each model call**, the processor checks if any trigger condition is met
2. If triggered, it finds a safe cutoff point that doesn't split tool call/response pairs
3. Older messages are summarized using a lightweight LLM call
4. The summary replaces the old messages, preserving recent context
5. The agent continues with the compressed history

### Tool Call Safety

The processor ensures tool calls and their responses stay together:

```
Messages: [User, AI+ToolCall, ToolResponse, User, AI+ToolCall, ToolResponse, User]
                                           ↑ Safe cutoff point (between complete pairs)
```

## Multiple Processors

You can chain multiple history processors:

```python
from pydantic_deep import create_deep_agent
from pydantic_deep.processors import create_summarization_processor

# Multiple processors are applied in order
agent = create_deep_agent(
    history_processors=[
        create_summarization_processor(trigger=("tokens", 100000)),
        # Add more processors as needed
    ],
)
```

## Best Practices

1. **Choose appropriate thresholds**: Set trigger thresholds below your model's context limit to leave room for the response

2. **Keep enough context**: Retain sufficient recent messages for the agent to understand the current task

3. **Monitor summarization quality**: Check that summaries preserve important context for your use case

4. **Use fraction-based triggers for portability**: When switching between models with different context limits

## Next Steps

- [Structured Output](structured-output.md) - Type-safe responses with Pydantic models
- [Streaming](streaming.md) - Real-time response handling
- [Human-in-the-Loop](human-in-the-loop.md) - Approval workflows
