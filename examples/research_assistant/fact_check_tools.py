"""Fact-checking tools for the research assistant subagent.

Provides local evidence search and Serper-powered web search utilities
to verify scientific statements.
"""

from __future__ import annotations

import os
import re
import textwrap
from html.parser import HTMLParser
from io import BytesIO

import httpx
import pypdf
from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

from pydantic_deep.deps import DeepAgentDeps


def _citation(path: str, quote: str) -> str:
    quote_clean = quote.replace("\n", " ").strip()
    return f"[[citation:{path}|{quote_clean}]]"


SERPER_API_URL = "https://google.serper.dev/search"
SERPER_SCHOLAR_API_URL = "https://google.serper.dev/scholar"


class _HTMLStripper(HTMLParser):
    """Simple HTML-to-text stripper for readability."""

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:  # pragma: no cover
        if data:
            self._chunks.append(data)

    def get_text(self) -> str:
        return " ".join(chunk.strip() for chunk in self._chunks if chunk.strip())


def _strip_html(html: str, max_chars: int = 4000) -> str:
    parser = _HTMLStripper()
    parser.feed(html[: max_chars * 2])  # limit parsing
    return parser.get_text()[:max_chars]


def _shorten(text: str, max_len: int = 300) -> str:
    text = text.replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _cap_sources(requested: int | None, fact_check_max_resources: int) -> int:
    """Apply global source cap."""
    CAP_DEFAULT = 5

    try:
        cap_from_env = (
            int(fact_check_max_resources) if fact_check_max_resources is not None else CAP_DEFAULT
        )
    except ValueError:
        cap_from_env = CAP_DEFAULT

    if requested is None:
        return max(1, cap_from_env)

    return max(1, min(requested, cap_from_env))


