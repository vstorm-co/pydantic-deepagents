# Periodic Task Reminders

Long tool-heavy runs tend to drift — the agent starts solving a sub-problem and
forgets the original goal. `PeriodicReminderCapability` injects a
"what are you supposed to be doing" nudge into the conversation every *N*
model-request turns to keep the agent anchored.

## Quick start

```python
from pydantic_deep import create_deep_agent

agent = create_deep_agent(periodic_reminder=True)
```

`True` fires the **first** reminder at turn **5**, then every **10 turns**
after that, using the zero-cost default generator (`None`), which extracts the
first user message verbatim and wraps it in a `<system-reminder>` tag.

## Custom cadence

```python
from pydantic_deep import create_deep_agent
from pydantic_deep.capabilities.periodic_reminder import PeriodicReminderConfig

agent = create_deep_agent(
    periodic_reminder=PeriodicReminderConfig(
        every_n_turns=5,           # remind every 5 turns
        first_after=3,             # first reminder at turn 3
        max_reminders_per_run=10,  # stop after 10 reminders
    )
)
```

## Generator modes

### `None` — first message (default, zero-cost)

When `generator=None`, the capability extracts the first user message and
formats it as a goal-check nudge:

```python
from pydantic_deep.capabilities.periodic_reminder import PeriodicReminderConfig

cfg = PeriodicReminderConfig(generator=None)  # default
```

The injected text looks like:

```
The original request was:
  "<first user message, up to 400 chars>"
Check that your next action advances this goal. If the goal is
already satisfied, produce the final answer instead of calling more tools.
```

### Static string (zero-cost)

Pass a fixed string when the goal is always the same:

```python
from pydantic_deep.capabilities.periodic_reminder import PeriodicReminderConfig

cfg = PeriodicReminderConfig(
    every_n_turns=8,
    generator="Remember: your task is to fix the failing tests, nothing else.",
)
```

### Async callable (zero-cost)

Supply any `async def(ctx, turn, messages) -> str` for dynamic content:

```python
from pydantic_deep.capabilities.periodic_reminder import PeriodicReminderConfig

async def my_reminder(ctx, turn, messages):
    return f"Turn {turn}: stay focused on the original objective."

cfg = PeriodicReminderConfig(generator=my_reminder)
```

### Compact transcript (zero-cost)

Use `_build_compact_transcript` to inject a summarized view of the conversation
without making any LLM calls:

```python
from pydantic_deep.capabilities.periodic_reminder import (
    PeriodicReminderConfig,
    _build_compact_transcript,
)

async def _context_gen(_ctx, _turn, messages):
    return _build_compact_transcript(messages, max_recent=10)

cfg = PeriodicReminderConfig(generator=_context_gen)
```

The transcript includes the original user goal and the last `max_recent` turns,
keeping each message brief (150 chars per user message, 400 chars for the goal).

### `LLMReminderGenerator` (Haiku call)

`LLMReminderGenerator` asks a small model to summarize progress and produce a
two-sentence nudge. It uses a compacted transcript to keep token cost low:

```python
from pydantic_deep.capabilities.periodic_reminder import (
    LLMReminderGenerator,
    PeriodicReminderConfig,
)

cfg = PeriodicReminderConfig(
    every_n_turns=15,
    generator=LLMReminderGenerator(
        model="anthropic:claude-haiku-4-5-20251001",
        max_context_messages=10,
    ),
)
```

If the LLM call fails for any reason, it falls back to the zero-cost first-message
default automatically.

## Generator comparison

| Generator | Token cost | Customisation | When to use |
|---|---|---|---|
| `None` (default) | Zero | None | Most runs — keeps the original user message visible |
| Static `str` | Zero | Fixed text | Task is always the same; you know the goal upfront |
| Async callable | Zero | Full | Goal depends on runtime state or per-session config |
| Compact transcript (`_build_compact_transcript`) | Zero | Full | Long runs where context drift is visible but LLM cost is unwanted |
| `LLMReminderGenerator` | Low (Haiku) | Automatic | Very long runs where the goal is complex or evolving |

## Render styles

The reminder text is wrapped before being injected as a `ModelRequest`:

| Style | Output |
|---|---|
| `system_reminder_tag` (default) | `<system-reminder>\n…\n</system-reminder>` |
| `user_prompt` | plain text |
| `developer_note` | `[Developer note for the assistant: …]` |

```python
cfg = PeriodicReminderConfig(render_style="developer_note")
```

## Using as a standalone capability

```python
from pydantic_ai import Agent
from pydantic_deep.capabilities.periodic_reminder import (
    PeriodicReminderCapability,
    PeriodicReminderConfig,
)

agent = Agent(
    "anthropic:claude-sonnet-4-6",
    capabilities=[
        PeriodicReminderCapability(
            config=PeriodicReminderConfig(every_n_turns=10)
        )
    ],
)
```

## CLI defaults

When using the CLI (`pydantic-deep`), periodic reminders are **enabled by
default** in `"llm"` mode (LLMReminderGenerator with Haiku). Use the `/remind`
command to switch modes at runtime:

| Mode | Generator | `first_after` | `every_n_turns` | Cost |
|---|---|---|---|---|
| `off` | disabled | — | — | — |
| `first` | `None` — first user message | 5 | 10 | zero |
| `context` | compact transcript | 5 | 10 | zero |
| `llm` | `LLMReminderGenerator` | 5 | 15 | low |

Config file override (`~/.pydantic-deep/config.toml`):

```toml
periodic_reminder = true
reminder_mode = "llm"   # "first" | "context" | "llm"
```

## Custom `ReminderGenerator` protocol

Any class or function satisfying this protocol works as a generator:

```python
from typing import Any
from pydantic_ai import RunContext
from pydantic_ai.messages import ModelMessage

class MyGenerator:
    async def __call__(
        self,
        ctx: RunContext[Any],
        turn: int,
        messages: list[ModelMessage],
    ) -> str:
        return f"Turn {turn}: keep going, original goal still pending."
```
