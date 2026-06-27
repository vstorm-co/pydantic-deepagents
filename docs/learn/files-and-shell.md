# Files & the shell

Your agent can already read, write, and edit files — and run shell commands. This page shows how, and how one line decides *where* all that happens.

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
        "Write a Python script greet.py that prints 'hello'. "
        "Then edit it to print 'hello, world'. "
        "Finally run it with `python greet.py` and tell me the output.",
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

The agent writes `greet.py`, edits it in place, runs it with `execute`, and reports back what the command printed. No files landed on your disk — everything lived in memory, because you used `StateBackend`.

!!! example "Check it"
    Add `print(await deps.backend.read("greet.py"))` after the run. The edited
    file is really there — in memory — exactly as the agent left it.

## The built-in tools

You didn't register any of this. `create_deep_agent()` ships a **console toolset** out of the box, so the model can:

- `ls` — list a directory.
- `read_file` — read a file (with optional line `offset`/`limit` for big ones).
- `write_file` — create or overwrite a file.
- `edit_file` — exact-string replacement (`old_string` → `new_string`, `replace_all` optional).
- `glob` — find files by pattern, e.g. `**/*.py`.
- `grep` — search file contents by regex.
- `execute` — run a shell command and capture its output.

That's the same vocabulary you'd reach for in a terminal. The model picks the right tool for each step; you just describe the goal.

!!! note "Long-running commands"
    For commands that don't finish quickly, the agent also has background-shell
    tools (`run_in_background`, `read_output`, `list_shells`, `kill_shell`) so it
    can start a process, keep working, and check on it later.

## Where do the files live?

Every one of those tools goes through the **backend**. The backend is the storage layer — and it's the *only* thing that decides whether a file is in memory, on your disk, or inside a container. Your agent code never changes.

You chose memory with one line:

```python hl_lines="1"
deps = DeepAgentDeps(backend=StateBackend())
```

Swap that line and the *same* agent touches real files:

```python hl_lines="1 3"
from pydantic_deep import LocalBackend

deps = DeepAgentDeps(backend=LocalBackend(root_dir="."))
```

Now `write_file`, `edit_file`, and `execute` operate on your actual working directory. Run the example again and `greet.py` shows up on disk for real.

!!! warning "LocalBackend is real"
    `LocalBackend` reads and writes actual files and runs actual shell commands.
    Point `root_dir` at a directory you're happy for the agent to change, and pass
    `allowed_directories=[...]` or `enable_execute=False` to tighten what it can
    reach.

## The four backends

The same `DeepAgentDeps(backend=…)` slot accepts any of these:

| Backend | Files live… | Runs commands? | Reach for it when… |
|---------|-------------|----------------|--------------------|
| `StateBackend` | in memory | no | testing, demos, leave-no-trace work |
| `LocalBackend` | on disk | yes | building a real tool on real files |
| `DockerSandbox` | in a container | yes (isolated) | running code you don't fully trust |
| `CompositeBackend` | mixed, by path | depends | different paths need different storage |

### Sandbox the shell

When `execute` might run untrusted code, give it a container instead of your machine:

```python
from pydantic_deep import DockerSandbox

sandbox = DockerSandbox(runtime="python-datascience")
try:
    deps = DeepAgentDeps(backend=sandbox)
    result = await agent.run("Run this code and tell me what it prints", deps=deps)
finally:
    sandbox.stop()
```

Same agent, same tools — but every file and every command now lives inside the container.

!!! tip "Mix storage with CompositeBackend"
    Want source files on disk but scratch space in memory? `CompositeBackend`
    routes each path to the right backend by prefix (longest match wins). See
    [Backends](../concepts/backends.md#compositebackend-route-by-path) for the
    full routing story.

## Dissect

Two ideas did all the work:

```python hl_lines="2"
agent = create_deep_agent(model="anthropic:claude-sonnet-4-6")
deps = DeepAgentDeps(backend=StateBackend())
```

- `create_deep_agent()` wires in the console toolset — `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`, `execute` — so the model can touch a filesystem and a shell from the very first call.
- `DeepAgentDeps(backend=…)` decides *where* those operations land. Memory, disk, or a sandbox — the agent code is identical; only this one argument changes.

That separation is the whole point: write your prompt once, then choose how much of the real world it gets to see.

## Recap

- Agents come with file and shell tools built in: `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`, and `execute`.
- The **backend** is the storage layer behind every one of those tools.
- `StateBackend()` keeps everything in memory; `LocalBackend(root_dir=".")` makes the exact same code touch real files.
- `DockerSandbox` runs the shell in an isolated container; `CompositeBackend` mixes backends by path.
- You swap behavior by changing one argument — `DeepAgentDeps(backend=…)` — never the agent.

Next, let's let the agent plan its work before it starts.

- [Planning with todos →](planning.md)
