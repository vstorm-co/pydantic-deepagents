"""Example demonstrating thinking/reasoning capability.

This example shows how to configure the thinking effort level
for different use cases.
"""

import asyncio

from pydantic_deep import DeepAgentDeps, create_deep_agent


async def main():
    # Default: thinking="high" — best for complex reasoning tasks
    agent = create_deep_agent()

    # Other effort levels (for reference):
    # create_deep_agent(thinking="low")    # Quick tasks
    # create_deep_agent(thinking="xhigh")  # Maximum reasoning
    # create_deep_agent(thinking=False)    # Disable thinking

    deps = DeepAgentDeps()

    # Give the agent some code to analyze: it lands at /src/algorithm.py
    await deps.upload_file(
        "algorithm.py",
        b'''\
def find_shortest_path(graph, start, end):
    """Find shortest path using BFS."""
    queue = [(start, [start])]
    visited = set()

    while queue:
        node, path = queue.pop(0)
        if node == end:
            return path

        if node in visited:
            continue
        visited.add(node)

        for neighbor in graph.get(node, []):
            queue.append((neighbor, path + [neighbor]))

    return None
''',
        upload_dir="src",
    )

    # With high thinking, the agent will reason through the algorithm
    result = await agent.run(
        "Analyze /src/algorithm.py. What is the time complexity? "
        "Are there any edge cases that could cause issues?",
        deps=deps,
    )

    print("Analysis with thinking='high':")
    print(result.output)


if __name__ == "__main__":
    asyncio.run(main())
