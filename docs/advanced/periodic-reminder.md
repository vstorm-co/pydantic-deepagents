# Periodic reminders

Long, tool-heavy runs drift. The agent starts chasing a sub-problem, then a sub-sub-problem, and ten turns later it has forgotten what you actually asked for. Periodic reminders fix that: every *N* turns, the original goal gets re-injected into the conversation so the agent stays anchored.

You turn it on with one flag.

```python
from pydantic_deep import create_deep_agent

agent = create_deep_agent(periodic_reminder=True)
```

## Run it

Give the agent a long task and let it run. Behind the scenes, a turn counter ticks up on every model request. The first reminder fires at **turn 5**, then every **10 turns** after that.

The injected nudge looks like this:

```
<system-reminder>
The original request was:
  "<your first message, up to 400 chars>"
Check that your next action advances this goal. If the goal is
already satisfied, produce the final answer instead of calling more tools.
</system-reminder>
```

!!! example "Check it"
    Pass `on_reminder=lambda turn, text: print(f"[reminder @ {turn}] {text}")`
    on the config (below) and you'll see exactly when each one fires, live.

## What `True` actually does

`periodic_reminder=True` is the zero-cost default. It re-states your **first user message** verbatim every few turns — no extra model calls, no token cost beyond the reminder text itself. For most runs that is all you need: keeping the original ask visible is usually enough to stop drift.

When you want more control, pass a `PeriodicReminderConfig` instead of `True`.

## Tuning the cadence

The config controls *when* reminders fire and *how many*.

```python
from pydantic_deep import create_deep_agent
from pydantic_deep.features.periodic_reminder import PeriodicReminderConfig

agent = create_deep_agent(
    periodic_reminder=PeriodicReminderConfig(
        every_n_turns=5,           # remind every 5 turns
        first_after=3,             # first reminder at turn 3
        max_reminders_per_run=10,  # stop after 10 reminders
    )
)
```

- `every_n_turns` — the interval after the first reminder. Must be `>= 1` (it's validated at construction, so a `0` fails fast with a clear error).
- `first_after` — the turn the *first* reminder fires. Pass `None` to reuse `every_n_turns`.
- `max_reminders_per_run` — a cap. `None` means unlimited.

## Choosing what the reminder says

The `generator` field decides the reminder *text*. Four shapes, from free to clever.

### First message — the default

`generator=None` (the default) extracts your first user message and wraps it in a goal-check nudge. Zero cost, no model call.

```python
cfg = PeriodicReminderConfig(generator=None)  # this is the default
```

### A static string

When the goal never changes, just hand over a fixed string. Also zero cost.

```python
cfg = PeriodicReminderConfig(
    every_n_turns=8,
    generator="Remember: your task is to fix the failing tests, nothing else.",
)
```

### An async callable

Need the text to depend on runtime state? Pass any `async def(ctx, turn, messages) -> str`.

```python
async def my_reminder(ctx, turn, messages):
    return f"Turn {turn}: stay focused on the original objective."

cfg = PeriodicReminderConfig(generator=my_reminder)
```

### A compact transcript

For long runs where the agent needs to see *recent* context — not just the goal — use `build_compact_transcript`. It stitches together the original goal plus the last few turns, keeping each line short. Still zero cost.

```python
from pydantic_deep.features.periodic_reminder import (
    PeriodicReminderConfig,
    build_compact_transcript,
)

async def context_gen(ctx, turn, messages):
    return build_compact_transcript(messages, max_recent=10)

cfg = PeriodicReminderConfig(generator=context_gen)
```

The goal is truncated to 400 chars and each recent user message to 150, so the transcript stays cheap. Reminders the capability injected itself are filtered out, so they don't pile up.

### An LLM-generated nudge

For very long or evolving tasks, let a small model summarize progress and write a fresh two-sentence reminder. This is the only option that costs tokens — and it's deliberately cheap.

```python
from pydantic_deep.features.periodic_reminder import (
    LLMReminderGenerator,
    PeriodicReminderConfig,
)

cfg = PeriodicReminderConfig(
    every_n_turns=15,
    generator=LLMReminderGenerator(
        model="anthropic:claude-haiku-4-5-20251001",  # optional; cheaper model
        max_context_messages=10,
    ),
)
```

`LLMReminderGenerator` defaults to a small model and only feeds it a compacted transcript. If the call fails for any reason, it falls back to the zero-cost first-message default automatically — a reminder always gets injected.

!!! tip "Which generator?"
    | Generator | Token cost | When to reach for it |
    |---|---|---|
    | `None` (default) | Zero | Most runs — keep the original ask visible |
    | Static `str` | Zero | The goal is fixed and you know it upfront |
    | Async callable | Zero | The goal depends on runtime state |
    | `build_compact_transcript` | Zero | Long runs where recent context matters |
    | `LLMReminderGenerator` | Low | Very long runs with a complex, evolving goal |

## How the reminder is wrapped

`render_style` controls the wrapper the text gets before injection:

| Style | Output |
|---|---|
| `system_reminder_tag` (default) | `<system-reminder>\n…\n</system-reminder>` |
| `developer_note` | `[Developer note for the assistant: …]` |
| `user_prompt` | plain text |

```python
cfg = PeriodicReminderConfig(render_style="developer_note")
```

## Named modes

If you'd rather not assemble a config by hand, `make_config_for_mode` maps a string to a ready-made one:

```python
from pydantic_deep.features.periodic_reminder import make_config_for_mode

cfg = make_config_for_mode("llm")  # also: "first", "context"
```

| Mode | Generator | `every_n_turns` | `max_reminders_per_run` |
|---|---|---|---|
| `first` | first user message | 10 | unlimited |
| `context` | compact transcript | 10 | unlimited |
| `llm` | `LLMReminderGenerator` | 15 | 3 |

This is exactly what the CLI uses — periodic reminders ship **enabled in `"llm"` mode**, and `/remind` switches modes at runtime. You can pin defaults in `~/.pydantic-deep/config.toml`:

```toml
periodic_reminder = true
reminder_mode = "llm"        # "off" | "first" | "context" | "llm"
reminder_model = "anthropic:claude-haiku-4-5-20251001"  # optional
```

## Using it standalone

`periodic_reminder=` is a convenience. Under the hood it registers a [`PeriodicReminderCapability`][pydantic_deep.features.periodic_reminder.PeriodicReminderCapability], which is an ordinary Pydantic AI capability — so you can add it to any agent directly.

```python
from pydantic_ai import Agent
from pydantic_deep.features.periodic_reminder import (
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

The capability isolates its turn counter per run via `for_run()`, so concurrent runs never share state.

!!! note "Write your own generator"
    Anything satisfying the `ReminderGenerator` protocol works — a plain
    `async def` or a class with `async def __call__(self, ctx, turn, messages)
    -> str`. Return the text; the capability handles rendering and injection.

## Recap

- Periodic reminders re-inject your goal every *N* turns so the agent doesn't drift on long runs.
- `periodic_reminder=True` is the zero-cost default — it re-states your first message at turn 5, then every 10 turns.
- A `PeriodicReminderConfig` tunes the cadence (`every_n_turns`, `first_after`, `max_reminders_per_run`) and the `generator`.
- Generators range from free (first message, static string, callable, compact transcript) to a low-cost `LLMReminderGenerator` that summarizes progress — with an automatic fallback if it fails.
- `make_config_for_mode("first" | "context" | "llm")` gives you the CLI's presets in one line.

Next, keep an eye on the agent in other ways:

- [Stuck-loop detection →](stuck-loop-detection.md)
- [Context management →](context-management.md)
- [Capabilities & lifecycle →](capabilities.md)
