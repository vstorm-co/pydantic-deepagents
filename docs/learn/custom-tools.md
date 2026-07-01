# Custom tools

Your agent already has files, a shell, planning, and web search. Now let's give it something only *you* can provide: a tool that talks to your own code, your own data, your own APIs.

There's almost nothing to learn. Any `async` function with type hints becomes a tool. Its docstring is the description the model reads, its type hints are the schema the model fills in, and your typed `DeepAgentDeps` is handed to it automatically.

```python
import asyncio

from pydantic_ai import RunContext

from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend


async def get_weather(ctx: RunContext[DeepAgentDeps], city: str) -> str:
    """Get the current weather for a city.

    Args:
        city: The city to look up, e.g. "Paris".
    """
    # Pretend this calls a real weather API.
    return f"It's 21°C and sunny in {city}."


async def main():
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        instructions="You are a helpful assistant.",
        tools=[get_weather],
    )

    deps = DeepAgentDeps(backend=StateBackend())

    result = await agent.run(
        "What's the weather in Paris? Then save it to weather.txt.",
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

The agent calls your `get_weather` tool with `city="Paris"`, gets your made-up forecast back, and then reaches for the *built-in* `write` tool to drop it into `weather.txt`. Your one function and the whole toolbox, working together — and you wrote none of the JSON schema, none of the dispatch, none of the glue.

!!! example "Check it"
    Add `print(await deps.backend.read("weather.txt"))` after the run. Your
    tool's output really made it into the file — because the model chained your
    custom tool into the built-in one on its own.

## Dissect it

Let's look at the function one piece at a time. This is the entire contract for a tool.

```python hl_lines="1 2 6"
async def get_weather(ctx: RunContext[DeepAgentDeps], city: str) -> str:
    """Get the current weather for a city.

    Args:
        city: The city to look up, e.g. "Paris".
    """
    return f"It's 21°C and sunny in {city}."
```

### `ctx.deps` is your typed dependencies

The first parameter, `ctx: RunContext[DeepAgentDeps]`, is how Pydantic AI hands your tool the run's context. The model never sees it — it's injected for you, and it's fully typed.

`ctx.deps` is the same `DeepAgentDeps` you passed to `agent.run()`. So your tool can read and write through the agent's backend, inspect its todos, and reach anything else you stashed on deps:

```python
async def save_report(ctx: RunContext[DeepAgentDeps], text: str) -> str:
    """Save a report to /reports/latest.md."""
    await ctx.deps.backend.write("/reports/latest.md", text)
    return "Saved."
```

Because `DeepAgentDeps` is typed, your editor autocompletes `ctx.deps.backend` and the type checker catches a typo before you ever run the agent.

### The docstring is the description

The model decides *whether* and *when* to call your tool based on its name and its docstring — nothing else. A vague docstring means a tool the model misuses or ignores; a clear one means it gets called at the right moment. Treat the docstring as a prompt, because that's exactly what it is.

The `Args:` section isn't decoration either. Each line documents one parameter and is shown to the model alongside the schema.

### The type hints are the schema

`city: str` tells the model this tool takes one required string argument called `city`. Pydantic AI turns your signature into a JSON schema automatically — so the model always sends well-formed, validated arguments. Optional parameters work the way you'd expect:

```python
async def get_weather(
    ctx: RunContext[DeepAgentDeps],
    city: str,
    units: str = "celsius",
) -> str:
    """Get the current weather for a city."""
    ...
```

`units` now has a default, so the model can leave it out. Rich types work too — a Pydantic `BaseModel` parameter or return type is schema'd and validated just the same.

!!! tip "`tools=` adds, it doesn't replace"
    Passing `tools=[get_weather]` *adds* your tool on top of everything
    `create_deep_agent()` already wires up — files, shell, planning, web search,
    sub-agents. You're extending the toolbox, never swapping it out.

!!! note "Sync functions are fine"
    Tools don't have to be `async`. A plain `def get_version(ctx) -> str` works
    too — use `async def` only when you actually `await` something (an HTTP call,
    a database query, the backend).

!!! warning "Return errors, don't raise them"
    When something goes wrong, return a helpful string the model can read and
    recover from — `return f"No city named {city!r}."` — rather than raising. An
    unhandled exception aborts the run; a returned message lets the agent try
    again.

## Recap

Adding a tool is just writing a function:

- Any `async` (or sync) function with type hints becomes a tool via `tools=[...]`.
- The first parameter `ctx: RunContext[DeepAgentDeps]` is injected for you; `ctx.deps` is your typed dependencies, including `ctx.deps.backend`.
- The **docstring** is the description the model reads; the **type hints** are the schema it fills in.
- `tools=` *extends* the built-in toolset — it never replaces it.
- Return errors as strings so the agent can recover.

When a few tools belong together — sharing setup, a prefix, or a common purpose — group them into a toolset instead of a loose list. See [Toolsets](../api/toolsets.md) for that.

Next, let's package reusable know-how the agent can load on demand.

- [Skills →](skills.md)
