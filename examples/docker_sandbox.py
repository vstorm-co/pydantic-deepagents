"""Example of an agent working in a Docker container.

This example demonstrates:
- Using DockerWorkspace for safe command execution
- Running code in an isolated container
- Using RuntimeConfig for pre-configured environments
- Removing the container when done (containers are kept after a run)

Note: Requires Docker to be installed and running.
"""

import asyncio

from pydantic_ai.workspaces import WorkspaceRef

from pydantic_deep import DeepAgentDeps, DockerWorkspace, RuntimeConfig, create_deep_agent


async def run_in_container(docker: DockerWorkspace, instructions: str, task: str) -> None:
    """Run one task in `docker`'s container, then remove the container."""
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        instructions=instructions,
        workspace=docker,
        interrupt_on={"execute": True},
    )
    try:
        result = await agent.run(task, deps=DeepAgentDeps())
        print("Agent output:")
        print(result.output)
    finally:
        # A named container: the same name finds it again, here to remove it.
        assert docker.container_name is not None
        await docker.destroy(WorkspaceRef(provider="docker", id=docker.container_name))


async def basic_example():
    """Basic example with default Python image."""
    print("=== Basic DockerWorkspace Example ===\n")

    await run_in_container(
        DockerWorkspace(
            image="python:3.12-slim",
            work_dir="/workspace",
            container_name="pydantic-deep-example-basic",
        ),
        instructions="""
        You are a Python development assistant.
        You can write code, save it to files, and execute it in a sandbox.
        Always test your code by running it.
        """,
        task="""Create a Python script that:
        1. Defines a function to calculate fibonacci numbers
        2. Prints the first 10 fibonacci numbers
        3. Save it to /workspace/fibonacci.py
        4. Run it and show the output
        """,
    )


async def runtime_example():
    """Example using RuntimeConfig for pre-configured environment."""
    print("\n=== RuntimeConfig Example ===\n")

    # Use a built-in runtime with data science packages pre-installed
    await run_in_container(
        DockerWorkspace(
            runtime="python-datascience",
            container_name="pydantic-deep-example-datascience",
        ),
        instructions="""
        You are a data science assistant.
        You have pandas, numpy, matplotlib, and other packages available.
        You can analyze data and create visualizations.
        """,
        task="""Create a Python script that:
        1. Uses pandas to create a DataFrame with sample sales data
        2. Calculates summary statistics
        3. Creates a simple bar chart with matplotlib
        4. Saves the chart to /workspace/chart.png
        5. Print the summary statistics
        """,
    )


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

    await run_in_container(
        DockerWorkspace(
            runtime=custom_runtime,
            work_dir="/app",
            container_name="pydantic-deep-example-fastapi",
        ),
        instructions="""
        You are a FastAPI development assistant.
        You have FastAPI, uvicorn, and httpx available.
        You can create and test API endpoints.
        """,
        task="""Create a simple FastAPI app in /app/main.py that:
        1. Has a GET endpoint at / that returns {"message": "Hello, World!"}
        2. Has a GET endpoint at /health that returns {"status": "ok"}
        3. Print the contents of the file
        """,
    )


async def main():
    """Run all examples."""
    await basic_example()
    await runtime_example()
    await custom_runtime_example()


if __name__ == "__main__":
    print("Note: This example requires Docker to be installed and running.")
    print("Install the extra: pip install 'pydantic-deep[sandbox]'")
    print()

    try:
        import docker  # noqa: F401

        asyncio.run(main())
    except ImportError:
        print("Docker package not installed. Run: pip install 'pydantic-deep[sandbox]'")
    except Exception as e:
        print(f"Error: {e}")
        print("Make sure Docker daemon is running.")
