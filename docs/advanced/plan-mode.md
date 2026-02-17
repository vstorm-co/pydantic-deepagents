# Plan Mode

Plan mode provides a Claude Code-style planning subagent that analyzes the codebase, asks clarifying questions, and creates step-by-step implementation plans — without making any changes.

## Quick Start

Plan mode is **enabled by default** when subagents are enabled:

```python
from pydantic_deep import create_deep_agent

agent = create_deep_agent(
    include_plan=True,       # Default: True
    include_subagents=True,  # Default: True
)
```

The main agent can invoke the planner:

```
User: "Plan how to add authentication to the app"
Agent: [delegates to planner subagent]
Planner: [reads code, asks questions, creates plan, saves to file]
```

## How It Works

The planner is a **subagent** registered with the task tool:

1. Main agent delegates to the "planner" subagent
2. Planner reads files to understand the codebase
3. Planner asks clarifying questions via `ask_user`
4. Planner writes a structured plan and saves it via `save_plan`

### Planner Tools

| Tool | Description |
|------|-------------|
| `ask_user` | Ask the user a question with predefined options |
| `save_plan` | Save the plan as a markdown file |

Plus all console tools (read_file, ls, grep, glob) for code exploration.

### ask_user

The `ask_user` tool pauses execution and asks the human a question with predefined options:

```python
# The planner calls:
ask_user(
    question="Which auth method should we use?",
    options=[
        {"label": "JWT", "description": "Stateless tokens", "recommended": "true"},
        {"label": "Session", "description": "Server-side sessions"},
        {"label": "OAuth", "description": "Third-party auth providers"},
    ],
)
```

When no `ask_user` callback is set on deps (headless mode), it auto-selects the recommended option.

### save_plan

Plans are saved as markdown files to the backend:

```python
save_plan(
    title="Add JWT Authentication",
    content="# Plan: Add JWT Authentication\n\n## Context\n..."
)
# Saves to: /plans/add-jwt-authentication-a1b2c3.md
```

## Configuration

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `include_plan` | `bool` | `True` | Enable the planner subagent |
| `plans_dir` | `str` | `"/plans"` | Directory for plan files |

## Plan Format

The planner produces structured markdown plans:

```markdown
# Plan: [Title]

## Context
[What needs to be done and why]

## Decisions Made
- [Decision 1]: [chosen option] — [reason]

## Implementation Steps

### Step 1: [Title]
- **Files**: `path/to/file.py`
- **Action**: create | modify | delete
- **Details**: [What to change and how]

### Step 2: [Title]
...

## Files Summary
| File | Action | Description |
|------|--------|-------------|
| ... | create/modify/delete | ... |

## Notes
[Caveats, dependencies, or follow-up items]
```

## Interactive Mode

To enable the `ask_user` callback for interactive planning, set it on deps:

```python
async def handle_ask_user(question: str, options: list[dict]) -> str:
    print(f"\n{question}")
    for i, opt in enumerate(options, 1):
        rec = " (recommended)" if opt.get("recommended") == "true" else ""
        print(f"  {i}. {opt['label']}{rec} — {opt['description']}")
    choice = input("Choose: ")
    return options[int(choice) - 1]["label"]

deps = DeepAgentDeps(
    backend=backend,
    ask_user=handle_ask_user,
)
```

!!! info "Multi-User Applications"
    Plans are saved as files in the backend. In multi-user apps, use separate
    backends per user. UUIDs in filenames prevent collisions, but users sharing a
    backend can see each other's plans. See [Multi-User Guide](multi-user.md).

## Disabling Plan Mode

```python
agent = create_deep_agent(include_plan=False)
```

## Components

| Component | Description |
|-----------|-------------|
| [`create_plan_toolset`][pydantic_deep.toolsets.plan.create_plan_toolset] | Factory for plan tools |
| `PLANNER_INSTRUCTIONS` | Built-in planner system prompt |
| `PLANNER_DESCRIPTION` | Planner subagent description |
| `DEFAULT_PLANS_DIR` | Default plans directory: `/plans` |

## Next Steps

- [Subagents](subagents.md) — Task delegation system
- [Teams](teams.md) — Multi-agent collaboration
- [Human-in-the-Loop](human-in-the-loop.md) — Approval workflows
