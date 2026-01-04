"""Basic streaming examples.

This demonstrates how to use the streaming API for real-time updates
during agent execution.
"""

import asyncio

from pydantic_ai.models.test import TestModel

from pydantic_ai_backends import StateBackend
from pydantic_deep import DeepAgentDeps, create_deep_agent
from pydantic_deep.streaming import (
    StreamEventType,
    collect_stream_result,
    run_stream,
    run_stream_with_tools,
    stream_text,
    stream_tool_calls,
)


async def basic_text_streaming():
    """Example 1: Simple text streaming."""
    print("=== Example 1: Basic Text Streaming ===\n")

    agent = create_deep_agent(
        model=TestModel(),
        instructions="You are a helpful assistant",
    )
    deps = DeepAgentDeps(backend=StateBackend())

    print("Assistant: ", end="", flush=True)
    async for chunk in stream_text(agent, "Say hello", deps):
        print(chunk, end="", flush=True)
    print("\n")


async def full_event_streaming():
    """Example 2: Stream all event types."""
    print("\n=== Example 2: Full Event Streaming ===\n")

    agent = create_deep_agent(
        model=TestModel(),
        instructions="You are a helpful assistant",
    )
    deps = DeepAgentDeps(backend=StateBackend())

    print("Streaming all events:\n")

    async for event in run_stream(agent, "Write a short poem", deps):
        if event.event_type == StreamEventType.AGENT_START:
            print(f"🚀 Agent started: {event.data['agent_name']}")

        elif event.event_type == StreamEventType.LLM_CHUNK:
            print(event.data["text"], end="", flush=True)

        elif event.event_type == StreamEventType.PROGRESS:
            tokens = event.data.get("total_tokens", 0)
            iteration = event.data["iteration"]
            print(f"\n📊 Progress: Iteration {iteration}, Tokens: {tokens}")

        elif event.event_type == StreamEventType.AGENT_END:
            duration = event.data.get("duration_seconds", 0)
            success = event.data["success"]
            status = "✓" if success else "✗"
            print(f"\n{status} Agent completed in {duration:.2f}s")

    print()


async def tool_call_streaming():
    """Example 3: Monitor tool calls."""
    print("\n=== Example 3: Tool Call Streaming ===\n")

    agent = create_deep_agent(
        model=TestModel(),
        instructions="You are a file management assistant",
    )
    deps = DeepAgentDeps(backend=StateBackend())

    print("Monitoring tool calls:\n")

    async for event in run_stream_with_tools(agent, "List the files", deps):
        if event.event_type == StreamEventType.TOOL_START:
            print(f"⚙️  Calling {event.data['tool_name']}...")

        elif event.event_type == StreamEventType.TOOL_END:
            tool_name = event.data["tool_name"]
            duration = event.data.get("duration_seconds", 0)
            print(f"✓  {tool_name} completed in {duration:.2f}s")

        elif event.event_type == StreamEventType.LLM_CHUNK:
            print(event.data["text"], end="", flush=True)

    print("\n")


async def simplified_tool_streaming():
    """Example 4: Simplified tool call streaming."""
    print("\n=== Example 4: Simplified Tool Streaming ===\n")

    agent = create_deep_agent(
        model=TestModel(),
        instructions="You are a file management assistant",
    )
    deps = DeepAgentDeps(backend=StateBackend())

    print("Tool calls:\n")

    async for tool_name, args, result in stream_tool_calls(agent, "Read config.json", deps):
        if result is None:
            # Tool starting
            print(f"→ {tool_name}")
            if args:
                print(f"  Args: {args}")
        else:
            # Tool completed
            print(f"  Result: {result}\n")


async def collect_events_example():
    """Example 5: Collect all events for analysis."""
    print("\n=== Example 5: Collect Events ===\n")

    agent = create_deep_agent(
        model=TestModel(),
        instructions="You are a helpful assistant",
    )
    deps = DeepAgentDeps(backend=StateBackend())

    event_counts = {}

    def count_events(event):
        """Count events by type."""
        event_type = event.event_type
        event_counts[event_type] = event_counts.get(event_type, 0) + 1

    print("Collecting events...\n")

    result, events = await collect_stream_result(
        agent,
        "Explain Python decorators briefly",
        deps,
        on_event=count_events,
    )

    print(f"\n📊 Event Statistics:")
    for event_type, count in sorted(event_counts.items()):
        print(f"  {event_type}: {count}")

    print(f"\n📝 Total events collected: {len(events)}")


