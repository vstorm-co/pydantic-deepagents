"""Browser toolset for pydantic-deep agents.

Provides async Playwright-backed browser tools: navigate, click, type, screenshot,
get_text, scroll, go_back, go_forward, execute_js.

The toolset requires the ``browser`` optional extra::

    pip install 'pydantic-deep[browser]'

which pulls in ``playwright`` and ``html2text``. After installation, run::

    playwright install chromium

to download the browser binary.

Usage::

    from pydantic_ai import Agent
    from pydantic_deep.capabilities.browser import BrowserCapability

    agent = Agent(
        "anthropic:claude-sonnet-4-6",
        capabilities=[BrowserCapability()],
    )
"""

from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

try:
    import playwright  # noqa: F401

    _HAS_PLAYWRIGHT = True
except ImportError:  # pragma: no cover
    _HAS_PLAYWRIGHT = False

try:
    import html2text as _html2text_module

    _HAS_HTML2TEXT = True
except ImportError:  # pragma: no cover
    _HAS_HTML2TEXT = False

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

DEFAULT_MAX_CONTENT_TOKENS: int = 4000
"""Default max page content tokens injected into the agent context."""

NUM_CHARS_PER_TOKEN: int = 4
"""Approximate characters per token (matches eviction.py convention)."""

DEFAULT_TIMEOUT_MS: int = 30_000
"""Default Playwright navigation timeout in milliseconds."""

# ── Tool description constants ────────────────────────────────────────────

NAVIGATE_DESCRIPTION = """\
Navigate the browser to a URL and return the page content as Markdown.

Args:
    url: Full URL to navigate to (e.g. https://example.com).

Returns page title, current URL, and rendered page content as Markdown.
Content is truncated to max_content_tokens if the page is very large."""

CLICK_DESCRIPTION = """\
Click an element on the current page.

Args:
    selector: CSS selector (e.g. 'button#submit', 'a.nav-link') or pixel
              coordinates as 'x,y' (e.g. '450,300').

Returns updated page content after the click."""

TYPE_TEXT_DESCRIPTION = """\
Type text into an input field on the current page.

Args:
    selector: CSS selector for the target input element.
    text: Text to type. Replaces any existing value in the field.

Returns updated page content after typing."""

SCREENSHOT_DESCRIPTION = """\
Take a screenshot of the current page.

Args:
    full_page: If True, capture the full scrollable page (default False).

Returns base64-encoded PNG image prefixed with the data URI scheme."""

GET_TEXT_DESCRIPTION = """\
Get the text content of the current page or a specific element.

Args:
    selector: CSS selector to extract text from. Omit for full page text.

Returns plain text content (Markdown for full page, raw text for element)."""

SCROLL_DESCRIPTION = """\
Scroll the page in a given direction.

Args:
    direction: 'up', 'down', 'left', or 'right'.
    x: Optional x coordinate for localized scroll (ignored when None).
    y: Optional y coordinate for localized scroll (ignored when None).

Returns updated page content after scrolling."""

GO_BACK_DESCRIPTION = """\
Navigate back in the browser history.

Returns page content of the previous page."""

GO_FORWARD_DESCRIPTION = """\
Navigate forward in the browser history.

Returns page content of the next page."""

EXECUTE_JS_DESCRIPTION = """\
Execute a JavaScript expression in the browser and return the result.

Args:
    script: JavaScript expression to evaluate. The return value is serialised
            to a string. For example: 'document.title' or
            'Array.from(document.querySelectorAll("h1")).map(e => e.innerText)'.

Returns stringified result, or an error message if evaluation failed."""


# ── Internal helpers ──────────────────────────────────────────────────────────


def _require_browser() -> None:
    """Raise ImportError with install hint when playwright is absent."""
    if not _HAS_PLAYWRIGHT:
        raise ImportError(
            "playwright is required for BrowserCapability. "
            "Install it with: pip install 'pydantic-deep[browser]'\n"
            "Then run: playwright install chromium"
        )


