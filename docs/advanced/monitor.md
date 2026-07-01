# Monitor — watch & react

Some commands never really finish: a log you're tailing, a test runner in watch mode, a CI poll, a dev server. You don't want the agent to block on them, and you don't want it to *poll* either. A **monitor** runs one of those commands in the background and pushes each new line of matching output straight back into the conversation — so the agent reacts the moment something happens.

```python
import asyncio

from pydantic_deep import create_deep_agent, DeepAgentDeps
from pydantic_ai_backends import LocalBackend


async def main():
    agent = create_deep_agent(model="anthropic:claude-sonnet-4-6")

    deps = DeepAgentDeps(backend=LocalBackend(root_dir="/tmp/monitor-demo"))

    result = await agent.run(
        "Start a monitor on this command, watching only for ERROR lines:\n"
        "  for i in 1 2 3; do echo \"tick $i\"; sleep 1; done; echo 'ERROR: boom'\n"
        "When you see an error, tell me what it said and stop the monitor.",
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

The agent calls `start_monitor` and keeps going. Three seconds later the command prints `ERROR: boom`; that line is delivered back into the conversation, the agent notices it matched the filter, reports the error, and calls `stop_monitor`. It never sat in a polling loop — the output came to *it*.

!!! example "Check it"
    Drop the `match` filter (ask for *all* output, no regex) and you'll see the
    `tick 1` / `tick 2` / `tick 3` lines arrive one batch at a time, plus a final
    "process exited" event. The filter is the difference between a firehose and a
    signal.

## Dissect

Let's walk the three tools the agent has, and the one requirement that makes them work.

### `start_monitor` — begin watching

```python
start_monitor(command, label="", match="")
```

Spawns `command` in the background and starts draining its output on a short interval. Returns a monitor id (like `mon_1`) you'll use to stop it.

- **`command`** — the shell command to watch (`tail -f app.log`, `npm run test:watch`, a CI-poll loop).
- **`label`** — a short human name; defaults to the id.
- **`match`** — an optional regex. Only output lines matching it are reported. `error|fail|exception` turns a chatty log into "tell me only when something breaks". Invalid regex falls back to a literal substring match, so you can't shoot yourself in the foot.

### `list_monitors` — see what's running

```python
list_monitors()
```

Returns each monitor with its state (`running` or `exited(<code>)`), label, command, and most recent output line. Handy when several monitors are live at once.

### `stop_monitor` — end one

```python
stop_monitor(monitor_id)
```

Stops the watch loop and kills the underlying process. Idempotent-ish: stopping an unknown id just tells you it doesn't exist.

!!! warning "Monitors need a background-capable backend"
    A monitor spawns a real long-lived process, so it needs a backend that
    supports background execution — `LocalBackend`
    or a `DockerSandbox`. On a plain `StateBackend`
    the tools don't crash; they return a clear "this backend can't run background
    processes" message and the agent moves on. That's why the example above uses
    `LocalBackend`.

## How the react path works

This is the part that makes it feel magic. The watch loop and the conversation are connected by the **message queue**.

1. `MonitorManager` polls the background process and collects new lines since the last poll.
2. It filters them through your `match` regex and, for each non-empty batch, emits a `MonitorEvent`.
3. The event hits the manager's **`on_event` sink**. By default `create_monitor_toolset` wires that sink to `ctx.deps.message_queue`: each event becomes a steering message via [`queue.steer()`][pydantic_deep.features.message_queue.MessageQueue.steer], tagged with `metadata={"source": "monitor", ...}`.
4. Steering messages are delivered **before the next model call**, so the agent sees the new output as part of the ongoing turn and reacts — no extra `agent.run()`, no polling tool calls.

When the process finally exits, one last event with `running=False` is pushed, so the agent learns the command finished (and with what exit code).

!!! note "No message queue? Still useful"
    If `deps.message_queue` is `None`, monitors still run and buffer their recent
    events — the agent just can't be *pushed* to; it would have to ask via
    `list_monitors`. The full hands-off "react" behavior is the message-queue
    path. See [Message queue & steering](message-queue.md) for the mechanism.

!!! info "On by default"
    The monitor toolset is included automatically (`include_monitoring=True` on
    [`create_deep_agent`][pydantic_deep.create_deep_agent]). Pass
    `include_monitoring=False` to leave it out. Because the tools no-op cleanly
    without a background backend, it's safe to keep on everywhere.

## Recap

- A **monitor** runs a long-lived command in the background and reports new output instead of blocking or polling.
- Three tools: **`start_monitor`** (with an optional `match` regex), **`list_monitors`**, **`stop_monitor`**.
- It needs a **background-capable backend** — `LocalBackend` or a sandbox, not `StateBackend`.
- New output reaches the agent through the **message queue**: each `MonitorEvent` becomes a steering message delivered before the next model call, so the agent **reacts** with no polling.
- A final `running=False` event tells the agent when the process exits.

Where to go next:

- [Message queue & steering →](message-queue.md) — the delivery channel monitors ride on.
- [Files & the shell →](../learn/files-and-shell.md) — backends and background execution.
- [`create_monitor_toolset`][pydantic_deep.features.monitoring.create_monitor_toolset] in the API reference.
