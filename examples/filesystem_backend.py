"""Example using LocalBackend for real file operations.

This example shows how to:
- Use LocalBackend for persistent file storage
- Work with real files on disk
"""

import asyncio
from pathlib import Path

from pydantic_deep import DeepAgentDeps, LocalBackend, create_deep_agent


async def main():
    # Create workspace directory
    workspace = Path("./workspace")
    workspace.mkdir(exist_ok=True)
    print(f"Workspace: {workspace.absolute()}")

    # Create a LocalBackend pointing to the workspace
    backend = LocalBackend(root_dir=str(workspace))

    # Create the agent
    agent = create_deep_agent(
        model="openai:gpt-4.1",
        instructions="You are a file organization assistant.",
    )

    deps = DeepAgentDeps(backend=backend)

    # Run the agent to create some files
    result = await agent.run(
        """Create a simple project structure:
        1. Create src/main.py with a hello world function
        2. Create src/utils.py with a helper function
        3. Create README.md with project description
        """,
        deps=deps,
    )

    print("Agent output:")
    print(result.output)

    # List actual files on disk
    print("\nFiles on disk:")
    for path in workspace.rglob("*"):
        if path.is_file():
            rel_path = path.relative_to(workspace)
            print(f"  {rel_path}")

    # Read a file from disk
    main_py = workspace / "src" / "main.py"
    if main_py.exists():
        print(f"\nContent of {main_py.name}:")
        print(main_py.read_text())


if __name__ == "__main__":
    asyncio.run(main())
