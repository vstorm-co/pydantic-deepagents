# Goal loop

Set a completion condition once, and the agent keeps working toward it across turns — no per-turn prompting from you. After each turn a small, fast model reads the transcript and judges whether the condition is met. If not, another turn starts automatically with the evaluator's feedback as guidance. When it's met, the loop stops.

This is a port of Claude Code's [`/goal`](https://code.claude.com/docs/en/goal). The engine in `pydantic_deep/goal.py` is provider- and UI-agnostic, so you can drive it from a headless loop, and the CLI ships a `/goal` command built on the very same pieces.

## The engine

Two objects do the work: [`GoalState`][pydantic_deep.goal.GoalState] holds what you're working toward, and [`GoalEvaluator`][pydantic_deep.goal.GoalEvaluator] decides whether you're there yet.

```python hl_lines="11 12 17"
import asyncio

from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend
from pydantic_deep.goal import GoalEvaluator, GoalState, goal_continue_directive


async def main():
    agent = create_deep_agent(model="anthropic:claude-sonnet-4-6")
    deps = DeepAgentDeps(backend=StateBackend())

    goal = GoalState(condition="fib.py exists and prints 55 for n=10")
    evaluator = GoalEvaluator()

    prompt = goal.condition
    messages = None
    while goal.is_active and not goal.exhausted:
        result = await agent.run(prompt, deps=deps, message_history=messages)
        messages = result.all_messages()

        evaluation = await evaluator.evaluate(goal.condition, messages)
        goal.record(evaluation)

        if evaluation.met:
            print(f"✓ Goal achieved in {goal.turns} turn(s): {evaluation.reason}")
        elif evaluation.impossible:
            print(f"✗ Goal impossible: {evaluation.reason}")
            break
        else:
            prompt = goal_continue_directive(goal.condition, evaluation.reason)


asyncio.run(main())
```

The agent runs, the evaluator judges, and the loop either stops or feeds the reason back and runs again. You wrote the condition once.

## Dissect

### The condition lives in `GoalState`

```python
goal = GoalState(condition="fib.py exists and prints 55 for n=10")
```

[`GoalState`][pydantic_deep.goal.GoalState] is plain mutable state — nothing UI-specific. It tracks `turns`, `achieved`, `last_reason`, and cumulative evaluator tokens. Two properties drive the loop:

- `goal.is_active` — `True` until the condition is achieved.
- `goal.exhausted` — `True` once `turns` hits `max_turns` (default `100`) without success. This is a hard safety cap so a vague condition can never loop forever.

`goal.record(evaluation)` folds one result in: it bumps `turns`, stores the reason, adds the token counts, and flips `achieved` when met.

### The evaluator judges from the transcript alone

```python
evaluation = await evaluator.evaluate(goal.condition, messages)
```

[`GoalEvaluator`][pydantic_deep.goal.GoalEvaluator] spins up a tiny Pydantic AI agent on a small, fast model (default `anthropic:claude-haiku-4-5`, the same cheap tier the [periodic reminder](periodic-reminder.md) uses) and asks one question: *is this condition satisfied by evidence already in the conversation?* It does **not** call tools or read files — it only reasons over what the agent surfaced.

`evaluate()` returns a [`GoalEvaluation`][pydantic_deep.goal.GoalEvaluation]:

- `met` — `True` only when the transcript shows clear, concrete evidence.
- `reason` — one sentence, quoting the transcript where it can.
- `impossible` — `True` only when the condition is genuinely unachievable this session (self-contradictory, needs an unavailable resource, or every reasonable approach is exhausted). Always implies `met is False`; the host stops instead of grinding to the turn cap.
- `input_tokens` / `output_tokens` — what the evaluation cost.

!!! note "Built to resist gaming"
    The evaluator treats the agent's own claim of success as evidence, not proof — it wants the actual artifact (command output, exit code, test summary). It's also told that weakening a check to pass it (editing assertions, skipping or deleting tests, narrowing scope) does **not** satisfy the goal. The output is a typed `Verdict` schema, so there's no `YES`/`NO` text to misparse, and any evaluator failure defaults to *not met* — a transient hiccup keeps the agent working rather than declaring premature success.

