# Sessions & checkpoints

So far every `agent.run()` has started from scratch. Real assistants remember: you ask a follow-up and the agent already knows what "it" refers to. And sometimes the agent goes down a wrong path and you want an undo button.

Two ideas cover both. **Sessions** continue a conversation across runs by feeding the previous messages back in. **Checkpoints** snapshot that conversation so you (or the agent) can rewind to a known-good state.

## Continue a conversation

Let's make the agent remember. The trick is one argument: `message_history`.

```python hl_lines="14 19 22 24"
import asyncio

from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend


async def main():
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        instructions="You are a helpful assistant.",
    )
    deps = DeepAgentDeps(backend=StateBackend())

    # First turn — no history yet.
    first = await agent.run("My favorite language is Python.", deps=deps)
    print(first.output)

    # Second turn — pass the messages from the first run back in.
    second = await agent.run(
        "What did I just tell you?",
        deps=deps,
        message_history=first.all_messages(),
    )
    print(second.output)


asyncio.run(main())
```

### Run it

Save it to `main.py` and run:

<div class="termy">

```console
$ python main.py
```

</div>

The first reply acknowledges your favorite language. The second reply says *Python* — because the agent saw the whole first exchange. Without `message_history` it would have no idea.

### Dissect it

Two lines do the work:

- `first.all_messages()` returns the complete message history of a run — your prompt, the model's reply, every tool call in between.
- `message_history=...` on the next `agent.run()` prepends those messages, so the model continues the same conversation.

That's a *session*: keep the latest `all_messages()` around and pass it to the next run. To persist a session across process restarts, save those messages — pydantic-ai's `ModelMessagesTypeAdapter` serializes them to JSON, and the [`FileCheckpointStore`](#persist-to-disk) below uses exactly that.

!!! tip "Keep deps too"
    Reuse the same `DeepAgentDeps` across turns so the agent keeps its
    backend — the files it wrote in turn one are still there in turn two.

## Snapshot with checkpoints

A session grows in one direction. Checkpoints let you go *back*. Turn them on with `include_checkpoints=True`:

```python hl_lines="3"
agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    include_checkpoints=True,
)
```

That gives the agent three new tools — and an in-memory store to hold the snapshots:

| Tool | What it does |
|------|--------------|
| `save_checkpoint` | Label the most recent snapshot (e.g. `"before-refactor"`) |
| `list_checkpoints` | Show every saved checkpoint with its label and turn |
| `rewind_to` | Rewind the conversation to a checkpoint |

By default a checkpoint is auto-saved after every tool call, so there's always something to rewind to. Set `checkpoint_frequency="every_turn"` or `"manual_only"` to change that.

## Rewind to a checkpoint

Rewinding is different from the other tools: it can't just return a value, because the conversation it needs to change is the one currently running. Instead, `rewind_to` raises [`RewindRequested`][pydantic_deep.features.checkpointing.RewindRequested], which propagates out of `agent.run()`. **You** catch it and restore the history.

```python hl_lines="20 21 22"
import asyncio

from pydantic_deep import (
    create_deep_agent,
    DeepAgentDeps,
    StateBackend,
    RewindRequested,
)


async def main():
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        include_checkpoints=True,
    )
    deps = DeepAgentDeps(backend=StateBackend())
    history = []

    while True:
        try:
            prompt = input("> ")
        except EOFError:
            break
        try:
            result = await agent.run(prompt, deps=deps, message_history=history)
            history = result.all_messages()
            print(result.output)
        except RewindRequested as exc:
            print(f"Rewound to '{exc.label}'.")
            history = exc.messages


asyncio.run(main())
```

### Run it

<div class="termy">

```console
$ python main.py
> Save a checkpoint called "start", then create notes.txt.
...
> Now delete notes.txt. Actually, rewind to "start".
Rewound to 'start'.
```

</div>

Ask the agent to save a checkpoint, do some work, then tell it to rewind. The `rewind_to` tool fires, `RewindRequested` breaks out of the run, and your loop swaps `history` for `exc.messages` — the conversation is back where it was. The agent forgets everything after the checkpoint.

### Dissect it

- The agent decides *when* to checkpoint and rewind; you just gave it the tools.
- `RewindRequested` carries `.label` (which checkpoint) and `.messages` (the restored history). Catching it and reassigning `history` is the whole integration.
- Because the loop owns `history`, the rewind sticks: the next turn starts from the restored snapshot.

!!! note "Why an exception, not a return value"
    pydantic-ai only intercepts `ModelRetry` and `UnexpectedModelBehavior`;
    every other exception flows straight to your caller. `RewindRequested`
    rides that path out so your run loop — the only code that owns the
    history — can act on it.

## Persist to disk

`InMemoryCheckpointStore` is the default and vanishes when the process exits. For checkpoints that survive restarts, pass a [`FileCheckpointStore`][pydantic_deep.features.checkpointing.FileCheckpointStore]:

```python hl_lines="4"
from pydantic_deep import create_deep_agent, FileCheckpointStore

agent = create_deep_agent(
    include_checkpoints=True,
    checkpoint_store=FileCheckpointStore("/path/to/checkpoints"),
)
```

Each checkpoint becomes one JSON file. Need a different store — Redis, a database — implement the [`CheckpointStore`][pydantic_deep.features.checkpointing.CheckpointStore] protocol and pass it the same way.

!!! warning "One store per user"
    In a multi-user app, give each session its own store
    (`checkpoint_store=` on `DeepAgentDeps` works at runtime). A shared
    `InMemoryCheckpointStore` means every user sees everyone's checkpoints.

## Fork instead of rewind

Rewinding rewrites the current session. To branch off a checkpoint *without* touching the original — try a different approach in parallel — use [`fork_from_checkpoint`][pydantic_deep.features.checkpointing.fork_from_checkpoint]:

```python
from pydantic_deep import fork_from_checkpoint

messages = await fork_from_checkpoint(store, checkpoint_id="abc123")
branch = await agent.run("Try a different approach", deps=deps, message_history=messages)
```

It returns the checkpoint's messages; feed them to a fresh run as `message_history` and you have a new session that shares a past with the old one. For more on checkpoint internals and stores, see the [Checkpointing reference](../learn/sessions.md).

## Recap

- A **session** is just `message_history=result.all_messages()` carried into the next `agent.run()` — that's how the agent remembers across runs.
- `include_checkpoints=True` gives the agent `save_checkpoint`, `list_checkpoints`, and `rewind_to`, auto-saving after each tool call by default.
- `rewind_to` raises `RewindRequested`; catch it in your run loop and restore `history = exc.messages`.
- Swap `InMemoryCheckpointStore` for `FileCheckpointStore` to persist; `fork_from_checkpoint` branches a new session without disturbing the old one.

Next, let's connect the agent to the outside world.

- [Web search & MCP →](web-and-mcp.md)
