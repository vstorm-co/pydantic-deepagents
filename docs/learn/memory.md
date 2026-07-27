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
    # memory_dir persists memory to disk (a FileStore), so it even outlives
    # the process. Omit it and memory lives in an in-memory store for the
    # lifetime of this `agent` object.
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        instructions="You are a helpful coding assistant.",
        memory_dir="./.memory",
    )

    deps = DeepAgentDeps(backend=StateBackend())

    # First session: tell it something worth remembering.
    await agent.run(
        "Remember that I always use pytest, never unittest. Save that to memory.",
        deps=deps,
    )

    # Second session: a fresh run against the same agent (and memory store).
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

The second `agent.run()` is a brand-new conversation. It has none of the first run's messages. Yet it answers correctly, because between the two runs the agent wrote a note to `MEMORY.md` and read it straight back out of its memory store.

!!! example "Check it"
    Print the file the agent wrote to disk (`memory_dir="./.memory"` → a `FileStore`):

    ```python
    print(open("./.memory/main/MEMORY.md").read())
    ```

    There it is — a markdown bullet the agent saved on its own. Real persistence, on disk because you set `memory_dir`. Drop `memory_dir` and the same thing happens in an ephemeral in-memory store instead.

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
| `read_memory` | Read one memory file |
| `write_memory` | Append to a file, or uniquely replace text (`old_text`) |
| `delete_memory` | Delete a non-main memory file |
| `search_memory` | Find relevant memory files by query |

The agent calls these on its own when it decides something is worth keeping. `MEMORY.md` is the main notebook; the agent can also keep longer topics in separate files it lists and searches. You can turn the whole thing off with `include_memory=False`.

### The store is the persistence

Memory is backed by the `Memory` capability from [pydantic-ai-harness](https://github.com/vstorm-co/pydantic-ai-harness), which keeps memory in its own `MemoryStore` — **separate from the agent's backend**. The store is created once when you build the agent and shared by the main agent and every subagent (each scoped by name) — unless a run's `DeepAgentDeps(memory_store=…)` overrides it, which is how per-user scoping and branch-local fork memory work.

- **Default:** an ephemeral `InMemoryStore` — memory lives as long as the agent object does (so the two runs above share it because they reuse the same `agent`).
- **On disk:** pass `memory_dir="./.memory"` and a `FileStore` writes `{memory_dir}/{agent_name}/MEMORY.md`, surviving the process.
- **Explicit:** pass `memory_store=SqliteMemoryStore(database="mem.db")` (or any `MemoryStore`) to control storage directly.

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

!!! warning "One store, one memory — watch multi-user apps"
    A memory store is keyed by agent name. If several users share one store, they share one `MEMORY.md`. Pass a per-user store on `DeepAgentDeps(memory_store=…)`, give each user their own agent-level `memory_store`/`memory_dir`, or partition one store with `memory_namespace=`. Context files still live in the backend, keyed by agent name. See [Multi-user](../advanced/multi-user.md).

## Recap

- **Memory** is on by default: `read_memory` / `write_memory` / `delete_memory` / `search_memory`, plus auto-injection of the latest lines into the prompt — the agent remembers across runs on its own.
- **The store is the persistence.** Memory lives in a harness `MemoryStore`, separate from the backend: ephemeral by default, on disk with `memory_dir`, or any store via `memory_store=`.
- **Context files** (`AGENTS.md`, `CLAUDE.md`, `DEEP.md`, `SOUL.md`) are project rules *you* write; `context_discovery=True` finds them, or list them with `context_files=`.
- Rule of thumb: the agent owns memory, you own context files — and `SOUL.md` stays with the main agent only.

Both of these survive a single process. To save, label, and rewind whole conversations, that's next.

- [Sessions & checkpoints →](sessions.md)
