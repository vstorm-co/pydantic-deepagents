"""Example adding an Xquik search tool to a deep agent.

This example demonstrates:
- Calling an authenticated HTTP API from a custom tool
- Returning structured X post search results to the agent
- Keeping third-party tools opt-in through environment variables
"""

import asyncio
import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic_ai import RunContext

from pydantic_deep import DeepAgentDeps, StateBackend, create_deep_agent

XQUIK_SEARCH_URL = "https://xquik.com/api/v1/x/tweets/search"


def _clamp_limit(limit: int) -> int:
    return max(1, min(limit, 50))


def _fetch_xquik_posts(query: str, limit: int, cursor: str | None) -> dict[str, Any]:
    params = {
        "q": query,
        "limit": str(_clamp_limit(limit)),
    }
    if cursor:
        params["cursor"] = cursor

    api_key = os.environ.get("XQUIK_API_KEY")
    if not api_key:
        return {
            "ok": False,
            "error": "Set XQUIK_API_KEY before calling search_x_posts.",
        }

    request = Request(
        f"{XQUIK_SEARCH_URL}?{urlencode(params)}",
        headers={
            "Accept": "application/json",
            "X-API-Key": api_key,
        },
    )

    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return {
            "ok": False,
            "status": exc.code,
            "error": exc.reason,
        }
    except (OSError, URLError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "error": str(exc),
        }

    return {
        "ok": True,
        "tweets": payload.get("tweets", []),
        "has_more": payload.get("has_more", False),
        "next_cursor": payload.get("next_cursor"),
    }


async def search_x_posts(
    ctx: RunContext[DeepAgentDeps],
    query: str,
    limit: int = 10,
    cursor: str | None = None,
) -> str:
    """Search public X posts with Xquik.

    Args:
        query: Keyword, X search query, Tweet ID, or X status URL.
        limit: Maximum posts to return, from 1 to 50.
        cursor: Optional pagination cursor from a previous response.
    """
    result = await asyncio.to_thread(_fetch_xquik_posts, query, limit, cursor)
    return json.dumps(result, ensure_ascii=False)


async def main():
    agent = create_deep_agent(
        model=os.environ.get("PYDANTIC_DEEP_MODEL", "anthropic:claude-sonnet-4-6"),
        instructions="""
        You are a research assistant.
        Use search_x_posts when a task needs current public X posts.
        Summarize patterns, include post URLs when available, and say when no results return.
        """,
        tools=[search_x_posts],
    )

    deps = DeepAgentDeps(backend=StateBackend())

    result = await agent.run(
        "Find recent public X posts about open source AI agents and summarize the themes.",
        deps=deps,
    )

    print("Agent output:")
    print(result.output)


if __name__ == "__main__":
    asyncio.run(main())
