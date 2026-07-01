<h1 align="center">Pydantic Deep Agents</h1>
<p align="center">
  <em>Build autonomous AI assistants in Python — file access, web search, memory, multi-agent teams, and unlimited context, out of the box.</em>
</p>
<p align="center">
  <a href="https://github.com/vstorm-co/pydantic-deepagents/actions/workflows/ci.yml"><img src="https://github.com/vstorm-co/pydantic-deepagents/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://codecov.io/gh/vstorm-co/pydantic-deepagents"><img src="https://img.shields.io/badge/coverage-100%25-brightgreen" alt="Coverage"></a>
  <a href="https://pypi.org/project/pydantic-deep/"><img src="https://img.shields.io/pypi/v/pydantic-deep.svg" alt="PyPI"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue" alt="Python"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/license-MIT-green" alt="License"></a>
  <a href="https://www.bestpractices.dev/projects/12495"><img src="https://www.bestpractices.dev/projects/12495/badge" alt="OpenSSF Best Practices"></a>
</p>

---

A language model can answer questions. It *can't* read your files, run code, search the web, remember things between sessions, or work on several tasks at once.

**Pydantic Deep Agents gives it all of that.** You call `create_deep_agent()` once, and the model gains a filesystem, a shell, web search and browsing, persistent memory, parallel sub-agents, and automatic handling of conversations longer than the context window. You describe *what* the agent should do — the library handles the *how*.

It's built on [Pydantic AI](https://ai.pydantic.dev/), so it speaks the language you already know: **type hints, `async`/`await`, and plain Python**. It works with Claude, GPT, Gemini, and any other model Pydantic AI supports.

!!! tip "Think of it as a foundation"
    Pydantic Deep Agents is the open-source, self-hosted base for building your own
    [Claude Code](https://claude.ai/code), [Manus](https://manus.im/), or
    [Devin](https://devin.ai/)-style assistant — without rebuilding the plumbing every time.

## The key features

- **Batteries included.** Filesystem, shell, web, memory, planning, and sub-agents are one keyword argument away — not a weekend of glue code.
- **Typed end to end.** Strict Pyright + MyPy, 100% test coverage. If it type-checks, it tends to just work.
- **Modular.** Use the whole framework, or cherry-pick a single package. Each capability is independently installable.
- **Safe by default.** Docker sandboxing, per-tool approval gates, and human-in-the-loop workflows for anything risky.
- **Unlimited context.** Long conversations are summarized and large tool outputs are evicted to files automatically — the agent keeps going.

## Your first agent

Let's start with the smallest thing that works. An agent that can think, and write code:

```python hl_lines="6 7 8 9"
import asyncio
from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend


async def main():
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        instructions="You are a helpful coding assistant.",
    )

    # StateBackend keeps files in memory — perfect for trying things out.
    deps = DeepAgentDeps(backend=StateBackend())

    result = await agent.run(
        "Create a Python function that calculates Fibonacci numbers",
        deps=deps,
    )
    print(result.output)


asyncio.run(main())
```

That's it. The agent already has a filesystem, planning, web search, and more — all enabled by default.

!!! note "Where did the file go?"
    The agent wrote to `deps.backend`. With `StateBackend` it lives in memory; swap in
    `LocalBackend(root_dir="…")` and the very same code writes to real files on disk.
    Your code doesn't change — only the backend does. More on that in
    [Backends](concepts/backends.md).

## Adding your own tools

Your agent isn't limited to the built-in tools. Any `async` function with type hints becomes a tool — and it gets the agent's dependencies injected for free:

```python hl_lines="5 6 7 8 9"
from pydantic_ai import RunContext
from pydantic_deep import create_deep_agent, DeepAgentDeps


async def get_weather(ctx: RunContext[DeepAgentDeps], city: str) -> str:
    """Get the weather for a city."""
    # Everything in deps is available via ctx.deps.
    return f"Weather in {city}: Sunny, 22°C"


agent = create_deep_agent(
    tools=[get_weather],
    instructions="You can check the weather and work with files.",
)
```

The docstring becomes the tool's description, the type hints become its schema, and `ctx.deps` is your typed `DeepAgentDeps`. No decorators to learn, no registry to maintain.

## What you get out of the box

| Capability | What it does |
|------------|--------------|
| **Planning** | A built-in todo list for breaking work down and tracking progress |
| **Filesystem** | Read, write, and edit files, with `grep` and `glob` |
| **Sub-agents** | Delegate focused tasks to isolated specialists |
| **Skills** | Modular capability packages, loaded on demand |
| **Backends** | `StateBackend`, `LocalBackend`, `DockerSandbox`, `CompositeBackend` |
| **Context management** | Automatic summarization so long conversations never overflow |

## A modular ecosystem

Pydantic Deep Agents is assembled from standalone packages. Need just one piece? Take just one piece:

| Package | What it gives you |
|---------|-------------------|
| [pydantic-ai-backend](https://github.com/vstorm-co/pydantic-ai-backend) | File storage, Docker sandbox, permission controls |
| [pydantic-ai-todo](https://github.com/vstorm-co/pydantic-ai-todo) | Task planning with PostgreSQL and event streaming |
| [subagents-pydantic-ai](https://github.com/vstorm-co/subagents-pydantic-ai) | Multi-agent orchestration |
| [summarization-pydantic-ai](https://github.com/vstorm-co/summarization-pydantic-ai) | Context-management processors |

## Installation

```bash
pip install pydantic-deep
```

Want isolated code execution in a container? Add the sandbox extra:

```bash
pip install "pydantic-deep[sandbox]"
```

!!! info "For LLMs and agents"
    The docs follow the [llms.txt](https://llmstxt.org/) standard — point any tool at
    `/llms.txt` for an LLM-optimized version of this site.

## Recap

You just saw the whole idea:

1. `create_deep_agent()` gives a model real capabilities — files, web, memory, sub-agents — with sensible defaults.
2. `DeepAgentDeps` + a backend decide *where* state lives; the same code runs in memory, on disk, or in a sandbox.
3. Your own `async` functions become typed tools with dependency injection, no boilerplate.

Ready to go deeper?

- [Installation](installation.md) — get set up in a couple of minutes
- [Core Concepts](concepts/index.md) — agents, backends, toolsets, and skills
- [Examples](examples/index.md) — pydantic-deep in real scenarios
- [API Reference](api/index.md) — every class and function
- [Getting Help](getting-help.md) — report a bug or ask a question
- [Contributing](contributing.md) — help make it better
