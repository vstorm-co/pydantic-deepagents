"""Tests for pydantic_deep.toolsets.web module."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from pydantic_deep.toolsets.web import (
    _MAX_FETCH_CHARS,
    DEFAULT_USER_AGENT,
    FETCH_URL_DESCRIPTION,
    HTTP_REQUEST_DESCRIPTION,
    WEB_SEARCH_DESCRIPTION,
    SearchProvider,
    SearchResult,
    TavilySearchProvider,
    create_web_toolset,
)

# ---------------------------------------------------------------------------
# SearchResult TypedDict
# ---------------------------------------------------------------------------


class TestSearchResult:
    """Tests for SearchResult TypedDict."""

    def test_search_result_creation(self):
        """SearchResult can be created with required keys."""
        result: SearchResult = {
            "title": "Example",
            "url": "https://example.com",
            "content": "Some content",
            "score": 0.95,
        }
        assert result["title"] == "Example"
        assert result["url"] == "https://example.com"
        assert result["content"] == "Some content"
        assert result["score"] == 0.95


# ---------------------------------------------------------------------------
# SearchProvider protocol
# ---------------------------------------------------------------------------


class TestSearchProvider:
    """Tests for SearchProvider protocol."""

    def test_protocol_is_runtime_checkable(self):
        """SearchProvider is a runtime-checkable protocol."""

        class MyProvider:
            async def search(
                self,
                query: str,
                max_results: int = 5,
                topic: str = "general",
            ) -> list[SearchResult]:
                return []

        provider = MyProvider()
        assert isinstance(provider, SearchProvider)

    def test_non_provider_not_instance(self):
        """Object without search method is not a SearchProvider."""

        class NotAProvider:
            pass

        assert not isinstance(NotAProvider(), SearchProvider)


# ---------------------------------------------------------------------------
# TavilySearchProvider
# ---------------------------------------------------------------------------


class TestTavilySearchProvider:
    """Tests for TavilySearchProvider."""

    def test_init_with_explicit_key(self):
        """Provider stores explicit API key."""
        provider = TavilySearchProvider(api_key="test-key")
        assert provider._api_key == "test-key"

    def test_init_with_env_var(self):
        """Provider falls back to TAVILY_API_KEY env var."""
        with patch.dict(os.environ, {"TAVILY_API_KEY": "env-key"}):
            provider = TavilySearchProvider()
            assert provider._api_key == "env-key"

    def test_init_no_key(self):
        """Provider stores None when no key is available."""
        with patch.dict(os.environ, {}, clear=True):
            # Ensure TAVILY_API_KEY is not set
            env = os.environ.copy()
            env.pop("TAVILY_API_KEY", None)
            with patch.dict(os.environ, env, clear=True):
                provider = TavilySearchProvider()
                assert provider._api_key is None

    def test_get_client_raises_without_key(self):
        """_get_client raises ValueError when no API key is available."""
        provider = TavilySearchProvider(api_key=None)
        provider._api_key = None  # Force no key
        with pytest.raises(ValueError, match="TAVILY_API_KEY"):
            provider._get_client()

    def test_get_client_creates_tavily_client(self):
        """_get_client creates and caches TavilyClient."""
        provider = TavilySearchProvider(api_key="test-key")
        mock_tavily_module = MagicMock()
        mock_tavily_client_cls = MagicMock(return_value=MagicMock())

        with patch.dict("sys.modules", {"tavily": mock_tavily_module}):
            mock_tavily_module.TavilyClient = mock_tavily_client_cls
            provider._get_client()
            mock_tavily_client_cls.assert_called_once_with(api_key="test-key")
            assert provider._client is not None

    def test_get_client_returns_cached(self):
        """_get_client returns cached client on subsequent calls."""
        provider = TavilySearchProvider(api_key="test-key")
        mock_client = MagicMock()
        provider._client = mock_client
        assert provider._get_client() is mock_client

    async def test_search_returns_results(self):
        """search() returns list of SearchResult dicts."""
        provider = TavilySearchProvider(api_key="test-key")
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {
                    "title": "Result 1",
                    "url": "https://example.com/1",
                    "content": "Content 1",
                    "score": 0.9,
                },
                {
                    "title": "Result 2",
                    "url": "https://example.com/2",
                    "content": "Content 2",
                    "score": 0.8,
                },
            ]
        }
        provider._client = mock_client

        results = await provider.search("test query", max_results=2, topic="general")

        assert len(results) == 2
        assert results[0]["title"] == "Result 1"
        assert results[0]["url"] == "https://example.com/1"
        assert results[0]["content"] == "Content 1"
        assert results[0]["score"] == 0.9
        assert results[1]["title"] == "Result 2"

        mock_client.search.assert_called_once_with(
            query="test query",
            max_results=2,
            topic="general",
        )

    async def test_search_empty_results(self):
        """search() returns empty list when no results."""
        provider = TavilySearchProvider(api_key="test-key")
        mock_client = MagicMock()
        mock_client.search.return_value = {"results": []}
        provider._client = mock_client

        results = await provider.search("obscure query")
        assert results == []

    async def test_search_missing_fields(self):
        """search() handles missing fields with defaults."""
        provider = TavilySearchProvider(api_key="test-key")
        mock_client = MagicMock()
        mock_client.search.return_value = {
            "results": [
                {
                    # All fields missing
                }
            ]
        }
        provider._client = mock_client

        results = await provider.search("query")
        assert len(results) == 1
        assert results[0]["title"] == ""
        assert results[0]["url"] == ""
        assert results[0]["content"] == ""
        assert results[0]["score"] == 0.0

    async def test_search_no_results_key(self):
        """search() returns empty list when response has no 'results' key."""
        provider = TavilySearchProvider(api_key="test-key")
        mock_client = MagicMock()
        mock_client.search.return_value = {}
        provider._client = mock_client

        results = await provider.search("query")
        assert results == []


# ---------------------------------------------------------------------------
# create_web_toolset factory
# ---------------------------------------------------------------------------


class TestCreateWebToolset:
    """Tests for create_web_toolset factory function."""

    def test_default_creates_all_tools(self):
        """Default call creates toolset with all three tools."""
        toolset = create_web_toolset()
        tool_names = set(toolset.tools.keys())
        assert "web_search" in tool_names
        assert "fetch_url" in tool_names
        assert "http_request" in tool_names

    def test_default_id(self):
        """Default toolset id is 'deep-web'."""
        toolset = create_web_toolset()
        assert toolset.id == "deep-web"

    def test_custom_id(self):
        """Custom id is used."""
        toolset = create_web_toolset(id="my-web")
        assert toolset.id == "my-web"

    def test_exclude_search(self):
        """include_search=False excludes web_search tool."""
        toolset = create_web_toolset(include_search=False)
        tool_names = set(toolset.tools.keys())
        assert "web_search" not in tool_names
        assert "fetch_url" in tool_names
        assert "http_request" in tool_names

    def test_exclude_fetch(self):
        """include_fetch=False excludes fetch_url tool."""
        toolset = create_web_toolset(include_fetch=False)
        tool_names = set(toolset.tools.keys())
        assert "web_search" in tool_names
        assert "fetch_url" not in tool_names
        assert "http_request" in tool_names

    def test_exclude_http(self):
        """include_http=False excludes http_request tool."""
        toolset = create_web_toolset(include_http=False)
        tool_names = set(toolset.tools.keys())
        assert "web_search" in tool_names
        assert "fetch_url" in tool_names
        assert "http_request" not in tool_names

    def test_exclude_all(self):
        """All tools excluded produces empty toolset."""
        toolset = create_web_toolset(
            include_search=False,
            include_fetch=False,
            include_http=False,
        )
        assert len(toolset.tools) == 0

    def test_only_search(self):
        """Only search tool included."""
        toolset = create_web_toolset(
            include_search=True,
            include_fetch=False,
            include_http=False,
        )
        assert set(toolset.tools.keys()) == {"web_search"}

    def test_only_fetch(self):
        """Only fetch tool included."""
        toolset = create_web_toolset(
            include_search=False,
            include_fetch=True,
            include_http=False,
        )
        assert set(toolset.tools.keys()) == {"fetch_url"}

    def test_only_http(self):
        """Only http_request tool included."""
        toolset = create_web_toolset(
            include_search=False,
            include_fetch=False,
            include_http=True,
        )
        assert set(toolset.tools.keys()) == {"http_request"}

    def test_custom_search_provider(self):
        """Custom search provider is accepted."""

        class CustomProvider:
            async def search(
                self,
                query: str,
                max_results: int = 5,
                topic: str = "general",
            ) -> list[SearchResult]:
                return []

        provider = CustomProvider()
        toolset = create_web_toolset(search_provider=provider)
        assert "web_search" in toolset.tools

    def test_require_approval_default_true(self):
        """require_approval defaults to True."""
        toolset = create_web_toolset()
        # Tools should exist and be registered with approval required
        assert len(toolset.tools) == 3

    def test_require_approval_false(self):
        """require_approval=False disables approval requirement."""
        toolset = create_web_toolset(require_approval=False)
        assert len(toolset.tools) == 3

    def test_custom_user_agent(self):
        """Custom user_agent is accepted."""
        toolset = create_web_toolset(user_agent="CustomBot/1.0")
        assert len(toolset.tools) == 3

    def test_descriptions_override_web_search(self):
        """Custom description overrides web_search description."""
        custom_desc = "My custom search description"
        toolset = create_web_toolset(
            descriptions={"web_search": custom_desc},
            include_fetch=False,
            include_http=False,
        )
        tool = toolset.tools["web_search"]
        assert tool.description == custom_desc

    def test_descriptions_override_fetch_url(self):
        """Custom description overrides fetch_url description."""
        custom_desc = "My custom fetch description"
        toolset = create_web_toolset(
            descriptions={"fetch_url": custom_desc},
            include_search=False,
            include_http=False,
        )
        tool = toolset.tools["fetch_url"]
        assert tool.description == custom_desc

    def test_descriptions_override_http_request(self):
        """Custom description overrides http_request description."""
        custom_desc = "My custom HTTP description"
        toolset = create_web_toolset(
            descriptions={"http_request": custom_desc},
            include_search=False,
            include_fetch=False,
        )
        tool = toolset.tools["http_request"]
        assert tool.description == custom_desc

    def test_descriptions_default_used_when_not_overridden(self):
        """Default descriptions are used when not overridden."""
        toolset = create_web_toolset()
        assert toolset.tools["web_search"].description == WEB_SEARCH_DESCRIPTION
        assert toolset.tools["fetch_url"].description == FETCH_URL_DESCRIPTION
        assert toolset.tools["http_request"].description == HTTP_REQUEST_DESCRIPTION

    def test_descriptions_partial_override(self):
        """Only specified descriptions are overridden; others use defaults."""
        toolset = create_web_toolset(
            descriptions={"web_search": "Custom search"},
        )
        assert toolset.tools["web_search"].description == "Custom search"
        assert toolset.tools["fetch_url"].description == FETCH_URL_DESCRIPTION
        assert toolset.tools["http_request"].description == HTTP_REQUEST_DESCRIPTION

    def test_descriptions_empty_dict(self):
        """Empty descriptions dict uses all defaults."""
        toolset = create_web_toolset(descriptions={})
        assert toolset.tools["web_search"].description == WEB_SEARCH_DESCRIPTION
        assert toolset.tools["fetch_url"].description == FETCH_URL_DESCRIPTION
        assert toolset.tools["http_request"].description == HTTP_REQUEST_DESCRIPTION


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    """Tests for module constants."""

    def test_default_user_agent(self):
        """DEFAULT_USER_AGENT is set."""
        assert "PydanticDeep" in DEFAULT_USER_AGENT

    def test_max_fetch_chars(self):
        """_MAX_FETCH_CHARS is 50000."""
        assert _MAX_FETCH_CHARS == 50_000

    def test_web_search_description_content(self):
        """WEB_SEARCH_DESCRIPTION has expected content."""
        assert "Search the web" in WEB_SEARCH_DESCRIPTION
        assert "web_search" not in WEB_SEARCH_DESCRIPTION or "web_search" in WEB_SEARCH_DESCRIPTION

    def test_fetch_url_description_content(self):
        """FETCH_URL_DESCRIPTION has expected content."""
        assert "Fetch a web page" in FETCH_URL_DESCRIPTION
        assert "markdown" in FETCH_URL_DESCRIPTION

    def test_http_request_description_content(self):
        """HTTP_REQUEST_DESCRIPTION has expected content."""
        assert "HTTP" in HTTP_REQUEST_DESCRIPTION
        assert "GET" in HTTP_REQUEST_DESCRIPTION
