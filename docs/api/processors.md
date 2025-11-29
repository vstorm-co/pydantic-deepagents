# Processors API

History processors for managing conversation context.

## create_summarization_processor

::: pydantic_deep.processors.create_summarization_processor
    options:
      show_source: false

### Signature

```python
def create_summarization_processor(
    model: str = "openai:gpt-4.1",
    trigger: ContextSize | list[ContextSize] | None = ("tokens", 170000),
    keep: ContextSize = ("messages", 20),
    max_input_tokens: int | None = None,
    token_counter: TokenCounter | None = None,
    summary_prompt: str | None = None,
) -> SummarizationProcessor
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model` | `str` | `"openai:gpt-4.1"` | Model for generating summaries |
| `trigger` | `ContextSize \| list[ContextSize] \| None` | `("tokens", 170000)` | When to trigger summarization |
| `keep` | `ContextSize` | `("messages", 20)` | How much context to keep |
| `max_input_tokens` | `int \| None` | `None` | Max tokens (required for fraction triggers) |
| `token_counter` | `TokenCounter \| None` | `None` | Custom token counting function |
| `summary_prompt` | `str \| None` | `None` | Custom summarization prompt |

### Returns

`SummarizationProcessor` - Configured processor instance.

### Example

```python
from pydantic_deep import create_deep_agent
from pydantic_deep.processors import create_summarization_processor

processor = create_summarization_processor(
    trigger=("tokens", 100000),
    keep=("messages", 20),
)

agent = create_deep_agent(history_processors=[processor])
```

---

## SummarizationProcessor

::: pydantic_deep.processors.SummarizationProcessor
    options:
      show_source: false

### Definition

```python
@dataclass
class SummarizationProcessor:
    model: str
    trigger: ContextSize | list[ContextSize] | None = None
    keep: ContextSize = ("messages", 20)
    token_counter: TokenCounter = _count_tokens_approximately
    summary_prompt: str = DEFAULT_SUMMARY_PROMPT
    max_input_tokens: int | None = None
    trim_tokens_to_summarize: int | None = 4000
```

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `model` | `str` | Model to use for generating summaries |
| `trigger` | `ContextSize \| list[ContextSize] \| None` | Threshold(s) that trigger summarization |
| `keep` | `ContextSize` | How much context to keep after summarization |
| `token_counter` | `TokenCounter` | Function to count tokens in messages |
| `summary_prompt` | `str` | Prompt template for generating summaries |
| `max_input_tokens` | `int \| None` | Maximum input tokens (required for fraction triggers) |
| `trim_tokens_to_summarize` | `int \| None` | Maximum tokens to include when generating summary |

### Methods

#### \_\_call\_\_

```python
async def __call__(self, messages: list[ModelMessage]) -> list[ModelMessage]
```

Process messages and summarize if needed. This is called automatically by pydantic-ai's history processor mechanism.

### Example

```python
from pydantic_deep.processors import SummarizationProcessor

processor = SummarizationProcessor(
    model="openai:gpt-4.1",
    trigger=[
        ("messages", 50),
        ("tokens", 100000),
    ],
    keep=("messages", 10),
    trim_tokens_to_summarize=4000,
)
```

---

## Type Aliases

### ContextSize

```python
ContextFraction = tuple[Literal["fraction"], float]
ContextTokens = tuple[Literal["tokens"], int]
ContextMessages = tuple[Literal["messages"], int]

ContextSize = ContextFraction | ContextTokens | ContextMessages
```

Specifies context size thresholds:

- `("messages", N)` - Number of messages
- `("tokens", N)` - Number of tokens
- `("fraction", F)` - Fraction of `max_input_tokens` (0 < F <= 1)

### TokenCounter

```python
TokenCounter = Callable[[Sequence[ModelMessage]], int]
```

Function type for custom token counting.

---

## Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `DEFAULT_SUMMARY_PROMPT` | (see source) | Default prompt template for summarization |

## Next Steps

- [Agent API](agent.md) - Agent factory and configuration
- [Types API](types.md) - Type definitions
