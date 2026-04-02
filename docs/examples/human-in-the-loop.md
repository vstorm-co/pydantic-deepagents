# Human-in-the-Loop Example

Approval workflows for sensitive operations.

## Source Code

:material-file-code: `examples/human_in_the_loop.py`

## Overview

This example demonstrates:

- Configuring tools that require approval
- Handling `DeferredToolRequests`
- Approving or denying tool calls
- Continuing execution after approval

## When to Use Human-in-the-Loop

Use approval workflows when:

- Executing potentially destructive commands
- Writing or modifying important files
- Making external API calls
- Running untrusted code
- Any operation that should be reviewed first

## Full Example

```python
"""Example demonstrating Human-in-the-Loop approval."""

import asyncio

from pydantic_ai.tools import (
    DeferredToolRequests,
    DeferredToolResults,
    ToolApproved,
    ToolDenied,
)

from pydantic_deep import DeepAgentDeps, StateBackend, create_deep_agent


async def get_user_approval(tool_name: str, args: dict) -> bool:
    """Simulate getting user approval (in real app, this would be UI)."""
    print(f"\n{'=' * 50}")
    print("APPROVAL REQUIRED")
    print(f"Tool: {tool_name}")
    print(f"Arguments: {args}")
    print(f"{'=' * 50}")

    # For demo, auto-approve write_file but deny execute
    if tool_name == "write_file":
        print("Auto-approving write_file...")
        return True
    elif tool_name == "execute":
        print("Auto-denying execute for safety...")
        return False

    return True


async def main():
    # Create agent with approval required for sensitive operations
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        instructions="You are a system administrator assistant.",
        interrupt_on={
            "write_file": True,   # Require approval for file writes
            "edit_file": True,    # Require approval for file edits
            "execute": True,      # Require approval for command execution
        },
    )

    deps = DeepAgentDeps(backend=StateBackend())

    # Ask the agent to do something that requires approval
    print("Running agent with task that requires approval...")

    result = await agent.run(
        "Create a backup script at /backup.sh that archives the /data directory",
        deps=deps,
    )

    # Check if we got deferred tool requests
    if isinstance(result.output, DeferredToolRequests):
        print(f"\nReceived {len(result.output.approvals)} approval request(s)")

        # Process each approval request
        approvals: dict[str, ToolApproved | ToolDenied] = {}

        for call in result.output.approvals:
            approved = await get_user_approval(call.tool_name, call.args)

            if approved:
                approvals[call.tool_call_id] = ToolApproved()
            else:
                approvals[call.tool_call_id] = ToolDenied(
                    message=f"User denied {call.tool_name} for safety reasons"
                )

        # Continue the agent with approvals
        print("\nContinuing agent with approval decisions...")

        final_result = await agent.run(
            None,  # No new prompt
            deps=deps,
            message_history=result.all_messages(),
            deferred_tool_results=DeferredToolResults(approvals=approvals),
        )

        print("\nFinal output:")
        print(final_result.output)

    else:
        # No approvals needed (shouldn't happen with our config)
        print("Output (no approvals needed):")
        print(result.output)

    # Show what files were created
    print("\nFiles in storage:")
    for path, data in deps.files.items():
        print(f"  {path}: {len(data['content'])} lines")


if __name__ == "__main__":
    asyncio.run(main())
```

## Running the Example

```bash
export OPENAI_API_KEY=your-api-key
uv run python examples/human_in_the_loop.py
```

## Expected Output

```
Running agent with task that requires approval...

Received 1 approval request(s)

==================================================
APPROVAL REQUIRED
Tool: write_file
Arguments: {'path': '/backup.sh', 'content': '#!/bin/bash\ntar -czf...'}
==================================================
Auto-approving write_file...

Continuing agent with approval decisions...

Final output:
I've created the backup script at /backup.sh. The script:
- Archives the /data directory
- Creates a timestamped backup file
- Uses gzip compression

Files in storage:
  /backup.sh: 12 lines
```

## Key Concepts

### Configuring Approval Requirements

```python
agent = create_deep_agent(
    interrupt_on={
        "write_file": True,   # Always require approval
        "edit_file": True,
        "execute": True,
        "read_file": False,   # No approval needed
    },
)
```

### Handling DeferredToolRequests

```python
result = await agent.run(prompt, deps=deps)

if isinstance(result.output, DeferredToolRequests):
    # Agent paused waiting for approval
    for call in result.output.approvals:
        print(f"Tool: {call.tool_name}")
        print(f"Args: {call.args}")
        print(f"ID: {call.tool_call_id}")
```

### Approving or Denying

```python
from pydantic_ai.tools import ToolApproved, ToolDenied

approvals = {}

# Approve a tool call
approvals[call.tool_call_id] = ToolApproved()

# Deny with a message
approvals[call.tool_call_id] = ToolDenied(
    message="Operation not permitted by security policy"
)
```

### Continuing After Approval

```python
from pydantic_ai.tools import DeferredToolResults

final_result = await agent.run(
    None,  # No new prompt needed
    deps=deps,
    message_history=result.all_messages(),  # Continue conversation
    deferred_tool_results=DeferredToolResults(approvals=approvals),
)
```

## Variations

### Interactive Console Approval

```python
async def interactive_approval(tool_name: str, args: dict) -> bool:
    """Get approval from user via console."""
    print(f"\nTool: {tool_name}")
    print(f"Args: {args}")

    while True:
        response = input("Approve? (y/n): ").strip().lower()
        if response in ("y", "yes"):
            return True
        elif response in ("n", "no"):
            return False
        print("Please enter 'y' or 'n'")
```

### Web UI Approval

```python
# In a FastAPI endpoint
@app.post("/approve/{request_id}")
async def approve_request(request_id: str, approved: bool):
    if approved:
        approvals[request_id] = ToolApproved()
    else:
        approvals[request_id] = ToolDenied(message="User denied")

    # Signal the agent to continue
    await continue_agent()
```

### Conditional Approval

```python
async def smart_approval(tool_name: str, args: dict) -> bool:
    """Auto-approve safe operations, require manual approval for others."""

    # Auto-approve reads
    if tool_name == "read_file":
        return True

    # Auto-approve writes to safe directories
    if tool_name == "write_file":
        path = args.get("path", "")
        if path.startswith("/workspace/") or path.startswith("/tmp/"):
            return True

    # Everything else requires manual approval
    return await get_manual_approval(tool_name, args)
```

### Approval with Modification

```python
# You can modify arguments before approving
if tool_name == "execute":
    # Add timeout to all commands
    modified_args = {**args, "timeout": 30}
    approvals[call.tool_call_id] = ToolApproved()
    # Note: Currently pydantic-ai doesn't support modifying args
    # This is for illustration purposes
```

## Best Practices

1. **Be specific** - Only require approval for truly sensitive operations
2. **Show context** - Display enough information for informed decisions
3. **Provide defaults** - Consider auto-approving safe variations
4. **Log decisions** - Keep audit trail of approvals/denials
5. **Handle timeouts** - What happens if approval never comes?

## Security Considerations

!!! warning "Security Warning"
    Human-in-the-loop is a safety mechanism, not a security boundary.

    - Users may approve dangerous operations accidentally
    - Approval fatigue leads to rubber-stamping
    - Consider additional safeguards (sandboxing, rate limiting)

## Next Steps

- [Docker Sandbox](docker-sandbox.md) - Combine with isolation
- [Full App](full-app.md) - Web-based approval UI
- [Advanced: Human-in-the-Loop](../advanced/human-in-the-loop.md) - Deep dive
