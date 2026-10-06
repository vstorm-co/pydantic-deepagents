# Memory & context files

By default an agent forgets everything the moment a run ends. This page gives it a memory that survives across sessions — and shows you how to drop a file in your project that every run picks up automatically.

There are two pieces, and they pull in opposite directions:

- **Memory** — a `MEMORY.md` the *agent* writes to. It learns something worth keeping ("you prefer pytest"), saves it, and recalls it next time.
- **Context files** — markdown *you* write (`AGENTS.md`, `CLAUDE.md`, `DEEP.md`, `SOUL.md`). The agent reads them but never edits them. They're how you hand a project its rules without re-explaining them every run.

Let's see memory first, because it's the one with the satisfying payoff.

```python
import asyncio

from pydantic_deep import create_deep_agent, DeepAgentDeps, LocalWorkspace


async def main():
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        instructions="You are a helpful coding assistant.",
        # One directory, used by both runs — that's what makes memory persist.
        workspace=LocalWorkspace("./project"),
    )

    # First session: tell it something worth remembering.
    await agent.run(
        "Remember that I always use pytest, never unittest. Save that to memory.",
        deps=DeepAgentDeps(),
    )

    # Second session: a fresh run, but the same directory.
    result = await agent.run("What testing framework do I use?", deps=DeepAgentDeps())
    print(result.output)


asyncio.run(main())
```

## Run it

Save it to `main.py`, create the `project` folder, and run:

<div class="termy">

```console
$ mkdir project
$ python main.py
You use pytest — you mentioned you always prefer it over unittest.
```

</div>

The second `agent.run()` is a brand-new conversation. It has none of the first run's messages. Yet it answers correctly, because between the two runs the agent wrote a note to `MEMORY.md` and read it straight back out of the workspace.

!!! example "Check it"
    Look at the file the agent wrote:

    ```console
    $ cat project/.deep/memory/main/MEMORY.md
    ```

    There it is — a markdown bullet the agent saved on its own, in a file on disk that outlives the whole process.

## Step by step

### Memory is already on

```python hl_lines="1"
agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    instructions="You are a helpful coding assistant.",
)
```

You didn't ask for memory — it ships enabled. Memory is the harness's [`Memory`](https://pydantic.dev/docs/ai/harness/) capability: each agent keeps a notebook of Markdown files, `MEMORY.md` is added to every request, and four tools work on the rest:

| Tool | What it does |
|------|--------------|
| `write_memory` | Append to a file, or replace one unique piece of text in it (`old_text=`) |
| `read_memory` | Read one memory file |
| `search_memory` | Search across the notebook's files |
| `delete_memory` | Delete a file — never `MEMORY.md` itself |

The agent calls these on its own when it decides something is worth keeping. You can turn the whole thing off with `include_memory=False`, or move the files with `memory_dir=` (default: `.deep/memory`, relative to the workspace's working directory).

### The workspace is the persistence

```python hl_lines="1"
workspace=LocalWorkspace("./project"),
```

This is the load-bearing line. Memory lives at `{memory_dir}/{agent_name}/MEMORY.md` *in the run's workspace* — so persistence is exactly as durable as the workspace you choose. Both runs here work in the same directory, so memory carries over.

The default workspace is different: `StateWorkspace()` keeps files in memory, and each run that starts a new conversation gets a new, empty document. A run that *continues* one (`message_history=result.all_messages()`) works in the same document — so in memory, the agent remembers within a conversation, not across them.

!!! note "Injected, not just available"
    A bounded excerpt of `MEMORY.md` — up to 200 lines, about 2,000 tokens — and the names of the other files are added to every request, so the agent often answers from memory *without* calling `read_memory` at all. The block goes in as user-role context on the current request only, so copies don't pile up in the history.

## Context files: what *you* hand the agent

Memory is the agent's notebook. Context files are yours. Drop an `AGENTS.md` in the workspace's root and the agent folds it into its prompt on every run — perfect for conventions, architecture, and "always run `make test` before committing."

```python hl_lines="8"
from pathlib import Path

from pydantic_deep import create_deep_agent, DeepAgentDeps, LocalWorkspace

Path("project/AGENTS.md").write_text(
    "# Project rules\n\n- Use snake_case for Python.\n- Always run `make test` before committing.\n"
)

agent = create_deep_agent(workspace=LocalWorkspace("./project"), context_discovery=True)
result = await agent.run("What's our naming convention?", deps=DeepAgentDeps())
print(result.output)  # -> "snake_case for Python"
```

`context_discovery=True` scans the workspace's root for known convention files and injects whatever it finds. Missing files are skipped silently, so you only create the ones you want.

| File | Purpose | Seen by subagents? |
|------|---------|--------------------|
| `AGENTS.md` | Project instructions, conventions, architecture | Yes |
| `CLAUDE.md` | Claude Code project instructions | Yes |
| `DEEP.md` | pydantic-deep project instructions | Yes |
| `SOUL.md` | Personality, tone, your preferences | No — main agent only |

Prefer to be explicit? Skip discovery and name the paths yourself with `context_files=["/AGENTS.md", "/SOUL.md"]`.

!!! tip "Memory vs. context, in one line"
    If the *agent* should write it, it's memory. If *you* write it, it's a context file. `MEMORY.md` has its own tools and per-agent isolation; it is **not** part of context discovery.

!!! warning "One workspace, one memory — watch multi-user apps"
    Memory and context both live in the workspace. If several users' runs share one workspace, give each its own notebook with `memory_namespace=` — a string, or a function of the run such as `lambda ctx: ctx.deps.user_id` — which files it under `{memory_dir}/{namespace}/{agent_name}/`. The model never sees or chooses the namespace. Giving each user their own workspace isolates their files as well. See [Multi-user](../advanced/multi-user.md).

## Recap

- **Memory** is on by default: the harness `Memory` capability, with `write_memory` / `read_memory` / `search_memory` / `delete_memory` and `MEMORY.md` added to every request — the agent remembers across runs on its own.
- **The workspace is the persistence.** Memory lives at `{memory_dir}/{agent_name}/MEMORY.md`; reuse the workspace and it carries over, swap it and it doesn't.
- **Context files** (`AGENTS.md`, `CLAUDE.md`, `DEEP.md`, `SOUL.md`) are project rules *you* write; `context_discovery=True` finds them, or list them with `context_files=`.
- Rule of thumb: the agent owns memory, you own context files — and `SOUL.md` stays with the main agent only.

Both of these survive a single process. To save, label, and rewind whole conversations, that's next.

- [Sessions & checkpoints →](sessions.md)
