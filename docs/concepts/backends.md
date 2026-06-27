# Backends

When your agent writes a file, where does it actually go? That's the backend's
job. A **backend** is the storage layer behind every file tool — `read`,
`write`, `edit`, `ls`, `grep`. Crucially, your agent code doesn't know or care
which one you use: swap the backend and the same agent runs against memory, real
disk, or an isolated Docker container.

pydantic-deep uses the backends from [pydantic-ai-backend](https://vstorm-co.github.io/pydantic-ai-backend/).

!!! info "Full reference"
    This page covers the essentials. For every method and option, see the
    **[pydantic-ai-backend docs](https://vstorm-co.github.io/pydantic-ai-backend/concepts/backends/)**.

## Which backend?

Four cover almost everything:

| Backend | Persistence | Execution | Reach for it when… |
|---------|-------------|-----------|--------------------|
| `LocalBackend` | Persistent | Yes | building a CLI tool or working on real local files |
| `StateBackend` | Ephemeral | No | testing, or anything that must leave no trace |
| `DockerSandbox` | Ephemeral | Yes | running code you don't fully trust |
| `CompositeBackend` | Mixed | Depends | different paths need different backends |

!!! tip "Start with StateBackend"
    When you're trying things out, `StateBackend()` keeps everything in memory —
    no files on disk, nothing to clean up. Switch to `LocalBackend` once you want
    the work to persist. Your agent code stays exactly the same.

## The four, by example

### LocalBackend — real files on disk

```python
from pydantic_deep import create_deep_agent, DeepAgentDeps, LocalBackend

backend = LocalBackend(root_dir="./workspace")
deps = DeepAgentDeps(backend=backend)

agent = create_deep_agent()
result = await agent.run("Create a Python script", deps=deps)
```

### StateBackend — in memory, zero side effects

```python
from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend

backend = StateBackend()
deps = DeepAgentDeps(backend=backend)

# Files live in memory only — perfect for tests.
backend.write("/src/app.py", "print('hello')")
```

### DockerSandbox — safe code execution

```python
from pydantic_deep import create_deep_agent, DeepAgentDeps, DockerSandbox

sandbox = DockerSandbox(runtime="python-datascience")
try:
    deps = DeepAgentDeps(backend=sandbox)
    agent = create_deep_agent()
    result = await agent.run("Analyze data with pandas", deps=deps)
finally:
    sandbox.stop()
```

!!! warning "Always stop the sandbox"
    `DockerSandbox` holds a real container. Wrap it in `try/finally` (or an
    `async with`) so the container is torn down even if the run raises.

### CompositeBackend — route by path

Sometimes one backend isn't enough: you want source files on real disk, scratch
space in memory, and untrusted code in a sandbox — all in the same run.
`CompositeBackend` routes each path to the right place:

```python
from pydantic_deep import CompositeBackend, StateBackend, LocalBackend, DockerSandbox

backend = CompositeBackend(
    default=StateBackend(),
    routes={
        "/project/": LocalBackend(root_dir="/my/project"),
        "/sandbox/": DockerSandbox(runtime="python-minimal"),
    },
)
```

The rules are simple:

1. Paths match by prefix — the **longest** match wins.
2. Operations forward to the matched backend.
3. Anything unmatched falls through to `default`.

```python
backend = CompositeBackend(
    default=StateBackend(),  # /tmp, /cache, …
    routes={
        "/src/": LocalBackend(root_dir="./src"),
        "/data/": LocalBackend(root_dir="./data"),
        "/output/": StateBackend(),
    },
)

backend.write("/src/app.py", "print('hello')")   # → LocalBackend("./src")
content = backend.read("/data/input.csv")          # → LocalBackend("./data")
backend.write("/tmp/cache.json", "{}")             # → default StateBackend
backend.write("/output/result.txt", "done")        # → StateBackend (explicit route)
```

Common shapes:

| Goal | Configuration |
|------|---------------|
| Read-only source + writable output | `routes={"/src/": LocalBackend()}`, `default=StateBackend()` |
| Multiple project directories | several `LocalBackend` routes |
| Safe execution beside local files | `routes={"/code/": DockerSandbox()}`, `default=LocalBackend()` |
| Testing with fixtures | `routes={"/fixtures/": LocalBackend("./test/fixtures")}` |

!!! note "Routes strip their prefix"
    A route forwards the path *without* its prefix. So with
    `routes={"/project/": LocalBackend(root_dir="/home/user/myproject")}`, a write
    to `/project/src/main.py` reaches `LocalBackend` as `/src/main.py` — landing at
    `/home/user/myproject/src/main.py`.

## Skills can live in a backend too

Backends also back the [skills system](skills.md#skills-with-backends). Point
`BackendSkillsDirectory` at any backend to discover skills stored *inside* it
(a `StateBackend`, a `DockerSandbox`, …) rather than on the local filesystem:

```python
from pydantic_deep.features.skills.backend import BackendSkillsDirectory

agent = create_deep_agent(
    skill_directories=[BackendSkillsDirectory(backend=sandbox, path="/skills")],
    backend=sandbox,
)
```

See [Skills with Backends](skills.md#skills-with-backends) for the full story.

## Recap

- A backend is *where files live* — and it's decoupled from your agent code.
- `StateBackend` for tests, `LocalBackend` for real work, `DockerSandbox` for
  untrusted code, `CompositeBackend` to mix them by path.
- Swapping backends never changes the agent — only `DeepAgentDeps(backend=…)`.

## Learn more

- **[Backends documentation](https://vstorm-co.github.io/pydantic-ai-backend/concepts/backends/)** — the full reference
- **[Docker Sandbox](https://vstorm-co.github.io/pydantic-ai-backend/concepts/docker/)** — execution environments
- **[Console toolset](https://vstorm-co.github.io/pydantic-ai-backend/concepts/console-toolset/)** — the file-operation tools
