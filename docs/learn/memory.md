# Memory & context files

By default an agent forgets everything the moment a run ends. This page gives it a memory that survives across sessions — and shows you how to drop a file in your project that every run picks up automatically.

There are two pieces, and they pull in opposite directions:

- **Memory** — a `MEMORY.md` the *agent* writes to. It learns something worth keeping ("you prefer pytest"), saves it, and recalls it next time.
- **Context files** — markdown *you* write (`AGENTS.md`, `CLAUDE.md`, `DEEP.md`, `SOUL.md`). The agent reads them but never edits them. They're how you hand a project its rules without re-explaining them every run.

Let's see memory first, because it's the one with the satisfying payoff.

```python
import asyncio

from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend


async def main():
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        instructions="You are a helpful coding assistant.",
    )

    # One backend, reused across both runs — that's what makes memory persist.
    deps = DeepAgentDeps(backend=StateBackend())

    # First session: tell it something worth remembering.
    await agent.run(
        "Remember that I always use pytest, never unittest. Save that to memory.",
        deps=deps,
    )

    # Second session: a fresh run, but the same backend.
    result = await agent.run("What testing framework do I use?", deps=deps)
    print(result.output)


asyncio.run(main())
```

## Run it

Save it to `main.py` and run:

<div class="termy">

```console
$ python main.py
You use pytest — you mentioned you always prefer it over unittest.
```

</div>

The second `agent.run()` is a brand-new conversation. It has none of the first run's messages. Yet it answers correctly, because between the two runs the agent wrote a note to `MEMORY.md` and read it straight back out of the backend.

!!! example "Check it"
    Print the file the agent wrote:

    ```python
    print(await deps.backend.read("/.deep/memory/main/MEMORY.md"))
    ```

    There it is — a markdown bullet the agent saved on its own. Real persistence, in memory because you used `StateBackend`. Swap in `LocalBackend` and it's a file on disk that outlives the whole process.

## Step by step

### Memory is already on

```python hl_lines="1"
agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    instructions="You are a helpful coding assistant.",
)
```

You didn't ask for memory — it ships enabled. Every agent gets three tools and a slice of `MEMORY.md` folded into its system prompt automatically:

| Tool | What it does |
|------|--------------|
| `read_memory` | Read the full memory file |
| `write_memory` | Append new content to memory |
| `update_memory` | Find-and-replace an existing entry |

The agent calls these on its own when it decides something is worth keeping. You can turn the whole thing off with `include_memory=False`, or move the files with `memory_dir=` (default: `/.deep/memory`).

### The backend is the persistence

```python hl_lines="1"
deps = DeepAgentDeps(backend=StateBackend())
```

This is the load-bearing line. Memory lives at `{memory_dir}/{agent_name}/MEMORY.md` *in the backend* — so persistence is exactly as durable as the backend you choose. Reuse the same backend (as both runs do here) and memory carries over. Hand each run a fresh `StateBackend()` and there's nothing to recall.

!!! note "Injected, not just available"
    Existing memory is pasted into the system prompt at the start of every run (the most recent ~200 lines), so the agent often answers from memory *without* calling `read_memory` at all. The tool is there for when it needs the full file.

## Context files: what *you* hand the agent

Memory is the agent's notebook. Context files are yours. Drop an `AGENTS.md` in the backend root and the agent folds it into its prompt on every run — perfect for conventions, architecture, and "always run `make test` before committing."

```python hl_lines="6"
from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend

backend = StateBackend()
await backend.write(
    "/AGENTS.md",
    b"# Project rules\n\n- Use snake_case for Python.\n- Always run `make test` before committing.\n",
)

agent = create_deep_agent(context_discovery=True)  # scan the backend root
result = await agent.run("What's our naming convention?", deps=DeepAgentDeps(backend=backend))
print(result.output)  # -> "snake_case for Python"
```

`context_discovery=True` scans the backend root for known convention files and injects whatever it finds. Missing files are skipped silently, so you only create the ones you want.

| File | Purpose | Seen by subagents? |
|------|---------|--------------------|
| `AGENTS.md` | Project instructions, conventions, architecture | Yes |
| `CLAUDE.md` | Claude Code project instructions | Yes |
| `DEEP.md` | pydantic-deep project instructions | Yes |
| `SOUL.md` | Personality, tone, your preferences | No — main agent only |

Prefer to be explicit? Skip discovery and name the paths yourself with `context_files=["/AGENTS.md", "/SOUL.md"]`.

!!! tip "Memory vs. context, in one line"
    If the *agent* should write it, it's memory. If *you* write it, it's a context file. `MEMORY.md` has its own tools and per-agent isolation; it is **not** part of context discovery.

!!! warning "One backend, one memory — watch multi-user apps"
    Memory and context both live in the backend, keyed only by agent name. If several users share one backend instance, they share one `MEMORY.md`. Give each user their own backend. See [Multi-user](../advanced/multi-user.md).

## Recap

- **Memory** is on by default: `read_memory` / `write_memory` / `update_memory`, plus auto-injection of the latest lines into the prompt — the agent remembers across runs on its own.
- **The backend is the persistence.** Memory lives at `{memory_dir}/{agent_name}/MEMORY.md`; reuse the backend and it carries over, swap it and it doesn't.
- **Context files** (`AGENTS.md`, `CLAUDE.md`, `DEEP.md`, `SOUL.md`) are project rules *you* write; `context_discovery=True` finds them, or list them with `context_files=`.
- Rule of thumb: the agent owns memory, you own context files — and `SOUL.md` stays with the main agent only.

Both of these survive a single process. To save, label, and rewind whole conversations, that's next.

- [Sessions & checkpoints →](sessions.md)
