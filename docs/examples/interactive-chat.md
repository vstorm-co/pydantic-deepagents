# Interactive Chat Example

CLI chatbot with streaming and tool visibility.

## Source Code

:material-file-code: `examples/interactive_chat.py`

## Overview

This example demonstrates:

- Interactive chat loop with message history
- Real-time streaming of AI responses
- Displaying tool calls and their results
- Showing the current TODO list
- Rich terminal output with colors

## Features

- **Streaming responses** - See text as it's generated
- **Tool visibility** - Watch tools being called in real-time
- **TODO tracking** - See the agent's task list
- **File tracking** - View files in storage
- **Slash commands** - `/quit`, `/clear`, `/files`, `/todos`

## Running the Example

```bash
export OPENAI_API_KEY=your-api-key
uv run python examples/interactive_chat.py
```

## Screenshot

```
╔══════════════════════════════════════════════════════════╗
║         pydantic-deep Interactive Chat                   ║
╚══════════════════════════════════════════════════════════╝
Type your message and press Enter. Commands:
  /quit or /exit - Exit the chat
  /clear         - Clear conversation history
  /files         - Show files in storage
  /todos         - Show current TODO list

You: Create a Python hello world script

AI:
  ⚡ write_todos({'todos': [...]})
    → [{'content': 'Create hello world script', 'status': 'in_progress'}]
  ⚡ write_file({'path': '/hello.py', 'content': 'print("Hello, World!")'})
    → Created /hello.py (1 lines)

I've created a simple Python script at /hello.py that prints "Hello, World!"

┌─ TODOs ─────────────────────────────────────────────────┐
│ ✓ Create hello world script                             │
└─────────────────────────────────────────────────────────┘

You: /files

┌─ Files ────────────────────────────────────────────────┐
│ /hello.py (1 lines)                                    │
└────────────────────────────────────────────────────────┘

You: /quit

Goodbye!
```

## Full Example

