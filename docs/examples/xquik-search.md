# Xquik Search Tool

Connect a deep agent to Xquik's public X post search endpoint with one custom
tool.

## Source Code

:material-file-code: `examples/xquik_search.py`

## Overview

This example demonstrates:

- Calling an authenticated HTTP API from a custom tool
- Returning structured X post search results to the agent
- Keeping third-party tools opt-in with environment variables
- Letting the agent summarize public X posts with the built-in tool loop

## Tool Function

```python
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
```

The helper reads `XQUIK_API_KEY`, calls
`https://xquik.com/api/v1/x/tweets/search`, and returns a JSON string with
`tweets`, `has_more`, and `next_cursor`.

## Running the Example

```bash
export ANTHROPIC_API_KEY=your-model-api-key
export XQUIK_API_KEY=your-xquik-api-key
uv run python examples/xquik_search.py
```

Use `PYDANTIC_DEEP_MODEL` to choose another supported model:

```bash
export PYDANTIC_DEEP_MODEL=openai:gpt-4o
```

## Key Concepts

The tool is just a typed async function passed to `create_deep_agent()`:

```python
agent = create_deep_agent(
    model=os.environ.get("PYDANTIC_DEEP_MODEL", "anthropic:claude-sonnet-4-6"),
    instructions="Use search_x_posts when a task needs current public X posts.",
    tools=[search_x_posts],
)
```

No Xquik dependency is loaded by default. The tool only runs when you register it
and provide `XQUIK_API_KEY`.

!!! tip "Paginate"
    If the response includes `has_more: true`, call `search_x_posts` again with
    the returned `next_cursor`.
