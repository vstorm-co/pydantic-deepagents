# Files & the shell

Your agent can already read, write, and edit files — and run shell commands. This page shows how, and how one argument decides *where* all that happens.

```python
import asyncio

from pydantic_deep import create_deep_agent, DeepAgentDeps, LocalWorkspace


async def main():
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        instructions="You are a helpful coding assistant.",
        workspace=LocalWorkspace("./playground"),
    )

    result = await agent.run(
        "Write a Python script greet.py that prints 'hello'. "
        "Then edit it to print 'hello, world'. "
        "Finally run it with `python greet.py` and tell me the output.",
        deps=DeepAgentDeps(),
    )
    print(result.output)


asyncio.run(main())
```

## Run it

Save it to `main.py`, create the `playground` folder, and run:

<div class="termy">

```console
$ mkdir playground
$ python main.py
```

</div>

The agent writes `greet.py`, edits it in place, runs it with `execute`, and reports back what the command printed. Look in `playground/` — the file is really there, exactly as the agent left it.

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

## Where do the files live?

Every one of those tools goes through the run's **workspace**. The workspace is the environment the run works in — and it's the *only* thing that decides whether a file is in memory, on your disk, or inside a container. Your agent code never changes.

You chose a directory on disk with one argument:

```python hl_lines="3"
agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    workspace=LocalWorkspace("./playground"),
)
```

Leave it out and the *same* agent works in memory instead:

```python
agent = create_deep_agent(model="anthropic:claude-sonnet-4-6")  # StateWorkspace()
result = await agent.run("Write greet.py that prints 'hello'", deps=DeepAgentDeps())

print(await result.workspace.read_text("greet.py"))
```

Nothing lands on your disk — and since memory has nowhere to run a command, the agent gets no `execute` tool. That's the right default for tests and demos.

!!! warning "LocalWorkspace is real"
    `LocalWorkspace` reads and writes actual files and runs actual shell commands
    on your machine. Point it at a directory you're happy for the agent to
    change; `LocalWorkspace(path, read_only=True)` refuses every write.

## Choosing a workspace

The same `workspace=` argument accepts any of these:

| Workspace | Files live… | Runs commands? | Reach for it when… |
|-----------|-------------|----------------|--------------------|
| `StateWorkspace()` *(default)* | in memory | no | testing, demos, leave-no-trace work |
| `LocalWorkspace(path)` | on disk | yes | building a real tool on real files |
| `DockerWorkspace(...)` | in a container | yes (isolated) | running code you don't fully trust |
| `SandboxdWorkspace`, `KubernetesWorkspace`, `DaytonaWorkspace` | in a remote sandbox | yes (isolated) | running agents' code away from the agent's process |

### Sandbox the shell

When `execute` might run untrusted code, give it a container instead of your machine:

```python
from pydantic_ai.workspaces import WorkspaceRef
from pydantic_deep import DockerWorkspace

docker = DockerWorkspace(runtime="python-datascience", container_name="greet")
agent = create_deep_agent(workspace=docker)
try:
    result = await agent.run("Run this code and tell me what it prints", deps=DeepAgentDeps())
finally:
    await docker.destroy(WorkspaceRef(provider="docker", id="greet"))
```

Same agent, same tools — but every file and every command now lives inside the container. The container outlives the run until you `destroy` it; see [Workspaces](../concepts/workspaces.md) for why.

## Dissect

Two ideas did all the work:

```python hl_lines="3"
agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    workspace=LocalWorkspace("./playground"),
)
```

- `create_deep_agent()` wires in the console toolset — `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`, `execute` — so the model can touch a filesystem and a shell from the very first call.
- `workspace=` decides *where* those operations land. Memory, disk, or a sandbox — the agent code is identical; only this one argument changes.

That separation is the whole point: write your prompt once, then choose how much of the real world it gets to see.

## Recap

- Agents come with file and shell tools built in: `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`, and `execute`.
- The **workspace** is the environment behind every one of those tools.
- The default `StateWorkspace()` keeps everything in memory, without commands; `LocalWorkspace(".")` makes the exact same code touch real files and run real commands.
- `DockerWorkspace` and the other sandboxes run the shell in isolation.
- You swap behavior by changing one argument — `workspace=…` — never the prompt or the tools.

Next, let's let the agent plan its work before it starts.

- [Planning with todos →](planning.md)