async def progress_monitoring():
    """Example 6: Monitor progress and costs."""
    print("\n=== Example 6: Progress Monitoring ===\n")

    agent = create_deep_agent(
        model=TestModel(),
        instructions="You are a helpful assistant",
    )
    deps = DeepAgentDeps(backend=StateBackend())

    total_tokens = 0
    total_cost = 0.0
    iterations = 0

    print("Processing request...\n")

    async for event in run_stream(agent, "Explain async/await", deps):
        if event.event_type == StreamEventType.LLM_CHUNK:
            print(event.data["text"], end="", flush=True)

        elif event.event_type == StreamEventType.PROGRESS:
            iterations = event.data["iteration"]
            total_tokens = event.data.get("total_tokens", 0)
            total_cost = event.data.get("total_cost_usd", 0.0)

        elif event.event_type == StreamEventType.AGENT_END:
            duration = event.data.get("duration_seconds", 0)
            print(f"\n\n📊 Final Statistics:")
            print(f"  Duration: {duration:.2f}s")
            print(f"  Iterations: {iterations}")
            print(f"  Tokens: {total_tokens}")
            if total_cost > 0:
                print(f"  Cost: ${total_cost:.6f}")


async def error_handling_example():
    """Example 7: Handle errors gracefully."""
    print("\n=== Example 7: Error Handling ===\n")

    agent = create_deep_agent(
        model=TestModel(),
        instructions="You are a helpful assistant",
    )
    deps = DeepAgentDeps(backend=StateBackend())

    print("Running with error handling...\n")

    try:
        async for event in run_stream(agent, "Process this task", deps):
            if event.event_type == StreamEventType.ERROR:
                print(f"\n❌ Error occurred: {event.data['error']}")
                print(f"   Type: {event.data.get('exception_type', 'Unknown')}")

            elif event.event_type == StreamEventType.LLM_CHUNK:
                print(event.data["text"], end="", flush=True)

            elif event.event_type == StreamEventType.AGENT_END:
                if event.data["success"]:
                    print("\n✓ Completed successfully")
                else:
                    print("\n✗ Completed with errors")

    except Exception as e:
        print(f"\n💥 Fatal error: {e}")

    print()


async def custom_event_handler():
    """Example 8: Build custom event handler."""
    print("\n=== Example 8: Custom Event Handler ===\n")

    class EventStats:
        """Track event statistics."""

        def __init__(self):
            self.text_chunks = []
            self.tool_calls = []
            self.total_tokens = 0
            self.errors = []

        def handle_event(self, event):
            """Handle each event."""
            if event.event_type == StreamEventType.LLM_CHUNK:
                self.text_chunks.append(event.data["text"])

            elif event.event_type == StreamEventType.TOOL_START:
                self.tool_calls.append(event.data["tool_name"])

            elif event.event_type == StreamEventType.PROGRESS:
                self.total_tokens = event.data.get("total_tokens", 0)

            elif event.event_type == StreamEventType.ERROR:
                self.errors.append(event.data["error"])

        def summary(self):
            """Print summary statistics."""
            print("\n📊 Event Handler Summary:")
            print(f"  Text chunks: {len(self.text_chunks)}")
            print(f"  Tool calls: {len(self.tool_calls)}")
            if self.tool_calls:
                print(f"    Tools used: {', '.join(set(self.tool_calls))}")
            print(f"  Total tokens: {self.total_tokens}")
            print(f"  Errors: {len(self.errors)}")

    agent = create_deep_agent(
        model=TestModel(),
        instructions="You are a helpful assistant",
    )
    deps = DeepAgentDeps(backend=StateBackend())

    stats = EventStats()

    print("Processing with custom handler...\n")

    async for event in run_stream(agent, "Explain Python generators", deps):
        stats.handle_event(event)

        # Still print text chunks
        if event.event_type == StreamEventType.LLM_CHUNK:
            print(event.data["text"], end="", flush=True)

    stats.summary()
    print()


if __name__ == "__main__":
    print("=" * 60)
    print("STREAMING EXAMPLES")
    print("=" * 60)

    asyncio.run(basic_text_streaming())
    asyncio.run(full_event_streaming())
    asyncio.run(tool_call_streaming())
    asyncio.run(simplified_tool_streaming())
    asyncio.run(collect_events_example())
    asyncio.run(progress_monitoring())
    asyncio.run(error_handling_example())
    asyncio.run(custom_event_handler())

    print("\n" + "=" * 60)
    print("All examples completed!")
    print("=" * 60)
