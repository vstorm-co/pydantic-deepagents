# Plan mode

Sometimes you want a plan *before* the agent touches anything. Plan mode gives you a built-in **planner** sub-agent that reads the codebase, asks you the questions it needs answered, and writes a step-by-step implementation plan to a file — without changing a single line. Look before you leap.

## Enable it

Plan mode is **on by default** whenever sub-agents are on. You already have it:

```python hl_lines="4 5"
from pydantic_deep import create_deep_agent

agent = create_deep_agent(
    include_plan=True,       # default: True
    include_subagents=True,  # default: True
)
```

Now just ask for a plan, and the main agent delegates to the planner:

```python
deps = DeepAgentDeps(backend=StateBackend())

result = await agent.run(
    "Plan how to add authentication to the app. Don't write any code yet.",
    deps=deps,
)
print(result.output)
```

!!! example "Check it"
    After the run, list the plans the agent wrote:
    `print(await deps.backend.ls("/plans"))`. There's a markdown file in there —
    a real, structured plan you can read, edit, and hand back for execution.

## What just happened

The planner is a sub-agent registered under the task tool. When you ask for a plan, here's the flow:

1. The main agent delegates to the **planner** sub-agent.
2. The planner reads files to understand the codebase — it has the full console toolset (`read_file`, `ls`, `grep`, `glob`) for exploration.
3. Whenever something is ambiguous, it calls `ask_user` to ask you a clarifying question.
4. It writes a structured plan and persists it with `save_plan`.

The planner is told, firmly, that it **only plans** — it never edits files or runs commands.

## The two planner tools

The planner has its own two-tool toolset on top of the read-only console tools.

### `ask_user`

`ask_user` pauses to ask you a question with a few concrete options. The planner must always offer 2–4 of them:

```python
ask_user(
    question="Which auth method should we use?",
    options=[
        {"label": "JWT", "description": "Stateless, good for APIs", "recommended": True},
        {"label": "Session", "description": "Traditional server-side state"},
        {"label": "OAuth2", "description": "Third-party auth providers"},
    ],
)
```

Each option is a `PlanOption` — a `label`, an optional `description`, and an optional `recommended` flag. Mark the one you'd lean toward as `recommended=True`; the planner is instructed to ask the most important questions first.

### `save_plan`

When the plan is ready, the planner calls `save_plan` with a title and the full markdown:

```python
save_plan(
    title="Add JWT Authentication",
    content="# Plan: Add JWT Authentication\n\n## Context\n...",
)
# -> Plan saved to `/plans/add-jwt-authentication-a1b2c3.md`
```

The title becomes a slug, a short random suffix keeps filenames unique, and the file lands in `plans_dir`. Non-Latin titles are preserved, so a plan titled in any language still gets a readable filename.

## Headless by default

Here's the part that makes plan mode safe to run unattended: **`ask_user` only blocks if you give it someone to ask.**

The tool looks for an `ask_user` callback on your deps. If there isn't one — the common case in scripts, tests, and background jobs — it doesn't hang waiting for input. It **auto-selects the recommended option** (or the first option if none is marked) and returns `[Auto-selected: JWT]` so the transcript records the choice. The planner keeps going and still produces a complete plan.

!!! tip "Best of both modes"
    Write your planner instructions to mark a sensible `recommended` option on
    every question. Then the same agent runs interactively when a human is
    present and falls through to good defaults when one isn't.

## Going interactive

To actually prompt a human, set an `ask_user` callback on your deps. It receives the question and the list of `PlanOption`s, and returns the chosen label:

```python
async def handle_ask_user(question: str, options: list) -> str:
    print(f"\n{question}")
    for i, opt in enumerate(options, 1):
        rec = " (recommended)" if opt.recommended else ""
        print(f"  {i}. {opt.label}{rec} — {opt.description}")
    choice = int(input("Choose: "))
    return options[choice - 1].label


deps = DeepAgentDeps(
    backend=StateBackend(),
    ask_user=handle_ask_user,
)
```

Now every `ask_user` call surfaces in your terminal and waits for a real answer.

## The plan it produces

The planner writes plans in a consistent shape, so they're easy to skim and easy to execute:

```markdown
# Plan: Add JWT Authentication

## Context
[What needs to be done and why]

## Decisions Made
- Auth method: JWT — stateless, fits the existing API surface

## Implementation Steps

### Step 1: Add token utilities
- **Files**: `app/auth/tokens.py`
- **Action**: create
- **Details**: encode/decode helpers, expiry handling

## Files Summary
| File | Action | Description |
|------|--------|-------------|
| app/auth/tokens.py | create | JWT encode/decode helpers |

## Notes
[Caveats, dependencies, follow-up items]
```

## Configuration

| Parameter | Type | Default | What it does |
|-----------|------|---------|--------------|
| `include_plan` | `bool` | `True` | Register the planner sub-agent |
| `plans_dir` | `str` | `"/plans"` | Where plan files are saved |

To turn plan mode off entirely:

```python
agent = create_deep_agent(include_plan=False)
```

!!! info "Multi-user apps"
    Plans are just files in the backend. Random suffixes keep filenames from
    colliding, but users who share one backend can read each other's plans. Give
    each user their own backend. See the [Multi-user guide](multi-user.md).

## Recap

- Plan mode ships **on by default** with sub-agents — the planner reads the code, asks, and writes a plan, but never edits.
- `ask_user` offers 2–4 options; `save_plan` writes structured markdown to `plans_dir`.
- With no `ask_user` callback it runs **headless**, auto-selecting the recommended option — safe for scripts and tests.
- Add an `ask_user` callback on `DeepAgentDeps` to make planning interactive.
- The [`create_plan_toolset`][pydantic_deep.features.plan.create_plan_toolset] factory builds the toolset behind it all.

Where to go next:

- [Subagents](../learn/subagents.md) — the delegation system the planner rides on
- [Human-in-the-loop](../learn/human-in-the-loop.md) — approval and review workflows
- [Agent teams](teams.md) — many agents working together