```python
"""Interactive CLI chatbot with streaming and tool visibility."""

import asyncio
from dataclasses import dataclass, field

from pydantic_ai import (
    Agent,
    AgentRunResultEvent,
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    PartDeltaEvent,
)
from pydantic_ai.messages import ModelMessage

from pydantic_deep import DeepAgentDeps, StateBackend, create_deep_agent

# ANSI color codes
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"


def print_header() -> None:
    """Print the chat header."""
    print(f"\n{BOLD}{CYAN}╔══════════════════════════════════════════════════════════╗{RESET}")
    print(f"{BOLD}{CYAN}║         pydantic-deep Interactive Chat                   ║{RESET}")
    print(f"{BOLD}{CYAN}╚══════════════════════════════════════════════════════════╝{RESET}")
    print(f"{DIM}Type your message and press Enter. Commands:{RESET}")
    print(f"{DIM}  /quit or /exit - Exit the chat{RESET}")
    print(f"{DIM}  /clear         - Clear conversation history{RESET}")
    print(f"{DIM}  /files         - Show files in storage{RESET}")
    print(f"{DIM}  /todos         - Show current TODO list{RESET}")
    print()


def print_todos(deps: DeepAgentDeps) -> None:
    """Print the current TODO list."""
    if not deps.todos:
        print(f"{DIM}No TODOs{RESET}")
        return

    print(f"\n{BOLD}{MAGENTA}┌─ TODOs ─────────────────────────────────────────────────┐{RESET}")
    for todo in deps.todos:
        if todo.status == "completed":
            icon = f"{GREEN}✓{RESET}"
            style = DIM
        elif todo.status == "in_progress":
            icon = f"{YELLOW}●{RESET}"
            style = BOLD
        else:
            icon = f"{DIM}○{RESET}"
            style = ""
        print(f"{MAGENTA}│{RESET} {icon} {style}{todo.content}{RESET}")
    print(f"{MAGENTA}└─────────────────────────────────────────────────────────┘{RESET}\n")


def print_files(deps: DeepAgentDeps) -> None:
    """Print the files in storage."""
    if not deps.files:
        print(f"{DIM}No files in storage{RESET}")
        return

    print(f"\n{BOLD}{BLUE}┌─ Files ────────────────────────────────────────────────┐{RESET}")
    for path, data in sorted(deps.files.items()):
        lines = len(data["content"])
        print(f"{BLUE}│{RESET} {path} ({lines} lines)")
    print(f"{BLUE}└────────────────────────────────────────────────────────┘{RESET}\n")


@dataclass
class StreamState:
    """State for tracking stream display."""
    current_text: str = ""
    showed_tools: bool = False
    needs_text_prefix: bool = False
    message_history: list[ModelMessage] = field(default_factory=list)


async def process_stream(
    agent: Agent[DeepAgentDeps, str],
    user_input: str,
    deps: DeepAgentDeps,
    state: StreamState,
) -> None:
    """Process the agent stream and display events."""
    async for event in agent.run_stream_events(
        user_input,
        deps=deps,
        message_history=state.message_history,
    ):
        if isinstance(event, PartDeltaEvent):
            # Stream text as it arrives
            if hasattr(event.delta, "content_delta"):
                chunk = event.delta.content_delta
                if state.needs_text_prefix:
                    print(f"{BOLD}{CYAN}AI:{RESET} ", end="", flush=True)
                    state.needs_text_prefix = False
                state.current_text += chunk
                print(chunk, end="", flush=True)

        elif isinstance(event, FunctionToolCallEvent):
            # Show tool call
            tool_name = event.part.tool_name
            tool_args = str(event.part.args)[:100]
            print(f"\n  {YELLOW}⚡ {tool_name}{RESET}{DIM}({tool_args}){RESET}", flush=True)
            state.needs_text_prefix = True

        elif isinstance(event, FunctionToolResultEvent):
            # Show tool result
            result = str(event.result.content)[:80]
            print(f"    {DIM}→ {result}{RESET}", flush=True)

        elif isinstance(event, AgentRunResultEvent):
            # Save message history for next turn
            state.message_history = event.result.all_messages()

    if state.current_text and not state.current_text.endswith("\n"):
        print()


async def chat_loop(agent: Agent[DeepAgentDeps, str], deps: DeepAgentDeps) -> None:
    """Main chat loop."""
    state = StreamState()

    while True:
        try:
            user_input = input(f"{BOLD}{GREEN}You:{RESET} ").strip()

            if not user_input:
                continue

            # Handle commands
            if user_input.lower() in ("/quit", "/exit"):
                print(f"\n{DIM}Goodbye!{RESET}")
                break
            if user_input.lower() == "/clear":
                state.message_history = []
                deps.todos = []
                print(f"{DIM}Conversation cleared.{RESET}\n")
                continue
            if user_input.lower() == "/files":
                print_files(deps)
                continue
            if user_input.lower() == "/todos":
                print_todos(deps)
                continue

            # Process AI response
            print(f"\n{BOLD}{CYAN}AI:{RESET} ", end="", flush=True)
            state.current_text = ""
            state.showed_tools = False

            await process_stream(agent, user_input, deps, state)

            if deps.todos:
                print_todos(deps)

            print()

        except KeyboardInterrupt:
            print(f"\n\n{DIM}Interrupted. Type /quit to exit.{RESET}\n")
        except EOFError:
            print(f"\n{DIM}Goodbye!{RESET}")
            break


async def run_chat() -> None:
    """Run the interactive chat."""
    print_header()

    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        instructions="""You are a helpful AI assistant. You have access to:
- TODO list for planning and tracking tasks
- Filesystem for reading/writing files

When working on complex tasks:
1. Break them down into steps using the TODO list
2. Mark tasks as in_progress when starting
3. Mark tasks as completed when done
4. Save your work to files when appropriate

Be concise but informative in your responses.""",
    )

    deps = DeepAgentDeps(backend=StateBackend())
    await chat_loop(agent, deps)


if __name__ == "__main__":
    asyncio.run(run_chat())
```

## Key Concepts

### Message History

The chat maintains conversation history:

```python
state.message_history = event.result.all_messages()

# Pass history to continue conversation
async for event in agent.run_stream_events(
    user_input,
    deps=deps,
    message_history=state.message_history,  # Previous messages
):
    ...
```

### Streaming Events

```python
async for event in agent.run_stream_events(prompt, deps=deps):
    if isinstance(event, PartDeltaEvent):
        # Text chunk
        print(event.delta.content_delta, end="")

    elif isinstance(event, FunctionToolCallEvent):
        # Tool being called
        print(f"Calling: {event.part.tool_name}")

    elif isinstance(event, FunctionToolResultEvent):
        # Tool returned
        print(f"Result: {event.result.content}")
```

### Slash Commands

```python
if user_input.startswith("/"):
    if user_input == "/quit":
        break
    elif user_input == "/files":
        show_files()
    elif user_input == "/todos":
        show_todos()
```

## Variations

### With Rich Library

```python
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

console = Console()

# Rich output
console.print(Panel("Hello", title="AI"))
console.print(Markdown("**Bold** text"))
```

### With Prompt Toolkit

```python
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory

session = PromptSession(history=FileHistory(".chat_history"))

while True:
    user_input = await session.prompt_async("You: ")
```

### Web-Based Chat

See [Full App](full-app.md) for a complete web-based implementation with:

- WebSocket streaming
- HTML/CSS UI
- File uploads
- Docker execution

## Best Practices

1. **Buffer output** - Print in chunks to avoid flicker
2. **Show progress** - Display tool calls as they happen
3. **Handle interrupts** - Catch Ctrl+C gracefully
4. **Persist history** - Save to file for session continuity

## Next Steps

- [Streaming](streaming.md) - Core streaming concepts
- [Full App](full-app.md) - Web-based version
- [Human-in-the-Loop](human-in-the-loop.md) - Add approval UI