### The feedback loop

```python
prompt = goal_continue_directive(goal.condition, evaluation.reason)
```

[`goal_continue_directive`][pydantic_deep.goal.goal_continue_directive] builds the next turn's prompt: it restates the goal, passes back the evaluator's reason, and tells the agent to surface concrete evidence (and not to cheat). That directive becomes the next `agent.run()` prompt — which is exactly how the agent keeps working without you typing anything.

## The pure helpers

The engine is deliberately split into small, host-agnostic functions so a CLI or a headless driver can wire it up however it likes:

- [`parse_goal_command(arg)`][pydantic_deep.goal.parse_goal_command] — interprets a `/goal` argument into `("status" | "clear" | "set", condition)`. Empty → status; a clear alias (`clear`, `stop`, `off`, `reset`, `none`, `cancel`) → clear; anything else → set (truncated to the 4,000-char cap).
- [`build_goal_transcript(messages)`][pydantic_deep.goal.build_goal_transcript] — renders the compact transcript the evaluator judges against. Unlike a reminder nudge, it keeps the *evidence*: assistant text and tool results (truncated), anchored by the original request.
- [`format_goal_status(state, elapsed_seconds)`][pydantic_deep.goal.format_goal_status] — a human-readable status block (condition, elapsed time, turns, evaluator tokens, latest reason).

!!! tip "Swap the evaluator model"
    `GoalEvaluator(model="openai:gpt-4o-mini")` — or pass any Pydantic AI `Model` instance. Keep the evaluator on the same provider as your session if you only have one key; a Haiku default needs an Anthropic key.

## In the CLI

The terminal assistant wires all of this behind one command — you never touch the engine directly.

```text
/goal all tests in tests/auth pass
```

Setting a goal kicks off the first turn immediately, with the condition as the directive. After each turn the CLI evaluates the active goal off the saved history: when it's met the goal clears with a `✓ Goal achieved` toast; otherwise the evaluator's reason is surfaced and fed into a fresh turn automatically. A `◎ goal` indicator sits on the status bar while a goal is active.

The rest of the surface:

| Command | What it does |
| --- | --- |
| `/goal <condition>` | Set the goal and start working toward it. |
| `/goal` | Show status if a goal is active; otherwise open a modal to type one. |
| `/goal clear` | Drop the active goal early (aliases: `stop`, `off`, `reset`, `none`, `cancel`). `/clear` also drops it. |

!!! info "Which evaluator model the CLI picks"
    The CLI prefers an explicit `goal_model`, then the cheap `reminder_model`, then falls back to your **main session model** — so an OpenRouter or Ollama user isn't silently routed to a direct Anthropic model they have no key for. Only when nothing resolves does it use the engine's Haiku default.

## Recap

- A **goal** is a completion condition the agent works toward across turns on its own — you set it once.
- [`GoalState`][pydantic_deep.goal.GoalState] holds the condition and progress; `is_active` and `exhausted` (capped by `max_turns`) drive the loop.
- [`GoalEvaluator`][pydantic_deep.goal.GoalEvaluator] judges *only* from the transcript with a small fast model and returns a [`GoalEvaluation`][pydantic_deep.goal.GoalEvaluation] (`met`, `reason`, `impossible`, token counts) — built to resist the agent gaming its way to "done".
- [`goal_continue_directive`][pydantic_deep.goal.goal_continue_directive] turns the evaluator's feedback into the next turn's prompt; pure helpers ([`parse_goal_command`][pydantic_deep.goal.parse_goal_command], [`build_goal_transcript`][pydantic_deep.goal.build_goal_transcript], [`format_goal_status`][pydantic_deep.goal.format_goal_status]) let any host wire it.
- In the CLI it's all one command: `/goal <condition>` to start, `/goal` for status, `/goal clear` to stop.

Where to go next:

- [Periodic reminders](periodic-reminder.md) — nudge a long run to stay on task each turn.
- [Stuck-loop detection](stuck-loop-detection.md) — catch an agent spinning on the same action.
- [Cost tracking & budgets](cost-tracking.md) — cap what an autonomous loop can spend.
