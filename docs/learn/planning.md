# Planning with todos

Give your agent a multi-step job and it won't just dive in — it writes a plan first, then ticks items off as it goes. That plan is a real, inspectable todo list, and you didn't have to build it.

```python
import asyncio

from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend


async def main():
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        instructions="You are a helpful coding assistant.",
    )

    deps = DeepAgentDeps(backend=StateBackend())

    result = await agent.run(
        "Build a small CLI calculator: write calc.py with add/sub/mul/div, "
        "add a tests file, run the tests, and fix anything that fails.",
        deps=deps,
    )
    print(result.output)

    # The plan the agent built and worked through:
    for todo in deps.todos:
        print(f"[{todo.status}] {todo.content}")


asyncio.run(main())
```

## Run it

Save it to `main.py` and run:

<div class="termy">

```console
$ python main.py
```

</div>

A task with four-plus distinct steps trips the agent's planning instinct. It calls `write_todos` to lay out the work, marks one item `in_progress`, does it, marks it `completed`, and moves to the next — so the final loop prints something like:

```text
[completed] Write calc.py with add/sub/mul/div
[completed] Write tests for the calculator
[completed] Run the test suite
[completed] Fix failing tests
```

!!! example "Check it"
    Add a simpler prompt — `"What's 2 + 2?"` — and print `deps.todos` after.
    It'll be empty. The agent only reaches for a plan when the work actually
    has steps; trivial asks stay todo-free.

## What's happening

You didn't register a todo tool — `create_deep_agent()` wired one in for you. Let's look at the two halves: the tools the model uses, and the list you read.

### The tools the agent gets

Because `include_todo=True` is the default, every agent gets a small set of planning tools:

- `read_todos` — view the current list with each item's ID and status.
- `write_todos` — replace the whole list (how the agent lays out a fresh plan).
- `add_todo` — append a single new task.
- `update_todo_status` — flip one task to `pending`, `in_progress`, or `completed` by ID.
- `remove_todo` — drop a task by ID.

The agent's instructions nudge it to use them for anything non-trivial: break the work down, keep exactly **one** task `in_progress` at a time, and mark things `completed` the moment they're done — not in a batch at the end.

!!! note "Three states"
    Every todo is `pending`, `in_progress`, or `completed`. That's the whole
    state machine — enough to drive a focused agent without ceremony.

### The list you read

```python hl_lines="2"
deps = DeepAgentDeps(backend=StateBackend())
# ... after the run ...
for todo in deps.todos:
    print(f"[{todo.status}] {todo.content}")
```

The todos don't vanish when the run ends — they live on `deps.todos`, a plain list of `Todo` objects you can read afterward. Each one has:

- `content` — the task in imperative form (`"Run the test suite"`).
- `status` — `pending` / `in_progress` / `completed`.
- `active_form` — the present-tense label (`"Running the test suite"`), handy for a live status line.
- `id` — a short identifier the tools use to target a single task.

Because the list is right there on your deps object, the same plan the model worked through is yours to inspect, log, or render in a UI.

!!! tip "Watch the plan live"
    `deps.todos` updates *during* the run, not just after it. Read it from a
    background task or a streaming handler to drive a progress display — see
    [Streaming](streaming.md) for the event-by-event view.

## Sharing todos with subagents

When your agent delegates to a [subagent](subagents.md), the subagent gets its **own, empty** todo list by default. That's deliberate: a subagent planning its slice of the work shouldn't scribble over the parent's plan.

If you *do* want one shared plan across the parent and its subagents, flip `share_todos` on the deps:

```python hl_lines="3"
deps = DeepAgentDeps(
    backend=StateBackend(),
    share_todos=True,  # subagents read and write the same todo list
)
```

Now a subagent's `write_todos` and `update_todo_status` land on the same list the parent sees — useful when you want a single, unified view of progress across a whole delegation tree.

!!! warning "Shared means shared"
    With `share_todos=True`, several agents can write to the same list
    concurrently. It's the right call for a single coordinated plan, but if you
    want each subagent to own its work independently, leave it `False` (the
    default).

## Recap

Your agent now plans its own work and you can see the plan:

- `create_deep_agent()` includes the todo tools by default (`include_todo=True`) — `read_todos`, `write_todos`, `add_todo`, `update_todo_status`, `remove_todo`.
- The agent breaks multi-step tasks into todos, keeps one `in_progress`, and marks each `completed` as it finishes.
- The plan lives on `deps.todos` — a list of `Todo` objects (`content`, `status`, `active_form`, `id`) you can read during or after the run.
- Subagents get isolated todos by default; set `share_todos=True` for one shared plan across the delegation tree.

Next, let's hand the agent tools of your own.

- [Custom tools →](custom-tools.md)
