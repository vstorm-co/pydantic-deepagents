"""Example demonstrating web search and fetch capabilities.

Shows how to configure WebSearch and WebFetch independently,
and how to use custom capabilities for advanced control.
"""

import asyncio

from pydantic_deep import DeepAgentDeps, StateBackend, create_deep_agent


async def main():
    # Default: both web_search and web_fetch enabled
    agent = create_deep_agent()

    deps = DeepAgentDeps(backend=StateBackend())

    # Agent can search the web and fetch URLs
    result = await agent.run(
        "Search for the latest Python 3.13 release notes and summarize "
        "the key new features. Save the summary to /notes/python313.md",
        deps=deps,
    )
    print(result.output)


async def search_only():
    """Example with web search but no fetch."""
    agent = create_deep_agent(
        web_search=True,
        web_fetch=False,  # Can search but not fetch full pages
    )

    deps = DeepAgentDeps(backend=StateBackend())
    result = await agent.run(
        "Search for the best Python async frameworks in 2026",
        deps=deps,
    )
    print(result.output)


async def custom_web_capabilities():
    """Example with custom WebSearch configuration via capabilities."""
    from pydantic_ai.capabilities import WebSearch

    agent = create_deep_agent(
        web_search=False,  # Disable default
        web_fetch=False,  # Disable default
        capabilities=[
            # Custom WebSearch with domain restrictions
            WebSearch(allowed_domains=["docs.python.org", "peps.python.org"]),
        ],
    )

    deps = DeepAgentDeps(backend=StateBackend())
    result = await agent.run(
        "Search Python documentation for information about pattern matching",
        deps=deps,
    )
    print(result.output)


if __name__ == "__main__":
    asyncio.run(main())
