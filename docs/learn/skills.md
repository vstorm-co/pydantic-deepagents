# Skills

Sometimes you don't want to teach an agent a *tool* — you want to teach it a *procedure*. Your team's release checklist, a house style for commit messages, the exact way you like bug reports written. **Skills** are how you hand that knowledge to an agent without stuffing it all into the system prompt.

A skill is a folder with a `SKILL.md` file. The agent sees a one-line summary of every skill you give it, and pulls in the full instructions only when a task actually calls for them. Cheap to have many; you pay for the one in use.

## A tiny skill

Let's give an agent one skill — a commit-message convention — and let it discover and load it on its own.

First, the skill. It's just a markdown file with a small YAML header:

```markdown title="skills/commit-style/SKILL.md"
---
name: commit-style
description: Write git commit messages in our team's conventional format
---

# Commit Style

Write every commit message like this:

```
<type>(<scope>): <subject>

<body explaining *why*, not *what*>
```

- `type` is one of: feat, fix, docs, refactor, test, chore
- `subject` is imperative and under 50 characters
- Always include a body for anything non-trivial
```

Now the agent. Point it at the folder that contains the skill:

```python hl_lines="13 14 15"
import asyncio

from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend


async def main():
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        instructions=(
            "You are a coding assistant. When a task matches one of your "
            "skills, load it and follow it."
        ),
        skill_directories=[
            {"path": "./skills", "recursive": True},
        ],
    )

    deps = DeepAgentDeps(backend=StateBackend())

    result = await agent.run(
        "I just fixed a null-pointer crash in the auth login flow. "
        "Write me a commit message for it.",
        deps=deps,
    )
    print(result.output)


asyncio.run(main())
```

## Run it

Save the Python to `main.py`, put the skill at `skills/commit-style/SKILL.md`, then run:

<div class="termy">

```console
$ python main.py
```

</div>

The agent reads its task, sees a `commit-style` skill whose description fits, loads it, and replies with something like:

```
fix(auth): handle missing session token on login

Guard against a null session when the login callback fires before the
token is persisted, which crashed the auth flow on first sign-in.
```

You never told it the format in the prompt. It found the skill and applied it.

!!! example "Check it"
    Add a second skill folder — say `skills/pr-description/SKILL.md` — and ask
    the agent something unrelated. It still only loads the one skill that
    matches. Many skills, lean prompt.

## How it works

Re-read the wiring one piece at a time.

### The `SKILL.md` file

```yaml
---
name: commit-style
description: Write git commit messages in our team's conventional format
---
```

Two fields do the work:

- `name` — a unique, hyphenated identifier the agent uses to load the skill.
- `description` — the one-liner the agent sees in the skill list. This is what it reads to *decide* whether a skill is relevant, so make it specific and task-shaped.

Everything below the frontmatter is the skill body — free-form markdown instructions the agent only sees once it loads the skill. `version`, `tags`, and `author` are optional extras you can add to the header.

### Pointing the agent at skills

```python
skill_directories=[
    {"path": "./skills", "recursive": True},
]
```

Each entry is a folder to scan. `recursive: True` walks subfolders, so one `skills/` directory can hold any number of skill packages. A bare string path works too — `["./skills"]` is shorthand for the dict form.

!!! tip "There's a default folder"
    With just `create_deep_agent(include_skills=True)` (the default), the agent
    scans `~/.pydantic-deep/skills`. Drop skill folders there and every agent
    picks them up — no `skill_directories` needed.

### What the agent can do

Enabling skills gives the agent three tools, used in exactly this order:

| Tool | What it does |
|------|--------------|
| `list_skills` | Lists every skill by `name` + `description` — the cheap summary view. |
| `load_skill` | Pulls in one skill's full `SKILL.md` body, on demand. |
| `read_skill_resource` | Reads an extra file bundled next to the skill (a template, a checklist). |

This is **progressive disclosure**: the agent pays for a handful of one-line descriptions up front, and only loads a full skill — or its resources — when it commits to using it.

### Bundling resources

A skill is a folder, not just a file, so you can ship supporting files beside it:

```
skills/commit-style/
├── SKILL.md
└── examples.md        # the agent reads this with read_skill_resource
```

The agent loads `examples.md` only if the skill tells it to. Resource access is sandboxed to the skill's own folder — path-traversal like `../other-skill/secret.md` is rejected.

## Skipping the filesystem

You don't have to read skills off disk. Pass `Skill` objects straight in and the agent skips discovery entirely:

```python
from pydantic_deep.features.skills import Skill, SkillsToolset

skill = Skill(
    name="commit-style",
    description="Write git commit messages in our team's conventional format",
    content="# Commit Style\n\nWrite every commit message like this...",
)

agent = create_deep_agent(
    toolsets=[SkillsToolset(skills=[skill])],
    include_skills=False,  # don't add a second, empty skills toolset
)
```

!!! note "Skills in other backends"
    `skill_directories` reads local files. To discover skills stored in an
    in-memory `StateBackend`, a `DockerSandbox`, or remote storage, use
    [`BackendSkillsDirectory`][pydantic_deep.features.skills.backend.BackendSkillsDirectory]
    instead — same idea, routed through the backend. See
    [Concepts: Skills](../concepts/skills.md) for the full rundown.

## Recap

- A **skill** is a `SKILL.md` folder — YAML `name` + `description`, then free-form instructions — the agent loads only when a task needs it.
- Point `create_deep_agent(skill_directories=[…])` at a folder, drop files in `~/.pydantic-deep/skills`, or pass `Skill` objects via a `SkillsToolset`.
- The agent works in three steps — `list_skills`, `load_skill`, `read_skill_resource` — so many skills stay cheap until one is actually used.
- The `description` is the agent's only clue at discovery time; write it to describe *when* to reach for the skill.

A skill teaches one agent a procedure. Next, let's hand whole subtasks to *other* agents.

- [Subagents →](subagents.md)
