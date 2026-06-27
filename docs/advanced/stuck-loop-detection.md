# Stuck-loop detection

Sometimes an agent gets stuck. It reads the same file again and again, bounces between two tools forever, or keeps calling something that does nothing. Left alone, it burns tokens and never finishes. Stuck-loop detection watches for that and steps in — nudging the model to try something else, or stopping the run.

It's on by default. You already have it.

```python
from pydantic_deep import create_deep_agent

# Stuck-loop detection is already running
agent = create_deep_agent(model="anthropic:claude-sonnet-4-6")
```

If the agent calls `read_file("/src/app.py")` three times in a row, the third call doesn't return a file — it returns a nudge telling the model to change course. You wrote nothing to make that happen.

## What it catches

It watches the stream of tool calls and looks for three shapes of "spinning."

### Repeated identical calls

The same tool, the same arguments, N times in a row:

```
read_file(path="/src/app.py")    # 1
read_file(path="/src/app.py")    # 2
read_file(path="/src/app.py")    # 3  -> triggered
```

### Alternating A-B-A-B

Two tools ping-ponging back and forth with nothing changing:

```
grep(pattern="TODO")             # A
read_file(path="/src/app.py")    # B
grep(pattern="TODO")             # A
read_file(path="/src/app.py")    # B  -> triggered
```

### No-op calls

A tool that keeps returning the *same result* — the call has no effect, so repeating it is pointless:

```
list_files(path="/src")  -> ["a.py", "b.py"]
list_files(path="/src")  -> ["a.py", "b.py"]
list_files(path="/src")  -> ["a.py", "b.py"]  -> triggered
```

## How it works

Stuck-loop detection is a [capability][pydantic_deep.features.stuck_loop.StuckLoopDetection] — it hooks into the agent lifecycle and runs after every tool call. For each call it records two things: a hash of the tool name plus its arguments, and a hash of the tool name plus its result. Then it checks the recent history against the three patterns above.

When a pattern matches, what happens next depends on `action`:

- `"warn"` (the default) raises a `ModelRetry`. The model receives the message as feedback and gets a chance to self-correct. The run keeps going.
- `"error"` raises a `StuckLoopError` and the run stops.

Each run gets its own fresh detection state (via `for_run()`), so concurrent runs never share history or trip over each other.

!!! note "The model sees the nudge"
    With `action="warn"`, the message is handed back to the model as a retry
    prompt — something like *"You called `read_file` with identical arguments
    3 times in a row. Try a different approach."* Most of the time that's
    enough to break the loop.

## Tuning it

You can dial the behaviour by passing your own `StuckLoopDetection` instance. Turn the default off so you don't run two copies, then add yours:

```python hl_lines="6 7 8"
from pydantic_deep import create_deep_agent
from pydantic_deep.features.stuck_loop import StuckLoopDetection

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    stuck_loop_detection=False,  # disable the default
    capabilities=[
        StuckLoopDetection(max_repeated=5, action="error"),
    ],
)
```

The knobs:

| Parameter | Type | Default | What it does |
|-----------|------|---------|--------------|
| `max_repeated` | `int` | `3` | How many repetitions before it triggers. Must be at least 2. |
| `action` | `str` | `"warn"` | `"warn"` raises `ModelRetry` (model self-corrects); `"error"` raises `StuckLoopError` (run aborts). |
| `detect_repeated` | `bool` | `True` | Catch the same call N times in a row. |
| `detect_alternating` | `bool` | `True` | Catch the A-B-A-B ping-pong. |
| `detect_noop` | `bool` | `True` | Catch a tool returning the same result repeatedly. |
| `ignore_tools` | `set[str]` | `set()` | Tool names exempt from all checks — for polling primitives that *are* meant to be called repeatedly. |

!!! tip "Exempt your pollers"
    Some tools are *supposed* to be called over and over with the same
    arguments — a status poller, a queue check. Add them to `ignore_tools`
    so a legitimate poll loop doesn't read as a stuck loop:
    `StuckLoopDetection(ignore_tools={"inspect_branches"})`.

## Handling a hard stop

When you choose `action="error"`, catch `StuckLoopError` to decide what happens next. It carries a `pattern` attribute telling you which shape tripped — `"repeated"`, `"alternating"`, or `"noop"`:

```python
from pydantic_deep import StuckLoopError

try:
    result = await agent.run("...", deps=deps)
except StuckLoopError as e:
    print(f"Agent got stuck ({e.pattern}): {e}")
```

!!! warning "Disable it only with a reason"
    The default `"warn"` mode is cheap insurance — it costs nothing until the
    agent actually loops, and it gives the model a chance to recover on its
    own. Reach for `create_deep_agent(stuck_loop_detection=False)` only when
    you have a deliberate reason to let loops run.

## Recap

- Stuck-loop detection is a capability that's **on by default** — it watches tool calls and breaks unproductive loops.
- It catches three patterns: **repeated** identical calls, **alternating** A-B-A-B, and **no-op** same-result calls.
- `max_repeated` (default `3`) sets the threshold; the count must be at least 2.
- `action="warn"` (default) raises `ModelRetry` so the model self-corrects; `action="error"` raises `StuckLoopError` and stops the run.
- Add noisy-but-legitimate pollers to `ignore_tools` so they aren't flagged.

Where to go next:

- [Capabilities & lifecycle](capabilities.md) — how capabilities hook into the agent.
- [Cost tracking & budgets](cost-tracking.md) — another guardrail, this one for spend.
- [Hooks](hooks.md) — run your own logic on tool events.
- [`StuckLoopDetection`][pydantic_deep.features.stuck_loop.StuckLoopDetection] and [`StuckLoopError`][pydantic_deep.features.stuck_loop.StuckLoopError] in the API reference.