def _truncate_content(content: str, max_tokens: int) -> str:
    """Truncate content to approximately max_tokens.

    Keeps the first 70 % of the budget as head and the last 30 % as tail,
    inserting a truncation marker in the middle.

    Args:
        content: Text to truncate.
        max_tokens: Estimated token budget (1 token ≈ 4 chars).

    Returns:
        Original content when short enough, otherwise head + marker + tail.
    """
    max_chars = max_tokens * NUM_CHARS_PER_TOKEN
    if len(content) <= max_chars:
        return content
    head_chars = int(max_chars * 0.7)
    tail_chars = max_chars - head_chars
    omitted = len(content) - max_chars
    marker = f"\n\n... [{omitted} chars truncated] ...\n\n"
    return content[:head_chars] + marker + content[-tail_chars:]


def _html_to_markdown(html: str) -> str:
    """Convert HTML to Markdown.

    Uses ``html2text`` when available, otherwise strips tags with a regex
    fallback.

    Args:
        html: Raw HTML string.

    Returns:
        Markdown representation of the HTML content.
    """
    if _HAS_HTML2TEXT:
        h = _html2text_module.HTML2Text()
        h.ignore_links = False
        h.ignore_images = True
        h.body_width = 0  # no line-wrapping
        return h.handle(html)
    # Fallback: basic tag stripping
    return re.sub(r"<[^>]+>", "", html).strip()


def _check_allowed_domain(url: str, allowed_domains: list[str] | None) -> bool:
    """Return True if the URL's domain is permitted.

    Args:
        url: URL to check.
        allowed_domains: Allowlist of domain strings (e.g. ``["example.com"]``).
            ``None`` means all domains are allowed.

    Returns:
        True when allowed, False otherwise.
    """
    if allowed_domains is None:
        return True
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        # Strip port from domain for comparison
        domain = domain.split(":")[0]
        return any(domain == d.lower() or domain.endswith("." + d.lower()) for d in allowed_domains)
    except Exception:
        return False


# ── Shared browser state ──────────────────────────────────────────────────────


@dataclass
class _BrowserState:
    """Mutable browser state shared between BrowserCapability and BrowserToolset.

    ``BrowserCapability.wrap_run`` sets ``_lazy_launcher`` at the start of
    each agent run.  ``BrowserToolset`` calls ``ensure_page()`` on the first
    tool invocation, which triggers the actual Chromium launch only when a
    browser tool is actually needed — keeping runs that never use the browser
    free of any Playwright overhead.
    """

    page: Any | None = field(default=None)
    """Active playwright.async_api.Page, or None when the browser has not been launched."""

    browser: Any | None = field(default=None)
    """Active playwright.async_api.Browser, or None when the browser has not been launched."""

    playwright_instance: Any | None = field(default=None)
    """Active playwright.async_api.Playwright context, set for the duration of wrap_run."""

    launch_error: str | None = field(default=None)
    """Set when browser launch failed (e.g. Chromium not installed)."""

    _lazy_launcher: Any | None = field(default=None, init=False, repr=False)
    """Async callable installed by BrowserCapability.wrap_run; triggers the actual launch."""

    async def ensure_page(self) -> Any:
        """Return the active page, launching Chromium lazily on the first call.

        Raises:
            RuntimeError: If the browser is not configured (wrap_run not active)
                or if the launch failed.
        """
        if self.launch_error:
            raise RuntimeError(self.launch_error)
        if self.page is None:
            if self._lazy_launcher is None:
                raise RuntimeError(
                    "Browser is not running. BrowserCapability.wrap_run must be active "
                    "before any browser tool is called."
                )
            await self._lazy_launcher()
            if self.page is None:
                raise RuntimeError(self.launch_error or "Browser failed to launch.")
        return self.page


# ── Toolset ───────────────────────────────────────────────────────────────────


