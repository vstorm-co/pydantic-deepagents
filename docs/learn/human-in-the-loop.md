# Human-in-the-loop

Some actions you don't want an agent doing on its own — running a shell command, overwriting a file, spending money. **Human-in-the-loop** hands those moments back to you: the agent pauses right before the risky call and waits for your yes or no.

You mark the tools you care about with `interrupt_on`. When the agent reaches one, it doesn't return a final answer — it stops and hands you the pending calls so you can approve or deny them, then resume.

```python hl_lines="14 15 16 39 47 48 49 50"
import asyncio

from pydantic_ai.tools import (
    DeferredToolRequests,
    DeferredToolResults,
    ToolApproved,
    ToolDenied,
)

from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend


async def main():
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        instructions="You are a helpful coding assistant.",
        interrupt_on={"execute": True},  # pause before any shell command
    )

    deps = DeepAgentDeps(backend=StateBackend())

    result = await agent.run(
        "Write a script hello.py that prints 'hello world', then run it.",
        deps=deps,
    )

    # The agent paused: it wants to run a command and needs your approval.
    while isinstance(result.output, DeferredToolRequests):
        approvals: dict[str, ToolApproved | ToolDenied] = {}

        for call in result.output.approvals:
            print(f"\nAgent wants to call: {call.tool_name}")
            print(f"With args: {call.args}")
            answer = input("Approve? [y/n]: ").strip().lower()

            if answer == "y":
                approvals[call.tool_call_id] = ToolApproved()
            else:
                approvals[call.tool_call_id] = ToolDenied(message="Denied by user.")

        # Resume the same run, carrying your decisions back in.
        result = await agent.run(
            None,
            deps=deps,
            message_history=result.all_messages(),
            deferred_tool_results=DeferredToolResults(approvals=approvals),
        )

    print(result.output)


asyncio.run(main())
```

## Run it

Save it to `main.py` and run:

<div class="termy">

```console
$ python main.py

Agent wants to call: execute
With args: {'command': 'python hello.py'}
Approve? [y/n]: y
Done — the script printed "hello world".
```

</div>

The agent wrote `hello.py` freely (you didn't gate `write_file`), but before it ran a single shell command it stopped and asked. Type `y` and it continues; type anything else and it backs off and reports the denial.

!!! example "Check it"
    Run it again and answer `n`. The agent never executes the command — it
    receives your `ToolDenied` message and tells you it couldn't finish the run.

## Step by step

Let's walk through the moving parts.

### Step 1: mark the risky tools

```python hl_lines="4"
agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    instructions="You are a helpful coding assistant.",
    interrupt_on={"execute": True},
)
```

`interrupt_on` is a dict of tool name → `True`. Anything you list pauses for approval; everything else runs as normal. Here only `execute` (shell commands) is gated — `read_file`, `write_file`, and `edit_file` still run freely. Gate more by adding keys: `{"execute": True, "write_file": True, "edit_file": True}`.

!!! note "Which tools can be gated"
    Approval is supported for the three sensitive console tools: `execute`,
    `write_file`, and `edit_file`. Other tools always run.

### Step 2: notice the run paused

```python
while isinstance(result.output, DeferredToolRequests):
    ...
```

Normally `result.output` is the model's answer. But when a gated tool comes up, the run ends early and `result.output` is a [`DeferredToolRequests`][pydantic_ai.tools.DeferredToolRequests] instead. That type is your signal: the agent is waiting. Each entry in `result.output.approvals` is one pending call, with a `tool_name`, the `args`, and a unique `tool_call_id`.

### Step 3: decide

```python
approvals[call.tool_call_id] = ToolApproved()
# or
approvals[call.tool_call_id] = ToolDenied(message="Denied by user.")
```

Build a dict keyed by `tool_call_id`. `ToolApproved()` lets the call through; `ToolDenied(message=...)` blocks it and feeds your message back to the model so it can react ("I wasn't allowed to run that"). You're free to decide however you like — prompt a human, check a policy, inspect the args.

!!! tip "Inspect the args before approving"
    `call.args` is the exact payload the tool will receive, so you can deny
    selectively — for example, deny any `execute` whose `command` contains `rm`,
    and approve the rest.

### Step 4: resume

```python hl_lines="2 4 5"
result = await agent.run(
    None,                                    # no new prompt
    deps=deps,
    message_history=result.all_messages(),   # continue the same conversation
    deferred_tool_results=DeferredToolResults(approvals=approvals),
)
```

You resume by calling `agent.run()` again with `None` as the prompt — there's nothing new to say, you're just handing back decisions. `message_history=result.all_messages()` carries the conversation forward, and `deferred_tool_results` delivers your approvals. The agent applies them and keeps going. The `while` loop matters: a resumed run can pause *again* on the next risky call, so you keep looping until `result.output` is no longer a `DeferredToolRequests`.

!!! warning "A gate, not a sandbox"
    Human-in-the-loop is a safety prompt, not a security boundary. People
    rubber-stamp prompts, and approval fatigue is real. For untrusted work,
    combine it with a `DockerSandbox` backend so even an approved command runs
    isolated.

## Recap

You put yourself in the loop for the calls that matter:

- `interrupt_on={"execute": True}` pauses the agent before a gated tool — `execute`, `write_file`, and `edit_file` are the ones you can gate.
- A paused run returns `DeferredToolRequests` as `result.output`; each `approvals` entry has a `tool_name`, `args`, and `tool_call_id`.
- Build a `{tool_call_id: ToolApproved() | ToolDenied(message=...)}` dict — inspect `args` to decide selectively.
- Resume with `agent.run(None, message_history=result.all_messages(), deferred_tool_results=DeferredToolResults(approvals=...))`, and loop until the output is a real answer.

Next, let's give the agent a memory that outlives a single run.

- [Memory & context files →](memory.md)
