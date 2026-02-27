"""Web tools for pydantic-deep agents.

Provides tools for web search, URL fetching, and HTTP requests:
- ``web_search``: Search the web via a pluggable provider (default: Tavily)
- ``fetch_url``: Fetch a URL and convert HTML to markdown
- ``http_request``: Make raw HTTP requests to APIs

Uses FunctionToolset for native pydantic-ai integration.
All tools return strings and never throw — errors are returned as messages.

Install dependencies: ``pip install 'pydantic-deep[web-tools]'``
"""

from __future__ import annotations

import json
import os
from typing import Any, Protocol, runtime_checkable

from pydantic_ai import RunContext
from pydantic_ai.toolsets.function import FunctionToolset
from typing_extensions import TypedDict

# ---------------------------------------------------------------------------
# Search provider protocol (pluggable)
# ---------------------------------------------------------------------------

DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; PydanticDeep/1.0)"

_MAX_FETCH_CHARS = 50_000
"""Maximum characters to return from fetch_url before truncation."""


class SearchResult(TypedDict):
    """A single web search result."""

    title: str
    url: str
    content: str
    score: float


@runtime_checkable
class SearchProvider(Protocol):
    """Protocol for web search providers.

    Implement this to swap the default Tavily provider for another service
    (e.g., SerpAPI, Brave Search, Google Custom Search).

    Example::

        class MySearchProvider:
            async def search(self, query, max_results=5, topic="general"):
                # Your implementation here
                return [SearchResult(title="...", url="...", content="...", score=0.9)]
    """

    async def search(
        self,
        query: str,
        max_results: int = 5,
        topic: str = "general",
    ) -> list[SearchResult]: ...


# ---------------------------------------------------------------------------
# Built-in Tavily provider
# ---------------------------------------------------------------------------


class TavilySearchProvider:
    """Default search provider using the Tavily API.

    Requires the ``tavily-python`` package and ``TAVILY_API_KEY`` env var
    (or pass ``api_key`` explicitly).

    Args:
        api_key: Tavily API key. Falls back to ``TAVILY_API_KEY`` env var.
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ.get("TAVILY_API_KEY")
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazy-init Tavily client."""
        if self._client is not None:
            return self._client

        if not self._api_key:
            msg = (
                "TAVILY_API_KEY environment variable is not set. "
                "Set it or pass api_key to TavilySearchProvider()."
            )
            raise ValueError(msg)

        from tavily import (
            TavilyClient,  # type: ignore[import-untyped,import-not-found,unused-ignore]
        )

        self._client = TavilyClient(api_key=self._api_key)
        return self._client

    async def search(
        self,
        query: str,
        max_results: int = 5,
        topic: str = "general",
    ) -> list[SearchResult]:
        """Search the web using Tavily.

        Args:
            query: Search query string.
            max_results: Maximum number of results.
            topic: Search topic — "general", "news", or "finance".

        Returns:
            List of search results.
        """
        client = self._get_client()
        response = client.search(
            query=query,
            max_results=max_results,
            topic=topic,
        )
        results: list[SearchResult] = []
        for item in response.get("results", []):
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    content=item.get("content", ""),
                    score=item.get("score", 0.0),
                )
            )
        return results


# ---------------------------------------------------------------------------
# Tool description constants
# ---------------------------------------------------------------------------

WEB_SEARCH_DESCRIPTION = """\
Search the web for current information, documentation, and answers.

Uses a web search API to find relevant pages and return excerpts. \
Results include title, URL, content excerpt, and relevance score.

## When to Use

- Need current/recent information (events, releases, documentation)
- Looking for answers to factual questions
- Researching a topic, library, or API you're unfamiliar with
- Need to verify or supplement your knowledge

## When NOT to Use

- You already have a specific URL — use `fetch_url` instead
- You need to call a REST API endpoint — use `http_request` instead
- The information is available in local files — use `read_file` or `grep`

## After Receiving Results

1. Read through the content excerpts from each result
2. Synthesize relevant information into a clear response
3. Cite sources by mentioning page titles or URLs
4. Do NOT dump raw JSON to the user — summarize naturally"""

FETCH_URL_DESCRIPTION = """\
Fetch a web page and convert its HTML content to readable markdown.

Makes a GET request to the URL and converts the response HTML into \
clean markdown text for easy reading and processing.

## When to Use

- Have a specific URL and need to read the page content
- Following a link from search results to get full details
- Reading documentation, blog posts, or articles

## When NOT to Use

- Searching for information without a URL — use `web_search` instead
- Calling a REST API (POST, PUT, DELETE) — use `http_request` instead
- Fetching binary files (images, PDFs) — use `http_request` instead

Content is truncated to ~50,000 characters if the page is very large."""

