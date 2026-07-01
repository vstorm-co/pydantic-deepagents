# Subagents

A long task can fill your agent's context with noise — half-finished plans, stale tool output, three threads of reasoning at once. **Subagents** are the fix: the main agent hands a focused job to a fresh specialist, that specialist runs in its own context, and only one clean result comes back. You delegate to a teammate who reports the answer, not one who narrates every step.

The main agent does this through a single built-in tool: `task`.

```python
import asyncio

from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend


async def main():
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        instructions="You are a coding assistant. Delegate self-contained jobs.",
    )

    deps = DeepAgentDeps(backend=StateBackend())

    result = await agent.run(
        "Use the general-purpose subagent to write a prime-sieve function "
        "in primes.py and a quick test for it. Then summarize what it did.",
        deps=deps,
    )
    print(result.output)


asyncio.run(main())
```

## Run it

Save it to `main.py` and run:

<div class="termy">

```console
$ python main.py
```

</div>

The main agent calls `task`, spins up a `general-purpose` subagent, and hands it the brief. That subagent writes `primes.py`, writes a test, runs it — all in its **own** conversation — then returns a short summary. The main agent never sees the subagent's intermediate steps, only its final report.

!!! example "Check it"
    Add `print(sorted(deps.files.keys()))` after the run. `primes.py` is there —
    the subagent shared your backend, so the files it wrote are really on disk
    (in memory here, because you used `StateBackend`).

## What just happened

The `task` tool takes two things, and the main agent fills them in:

- `subagent_type` — *which* specialist to run (here, the built-in `general-purpose`).
- `description` — the brief. This becomes the subagent's user prompt.

Each call creates a full deep agent — filesystem, shell, web, todos — runs it once with that brief, and returns its output. That is the whole contract: one focused job in, one result out.

## Isolation is the point

A subagent does **not** inherit your conversation. It starts with a clean slate:

- **Fresh context** — it never sees the main agent's message history. The brief is all it knows, so write it self-contained.
- **Separate todo list** — the subagent plans its own work without inheriting yours, so neither one's plan pollutes the other.
- **Shared backend** — files are the exception. The subagent reads and writes the *same* backend, so handing work off is as simple as "look at `/src/auth.py`."

That separation is what keeps the main agent's context small and on-task — the subagent absorbs the noise and returns only the signal.

!!! tip "Write a complete brief"
    The subagent can't ask "wait, what file did you mean?" — it doesn't share
    your context. Put everything it needs in the `description`: paths, goals,
    and the format you want back.

## The built-in subagents

You don't have to define anything to start delegating. Every agent ships with these (`include_builtin_subagents=True` by default):

| `subagent_type` | Use it for |
|-----------------|------------|
| `general-purpose` | Any multi-step job — implementing features, editing files, running commands and tests, mixed research-and-build work. Full toolset. |
| `research` | Investigation only — exploring a codebase, searching the web, gathering information across many sources. Reads, doesn't build. |
| `planner` | Plan mode — analyzing the code and proposing a step-by-step plan before any changes. Added when `include_plan=True` (the default). |

Turn them off if you only want your own:

```python
agent = create_deep_agent(
    subagents=my_subagents,
    include_builtin_subagents=False,
)
```

## Defining your own specialist

When a job recurs, give it a name and a focused system prompt with `SubAgentConfig`. The main agent reads each `description` to decide when to delegate.

```python hl_lines="1 12 13 14 15 16 17 18"
from pydantic_deep import create_deep_agent, SubAgentConfig

reviewer = SubAgentConfig(
    name="security-reviewer",
    description=(
        "Reviews code specifically for security issues — SQL injection, "
        "XSS, auth and authorization flaws. Use before merging."
    ),
    instructions="""
    You are a security expert. Focus ONLY on security:
    SQL injection, XSS, auth, authorization.
    Do NOT comment on style or performance.

    Report as markdown with a Summary, Critical Issues, and Recommendations.
    """,
)

agent = create_deep_agent(subagents=[reviewer])
```

Now the main agent can call `task(subagent_type="security-reviewer", description="Review /src/auth.py")` whenever the work calls for it — alongside the built-ins.

!!! note "You only write the specialized part"
    Every subagent gets the core deep-agent behavior automatically, plus the
    `instructions` you provide. Keep them tight and single-purpose: a clear
    `description` so the main agent picks the right one, and focused
    `instructions` so the subagent excels at one thing.

!!! tip "A different model per specialist"
    Pass `model=` on a `SubAgentConfig` to run a cheap, fast model for simple
    jobs and a stronger one for hard analysis — without touching the main
    agent's model.

## Sync vs. background

By default `task` runs **synchronously**: the main agent waits for the result before moving on. For long jobs it can delegate in the **background** and keep working, then check in later — using `check_task` and `list_active_tasks` to collect results. That, plus nested delegation, lives in [Subagents (advanced)](../learn/subagents.md).

## Recap

You taught your agent to delegate:

- The main agent calls the `task` tool with a `subagent_type` and a `description` — one focused job in, one clean result out.
- Subagents are **isolated**: fresh context and their own todo list, but a **shared backend** so files pass between them.
- Three subagents ship for free — `general-purpose`, `research`, and `planner`.
- Define your own with `SubAgentConfig(name, description, instructions)` — a sharp description so the main agent picks it, focused instructions so it excels.

Next, let's make the agent return a typed object instead of a string.

- [Structured output →](structured-output.md)
