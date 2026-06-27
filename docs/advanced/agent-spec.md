# Agent Spec (declarative)

So far you've built agents in Python, passing keyword arguments to `create_deep_agent()`. Sometimes you'd rather keep that configuration in a *file* — to version it in git, share it across a team, or let a non-developer tweak the model without touching code.

That's what an **agent spec** is: a YAML or JSON file that describes an agent declaratively. You load it with one call and get back the same agent you'd have built by hand.

## The smallest spec that works

Create a file called `agent.yaml`:

```yaml
model: anthropic:claude-sonnet-4-6
instructions: You are a helpful coding assistant.
```

Load it in Python:

```python
import asyncio

from pydantic_deep import DeepAgent


async def main():
    agent, deps = DeepAgent.from_file("agent.yaml")
    result = await agent.run("Create a Python script that prints the time.", deps=deps)
    print(result.output)


asyncio.run(main())
```

## Run it

<div class="termy">

```console
$ python main.py
```

</div>

You get the exact same agent as `create_deep_agent(model="anthropic:claude-sonnet-4-6", instructions="…")` — files, shell, planning, web search, sub-agents, memory, all the defaults. The only difference is *where* the configuration lives.

!!! note "Defaults come for free"
    Your spec only listed two keys, but the agent has every default capability
    enabled. The spec is layered *on top of* the same defaults as
    [`create_deep_agent()`][pydantic_deep.agent.create_deep_agent] — you only
    write down what you want to change.

## Step by step

### Step 1: write the spec

```yaml
model: anthropic:claude-sonnet-4-6
instructions: You are a helpful coding assistant.
```

Every key here maps 1:1 to a `create_deep_agent()` parameter. `model:` is `model=`, `instructions:` is `instructions=`. If you know one, you know the other.

### Step 2: load it

```python hl_lines="1"
agent, deps = DeepAgent.from_file("agent.yaml")
```

`DeepAgent.from_file()` reads the file, validates it, and hands you back a `(agent, deps)` tuple — already wired and ready to run. The file extension picks the parser: `.yaml`/`.yml` for YAML, `.json` for JSON.

### Step 3: run it

```python
result = await agent.run("…your prompt…", deps=deps)
```

From here it's an ordinary agent. `deps` comes pre-built with an in-memory `StateBackend`, so the spec runs with zero extra setup — see [Files & the shell](../learn/files-and-shell.md) to point it at real disk instead.

## Turning on more features

Adding a capability is just adding a key. Here's a richer spec:

```yaml hl_lines="3 4 5 6 7"
model: anthropic:claude-sonnet-4-6
instructions: You are a helpful coding assistant.
include_memory: true
memory_dir: .pydantic-deep
include_checkpoints: true
retries: 3
model_settings:
  temperature: 0.7
```

Each key is the same flag you'd pass in Python. The full set mirrors `create_deep_agent()`, including `include_todo`, `include_filesystem`, `include_subagents`, `include_skills`, `include_plan`, `web_search`, `web_fetch`, `thinking`, `context_manager`, `cost_tracking`, and more.

!!! tip "Sub-agents in YAML too"
    You can declare sub-agents inline — each one is just a small mapping:

    ```yaml
    subagents:
      - name: researcher
        description: Research assistant
        instructions: You research topics thoroughly.
        model: anthropic:claude-haiku-4-5-20251001
    ```

## Serializable vs. runtime params

A spec file can only hold things a file can hold: strings, numbers, booleans, lists, and mappings. Live Python objects and callbacks can't be written to YAML — so you pass *those* as keyword overrides when you load.

```python hl_lines="5 6"
from pydantic_ai_backends import LocalBackend

agent, deps = DeepAgent.from_file(
    "agent.yaml",
    backend=LocalBackend(root_dir="/workspace"),
    on_cost_update=my_cost_callback,
)
```

Overrides take precedence over the file, and they're the *only* way to supply non-serializable params:

| In the spec file (serializable) | As a keyword override (runtime) |
|---|---|
| `model`, `instructions`, `retries` | `backend` |
| `include_*` feature flags | `tools`, `toolsets` |
| `model_settings`, `thinking` | `hooks`, `middleware`, `history_processors` |
| `subagents`, `skill_directories` | `output_type`, `checkpoint_store` |
| `memory_dir`, `context_files` | `on_cost_update`, `on_context_update`, `on_eviction`, `on_before_compress`, `on_after_compress` |

!!! info "Backend defaults to in-memory"
    If you don't pass `backend=`, the loaded `deps` uses a `StateBackend` so the
    agent runs out of the box. Pass a `LocalBackend` or `DockerSandbox` override
    the moment you want files to land somewhere real.

## Loading from a dict

If your config already lives in Python — say it came from a database or an HTTP request — skip the file and use `from_spec()` directly:

```python
agent, deps = DeepAgent.from_spec(
    {
        "model": "anthropic:claude-sonnet-4-6",
        "include_memory": True,
        "memory_dir": ".pydantic-deep",
    },
    backend=LocalBackend(root_dir="/workspace"),
)
```

`from_file()` is just `from_spec()` with a file read in front of it — same rules, same overrides.

## Saving a spec

Going the other way, `DeepAgent.to_file()` writes a config out. Only **non-default** values are saved, so the file stays small and readable — it records your *changes*, not the whole surface area.

```python
DeepAgent.to_file(
    "agent.yaml",
    model="anthropic:claude-sonnet-4-6",
    include_memory=True,
    memory_dir=".pydantic-deep",
)
```

Non-serializable params handed to `to_file()` are silently dropped — they can't round-trip through a file, so they don't belong in one.

## JSON works too

Everything above works identically in JSON; the extension decides the format.

```json
{
  "model": "anthropic:claude-sonnet-4-6",
  "include_memory": true,
  "memory_dir": ".pydantic-deep",
  "model_settings": {
    "temperature": 0.7
  }
}
```

```python
agent, deps = DeepAgent.from_file("agent.json")
```

!!! warning "YAML needs PyYAML"
    YAML support is an optional extra. If you see an `ImportError`, install it
    with `pip install 'pydantic-deep[yaml]'`. JSON has no extra dependency.

## Recap

You can now define agents without writing Python:

- An **agent spec** is a YAML or JSON file whose keys map 1:1 to
  [`create_deep_agent()`][pydantic_deep.agent.create_deep_agent] parameters.
- `DeepAgent.from_file()` (or `from_spec()` for a dict) returns a ready
  `(agent, deps)` tuple, layered on the same defaults as the factory.
- **Serializable** params (models, flags, `model_settings`, `subagents`) live in
  the file; **runtime** params (`backend`, `tools`, callbacks, `output_type`)
  are passed as keyword overrides — and overrides win.
- `DeepAgent.to_file()` writes a minimal spec containing only your non-default
  values.

Next, run the same agent for many users at once.

- [Multi-user / multi-tenant →](multi-user.md)