class BrowserToolset(FunctionToolset[Any]):
    """Async Playwright-backed browser toolset.

    Tools are registered at construction via ``@self.tool()`` closures that
    capture ``self._state``. The actual Playwright page is injected into
    ``self._state.page`` by ``BrowserCapability.wrap_run`` before any tool is
    invoked.

    Typical usage is through ``BrowserCapability`` rather than directly::

        from pydantic_deep.capabilities.browser import BrowserCapability

        agent = Agent("...", capabilities=[BrowserCapability()])

    Direct usage (advanced)::

        state = _BrowserState()
        toolset = BrowserToolset(state=state)
        # Manually set state.page before calling tools.
    """

    def __init__(
        self,
        *,
        state: _BrowserState,
        allowed_domains: list[str] | None = None,
        screenshot_on_navigate: bool = False,
        max_content_tokens: int = DEFAULT_MAX_CONTENT_TOKENS,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        descriptions: dict[str, str] | None = None,
    ) -> None:
        """Initialise the toolset and register all browser tools.

        Args:
            state: Shared mutable state; ``state.page`` must be set before
                any tool is called (done by ``BrowserCapability.wrap_run``).
            allowed_domains: Domain allowlist. ``None`` allows all domains.
            screenshot_on_navigate: Append a screenshot to ``navigate`` results.
            max_content_tokens: Token budget for page content truncation.
            timeout_ms: Default Playwright timeout in milliseconds.
            descriptions: Optional override map for tool descriptions.
                Keys: ``navigate``, ``click``, ``type_text``, ``screenshot``,
                ``get_text``, ``scroll``, ``go_back``, ``go_forward``,
                ``execute_js``.
        """
        super().__init__(id="deep-browser")
        self._state = state
        self._allowed_domains = allowed_domains
        self._screenshot_on_navigate = screenshot_on_navigate
        self._max_content_tokens = max_content_tokens
        self._timeout_ms = timeout_ms
        descs = descriptions or {}
        self._register_tools(descs)

    # ── Internal helpers ──────────────────────────────────────────────────

    def _get_page(self) -> Any:
        """Return the active page or raise RuntimeError if browser is not running.

        Sync accessor — only valid after ``_ensure_page()`` has been awaited.
        """
        if self._state.page is None:
            if self._state.launch_error:
                raise RuntimeError(self._state.launch_error)
            raise RuntimeError(
                "Browser is not running. BrowserCapability.wrap_run must be active "
                "before any browser tool is called."
            )
        return self._state.page

    async def _ensure_page(self) -> Any:
        """Trigger lazy browser launch and return the active page.

        Call this at the start of every tool function instead of
        ``_get_page()`` so that Chromium is only launched when a tool is
        actually invoked.
        """
        return await self._state.ensure_page()

    async def _page_content_as_markdown(self) -> str:
        """Return current page content as truncated Markdown."""
        page = self._get_page()
        html: str = await page.content()
        md = _html_to_markdown(html)
        return _truncate_content(md, self._max_content_tokens)

    async def _screenshot_b64(self, full_page: bool = False) -> str:
        """Take a screenshot and return it as a base64 string."""
        page = self._get_page()
        png: bytes = await page.screenshot(full_page=full_page)
        return base64.b64encode(png).decode("ascii")

    # ── Tool registration ─────────────────────────────────────────────────

    def _register_tools(self, descs: dict[str, str]) -> None:  # noqa: C901
        """Register all browser tools with the toolset."""

        @self.tool(description=descs.get("navigate", NAVIGATE_DESCRIPTION))
        async def navigate(ctx: RunContext[Any], url: str) -> str:
            """Navigate to a URL and return page content as Markdown.

            Args:
                url: Full URL to navigate to (e.g. https://example.com).
            """
            if not _check_allowed_domain(url, self._allowed_domains):
                return f"Error: domain not in allowed_domains list: {url}"
            page = await self._ensure_page()
            await page.goto(url, timeout=self._timeout_ms)
            await page.wait_for_load_state("domcontentloaded")
            title: str = await page.title()
            content = await self._page_content_as_markdown()
            result = f"URL: {page.url}\nTitle: {title}\n\n{content}"
            if self._screenshot_on_navigate:
                b64 = await self._screenshot_b64()
                result += f"\n\n[screenshot: data:image/png;base64,{b64}]"
            return result

        @self.tool(description=descs.get("click", CLICK_DESCRIPTION))
        async def click(ctx: RunContext[Any], selector: str) -> str:
            """Click an element on the current page.

            Args:
                selector: CSS selector or pixel coordinates 'x,y'.
            """
            page = await self._ensure_page()
            parts = selector.split(",", 1)
            if len(parts) == 2 and all(p.strip().lstrip("-").isdigit() for p in parts):
                x, y = int(parts[0].strip()), int(parts[1].strip())
                await page.mouse.click(x, y)
            else:
                await page.click(selector, timeout=self._timeout_ms)
            await page.wait_for_load_state("domcontentloaded")
            content = await self._page_content_as_markdown()
            return f"Clicked '{selector}'. URL: {page.url}\n\n{content}"

        @self.tool(description=descs.get("type_text", TYPE_TEXT_DESCRIPTION))
        async def type_text(ctx: RunContext[Any], selector: str, text: str) -> str:
            """Type text into an input field.

            Args:
                selector: CSS selector for the target input element.
                text: Text to type (replaces existing value).
            """
            page = await self._ensure_page()
            await page.fill(selector, text, timeout=self._timeout_ms)
            content = await self._page_content_as_markdown()
            return f"Typed into '{selector}'.\n\n{content}"

        @self.tool(description=descs.get("screenshot", SCREENSHOT_DESCRIPTION))
        async def screenshot(ctx: RunContext[Any], full_page: bool = False) -> str:
            """Take a screenshot of the current page.

            Args:
                full_page: Capture the full scrollable page when True.
            """
            page = await self._ensure_page()
            b64 = await self._screenshot_b64(full_page=full_page)
            return f"data:image/png;base64,{b64}\nURL: {page.url}"

        @self.tool(description=descs.get("get_text", GET_TEXT_DESCRIPTION))
        async def get_text(ctx: RunContext[Any], selector: str | None = None) -> str:
            """Get text content of the page or a specific element.

            Args:
                selector: CSS selector to target. Omit for full page Markdown.
            """
            page = await self._ensure_page()
            if selector:
                try:
                    return str(await page.inner_text(selector, timeout=self._timeout_ms))
                except Exception as exc:
                    return f"Error getting text from '{selector}': {exc}"
            return await self._page_content_as_markdown()

        @self.tool(description=descs.get("scroll", SCROLL_DESCRIPTION))
        async def scroll(
            ctx: RunContext[Any],
            direction: str,
            x: int | None = None,
            y: int | None = None,
        ) -> str:
            """Scroll the page.

            Args:
                direction: 'up', 'down', 'left', or 'right'.
                x: Optional x coordinate for localised scroll.
                y: Optional y coordinate for localised scroll.
            """
            page = await self._ensure_page()
            delta_map: dict[str, tuple[int, int]] = {
                "up": (0, -300),
                "down": (0, 300),
                "left": (-300, 0),
                "right": (300, 0),
            }
            dx, dy = delta_map.get(direction.lower(), (0, 300))
            if x is not None and y is not None:
                await page.mouse.move(x, y)
                await page.mouse.wheel(dx, dy)
            else:
                await page.evaluate(f"window.scrollBy({dx}, {dy})")
            content = await self._page_content_as_markdown()
            return f"Scrolled {direction}.\n\n{content}"

        @self.tool(description=descs.get("go_back", GO_BACK_DESCRIPTION))
        async def go_back(ctx: RunContext[Any]) -> str:
            """Navigate back in the browser history."""
            page = await self._ensure_page()
            await page.go_back(timeout=self._timeout_ms)
            await page.wait_for_load_state("domcontentloaded")
            content = await self._page_content_as_markdown()
            return f"Went back. URL: {page.url}\n\n{content}"

        @self.tool(description=descs.get("go_forward", GO_FORWARD_DESCRIPTION))
        async def go_forward(ctx: RunContext[Any]) -> str:
            """Navigate forward in the browser history."""
            page = await self._ensure_page()
            await page.go_forward(timeout=self._timeout_ms)
            await page.wait_for_load_state("domcontentloaded")
            content = await self._page_content_as_markdown()
            return f"Went forward. URL: {page.url}\n\n{content}"

        @self.tool(description=descs.get("execute_js", EXECUTE_JS_DESCRIPTION))
        async def execute_js(ctx: RunContext[Any], script: str) -> str:
            """Execute JavaScript in the browser.

            Args:
                script: JavaScript expression to evaluate.
            """
            page = await self._ensure_page()
            try:
                result = await page.evaluate(script)
                return str(result)
            except Exception as exc:
                return f"JS error: {exc}"
