"""Browser capability for pydantic-deep agents.

Provides a real async Playwright browser to the agent via `BrowserCapability`.
The browser lifecycle (launch on run start, close on run end) is managed through
`wrap_run` - guaranteeing cleanup even when the agent raises an exception.

Example::

    from pydantic_ai import Agent
    from pydantic_deep.features.browser.capability import BrowserCapability

    agent = Agent(
        "anthropic:claude-sonnet-4-6",
        capabilities=[BrowserCapability(headless=True)],
    )
    result = await agent.run("What is the title of https://example.com?")
"""

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass, field, replace
from typing import Any

from pydantic_ai import AgentRunResult, RunContext
from pydantic_ai.capabilities import AbstractCapability, WrapRunHandler
from pydantic_ai.tools import ToolDefinition
from pydantic_ai.toolsets import AbstractToolset

from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.features.browser.toolset import (
    DEFAULT_MAX_CONTENT_TOKENS,
    DEFAULT_TIMEOUT_MS,
    BrowserToolset,
    _BrowserState,
    _check_allowed_domain,
    _require_browser,
)

try:
    from playwright.async_api import async_playwright
except ImportError:  # pragma: no cover
    async_playwright = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


async def _auto_install_chromium() -> bool:
    """Run `playwright install chromium` and return `True` on success.

    Uses the same Python interpreter so that the correct Playwright installation
    is targeted even inside a virtualenv.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "playwright",
            "install",
            "chromium",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.warning(
                "playwright install chromium failed (exit %d): %s",
                proc.returncode,
                stderr.decode(errors="replace").strip(),
            )
            return False
        logger.info("Chromium installed successfully.")
        return True
    except Exception as exc:  # pragma: no cover
        logger.warning("Failed to run playwright install: %s", exc)
        return False


BROWSER_INSTRUCTIONS: str = """\
You have access to a real web browser powered by Playwright.

**When to use the browser (and NOT web_search / web_fetch):**
- Pages that require login, authentication, or session cookies
- JavaScript-heavy SPAs that don't render without JS
- Interactive workflows: clicking buttons, filling forms, multi-step flows
- Scraping paginated or dynamically loaded content
- Visual debugging — taking screenshots to inspect UI

**When to use web_search / web_fetch instead:**
- Looking up information, documentation, or public articles
- Reading a known URL whose content is static or server-rendered
- Any task that doesn't require interaction — prefer the lighter tools

Browser tools:
- `navigate(url)` — go to a URL and read the page as Markdown
- `click(selector)` — click a CSS selector or pixel coordinates 'x,y'
- `type_text(selector, text)` — fill an input field
- `screenshot(full_page?)` — capture a screenshot (base64 PNG)
- `get_text(selector?)` — extract text from the page or a specific element
- `scroll(direction)` — scroll 'up', 'down', 'left', or 'right'
- `go_back()` / `go_forward()` — navigate browser history
- `execute_js(script)` — run JavaScript and get the result

