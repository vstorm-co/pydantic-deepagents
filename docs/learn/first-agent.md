# Your first agent

Let's start with the smallest thing that works: an agent that can think and act.

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
        "Write a Python function that returns the nth Fibonacci number, "
        "save it to fib.py, then read it back to me.",
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

The agent plans the task, writes `fib.py`, reads it back, and replies with a summary — using a filesystem, a shell, and a todo list it had from the very first line. You wrote none of that plumbing.

!!! example "Check it"
    Add `print(await deps.backend.read("fib.py"))` after the run. The file the
    agent created is really there — in memory, because you used `StateBackend`.

## Step by step

Let's look at the same code one piece at a time.

### Step 1: import

```python
from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend
```

Three names cover the basics:

- `create_deep_agent` — the one factory that builds a fully-equipped agent.
- `DeepAgentDeps` — the per-run dependencies (where files live, what's shared).
- `StateBackend` — an in-memory filesystem, perfect for trying things out.

### Step 2: create the agent

```python hl_lines="2 3"
agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    instructions="You are a helpful coding assistant.",
)
```

`create_deep_agent()` returns a Pydantic AI [`Agent`](https://ai.pydantic.dev/), already wired with a filesystem, shell, planning, web search, sub-agents, and automatic context management. You only had to say *which model* and *who it is*.

!!! note "Any model works"
    `model=` takes any model string Pydantic AI understands — `anthropic:…`,
    `openai:…`, `google-gla:…`, `openrouter:…`, and more. Swap the string,
    keep the code.

### Step 3: choose where state lives

```python
deps = DeepAgentDeps(backend=StateBackend())
```

The *backend* decides where the agent's files actually go. `StateBackend` keeps them in memory; swap in `LocalBackend(root_dir="…")` and the exact same agent writes to real files on disk, or a `DockerSandbox` to run inside a container. Your code doesn't change — only the backend does. More on that in [Files & the shell](files-and-shell.md).

### Step 4: run it

```python
result = await agent.run("…your prompt…", deps=deps)
print(result.output)
```

`agent.run()` is `async` — `await` it. It returns an `AgentRunResult`; `result.output` is the model's final answer (a `str` here, or your own type once you add [structured output](structured-output.md)).

!!! tip "Already streaming under the hood"
    A single `agent.run()` may take many internal steps — plan, write, read,
    summarize. You get the final result here; to watch it happen live, see
    [Streaming](streaming.md).

## Recap

You just built a working agent:

- `create_deep_agent()` gives a model real capabilities with sensible defaults — files, shell, planning, web, sub-agents.
- `DeepAgentDeps` + a backend decide *where* state lives; the same code runs in memory, on disk, or in a sandbox.
- `agent.run(prompt, deps=deps)` is one awaited call; `result.output` is the answer.

Next, let's give the agent real files to work with.

- [Files & the shell →](files-and-shell.md)
