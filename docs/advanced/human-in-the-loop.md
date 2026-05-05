# Human-in-the-Loop

pydantic-deep supports requiring human approval for sensitive tool calls through the `interrupt_on` parameter. When a deferred tool is called, the agent pauses and returns a [`DeferredToolRequests`][pydantic_ai.tools.DeferredToolRequests] object instead of a final answer. You review the pending calls, build an approvals dict, and resume the agent with [`DeferredToolResults`][pydantic_ai.tools.DeferredToolResults].

## Configuration

```python
from pydantic_deep import create_deep_agent

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    interrupt_on={
        "execute": True,       # Shell command execution
        "write_file": True,    # Creating/overwriting files
        "edit_file": True,     # Modifying existing files
    },
)
```

## How It Works

1. Agent decides to call a tool marked for approval
2. Agent run ends early — returns `DeferredToolRequests` as `result.output`
3. You inspect `result.output.approvals` and build an approval decision per `tool_call_id`
4. Resume with `agent.run(None, ..., deferred_tool_results=DeferredToolResults(approvals=...))`

## Example Flow

```python
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
        interrupt_on={
            "execute": True,
            "write_file": True,
        },
    )

    deps = DeepAgentDeps(backend=StateBackend())

    result = await agent.run(
        "Create a script that prints hello world and run it",
        deps=deps,
    )

    if isinstance(result.output, DeferredToolRequests):
        print(f"Approval needed for {len(result.output.approvals)} tool call(s):")
        for call in result.output.approvals:
            print(f"  - {call.tool_name}: {call.args}")

        # Approve all pending calls
        approvals = {call.tool_call_id: ToolApproved() for call in result.output.approvals}

        # Resume execution with approval decisions
        result = await agent.run(
            None,
            deps=deps,
            message_history=result.all_messages(),
            deferred_tool_results=DeferredToolResults(approvals=approvals),
        )

    print(result.output)


asyncio.run(main())
```

## Selective Approval

```python
from pydantic_ai.tools import (
    DeferredToolRequests,
    DeferredToolResults,
    ToolApproved,
    ToolDenied,
)

if isinstance(result.output, DeferredToolRequests):
    approvals: dict[str, ToolApproved | ToolDenied] = {}

    for call in result.output.approvals:
        if call.tool_name == "execute":
            if "rm" in call.args.get("command", ""):
                approvals[call.tool_call_id] = ToolDenied(
                    message="Destructive command not allowed"
                )
            else:
                approvals[call.tool_call_id] = ToolApproved()
        else:
            approvals[call.tool_call_id] = ToolApproved()

    result = await agent.run(
        None,
        deps=deps,
        message_history=result.all_messages(),
        deferred_tool_results=DeferredToolResults(approvals=approvals),
    )
```

## Interactive Approval

```python
from pydantic_ai.tools import (
    DeferredToolRequests,
    DeferredToolResults,
    ToolApproved,
    ToolDenied,
)


async def interactive_run(agent, prompt, deps):
    result = await agent.run(prompt, deps=deps)

    while isinstance(result.output, DeferredToolRequests):
        approvals: dict[str, ToolApproved | ToolDenied] = {}

        for call in result.output.approvals:
            print(f"\nTool: {call.tool_name}")
            print(f"Args: {call.args}")
            response = input("Approve? [y/n]: ").strip().lower()

            if response == "y":
                approvals[call.tool_call_id] = ToolApproved()
            else:
                reason = input("Reason for denial: ")
                approvals[call.tool_call_id] = ToolDenied(message=reason)

        result = await agent.run(
            None,
            deps=deps,
            message_history=result.all_messages(),
            deferred_tool_results=DeferredToolResults(approvals=approvals),
        )

    return result
```

## Web Application Integration

```python
from fastapi import FastAPI
from pydantic_ai.tools import (
    DeferredToolRequests,
    DeferredToolResults,
    ToolApproved,
    ToolDenied,
)

app = FastAPI()
pending_approvals: dict[str, dict] = {}


@app.post("/agent/run")
async def run_agent(prompt: str):
    result = await agent.run(prompt, deps=deps)

    if isinstance(result.output, DeferredToolRequests):
        request_id = generate_id()
        pending_approvals[request_id] = {
            "messages": result.all_messages(),
            "calls": result.output.approvals,
        }
        return {
            "status": "pending_approval",
            "request_id": request_id,
            "tools": [
                {"name": c.tool_name, "args": c.args, "id": c.tool_call_id}
                for c in result.output.approvals
            ],
        }

    return {"status": "complete", "output": result.output}


@app.post("/agent/approve/{request_id}")
async def approve(request_id: str, decisions: list[dict]):
    pending = pending_approvals.pop(request_id)
    approvals: dict[str, ToolApproved | ToolDenied] = {}

    for i, decision in enumerate(decisions):
        call = pending["calls"][i]
        if decision["approved"]:
            approvals[call.tool_call_id] = ToolApproved()
        else:
            approvals[call.tool_call_id] = ToolDenied(
                message=decision.get("reason", "Denied by user")
            )

    result = await agent.run(
        None,
        deps=deps,
        message_history=pending["messages"],
        deferred_tool_results=DeferredToolResults(approvals=approvals),
    )

    return {"status": "complete", "output": result.output}
```

## Default Behavior

| Tool | Requires Approval |
|------|-------------------|
| `execute` | Only when `interrupt_on={"execute": True}` |
| `write_file` | Only when `interrupt_on={"write_file": True}` |
| `edit_file` | Only when `interrupt_on={"edit_file": True}` |
| Other tools | Never (not supported) |

By default, when `interrupt_on` is not set, no approval flow is triggered.

## Best Practices

### 1. Always Review Execute

```python
interrupt_on={"execute": True}
```

Shell commands can be dangerous. Always require approval.

### 2. Review Writes in Production

```python
interrupt_on={
    "write_file": True,
    "edit_file": True,
}
```

### 3. Log All Decisions

```python
import logging

logger = logging.getLogger(__name__)

approvals = {}
for call in result.output.approvals:
    approvals[call.tool_call_id] = ToolApproved()
    logger.info("Approved %s with args %s", call.tool_name, call.args)
```

### 4. Set Timeouts

```python
import asyncio

async def timed_approval(call) -> ToolApproved | ToolDenied:
    try:
        approved = await asyncio.wait_for(
            get_user_approval(call.tool_name, call.args),
            timeout=300,  # 5 minute timeout
        )
        return ToolApproved() if approved else ToolDenied(message="User denied")
    except asyncio.TimeoutError:
        return ToolDenied(message="Approval timed out")
```

## Next Steps

- [Subagents](subagents.md) - Task delegation
- [Streaming](streaming.md) - Real-time output
- [Examples: Human-in-the-Loop](../examples/human-in-the-loop.md) - Full working example