Page content is returned as Markdown and truncated to ~{max_content_tokens} tokens.
Use `get_text` with a CSS selector to extract specific sections of large pages.
The browser is single-tab; new-tab links are redirected to the current tab.
Allowed domains: {allowed_domains}
"""


@dataclass
class BrowserCapability(AbstractCapability[DeepAgentDeps]):
    """Provides a real async Playwright browser to the agent.

    Manages the full browser lifecycle: Playwright and Chromium are started
    lazily on the first browser-tool call and closed in a `finally` block,
    guaranteeing cleanup on both success and failure paths.  Runs that never
    invoke a browser tool incur zero Playwright overhead.

    Requires the `browser` optional extra::

        pip install 'pydantic-deep[browser]'
        playwright install chromium

    Args:
        headless: Run the browser without a visible window (default `True`).
        allowed_domains: Domain allowlist. `None` (default) allows all domains.
            Example: `["docs.python.org", "github.com"]`.
        screenshot_on_navigate: Append a base64 screenshot to every `navigate`
            response (default `False`).
        max_content_tokens: Maximum estimated tokens for page content
            (default `4000`).
        timeout_ms: Default Playwright navigation timeout in milliseconds
            (default `30000`).
        auto_install: Automatically run `playwright install chromium` when
            the Chromium binary is missing (default `True`).  Uses the
            current Python interpreter so virtualenv installs are respected.

    Example::

        from pydantic_ai import Agent
        from pydantic_deep.features.browser.capability import BrowserCapability

        agent = Agent(
            "anthropic:claude-sonnet-4-6",
            capabilities=[
                BrowserCapability(
                    headless=True,
                    allowed_domains=["docs.python.org"],
                )
            ],
        )
        result = await agent.run("What's new in Python 3.13?")
    """

    headless: bool = True
    allowed_domains: list[str] | None = None
    screenshot_on_navigate: bool = False
    max_content_tokens: int = DEFAULT_MAX_CONTENT_TOKENS
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    auto_install: bool = True

    _BROWSER_TOOL_NAMES: frozenset[str] = frozenset(
        {
            "navigate",
            "click",
            "type_text",
            "screenshot",
            "get_text",
            "scroll",
            "go_back",
            "go_forward",
            "execute_js",
        }
    )

    _state: _BrowserState = field(default_factory=_BrowserState, init=False, repr=False)
    _toolset: BrowserToolset | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._state = _BrowserState()
        self._toolset = BrowserToolset(
            state=self._state,
            allowed_domains=self.allowed_domains,
            screenshot_on_navigate=self.screenshot_on_navigate,
            max_content_tokens=self.max_content_tokens,
            timeout_ms=self.timeout_ms,
        )

    def get_toolset(self) -> AbstractToolset[Any] | None:
        return self._toolset

    def get_instructions(self) -> Any:
        def _instructions(ctx: RunContext[DeepAgentDeps]) -> str | None:
            if self._state.launch_error:
                return None
            return BROWSER_INSTRUCTIONS.format(
                max_content_tokens=self.max_content_tokens,
                allowed_domains=", ".join(self.allowed_domains) if self.allowed_domains else "all",
            )

        return _instructions

    async def prepare_tools(
        self,
        ctx: RunContext[DeepAgentDeps],
        tool_defs: list[ToolDefinition],
    ) -> list[ToolDefinition]:
        """Filter browser tools based on availability and approval state.

        - When Chromium is not installed (`launch_error` is set), browser
          tools are hidden from the model entirely - no point offering tools
          that always return an error.
        - When the browser is available, any browser tool marked as
          `unapproved` is reset to `function` so it never triggers
          approval dialogs.
        """

        # If browser failed to launch, hide browser tools completely
        if self._state.launch_error:
            return [td for td in tool_defs if td.name not in self._BROWSER_TOOL_NAMES]

        result: list[ToolDefinition] = []
        for td in tool_defs:
            if td.name in self._BROWSER_TOOL_NAMES and td.kind == "unapproved":
                result.append(replace(td, kind="function"))
            else:
                result.append(td)
        return result

    async def wrap_run(  # noqa: C901
        self,
        ctx: RunContext[DeepAgentDeps],
        *,
        handler: WrapRunHandler,
    ) -> AgentRunResult[Any]:
        """Install a lazy browser launcher and clean up after the run.

        Both Playwright and Chromium are started only when the first browser
        tool is actually called.  Runs that never use the browser incur zero
        Playwright overhead - no subprocess is spawned, no browser window
        appears.

        A `finally` block guarantees cleanup of the browser and the
        Playwright driver whether the run succeeds, raises, or is cancelled.

        If Chromium is not installed and `auto_install` is `True` (the
        default), `playwright install chromium` is run automatically on the
        first tool call, and the launch is retried once.
        """
        _require_browser()
        assert async_playwright is not None  # guaranteed by _require_browser()
        _start_playwright = async_playwright  # local non-None reference for the closure

        _pw_ctx: Any = None  # Playwright context manager - entered lazily

        async def _launch() -> None:
            nonlocal _pw_ctx
            _pw_ctx = _start_playwright()
            pw = await _pw_ctx.__aenter__()
            self._state.playwright_instance = pw

            browser = None
            try:
                browser = await pw.chromium.launch(headless=self.headless)
            except Exception as first_exc:
                if self.auto_install:
                    logger.info(
                        "Chromium binary not found (%s). "
                        "Attempting auto-install via `playwright install chromium`…",
                        first_exc,
                    )
                    installed = await _auto_install_chromium()
                    if installed:
                        try:
                            browser = await pw.chromium.launch(headless=self.headless)
                        except Exception as retry_exc:  # pragma: no cover
                            logger.warning(
                                "Chromium launch failed after auto-install: %s",
                                retry_exc,
                            )

                if browser is None:
                    logger.warning(
                        "Browser unavailable — Chromium binary not found. "
                        "Run `playwright install chromium` to enable browser tools. "
                        "Error: %s",
                        first_exc,
                    )
                    self._state.launch_error = (
                        "Chromium is not installed. Run `playwright install chromium` "
                        "and restart the agent to enable browser tools."
                    )
                    return

            page = await browser.new_page()

            # Network-level allowlist enforcement: abort top-level navigation
            # requests to disallowed domains. This is the real boundary - it
            # covers every navigation path (navigate, click, execute_js,
            # go_back, go_forward) rather than just the navigate tool, so the
            # allowlist cannot be bypassed by clicking a cross-domain link or
            # setting location.href from JavaScript.
            if self.allowed_domains is not None:

                async def _route_guard(route: Any, request: Any) -> None:
                    if (
                        request.is_navigation_request()
                        and request.frame == page.main_frame
                        and not _check_allowed_domain(request.url, self.allowed_domains)
                    ):
                        await route.abort()
                        return
                    await route.continue_()

                await page.route("**/*", _route_guard)

            # Single-tab design: redirect popup windows back to the current tab,
            # but only when the popup URL passes the domain allowlist - otherwise
            # a popup could be used to bypass allowed_domains.
            async def _handle_popup(popup: Any) -> None:
                # Close the popup first, then navigate the main tab. Sequencing
                # both steps inside one coroutine gives deterministic ordering
                # instead of racing two independent tasks.
                new_url = popup.url
                await popup.close()
                if _check_allowed_domain(new_url, self.allowed_domains):
                    await page.goto(new_url)

            def _on_popup(popup: Any) -> None:
                # Keep a strong reference to the task so it is not garbage
                # collected before completion, and attach a done callback that
                # retrieves/logs any exception and discards the reference.
                task = asyncio.ensure_future(_handle_popup(popup))
                self._state._popup_tasks.add(task)

                def _on_done(finished: Any) -> None:
                    self._state._popup_tasks.discard(finished)
                    if finished.cancelled():
                        return
                    exc = finished.exception()
                    if exc is not None:
                        logger.warning("Popup handling task failed: %s", exc)

                task.add_done_callback(_on_done)

            page.on("popup", _on_popup)

            self._state.browser = browser
            self._state.page = page

        self._state._lazy_launcher = _launch
        try:
            return await handler()
        finally:
            self._state._lazy_launcher = None
            self._state.playwright_instance = None
            # NOTE: `launch_error` is intentionally NOT cleared here. `_state`
            # is created once in `__post_init__` and is shared across every run,
            # so a launch failure must persist to keep browser tools hidden (via
            # `prepare_tools`) until the process is restarted - matching the
            # "restart the agent to enable browser tools" message. Clearing it
            # would re-expose the tools and re-attempt the still-failing launch
            # (paying the auto-install cost) on every subsequent run.
            if self._state.browser is not None:
                browser = self._state.browser
                self._state.page = None
                self._state.browser = None
                await browser.close()
            else:
                self._state.page = None
            if _pw_ctx is not None:
                await _pw_ctx.__aexit__(None, None, None)
