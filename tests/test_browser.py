"""Tests for BrowserToolset and BrowserCapability."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from pydantic_deep.capabilities.browser import (
    BROWSER_INSTRUCTIONS,
    BrowserCapability,
    _auto_install_chromium,
)
from pydantic_deep.toolsets.browser import (
    DEFAULT_MAX_CONTENT_TOKENS,
    DEFAULT_TIMEOUT_MS,
    BrowserToolset,
    _BrowserState,
    _check_allowed_domain,
    _html_to_markdown,
    _require_browser,
    _truncate_content,
)
from pydantic_deep.types import BrowseResult

TEST_MODEL = TestModel()


def _ctx(deps: Any = None) -> Any:
    from pydantic_ai import RunContext

    return RunContext(deps=deps, model=TEST_MODEL, usage=RunUsage())


# ── _BrowserState ─────────────────────────────────────────────────────────────


class TestBrowserState:
    def test_defaults(self) -> None:
        state = _BrowserState()
        assert state.page is None
        assert state.browser is None
        assert state.playwright_instance is None

    def test_fields_assignable(self) -> None:
        state = _BrowserState()
        mock = MagicMock()
        state.page = mock
        state.browser = mock
        state.playwright_instance = mock
        assert state.page is mock
        assert state.browser is mock
        assert state.playwright_instance is mock


# ── _require_browser ──────────────────────────────────────────────────────────


class TestRequireBrowser:
    def test_raises_when_playwright_missing(self) -> None:
        with (
            patch("pydantic_deep.toolsets.browser._HAS_PLAYWRIGHT", False),
            pytest.raises(ImportError, match="playwright"),
        ):
            _require_browser()

    def test_noop_when_available(self) -> None:
        with patch("pydantic_deep.toolsets.browser._HAS_PLAYWRIGHT", True):
            _require_browser()  # must not raise


# ── _auto_install_chromium ────────────────────────────────────────────────────


class TestAutoInstallChromium:
    @pytest.mark.asyncio
    async def test_returns_true_on_success(self) -> None:
        """Returns True when playwright install exits with code 0."""
        mock_proc = AsyncMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))

        with patch(
            "pydantic_deep.capabilities.browser.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ):
            result = await _auto_install_chromium()

        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_on_nonzero_exit(self) -> None:
        """Returns False when playwright install exits with non-zero code."""
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b"some error"))

        with patch(
            "pydantic_deep.capabilities.browser.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ):
            result = await _auto_install_chromium()

        assert result is False


# ── _truncate_content ─────────────────────────────────────────────────────────


class TestTruncateContent:
    def test_no_truncation_when_short(self) -> None:
        text = "hello world"
        assert _truncate_content(text, max_tokens=100) == text

    def test_exact_limit_not_truncated(self) -> None:
        text = "x" * 400  # 400 chars == 100 tokens exactly
        result = _truncate_content(text, max_tokens=100)
        assert result == text

    def test_truncation_inserts_marker(self) -> None:
        text = "a" * 10_000
        result = _truncate_content(text, max_tokens=100)
        assert "truncated" in result
        assert len(result) < len(text)

    def test_head_is_70_percent(self) -> None:
        text = "A" * 800 + "B" * 800  # 1600 chars
        # max_tokens=100 → max_chars=400, head=280, tail=120
        result = _truncate_content(text, max_tokens=100)
        head_part = result.split("...")[0]
        assert "A" in head_part
        assert "B" not in head_part.replace(" ", "").replace("\n", "")

    def test_tail_contains_end_of_text(self) -> None:
        text = "A" * 2000 + "ZEND"
        result = _truncate_content(text, max_tokens=10)
        assert result.endswith("ZEND")

    @pytest.mark.parametrize("direction", ["up", "down", "left", "right"])
    def test_scroll_directions_accepted(self, direction: str) -> None:
        # Smoke test that the direction string itself doesn't affect truncation logic
        text = "x" * 5
        assert _truncate_content(text, 100) == text


# ── _html_to_markdown ─────────────────────────────────────────────────────────


class TestHtmlToMarkdown:
    def test_uses_html2text_when_available(self) -> None:
        mock_handler = MagicMock()
        mock_handler.handle.return_value = "# Title"
        mock_module = MagicMock()
        mock_module.HTML2Text.return_value = mock_handler

        with (
            patch("pydantic_deep.toolsets.browser._HAS_HTML2TEXT", True),
            patch("pydantic_deep.toolsets.browser._html2text_module", mock_module),
        ):
            result = _html_to_markdown("<h1>Title</h1>")

        mock_module.HTML2Text.assert_called_once()
        assert result == "# Title"

    def test_fallback_strips_tags(self) -> None:
        with patch("pydantic_deep.toolsets.browser._HAS_HTML2TEXT", False):
            result = _html_to_markdown("<p>Hello <b>world</b></p>")
        assert "Hello" in result
        assert "world" in result
        assert "<" not in result

    def test_fallback_empty_html(self) -> None:
        with patch("pydantic_deep.toolsets.browser._HAS_HTML2TEXT", False):
            result = _html_to_markdown("")
        assert result == ""

    def test_fallback_plain_text_unchanged(self) -> None:
        with patch("pydantic_deep.toolsets.browser._HAS_HTML2TEXT", False):
            result = _html_to_markdown("no tags here")
        assert result == "no tags here"


# ── _check_allowed_domain ─────────────────────────────────────────────────────


class TestCheckAllowedDomain:
    def test_none_allows_all(self) -> None:
        assert _check_allowed_domain("https://example.com", None) is True

    def test_exact_domain_allowed(self) -> None:
        assert _check_allowed_domain("https://example.com/path", ["example.com"]) is True

    def test_subdomain_allowed(self) -> None:
        assert _check_allowed_domain("https://docs.example.com", ["example.com"]) is True

    def test_different_domain_blocked(self) -> None:
        assert _check_allowed_domain("https://evil.com", ["example.com"]) is False

    def test_empty_list_blocks_all(self) -> None:
        assert _check_allowed_domain("https://example.com", []) is False

    def test_case_insensitive(self) -> None:
        assert _check_allowed_domain("https://EXAMPLE.COM", ["example.com"]) is True

    def test_domain_with_port(self) -> None:
        assert _check_allowed_domain("https://example.com:8080/path", ["example.com"]) is True

    def test_invalid_url_returns_false(self) -> None:
        assert _check_allowed_domain("not-a-url", ["example.com"]) is False

    def test_urlparse_exception_returns_false(self) -> None:
        with patch("pydantic_deep.toolsets.browser.urlparse", side_effect=Exception("parse error")):
            assert _check_allowed_domain("https://example.com", ["example.com"]) is False


# ── BrowserToolset helpers ────────────────────────────────────────────────────


def _make_page() -> AsyncMock:
    page = AsyncMock()
    page.url = "https://example.com"
    page.title = AsyncMock(return_value="Example Domain")
    page.content = AsyncMock(return_value="<html><body><p>Hello world</p></body></html>")
    page.goto = AsyncMock()
    page.wait_for_load_state = AsyncMock()
    page.click = AsyncMock()
    page.fill = AsyncMock()
    page.screenshot = AsyncMock(return_value=b"\x89PNG\r\n\x1a\n")
    page.inner_text = AsyncMock(return_value="Hello world")
    page.evaluate = AsyncMock(return_value="js-result")
    page.go_back = AsyncMock()
    page.go_forward = AsyncMock()
    page.mouse = AsyncMock()
    page.mouse.click = AsyncMock()
    page.mouse.move = AsyncMock()
    page.mouse.wheel = AsyncMock()
    return page


# ── BrowserToolset ────────────────────────────────────────────────────────────


class TestBrowserStateEnsurePage:
    @pytest.mark.asyncio
    async def test_ensure_page_raises_when_no_launcher(self) -> None:
        state = _BrowserState()
        with pytest.raises(RuntimeError, match="Browser is not running"):
            await state.ensure_page()

    @pytest.mark.asyncio
    async def test_ensure_page_raises_when_launch_error_set(self) -> None:
        state = _BrowserState(launch_error="Chromium not installed")
        with pytest.raises(RuntimeError, match="Chromium not installed"):
            await state.ensure_page()

    @pytest.mark.asyncio
    async def test_ensure_page_calls_launcher_and_returns_page(self) -> None:
        mock_page = MagicMock()
        called = False

        async def launcher() -> None:
            nonlocal called
            called = True
            state.page = mock_page

        state = _BrowserState()
        state._lazy_launcher = launcher
        result = await state.ensure_page()
        assert result is mock_page
        assert called

    @pytest.mark.asyncio
    async def test_ensure_page_returns_existing_page_without_relaunching(self) -> None:
        mock_page = MagicMock()
        called = False

        async def launcher() -> None:  # pragma: no cover
            nonlocal called
            called = True

        state = _BrowserState(page=mock_page)
        state._lazy_launcher = launcher
        result = await state.ensure_page()
        assert result is mock_page
        assert not called  # launcher not called when page already set

    @pytest.mark.asyncio
    async def test_ensure_page_raises_when_launcher_sets_launch_error(self) -> None:
        async def failing_launcher() -> None:
            state.launch_error = "install failed"

        state = _BrowserState()
        state._lazy_launcher = failing_launcher
        with pytest.raises(RuntimeError, match="install failed"):
            await state.ensure_page()


class TestBrowserToolset:
    def test_get_page_raises_when_no_page(self) -> None:
        state = _BrowserState()
        ts = BrowserToolset(state=state)
        with pytest.raises(RuntimeError, match="Browser is not running"):
            ts._get_page()

    def test_get_page_returns_page(self) -> None:
        mock_page = MagicMock()
        state = _BrowserState(page=mock_page)
        ts = BrowserToolset(state=state)
        assert ts._get_page() is mock_page

    @pytest.mark.asyncio
    async def test_ensure_page_triggers_lazy_launch(self) -> None:
        mock_page = MagicMock()

        async def launcher() -> None:
            state.page = mock_page

        state = _BrowserState()
        state._lazy_launcher = launcher
        ts = BrowserToolset(state=state)
        result = await ts._ensure_page()
        assert result is mock_page

    def test_tools_registered(self) -> None:
        ts = BrowserToolset(state=_BrowserState())
        tool_names = {t.name for t in ts.tools.values()}
        expected = {
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
        assert expected.issubset(tool_names)

    def test_custom_descriptions(self) -> None:
        ts = BrowserToolset(
            state=_BrowserState(),
            descriptions={"navigate": "Custom navigate description"},
        )
        tool = next(t for t in ts.tools.values() if t.name == "navigate")
        assert tool.description == "Custom navigate description"

    @pytest.mark.asyncio
    async def test_navigate_success(self) -> None:
        page = _make_page()
        state = _BrowserState(page=page)
        ts = BrowserToolset(state=state)
        ctx = _ctx()

        with patch("pydantic_deep.toolsets.browser._HAS_HTML2TEXT", False):
            tool = next(t for t in ts.tools.values() if t.name == "navigate")
            result = await tool.function(ctx, "https://example.com")

        assert "example.com" in result.lower() or "Example" in result
        page.goto.assert_called_once()

    @pytest.mark.asyncio
    async def test_navigate_blocked_domain(self) -> None:
        page = _make_page()
        state = _BrowserState(page=page)
        ts = BrowserToolset(state=state, allowed_domains=["safe.com"])
        ctx = _ctx()

        tool = next(t for t in ts.tools.values() if t.name == "navigate")
        result = await tool.function(ctx, "https://evil.com/")

        assert "allowed_domains" in result
        page.goto.assert_not_called()

    @pytest.mark.asyncio
    async def test_navigate_with_screenshot(self) -> None:
        page = _make_page()
        state = _BrowserState(page=page)
        ts = BrowserToolset(state=state, screenshot_on_navigate=True)
        ctx = _ctx()

        with patch("pydantic_deep.toolsets.browser._HAS_HTML2TEXT", False):
            tool = next(t for t in ts.tools.values() if t.name == "navigate")
            result = await tool.function(ctx, "https://example.com")

        assert "data:image/png;base64," in result

    @pytest.mark.asyncio
    async def test_click_css_selector(self) -> None:
        page = _make_page()
        state = _BrowserState(page=page)
        ts = BrowserToolset(state=state)
        ctx = _ctx()

        with patch("pydantic_deep.toolsets.browser._HAS_HTML2TEXT", False):
            tool = next(t for t in ts.tools.values() if t.name == "click")
            result = await tool.function(ctx, "button#submit")

        page.click.assert_called_once_with("button#submit", timeout=DEFAULT_TIMEOUT_MS)
        assert "Clicked" in result

    @pytest.mark.asyncio
    async def test_click_coordinates(self) -> None:
        page = _make_page()
        state = _BrowserState(page=page)
        ts = BrowserToolset(state=state)
        ctx = _ctx()

        with patch("pydantic_deep.toolsets.browser._HAS_HTML2TEXT", False):
            tool = next(t for t in ts.tools.values() if t.name == "click")
            await tool.function(ctx, "100,200")

        page.mouse.click.assert_called_once_with(100, 200)

    @pytest.mark.asyncio
    async def test_type_text(self) -> None:
        page = _make_page()
        state = _BrowserState(page=page)
        ts = BrowserToolset(state=state)
        ctx = _ctx()

        with patch("pydantic_deep.toolsets.browser._HAS_HTML2TEXT", False):
            tool = next(t for t in ts.tools.values() if t.name == "type_text")
            result = await tool.function(ctx, "#search", "hello")

        page.fill.assert_called_once_with("#search", "hello", timeout=DEFAULT_TIMEOUT_MS)
        assert "Typed" in result

    @pytest.mark.asyncio
    async def test_screenshot_default(self) -> None:
        page = _make_page()
        state = _BrowserState(page=page)
        ts = BrowserToolset(state=state)
        ctx = _ctx()

        tool = next(t for t in ts.tools.values() if t.name == "screenshot")
        result = await tool.function(ctx)

        page.screenshot.assert_called_once_with(full_page=False)
        assert "data:image/png;base64," in result

    @pytest.mark.asyncio
    async def test_screenshot_full_page(self) -> None:
        page = _make_page()
        state = _BrowserState(page=page)
        ts = BrowserToolset(state=state)
        ctx = _ctx()

        tool = next(t for t in ts.tools.values() if t.name == "screenshot")
        await tool.function(ctx, True)

        page.screenshot.assert_called_once_with(full_page=True)

    @pytest.mark.asyncio
    async def test_get_text_full_page(self) -> None:
        page = _make_page()
        state = _BrowserState(page=page)
        ts = BrowserToolset(state=state)
        ctx = _ctx()

        with patch("pydantic_deep.toolsets.browser._HAS_HTML2TEXT", False):
            tool = next(t for t in ts.tools.values() if t.name == "get_text")
            result = await tool.function(ctx)

        assert "Hello world" in result

    @pytest.mark.asyncio
    async def test_get_text_with_selector(self) -> None:
        page = _make_page()
        state = _BrowserState(page=page)
        ts = BrowserToolset(state=state)
        ctx = _ctx()

        tool = next(t for t in ts.tools.values() if t.name == "get_text")
        result = await tool.function(ctx, "h1")

        page.inner_text.assert_called_once_with("h1", timeout=DEFAULT_TIMEOUT_MS)
        assert result == "Hello world"

    @pytest.mark.asyncio
    async def test_get_text_selector_error(self) -> None:
        page = _make_page()
        page.inner_text = AsyncMock(side_effect=Exception("not found"))
        state = _BrowserState(page=page)
        ts = BrowserToolset(state=state)
        ctx = _ctx()

        tool = next(t for t in ts.tools.values() if t.name == "get_text")
        result = await tool.function(ctx, "h99")

        assert "Error" in result

    @pytest.mark.parametrize("direction", ["up", "down", "left", "right"])
    @pytest.mark.asyncio
    async def test_scroll_directions(self, direction: str) -> None:
        page = _make_page()
        state = _BrowserState(page=page)
        ts = BrowserToolset(state=state)
        ctx = _ctx()

        with patch("pydantic_deep.toolsets.browser._HAS_HTML2TEXT", False):
            tool = next(t for t in ts.tools.values() if t.name == "scroll")
            result = await tool.function(ctx, direction)

        assert f"Scrolled {direction}" in result

    @pytest.mark.asyncio
    async def test_scroll_with_coordinates(self) -> None:
        page = _make_page()
        state = _BrowserState(page=page)
        ts = BrowserToolset(state=state)
        ctx = _ctx()

        with patch("pydantic_deep.toolsets.browser._HAS_HTML2TEXT", False):
            tool = next(t for t in ts.tools.values() if t.name == "scroll")
            await tool.function(ctx, "down", 100, 200)

        page.mouse.move.assert_called_once_with(100, 200)
        page.mouse.wheel.assert_called_once()

    @pytest.mark.asyncio
    async def test_go_back(self) -> None:
        page = _make_page()
        state = _BrowserState(page=page)
        ts = BrowserToolset(state=state)
        ctx = _ctx()

        with patch("pydantic_deep.toolsets.browser._HAS_HTML2TEXT", False):
            tool = next(t for t in ts.tools.values() if t.name == "go_back")
            result = await tool.function(ctx)

        page.go_back.assert_called_once_with(timeout=DEFAULT_TIMEOUT_MS)
        assert "Went back" in result

    @pytest.mark.asyncio
    async def test_go_forward(self) -> None:
        page = _make_page()
        state = _BrowserState(page=page)
        ts = BrowserToolset(state=state)
        ctx = _ctx()

        with patch("pydantic_deep.toolsets.browser._HAS_HTML2TEXT", False):
            tool = next(t for t in ts.tools.values() if t.name == "go_forward")
            result = await tool.function(ctx)

        page.go_forward.assert_called_once_with(timeout=DEFAULT_TIMEOUT_MS)
        assert "Went forward" in result

    @pytest.mark.asyncio
    async def test_execute_js_success(self) -> None:
        page = _make_page()
        state = _BrowserState(page=page)
        ts = BrowserToolset(state=state)
        ctx = _ctx()

        tool = next(t for t in ts.tools.values() if t.name == "execute_js")
        result = await tool.function(ctx, "document.title")

        assert result == "js-result"

    @pytest.mark.asyncio
    async def test_execute_js_error(self) -> None:
        page = _make_page()
        page.evaluate = AsyncMock(side_effect=Exception("syntax error"))
        state = _BrowserState(page=page)
        ts = BrowserToolset(state=state)
        ctx = _ctx()

        tool = next(t for t in ts.tools.values() if t.name == "execute_js")
        result = await tool.function(ctx, "??invalid??")

        assert "JS error" in result


# ── BrowserCapability ─────────────────────────────────────────────────────────


def _make_playwright_mock() -> tuple[AsyncMock, AsyncMock, AsyncMock]:
    """Return (pw_ctx_manager, browser_mock, page_mock)."""
    page = _make_page()

    browser = AsyncMock()
    browser.new_page = AsyncMock(return_value=page)
    browser.close = AsyncMock()

    chromium = AsyncMock()
    chromium.launch = AsyncMock(return_value=browser)

    pw = AsyncMock()
    pw.chromium = chromium
    pw.__aenter__ = AsyncMock(return_value=pw)
    pw.__aexit__ = AsyncMock(return_value=False)

    return pw, browser, page


class TestBrowserCapability:
    def test_default_construction(self) -> None:
        cap = BrowserCapability()
        assert cap.headless is True
        assert cap.allowed_domains is None
        assert cap.screenshot_on_navigate is False
        assert cap.max_content_tokens == DEFAULT_MAX_CONTENT_TOKENS
        assert cap.timeout_ms == DEFAULT_TIMEOUT_MS
        assert cap.auto_install is True
        assert cap._toolset is not None
        assert cap._state is not None

    def test_custom_fields(self) -> None:
        cap = BrowserCapability(
            headless=False,
            allowed_domains=["example.com"],
            screenshot_on_navigate=True,
            max_content_tokens=1000,
            timeout_ms=5000,
        )
        assert cap.headless is False
        assert cap.allowed_domains == ["example.com"]
        assert cap.screenshot_on_navigate is True
        assert cap.max_content_tokens == 1000
        assert cap.timeout_ms == 5000

    def test_get_toolset_returns_toolset(self) -> None:
        cap = BrowserCapability()
        assert cap.get_toolset() is cap._toolset

    def test_get_instructions_contains_key_terms(self) -> None:
        cap = BrowserCapability()
        instr_fn = cap.get_instructions()
        instr = instr_fn(_ctx())
        assert isinstance(instr, str)
        assert "navigate" in instr
        assert "screenshot" in instr
        assert "all" in instr  # allowed_domains = None → "all"

    def test_get_instructions_shows_custom_domains(self) -> None:
        cap = BrowserCapability(allowed_domains=["docs.python.org", "github.com"])
        instr = cap.get_instructions()(_ctx())
        assert "docs.python.org" in instr
        assert "github.com" in instr

    def test_get_instructions_shows_max_tokens(self) -> None:
        cap = BrowserCapability(max_content_tokens=9999)
        instr = cap.get_instructions()(_ctx())
        assert "9999" in instr

    @pytest.mark.asyncio
    async def test_wrap_run_installs_lazy_launcher(self) -> None:
        """wrap_run installs _lazy_launcher on state; does NOT eagerly launch Chromium."""
        cap = BrowserCapability()
        pw, browser, page = _make_playwright_mock()

        launcher_installed: Any = None

        async def handler() -> Any:
            nonlocal launcher_installed
            # At handler entry the browser has NOT been launched yet
            assert cap._state.page is None
            launcher_installed = cap._state._lazy_launcher
            return MagicMock()

        with (
            patch("pydantic_deep.capabilities.browser._require_browser"),
            patch("pydantic_deep.capabilities.browser.async_playwright", return_value=pw),
        ):
            await cap.wrap_run(_ctx(), handler=handler)

        assert launcher_installed is not None  # launcher was installed
        pw.chromium.launch.assert_not_called()  # Chromium NOT started
        browser.close.assert_not_called()  # nothing to close

    @pytest.mark.asyncio
    async def test_lazy_launcher_injects_page_and_cleanup_works(self) -> None:
        """Calling _lazy_launcher() starts the browser; finally closes it."""
        cap = BrowserCapability()
        pw, browser, page = _make_playwright_mock()

        page_during_run: Any = None

        async def handler() -> Any:
            nonlocal page_during_run
            # Simulate a tool call: trigger lazy launch
            assert cap._state._lazy_launcher is not None
            await cap._state._lazy_launcher()
            page_during_run = cap._state.page
            return MagicMock()

        with (
            patch("pydantic_deep.capabilities.browser._require_browser"),
            patch("pydantic_deep.capabilities.browser.async_playwright", return_value=pw),
        ):
            await cap.wrap_run(_ctx(), handler=handler)

        assert page_during_run is page
        assert cap._state.page is None
        assert cap._state.browser is None
        assert cap._state.playwright_instance is None
        browser.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_wrap_run_cleans_up_on_exception_without_launch(self) -> None:
        """If the handler raises before any tool call, no browser is opened or closed."""
        cap = BrowserCapability()
        pw, browser, _ = _make_playwright_mock()

        async def handler() -> Any:
            raise RuntimeError("agent exploded")

        with (
            patch("pydantic_deep.capabilities.browser._require_browser"),
            patch("pydantic_deep.capabilities.browser.async_playwright", return_value=pw),
            pytest.raises(RuntimeError, match="agent exploded"),
        ):
            await cap.wrap_run(_ctx(), handler=handler)

        assert cap._state.page is None
        browser.close.assert_not_called()  # browser was never launched

    @pytest.mark.asyncio
    async def test_wrap_run_cleans_up_browser_if_launched_then_exception(self) -> None:
        """If the browser was lazily launched and then the handler raises, it is closed."""
        cap = BrowserCapability()
        pw, browser, page = _make_playwright_mock()

        async def handler() -> Any:
            assert cap._state._lazy_launcher is not None
            await cap._state._lazy_launcher()  # triggers launch
            raise RuntimeError("tool failed")

        with (
            patch("pydantic_deep.capabilities.browser._require_browser"),
            patch("pydantic_deep.capabilities.browser.async_playwright", return_value=pw),
            pytest.raises(RuntimeError, match="tool failed"),
        ):
            await cap.wrap_run(_ctx(), handler=handler)

        assert cap._state.page is None
        browser.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_wrap_run_proceeds_without_browser_when_launch_fails(self) -> None:
        """Launch_error is set when Chromium is missing and auto-install fails."""
        cap = BrowserCapability()
        pw, browser, page = _make_playwright_mock()
        pw.chromium.launch = AsyncMock(side_effect=Exception("Executable doesn't exist"))

        error_during_run: str | None = None

        async def handler() -> Any:
            nonlocal error_during_run
            assert cap._state._lazy_launcher is not None
            await cap._state._lazy_launcher()  # triggers failed launch
            error_during_run = cap._state.launch_error
            return MagicMock()

        with (
            patch("pydantic_deep.capabilities.browser._require_browser"),
            patch("pydantic_deep.capabilities.browser.async_playwright", return_value=pw),
            patch(
                "pydantic_deep.capabilities.browser._auto_install_chromium",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            await cap.wrap_run(_ctx(), handler=handler)

        assert cap._state.page is None
        assert "playwright install chromium" in (error_during_run or "")

    @pytest.mark.asyncio
    async def test_wrap_run_auto_installs_and_retries_on_launch_failure(self) -> None:
        """When launch fails but auto-install succeeds, browser is launched on retry."""
        cap = BrowserCapability()
        pw, browser, page = _make_playwright_mock()

        # First call raises, second call (after install) succeeds.
        pw.chromium.launch = AsyncMock(side_effect=[Exception("binary missing"), browser])

        page_during_run: Any = None

        async def handler() -> Any:
            nonlocal page_during_run
            assert cap._state._lazy_launcher is not None
            await cap._state._lazy_launcher()  # triggers lazy launch + auto-install
            page_during_run = cap._state.page
            return MagicMock()

        with (
            patch("pydantic_deep.capabilities.browser._require_browser"),
            patch("pydantic_deep.capabilities.browser.async_playwright", return_value=pw),
            patch(
                "pydantic_deep.capabilities.browser._auto_install_chromium",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            await cap.wrap_run(_ctx(), handler=handler)

        assert page_during_run is page
        browser.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_wrap_run_no_auto_install_when_disabled(self) -> None:
        """When auto_install=False, no install attempt is made on launch failure."""
        cap = BrowserCapability(auto_install=False)
        pw, browser, _ = _make_playwright_mock()
        pw.chromium.launch = AsyncMock(side_effect=Exception("binary missing"))

        async def handler() -> Any:
            assert cap._state._lazy_launcher is not None
            await cap._state._lazy_launcher()  # triggers failed launch
            return MagicMock()

        mock_installer = AsyncMock()
        with (
            patch("pydantic_deep.capabilities.browser._require_browser"),
            patch("pydantic_deep.capabilities.browser.async_playwright", return_value=pw),
            patch(
                "pydantic_deep.capabilities.browser._auto_install_chromium",
                mock_installer,
            ),
        ):
            await cap.wrap_run(_ctx(), handler=handler)

        mock_installer.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_page_returns_launch_error_message(self) -> None:
        """_get_page raises RuntimeError with launch_error when browser failed to start."""
        from pydantic_deep.toolsets.browser import BrowserToolset, _BrowserState

        state = _BrowserState(
            launch_error="Chromium is not installed. Run `playwright install chromium`"
        )
        toolset = BrowserToolset(state=state)

        with pytest.raises(RuntimeError, match="playwright install chromium"):
            toolset._get_page()

    @pytest.mark.asyncio
    async def test_wrap_run_raises_import_error_when_no_playwright(self) -> None:
        cap = BrowserCapability()

        with (
            patch(
                "pydantic_deep.capabilities.browser._require_browser",
                side_effect=ImportError("playwright not installed"),
            ),
            pytest.raises(ImportError, match="playwright"),
        ):
            await cap.wrap_run(_ctx(), handler=AsyncMock())

    @pytest.mark.asyncio
    async def test_wrap_run_popup_handler_registered(self) -> None:
        """Popup handler is registered on the page after lazy launch."""
        cap = BrowserCapability()
        pw, browser, page = _make_playwright_mock()
        registered_events: list[str] = []

        def on_event(event: str, callback: Any) -> None:
            registered_events.append(event)

        page.on = on_event

        async def handler() -> Any:
            assert cap._state._lazy_launcher is not None
            await cap._state._lazy_launcher()  # triggers launch + popup registration
            return MagicMock()

        with (
            patch("pydantic_deep.capabilities.browser._require_browser"),
            patch("pydantic_deep.capabilities.browser.async_playwright", return_value=pw),
        ):
            await cap.wrap_run(_ctx(), handler=handler)

        assert "popup" in registered_events

    @pytest.mark.asyncio
    async def test_wrap_run_popup_callback_fires(self) -> None:
        """The _on_popup callback executes after lazy launch."""
        cap = BrowserCapability()
        pw, browser, page = _make_playwright_mock()
        captured_callback: Any = None

        def on_event(event: str, callback: Any) -> None:
            nonlocal captured_callback
            if event == "popup":
                captured_callback = callback

        page.on = on_event
        ensure_future_calls: list[Any] = []

        async def handler() -> Any:
            assert cap._state._lazy_launcher is not None
            await cap._state._lazy_launcher()  # triggers launch + popup registration
            # Invoke the popup callback while still inside wrap_run (and the patch)
            assert captured_callback is not None
            fake_popup = MagicMock()
            fake_popup.url = "https://popup.example.com"
            fake_popup.close = AsyncMock()
            captured_callback(fake_popup)
            # ensure_future should have been called twice (close + goto)
            assert len(ensure_future_calls) == 2
            return MagicMock()

        with (
            patch("pydantic_deep.capabilities.browser._require_browser"),
            patch("pydantic_deep.capabilities.browser.async_playwright", return_value=pw),
            patch(
                "pydantic_deep.capabilities.browser.asyncio.ensure_future",
                side_effect=lambda coro: ensure_future_calls.append(coro),
            ),
        ):
            await cap.wrap_run(_ctx(), handler=handler)

    async def test_prepare_tools_clears_unapproved_on_browser_tools(self) -> None:
        """Browser tools with kind='unapproved' are reset to 'function'."""
        from pydantic_ai.tools import ToolDefinition

        cap = BrowserCapability()
        tool_defs = [
            ToolDefinition(name="navigate", description="nav", kind="unapproved"),
            ToolDefinition(name="execute_js", description="js", kind="unapproved"),
            ToolDefinition(name="execute", description="shell", kind="unapproved"),
            ToolDefinition(name="click", description="click", kind="function"),
        ]
        result = await cap.prepare_tools(_ctx(), tool_defs)
        # Browser tools should have kind='function'
        by_name = {td.name: td for td in result}
        assert by_name["navigate"].kind == "function"
        assert by_name["execute_js"].kind == "function"
        assert by_name["click"].kind == "function"  # already function, unchanged
        # Non-browser tool keeps unapproved
        assert by_name["execute"].kind == "unapproved"

    async def test_prepare_tools_no_change_when_already_function(self) -> None:
        """Browser tools already kind='function' pass through unchanged."""
        from pydantic_ai.tools import ToolDefinition

        cap = BrowserCapability()
        tool_defs = [
            ToolDefinition(name="navigate", description="nav", kind="function"),
        ]
        result = await cap.prepare_tools(_ctx(), tool_defs)
        assert result[0].kind == "function"

    async def test_prepare_tools_hides_browser_tools_when_launch_failed(self) -> None:
        """When Chromium is not installed, browser tools are hidden from the model."""
        from pydantic_ai.tools import ToolDefinition

        cap = BrowserCapability()
        cap._state.launch_error = "Chromium is not installed."
        tool_defs = [
            ToolDefinition(name="navigate", description="nav"),
            ToolDefinition(name="execute_js", description="js"),
            ToolDefinition(name="execute", description="shell"),  # non-browser
            ToolDefinition(name="read_file", description="read"),  # non-browser
        ]
        result = await cap.prepare_tools(_ctx(), tool_defs)
        names = [td.name for td in result]
        assert "navigate" not in names
        assert "execute_js" not in names
        assert "execute" in names
        assert "read_file" in names

    async def test_get_instructions_returns_none_when_launch_failed(self) -> None:
        """No browser instructions injected when Chromium is not available."""
        cap = BrowserCapability()
        cap._state.launch_error = "Chromium is not installed."
        instructions_fn = cap.get_instructions()
        result = instructions_fn(_ctx())
        assert result is None

    async def test_get_instructions_returns_text_when_browser_available(self) -> None:
        """Browser instructions are injected when browser is available."""
        cap = BrowserCapability()
        instructions_fn = cap.get_instructions()
        result = instructions_fn(_ctx())
        assert result is not None
        assert "navigate" in result


# ── BrowseResult ──────────────────────────────────────────────────────────────


class TestBrowseResult:
    def test_minimal_construction(self) -> None:
        r = BrowseResult(url="https://x.com", title="X", content="body")
        assert r.url == "https://x.com"
        assert r.title == "X"
        assert r.content == "body"
        assert r.screenshot is None
        assert r.error is None

    def test_with_screenshot(self) -> None:
        r = BrowseResult(url="u", title="t", content="c", screenshot="base64abc")
        assert r.screenshot == "base64abc"

    def test_with_error(self) -> None:
        r = BrowseResult(url="u", title="t", content="", error="timeout")
        assert r.error == "timeout"


# ── Capability package export ─────────────────────────────────────────────────


class TestCapabilityExports:
    def test_browser_capability_importable_from_package(self) -> None:
        from pydantic_deep.capabilities import BrowserCapability as BC

        assert BC is BrowserCapability

    def test_browser_capability_importable_from_root(self) -> None:
        from pydantic_deep import BrowserCapability as BC

        assert BC is BrowserCapability

    def test_browser_toolset_importable_from_root(self) -> None:
        from pydantic_deep import BrowserToolset as BT

        assert BT is BrowserToolset

    def test_browse_result_importable_from_root(self) -> None:
        from pydantic_deep import BrowseResult as BR

        assert BR is BrowseResult

    def test_browser_instructions_is_string(self) -> None:
        assert isinstance(BROWSER_INSTRUCTIONS, str)
        assert "{max_content_tokens}" in BROWSER_INSTRUCTIONS
        assert "{allowed_domains}" in BROWSER_INSTRUCTIONS
