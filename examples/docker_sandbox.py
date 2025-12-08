"""Example using DockerSandbox for isolated command execution.

This example demonstrates:
- Using DockerSandbox for safe command execution
- Running code in an isolated container
- Using RuntimeConfig for pre-configured environments
- Combining file operations with execution

Note: Requires Docker to be installed and running.
"""

import asyncio

from pydantic_deep import DeepAgentDeps, DockerSandbox, RuntimeConfig, create_deep_agent


async def basic_example():
    """Basic example with default Python image."""
    print("=== Basic DockerSandbox Example ===\n")

    # Create a Docker sandbox with default image
    sandbox = DockerSandbox(
        image="python:3.12-slim",
        work_dir="/workspace",
    )

    try:
        agent = create_deep_agent(
            model="openai:gpt-4.1",
            instructions="""
            You are a Python development assistant.
            You can write code, save it to files, and execute it in a sandbox.
            Always test your code by running it.
            """,
            interrupt_on={"execute": True},
        )

        deps = DeepAgentDeps(backend=sandbox)

        result = await agent.run(
            """Create a Python script that:
            1. Defines a function to calculate fibonacci numbers
            2. Prints the first 10 fibonacci numbers
            3. Save it to /workspace/fibonacci.py
            4. Run it and show the output
            """,
            deps=deps,
        )

        print("Agent output:")
        print(result.output)

    finally:
        sandbox.stop()


async def runtime_example():
    """Example using RuntimeConfig for pre-configured environment."""
    print("\n=== RuntimeConfig Example ===\n")

    # Use a built-in runtime with data science packages pre-installed
    sandbox = DockerSandbox(runtime="python-datascience")

    try:
        agent = create_deep_agent(
            model="openai:gpt-4.1",
            instructions="""
            You are a data science assistant.
            You have pandas, numpy, matplotlib, and other packages available.
            You can analyze data and create visualizations.
            """,
            interrupt_on={"execute": True},
        )

        deps = DeepAgentDeps(backend=sandbox)

        result = await agent.run(
            """Create a Python script that:
            1. Uses pandas to create a DataFrame with sample sales data
            2. Calculates summary statistics
            3. Creates a simple bar chart with matplotlib
            4. Saves the chart to /workspace/chart.png
            5. Print the summary statistics
            """,
            deps=deps,
        )

        print("Agent output:")
        print(result.output)

    finally:
        sandbox.stop()


async def custom_runtime_example():
    """Example with custom RuntimeConfig."""
    print("\n=== Custom RuntimeConfig Example ===\n")

    # Create a custom runtime configuration
    custom_runtime = RuntimeConfig(
        name="web-api-dev",
        description="Web API development environment",
        base_image="python:3.12-slim",
        packages=["fastapi", "uvicorn", "httpx", "pydantic"],
        setup_commands=["apt-get update", "apt-get install -y curl"],
        env_vars={"PYTHONUNBUFFERED": "1"},
        work_dir="/app",
    )

    sandbox = DockerSandbox(runtime=custom_runtime)

    try:
        agent = create_deep_agent(
            model="openai:gpt-4.1",
            instructions="""
            You are a FastAPI development assistant.
            You have FastAPI, uvicorn, and httpx available.
            You can create and test API endpoints.
            """,
            interrupt_on={"execute": True},
        )

        deps = DeepAgentDeps(backend=sandbox)

        result = await agent.run(
            """Create a simple FastAPI app in /app/main.py that:
            1. Has a GET endpoint at / that returns {"message": "Hello, World!"}
            2. Has a GET endpoint at /health that returns {"status": "ok"}
            3. Print the contents of the file
            """,
            deps=deps,
        )

        print("Agent output:")
        print(result.output)

    finally:
        sandbox.stop()


async def main():
    """Run all examples."""
    await basic_example()
    await runtime_example()
    await custom_runtime_example()


if __name__ == "__main__":
    print("Note: This example requires Docker to be installed and running.")
    print("Install docker package: uv add docker")
    print()

    try:
        import docker  # noqa: F401

        asyncio.run(main())
    except ImportError:
        print("Docker package not installed. Run: uv add docker")
    except Exception as e:
        print(f"Error: {e}")
        print("Make sure Docker daemon is running.")
