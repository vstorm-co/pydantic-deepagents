"""File uploads example for pydantic-deep.

This example demonstrates how to upload files for agent processing:
- Using run_with_files() helper function
- Using deps.upload_file() directly
- Agent sees uploaded files in system prompt
- Agent uses file tools to analyze uploaded content
"""

import asyncio

from pydantic_deep import DeepAgentDeps, StateBackend, create_deep_agent, run_with_files


async def example_run_with_files():
    """Example using run_with_files() helper."""
    print("=" * 60)
    print("Example 1: Using run_with_files()")
    print("=" * 60)

    # Create agent and deps
    agent = create_deep_agent(
        model="openai:gpt-4.1",
        instructions="""
        You are a data analyst. When given data files:
        1. Read the file to understand its structure
        2. Analyze the data
        3. Provide insights
        """,
    )
    deps = DeepAgentDeps(backend=StateBackend())

    # Sample CSV data
    csv_data = b"""product,sales,region
Widget A,150,North
Widget B,230,South
Widget C,180,North
Widget A,120,South
Widget B,290,East
Widget C,95,West
"""

    # Run agent with file
    result = await run_with_files(
        agent,
        "Analyze the sales data and tell me which product has the highest total sales",
        deps,
        files=[("sales.csv", csv_data)],
    )

    print(f"\nAgent response:\n{result}")

    # Check what files were uploaded
    print("\n\nUploaded files:")
    for path, info in deps.uploads.items():
        print(f"  {path}: {info['size']} bytes, {info['line_count']} lines")


async def example_direct_upload():
    """Example using deps.upload_file() directly."""
    print("\n" + "=" * 60)
    print("Example 2: Using deps.upload_file() directly")
    print("=" * 60)

    agent = create_deep_agent(
        model="openai:gpt-4.1",
        instructions="You are a helpful assistant that analyzes JSON configs.",
    )
    deps = DeepAgentDeps(backend=StateBackend())

    # Upload multiple files
    deps.upload_file("config.json", b'{"debug": true, "max_workers": 4}')
    deps.upload_file(
        "settings.json",
        b'{"theme": "dark", "language": "en"}',
        upload_dir="/configs",  # Custom upload directory
    )

    # Check uploads
    print("\nUploaded files:")
    for path, info in deps.uploads.items():
        print(f"  {path}: {info['size']} bytes")

    # Run agent - it will see the uploaded files in system prompt
    result = await agent.run(
        "What configuration files are available? Summarize their contents.",
        deps=deps,
    )

    print(f"\nAgent response:\n{result.output}")


async def example_large_file():
    """Example with a larger file showing pagination hints."""
    print("\n" + "=" * 60)
    print("Example 3: Large file handling")
    print("=" * 60)

    agent = create_deep_agent(
        model="openai:gpt-4.1",
        instructions="""
        You are a log analyzer. For large files:
        - Use read_file with offset and limit to paginate
        - Use grep to search for specific patterns
        """,
    )
    deps = DeepAgentDeps(backend=StateBackend())

    # Generate a larger log file
    log_lines = []
    for i in range(100):
        level = ["INFO", "DEBUG", "WARNING", "ERROR"][i % 4]
        log_lines.append(f"[{level}] Line {i}: Some log message here")

    log_data = "\n".join(log_lines).encode("utf-8")

    deps.upload_file("app.log", log_data)

    print("\nUploaded files:")
    for path, info in deps.uploads.items():
        print(f"  {path}: {info['size']} bytes, {info['line_count']} lines")

    # Check uploads summary that agent sees
    print("\nSystem prompt section for uploads:")
    print(deps.get_uploads_summary())

    result = await agent.run(
        "Count how many ERROR level logs are in the file",
        deps=deps,
    )

    print(f"\nAgent response:\n{result.output}")


async def example_binary_file():
    """Example with binary file."""
    print("\n" + "=" * 60)
    print("Example 4: Binary file (no line count)")
    print("=" * 60)

    deps = DeepAgentDeps(backend=StateBackend())

    # Upload a binary file (e.g., image header simulation)
    binary_data = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])  # PNG header
    deps.upload_file("image.png", binary_data)

    print("\nUploaded files:")
    for path, info in deps.uploads.items():
        line_info = f"{info['line_count']} lines" if info["line_count"] else "binary"
        print(f"  {path}: {info['size']} bytes, {line_info}")


async def main():
    """Run all examples."""
    await example_run_with_files()
    await example_direct_upload()
    await example_large_file()
    await example_binary_file()


if __name__ == "__main__":
    asyncio.run(main())