def _make_snippet(text: str, query: str, window: int = 160) -> str:
    text_lower = text.lower()
    query_lower = query.lower().strip()
    idx = text_lower.find(query_lower)
    if idx == -1:
        return _shorten(text, window)

    start = max(0, idx - window // 2)
    end = min(len(text), idx + len(query_lower) + window // 2)
    snippet = text[start:end]
    return _shorten(snippet, window)


def _extract_pdf_excerpt(
    data: bytes, query: str, max_pages: int = 4, max_chars: int = 4000
) -> str | None:
    try:
        reader = pypdf.PdfReader(BytesIO(data))
    except Exception:
        return None

    text_chunks: list[str] = []
    for page in reader.pages[:max_pages]:
        try:
            text_chunks.append(page.extract_text() or "")
        except Exception:
            continue
        if sum(len(t) for t in text_chunks) >= max_chars:
            break

    joined = "\n".join(text_chunks)
    if not joined:
        return None

    if query.lower() in joined.lower():
        return _make_snippet(joined, query, window=220)

    return _shorten(joined, 220)


async def _serper_search(query: str, api_key: str, num_results: int = 5) -> list[dict]:
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    payload = {"q": query, "num": num_results}

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(SERPER_API_URL, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    results: list[dict] = []
    for item in data.get("organic", [])[:num_results]:
        results.append(
            {
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            }
        )

    return results


def create_fact_check_toolset(  # noqa: C901
    id: str | None = None, fact_check_max_resources: int = 5
) -> FunctionToolset[DeepAgentDeps]:
    """Create tools to support fact checking (local + web)."""

    toolset: FunctionToolset[DeepAgentDeps] = FunctionToolset(id=id)

    @toolset.tool
    async def fact_check_search_local(  # noqa: C901
        ctx: RunContext[DeepAgentDeps],
        query: str,
        max_results: int = 8,
        file_paths: list[str] | None = None,
    ) -> str:
        """Search specific files (or common workspace/upload targets)
        for evidence matching the query."""

        if not query.strip():
            return "Please provide a non-empty query to search for."

        backend = ctx.deps.backend
        effective_max = _cap_sources(max_results, fact_check_max_resources)
        hits: list[str] = []
        roots = ["/workspace", "/uploads"]

        search_globs = [
            "*.md",
            "*.txt",
            "*.tex",
            "*.rst",
            "*.csv",
            "*.tsv",
            "*.json",
            "*.yaml",
            "*.yml",
        ]

        pattern = re.escape(query.strip()) if query.strip() else query

        # Targeted file list first (uploaded files or explicit list)
        candidate_files: list[str] = []
        if file_paths:
            candidate_files.extend(file_paths)
        else:
            candidate_files.extend(ctx.deps.uploads.keys())

        # If no explicit files, fall back to small glob search per root
        if candidate_files:
            for path in candidate_files:
                res = backend.grep_raw(pattern, path=path)  # type: ignore[arg-type]
                if isinstance(res, str):
                    continue
                for match in res:
                    snippet = _make_snippet(match["line"], query)
                    cite = _citation(match["path"], snippet or query)
                    hits.append(f"- {match['path']}:{match['line_number']}: {snippet} {cite}")
                    if len(hits) >= effective_max:
                        break
                if len(hits) >= effective_max:
                    break

        if len(hits) < effective_max:
            for root in roots:
                for glob in search_globs:
                    res = backend.grep_raw(pattern, path=root, glob=glob)  # type: ignore[arg-type]
                    if isinstance(res, str):
                        continue
                    for match in res:
                        snippet = _make_snippet(match["line"], query)
                        cite = _citation(match["path"], snippet or query)
                        hits.append(f"- {match['path']}:{match['line_number']}: {snippet} {cite}")
                        if len(hits) >= effective_max:
                            break
                    if len(hits) >= effective_max:
                        break
                if len(hits) >= effective_max:
                    break

        # PDF sampling
        pdf_hits = []
        for root in roots:
            pdf_files = backend.glob_info("*.pdf", path=root)  # type: ignore[arg-type]
            for info in pdf_files[:3]:  # limit processing
                raw = backend._read_bytes(info["path"])  # type: ignore[index]
                excerpt = _extract_pdf_excerpt(raw, query)
                if excerpt:
                    cite = _citation(info["path"], excerpt)
                    pdf_hits.append(f"- {info['path']}: {excerpt} {cite}")
                if len(pdf_hits) + len(hits) >= effective_max:
                    break
            if len(pdf_hits) + len(hits) >= effective_max:
                break

        combined = hits + pdf_hits
        if not combined:
            return "No local evidence found in /workspace or /uploads."

        return "Local evidence (top matches):\n" + "\n".join(combined[:effective_max])

    @toolset.tool
    async def fact_check_web_search(
        ctx: RunContext[DeepAgentDeps],
        query: str,
        num_results: int = 5,
    ) -> str:
        """Search the web with Serper for external evidence."""

        if not query.strip():
            return "Please provide a non-empty query to search for."

        api_key = os.getenv("SERPER_API_KEY")
        if not api_key:
            return "Serper API key missing. Set SERPER_API_KEY in the environment or .env file."

        effective_num = _cap_sources(num_results, fact_check_max_resources)

        try:
            results = await _serper_search(query, api_key, num_results=effective_num)
        except Exception as e:  # pragma: no cover - network path
            return f"Serper search failed: {e}"

        if not results:
            return "No web results found."

        lines = ["Web results:"]
        for i, item in enumerate(results[:effective_num], 1):
            title = item.get("title", "").strip()
            link = item.get("link", "").strip()
            snippet = _shorten(item.get("snippet", ""), 260)
            cite = _citation(link, snippet or title or link)
            lines.append(f"{i}. {title}\n   {link}\n   Snippet: {snippet} {cite}")

        return "\n".join(lines)

    @toolset.tool
    async def fact_check_scholar_search(
        ctx: RunContext[DeepAgentDeps],
        query: str,
        num_results: int = 5,
    ) -> str:
        """Search Google Scholar via Serper for academic evidence."""

        if not query.strip():
            return "Please provide a non-empty query to search for."

        api_key = os.getenv("SERPER_API_KEY")
        if not api_key:
            return "Serper API key missing. Set SERPER_API_KEY in the environment or .env file."

        effective_num = _cap_sources(num_results, fact_check_max_resources)

        headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
        payload = {"q": query, "num": effective_num}

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(SERPER_SCHOLAR_API_URL, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:  # pragma: no cover - network path
            return f"Serper scholar search failed: {e}"

        results: list[dict] = []
        for item in data.get("organic", [])[:effective_num]:
            results.append(
                {
                    "title": item.get("title", ""),
                    "link": item.get("link", ""),
                    "snippet": item.get("snippet", ""),
                    "year": item.get("year"),
                    "authors": item.get("authors"),
                }
            )

        if not results:
            return "No scholar results found."

        lines = ["Scholar results:"]
        for i, item in enumerate(results, 1):
            title = item.get("title", "").strip()
            link = item.get("link", "").strip()
            snippet = _shorten(item.get("snippet", ""), 260)
            authors = item.get("authors") or ""
            year = item.get("year") or ""
            meta = f" ({year}, {authors})" if authors or year else ""
            cite = _citation(link, title or snippet or link)
            lines.append(f"{i}. {title}{meta}\n   {link}\n   Snippet: {snippet} {cite}")

        return "\n".join(lines)

    @toolset.tool
    async def fact_check_fetch_url(
        ctx: RunContext[DeepAgentDeps],
        url: str,
        max_chars: int = 4000,
    ) -> str:
        """Fetch a URL and return plain text for citation and verification."""

        async with httpx.AsyncClient(timeout=20) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except Exception as e:  # pragma: no cover - network path
                return f"Failed to fetch URL: {e}"

        content_type = resp.headers.get("content-type", "").lower()
        text = resp.text

        if "html" in content_type:
            text = _strip_html(text, max_chars=max_chars * 2)

        text = textwrap.shorten(text, width=max_chars, placeholder="...")
        cite = _citation(url, text if text else url)
        return f"Fetched content from {url} (content-type: {content_type}):\n{text}\n{cite}"

    return toolset


FACT_CHECKING_SYSTEM_PROMPT = """
## Fact Checking Tools

You have access to Fact Checking tools:

- `fact_check_search_local`: Search for evidence in local files.
- `fact_check_web_search`: Search for evidence on the web.
- `fact_check_fetch_url`: Fetch and extract text from a URL.

### Citation Requirements
- Always attach source links using the citation format `[[citation:PATH_OR_URL|QUOTE]]`.
- For local files (workspace/uploads), use the absolute path (e.g., `/uploads/file.pdf`).
- For web sources, use the full URL.
- Keep quotes short and specific to the claim being supported.
"""