HTTP_REQUEST_DESCRIPTION = """\
Make raw HTTP requests to APIs and web services.

Supports all HTTP methods (GET, POST, PUT, DELETE, PATCH) with custom \
headers and request body. Auto-detects JSON responses.

## When to Use

- Calling REST API endpoints (POST, PUT, DELETE)
- Need to send custom headers (Authorization, Content-Type)
- Need to send a JSON or form payload
- Interacting with webhooks or third-party APIs

## When NOT to Use

- Reading a web page for its content — use `fetch_url` instead
- Searching the web for information — use `web_search` instead
- Simple GET requests for HTML pages — use `fetch_url` instead"""


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_web_toolset(  # noqa: C901
    *,
    id: str | None = None,
    search_provider: SearchProvider | None = None,
    include_search: bool = True,
    include_fetch: bool = True,
    include_http: bool = True,
    require_approval: bool = True,
    user_agent: str = DEFAULT_USER_AGENT,
    descriptions: dict[str, str] | None = None,
) -> FunctionToolset[Any]:
    """Create a web toolset with search, fetch, and HTTP request tools.

    All tools return strings and never raise exceptions — errors are
    returned as descriptive messages the agent can act on.

    Args:
        id: Toolset identifier. Defaults to ``"deep-web"``.
        search_provider: Pluggable search provider. Defaults to
            :class:`TavilySearchProvider` (requires ``TAVILY_API_KEY``).
        include_search: Include the ``web_search`` tool.
        include_fetch: Include the ``fetch_url`` tool.
        include_http: Include the ``http_request`` tool.
        require_approval: Whether web tools require user approval.
        user_agent: User-Agent header for HTTP requests.
        descriptions: Optional mapping of tool name to custom description.
            Supported keys: ``web_search``, ``fetch_url``, ``http_request``.
            When a key is absent the built-in default is used.

    Returns:
        FunctionToolset with web tools.
    """
    toolset: FunctionToolset[Any] = FunctionToolset(id=id or "deep-web")
    _descs = descriptions or {}

    _provider = search_provider or TavilySearchProvider()
    _user_agent = user_agent

    if include_search:
        _search_desc = _descs.get("web_search", WEB_SEARCH_DESCRIPTION)

        @toolset.tool(description=_search_desc, requires_approval=require_approval)
        async def web_search(  # pragma: no cover
            ctx: RunContext[Any],
            query: str,
            max_results: int = 5,
            topic: str = "general",
        ) -> str:
            """Search the web for information.

            Args:
                query: The search query. Be specific and detailed.
                max_results: Number of results to return (1-10).
                topic: Search topic — "general", "news", or "finance".
            """
            try:
                results = await _provider.search(
                    query=query,
                    max_results=min(max_results, 10),
                    topic=topic,
                )
                if not results:
                    return f"No results found for: {query}"
                return json.dumps(results, ensure_ascii=False, indent=2)
            except ImportError:
                return (
                    "Error: Required package not installed. "
                    "Install with: pip install 'pydantic-deep[web-tools]'"
                )
            except ValueError as e:
                return f"Error: {e}"
            except Exception as e:
                return f"Error searching the web: {e}"

    if include_fetch:
        _fetch_desc = _descs.get("fetch_url", FETCH_URL_DESCRIPTION)

        @toolset.tool(description=_fetch_desc, requires_approval=require_approval)
        async def fetch_url(  # pragma: no cover
            ctx: RunContext[Any],
            url: str,
            timeout: int = 30,
        ) -> str:
            """Fetch a URL and convert HTML to markdown.

            Args:
                url: The URL to fetch (must be HTTP or HTTPS).
                timeout: Request timeout in seconds.
            """
            try:
                import requests  # type: ignore[import-untyped,import-not-found,unused-ignore]
                from markdownify import (
                    markdownify,  # type: ignore[import-untyped,import-not-found,unused-ignore]
                )
            except ImportError:
                return (
                    "Error: Required packages not installed. "
                    "Install with: pip install 'pydantic-deep[web-tools]'"
                )

            try:
                response = requests.get(
                    url,
                    timeout=timeout,
                    headers={"User-Agent": _user_agent},
                )
                response.raise_for_status()

                markdown_content: str = markdownify(response.text).strip()

                if len(markdown_content) > _MAX_FETCH_CHARS:
                    omitted = len(markdown_content) - _MAX_FETCH_CHARS
                    markdown_content = (
                        markdown_content[:_MAX_FETCH_CHARS]
                        + f"\n\n... [truncated — {omitted} chars omitted]"
                    )

                return markdown_content or "(empty page)"
            except requests.exceptions.Timeout:
                return f"Error: Request timed out after {timeout}s for {url}"
            except requests.exceptions.RequestException as e:
                return f"Error fetching {url}: {e}"

    if include_http:
        _http_desc = _descs.get("http_request", HTTP_REQUEST_DESCRIPTION)

        @toolset.tool(description=_http_desc, requires_approval=require_approval)
        async def http_request(  # pragma: no cover
            ctx: RunContext[Any],
            url: str,
            method: str = "GET",
            headers: dict[str, str] | None = None,
            data: str | None = None,
            timeout: int = 30,
        ) -> str:
            """Make an HTTP request to an API or web service.

            Args:
                url: Target URL.
                method: HTTP method (GET, POST, PUT, DELETE, PATCH).
                headers: HTTP headers to include.
                data: Request body (string or JSON string).
                timeout: Request timeout in seconds.
            """
            try:
                import requests as req  # type: ignore[import-untyped,import-not-found,unused-ignore]
            except ImportError:
                return (
                    "Error: Required package not installed. "
                    "Install with: pip install 'pydantic-deep[web-tools]'"
                )

            try:
                request_headers = dict(headers or {})
                if "User-Agent" not in request_headers:
                    request_headers["User-Agent"] = _user_agent

                # Parse data as JSON if possible
                request_data = None
                request_json = None
                if data is not None:
                    try:
                        request_json = json.loads(data)
                    except (json.JSONDecodeError, TypeError):
                        request_data = data

                response = req.request(
                    method=method.upper(),
                    url=url,
                    headers=request_headers,
                    data=request_data,
                    json=request_json,
                    timeout=timeout,
                )

                # Auto-detect response content type
                try:
                    content = response.json()
                except (ValueError, Exception):
                    content = response.text

                result = {
                    "success": response.status_code < 400,
                    "status_code": response.status_code,
                    "url": str(response.url),
                    "content": content,
                }
                return json.dumps(result, ensure_ascii=False, indent=2)
            except req.exceptions.Timeout:
                return f"Error: Request timed out after {timeout}s for {url}"
            except req.exceptions.RequestException as e:
                return f"Error: HTTP request failed: {e}"

    return toolset
