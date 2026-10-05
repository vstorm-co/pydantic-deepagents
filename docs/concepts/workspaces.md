# Workspaces

When your agent writes a file, where does it actually go? Into its
**workspace**: the environment a run works in. Every file tool — `read_file`,
`write_file`, `edit_file`, `ls`, `grep` — and every command `execute` runs goes
through it, and so do memory, context files, plans, evicted tool output and
uploads. Your agent code doesn't know which one it is: swap the workspace and the
same agent runs in memory, in a directory on disk, or in an isolated container.

Workspaces are part of Pydantic AI (2.52 and later). Inside a tool, the run's
workspace is `ctx.workspace`. pydantic-deep picks one for you and re-exports the
workspace capabilities from
[pydantic-ai-backend](https://vstorm-co.github.io/pydantic-ai-backend/concepts/workspaces/).

!!! info "Full reference"
    This page covers the essentials. For every option, how refs work and how each
    sandbox is isolated, see the
    **[pydantic-ai-backend workspaces docs](https://vstorm-co.github.io/pydantic-ai-backend/concepts/workspaces/)**.

## Which workspace?

| Workspace | Files | Commands | Reach for it when… |
|-----------|-------|----------|--------------------|
| `StateWorkspace()` *(default)* | In memory | No | testing, or anything that must leave no trace |
| `LocalWorkspace(path)` | A directory on this machine | Yes | a CLI tool, or working on real local files |
| `DockerWorkspace(...)` | A container on this host | Yes | running code you don't fully trust |
| `SandboxdWorkspace(...)` | A `sandboxd` session | Yes | containers, without a Docker socket in the agent's process |
| `KubernetesWorkspace(...)` | A pod | Yes | running agents' code on a cluster |
| `DaytonaWorkspace(...)` | A Daytona sandbox | Yes | a hosted sandbox |

Pass one to `create_deep_agent`:

```python
from pydantic_deep import create_deep_agent, LocalWorkspace

agent = create_deep_agent(workspace=LocalWorkspace("./project"))
```

Any Pydantic AI workspace capability works here, including the harness's E2B,
Modal and Sprites workspaces.

!!! tip "The default has no commands"
    `StateWorkspace()` is files only, so the agent gets no `execute` tool unless
    you ask for it with `include_execute=True` — and then every command answers
    that this workspace does not support command execution. Pick a workspace
    that runs commands when the agent needs a shell.

## The workspaces, by example

### StateWorkspace — in memory, zero side effects

```python
from pydantic_deep import create_deep_agent, DeepAgentDeps

agent = create_deep_agent()  # StateWorkspace() by default
result = await agent.run("Write /notes.md with three ideas", deps=DeepAgentDeps())

# The run's workspace outlives the run
print(await result.workspace.read_text("/notes.md"))
```

Each run without history gets a new document. A run that continues a
conversation (`message_history=result.all_messages()`) works in the same one:
the history carries the workspace's ref.

To start from files of your own, fill a `StateBackend` document and hand the run
a backend for it:

```python
from pydantic_ai.workspaces import WorkspaceRef
from pydantic_deep import StateBackend, StateWorkspace

document = StateBackend()
document.write_bytes("/src/app.py", b"print('hello')")
documents = StateWorkspace(store={"demo": document})

result = await agent.run(
    "Review /src/app.py",
    deps=DeepAgentDeps(),
    workspace=documents.backend(WorkspaceRef(provider="state", id="demo")),
)
```

### LocalWorkspace — real files on disk

```python
from pydantic_deep import create_deep_agent, DeepAgentDeps, LocalWorkspace

agent = create_deep_agent(workspace=LocalWorkspace("./workspace"))
result = await agent.run("Create a Python script and run it", deps=DeepAgentDeps())
```

Commands run on your machine, in that directory. `LocalWorkspace(path,
read_only=True)` refuses every write.

### DockerWorkspace — safe code execution

```python
from pydantic_ai.workspaces import WorkspaceRef
from pydantic_deep import create_deep_agent, DeepAgentDeps, DockerWorkspace

docker = DockerWorkspace(runtime="python-datascience", container_name="analysis")
agent = create_deep_agent(workspace=docker)
try:
    result = await agent.run("Analyze data with pandas", deps=DeepAgentDeps())
finally:
    await docker.destroy(WorkspaceRef(provider="docker", id="analysis"))
```

!!! warning "Containers are kept after a run"
    A container is created on first use and **not** removed when the run ends —
    a later run carrying its ref attaches to it again. Remove it with
    `await docker.destroy(ref)`. A `container_name` makes the ref predictable;
    without one, take it from `result.workspace.ref`.

`volumes={"/host/dir": "/workspace"}` mounts a host directory into the
container, so the agent can work on a project in place.

## Per-run workspaces

An application serving many users usually wants one workspace per session rather
than one per agent. Build the agent with `workspace=False` and pass each run its
session's workspace:

```python
from pydantic_ai.workspaces import Workspace

agent = create_deep_agent(workspace=False)

session_workspace = Workspace(
    DockerWorkspace(container_name=f"session-{session_id}").backend()
)
result = await agent.run(prompt, deps=deps, workspace=session_workspace)
```

`agent.run(workspace=...)` also overrides the capability for one run when the
agent has one.

## In your own tools

A tool reaches the workspace through its run context:

```python
from pydantic_ai import RunContext
from pydantic_deep import DeepAgentDeps

async def count_lines(ctx: RunContext[DeepAgentDeps], path: str) -> int:
    """Count the lines in a file."""
    return len((await ctx.workspace.read_text(path)).splitlines())
```

`read_bytes`/`write_bytes`, `read_text`/`write_text`, `list_dir`, `stat`,
`exists`, `make_dir` and `remove` work in every workspace; `run` works in those
that run commands. A missing file raises `FileNotFoundError`, a read-only
workspace raises `PermissionError`.

## Uploads

`deps.upload_file(name, data)` queues a file for the next run. It is written
into the workspace when that run starts — under `uploads/` by default — and the
system prompt tells the agent it is there. See [File uploads](../examples/file-uploads.md).

## Subagents and forks

Subagents work in their parent's workspace. [Forked branches](../advanced/forking.md)
each work in an overlay of it, and the winning branch's changes are written back
on merge.

## Skills can live in a workspace too

`skill_directories` reads skills from the machine the agent is built on.
`WorkspaceSkillsDirectory` discovers them inside the run's workspace instead — a
`skills/` folder in its container, its sandbox session, its document:

```python
from pydantic_deep import WorkspaceSkillsDirectory

agent = create_deep_agent(
    workspace=docker,
    skill_directories=[WorkspaceSkillsDirectory(path="skills")],
)
```

See [Skills in the workspace](skills.md#skills-in-the-workspace).

## Coming from backends

pydantic-deep 0.3.44 and earlier took a `backend` in `DeepAgentDeps`. That
abstraction is gone:

| Before | Now |
|--------|-----|
| `DeepAgentDeps(backend=StateBackend())` | `create_deep_agent()` — `StateWorkspace()` is the default |
| `DeepAgentDeps(backend=LocalBackend(root_dir=p))` | `create_deep_agent(workspace=LocalWorkspace(p))` |
| `DeepAgentDeps(backend=DockerSandbox(...))` | `create_deep_agent(workspace=DockerWorkspace(...))` |
| `CompositeBackend(routes=...)` | no equivalent: one workspace per run |
| `ctx.deps.backend.read(path)` | `await ctx.workspace.read_text(path)` |
| `ctx.deps.backend.write(path, text)` | `await ctx.workspace.write_text(path, text)` |
| `ctx.deps.backend.execute(cmd)` | `await ctx.workspace.run(cmd, shell=True)` |
| `deps.files` / `get_files_summary()` | `await result.workspace.list_dir("/")` |
| `BackendSkillsDirectory(backend=...)` | `WorkspaceSkillsDirectory(path=...)` |
| `sandbox.stop()` | `await capability.destroy(ref)` |

## Recap

- The workspace is *where the run works* — and it's decoupled from your agent code.
- `StateWorkspace` for tests, `LocalWorkspace` for real work, `DockerWorkspace`
  and the other sandboxes for untrusted code.
- Choose it with `create_deep_agent(workspace=...)`, or per run with
  `agent.run(workspace=...)`; read it in tools as `ctx.workspace`.

## Learn more

- **[Workspaces documentation](https://vstorm-co.github.io/pydantic-ai-backend/concepts/workspaces/)** — the full reference
- **[Docker](https://vstorm-co.github.io/pydantic-ai-backend/concepts/docker/)** — containers, runtimes and isolation
- **[Console toolset](https://vstorm-co.github.io/pydantic-ai-backend/concepts/console-toolset/)** — the file and shell tools
