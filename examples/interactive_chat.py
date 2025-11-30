"""Interactive CLI chatbot with streaming and tool visibility.

This example demonstrates:
- Interactive chat loop with message history
- Real-time streaming of AI responses
- Displaying tool calls and their results
- Showing the current TODO list
- Rich terminal output with colors
"""

import asyncio
import sys
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
RED = "\033[31m"


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


def truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis if too long."""
    return text[: max_len - 3] + "..." if len(text) > max_len else text


@dataclass
class StreamState:
    """State for tracking stream display."""

    current_text: str = ""
    showed_tools: bool = False
    needs_text_prefix: bool = False  # True when we need to print AI prefix before text
    message_history: list[ModelMessage] = field(default_factory=list)


def handle_text_delta(state: StreamState, event: PartDeltaEvent) -> None:
    """Handle streaming text delta."""
    if hasattr(event.delta, "content_delta"):
        chunk = event.delta.content_delta
        # Print prefix if this is first text after tools
        if state.needs_text_prefix:
            print(f"{BOLD}{CYAN}AI:{RESET} ", end="", flush=True)
            state.needs_text_prefix = False
        state.current_text += chunk
        print(chunk, end="", flush=True)


def handle_tool_call(state: StreamState, event: FunctionToolCallEvent) -> None:
    """Handle tool call event."""
    tool_name = event.part.tool_name
    tool_args = event.part.args

    if state.current_text:
        print()
        state.current_text = ""

    if not state.showed_tools:
        print()
        state.showed_tools = True

    args_str = truncate(str(tool_args), 100)
    print(f"  {YELLOW}⚡ {tool_name}{RESET}{DIM}({args_str}){RESET}", flush=True)

    # Mark that we need AI prefix before next text
    state.needs_text_prefix = True


def handle_tool_result(event: FunctionToolResultEvent) -> None:
    """Handle tool result event."""
    content = str(event.result.content)
    display = truncate(content, 200).replace("\n", " ")
    result_preview = truncate(display, 80)
    print(f"    {DIM}→ {result_preview}{RESET}", flush=True)


def handle_final_result(state: StreamState, event: AgentRunResultEvent) -> None:
    """Handle final result event."""
    state.message_history = event.result.all_messages()


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
            handle_text_delta(state, event)
        elif isinstance(event, FunctionToolCallEvent):
            handle_tool_call(state, event)
        elif isinstance(event, FunctionToolResultEvent):
            handle_tool_result(event)
        elif isinstance(event, AgentRunResultEvent):
            handle_final_result(state, event)

    if state.current_text and not state.current_text.endswith("\n"):
        print()


def handle_command(cmd: str, deps: DeepAgentDeps, state: StreamState) -> bool | None:
    """Handle slash commands. Returns True to break, False to continue, None for no match."""
    cmd_lower = cmd.lower()

    if cmd_lower in ("/quit", "/exit"):
        print(f"\n{DIM}Goodbye!{RESET}")
        return True

    if cmd_lower == "/clear":
        state.message_history = []
        deps.todos = []
        print(f"{DIM}Conversation cleared.{RESET}\n")
        return False

    if cmd_lower == "/files":
        print_files(deps)
        return False

    if cmd_lower == "/todos":
        print_todos(deps)
        return False

    return None


async def chat_loop(agent: Agent[DeepAgentDeps, str], deps: DeepAgentDeps) -> None:
    """Main chat loop."""
    state = StreamState()

    while True:
        try:
            user_input = input(f"{BOLD}{GREEN}You:{RESET} ").strip()

            if not user_input:
                continue

            # Check for commands
            cmd_result = handle_command(user_input, deps, state)
            if cmd_result is True:
                break
            if cmd_result is False:
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
        except Exception as e:
            print(f"\n{RED}Error: {e}{RESET}\n")
            if "--debug" in sys.argv:
                import traceback

                traceback.print_exc()


async def run_chat() -> None:
    """Run the interactive chat."""
    print_header()

    agent = create_deep_agent(
        model="openai:gpt-4.1",
        instructions="""You are a helpful AI assistant. You have access to:
- TODO list for planning and tracking tasks
- Filesystem for reading/writing files
- Subagents for delegating specialized tasks

When working on complex tasks:
1. Break them down into steps using the TODO list
2. Mark tasks as in_progress when starting
3. Mark tasks as completed when done
4. Save your work to files when appropriate

Be concise but informative in your responses.""",
    )

    deps = DeepAgentDeps(backend=StateBackend())
    await chat_loop(agent, deps)


def main() -> None:
    """Entry point."""
    asyncio.run(run_chat())


if __name__ == "__main__":
    main()
