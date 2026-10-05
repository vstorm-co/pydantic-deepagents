"""Basic usage example for pydantic-deep.

This example demonstrates the core functionality:
- Creating a deep agent
- Using the todo toolset for planning
- Using the filesystem toolset for file operations
"""

import asyncio

from pydantic_deep import DeepAgentDeps, create_deep_agent


async def main():
    # Create a deep agent with default settings
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        instructions="""
        You are a helpful coding assistant.
        When given a task:
        1. Break it down into steps using the todo list
        2. Work through each step methodically
        3. Save your work to files
        """,
    )

    # Files live in the run's workspace: by default an in-memory document
    deps = DeepAgentDeps()

    # Run the agent
    result = await agent.run(
        "Create a simple Python calculator module with add, subtract, multiply, "
        "and divide functions. Save it to /calculator.py",
        deps=deps,
    )

    print("Agent output:")
    print(result.output)

    # Check what files were created
    workspace = result.workspace
    print("\nFiles in the workspace:")
    for entry in await workspace.list_dir("/"):
        print(f"  {entry.path}" + ("/" if entry.is_dir else f": {entry.size} bytes"))

    # Read the created file
    content = await workspace.read_text("/calculator.py")
    print("\nCreated file content:")
    print(content)


if __name__ == "__main__":
    asyncio.run(main())
