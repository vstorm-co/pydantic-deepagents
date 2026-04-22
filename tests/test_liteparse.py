"""Tests for LiteparseToolset."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage

from pydantic_deep.toolsets.liteparse import (
    _NOT_INSTALLED_MSG,
    PARSE_DOCUMENT_DESCRIPTION,
    SCREENSHOT_DOCUMENT_DESCRIPTION,
    LiteparseCliNotFoundError,
    LiteparseToolset,
)

TEST_MODEL = TestModel()


def _ctx(backend: Any = None) -> Any:
    from pydantic_ai import RunContext

    deps = MagicMock()
    deps.backend = backend or MagicMock()
    return RunContext(deps=deps, model=TEST_MODEL, usage=RunUsage())


# ── LiteparseToolset construction ─────────────────────────────────────────────


class TestLiteparseToolsetInit:
    def test_default_id(self) -> None:
        ts = LiteparseToolset()
        assert ts.id == "deep-liteparse"

    def test_default_params(self) -> None:
        ts = LiteparseToolset()
        assert ts._ocr_enabled is True
        assert ts._ocr_language == "en"
        assert ts._ocr_server_url is None
        assert ts._dpi == 150
        assert ts._max_pages == 10_000
        assert ts._install_if_not_available is True
        assert ts._parser is None

    def test_custom_params(self) -> None:
        ts = LiteparseToolset(
            ocr_enabled=False,
            ocr_language="fr",
            ocr_server_url="http://localhost:8828/ocr",
            dpi=300,
            max_pages=50,
            install_if_not_available=False,
        )
        assert ts._ocr_enabled is False
        assert ts._ocr_language == "fr"
        assert ts._ocr_server_url == "http://localhost:8828/ocr"
        assert ts._dpi == 300
        assert ts._max_pages == 50
        assert ts._install_if_not_available is False

    def test_custom_descriptions(self) -> None:
        custom = {"parse_document": "Custom parse desc", "screenshot_document": "Custom ss desc"}
        ts = LiteparseToolset(descriptions=custom)
        assert ts.tools["parse_document"].description == "Custom parse desc"
        assert ts.tools["screenshot_document"].description == "Custom ss desc"

    def test_default_descriptions(self) -> None:
        ts = LiteparseToolset()
        assert ts.tools["parse_document"].description == PARSE_DOCUMENT_DESCRIPTION
        assert ts.tools["screenshot_document"].description == SCREENSHOT_DOCUMENT_DESCRIPTION

    def test_tools_registered(self) -> None:
        ts = LiteparseToolset()
        assert "parse_document" in ts.tools
        assert "screenshot_document" in ts.tools


# ── _get_parser ───────────────────────────────────────────────────────────────


class TestGetParser:
    def test_lazy_init(self) -> None:
        ts = LiteparseToolset()
        mock_parser = MagicMock()
        with patch("pydantic_deep.toolsets.liteparse._LiteParse", return_value=mock_parser):
            parser = ts._get_parser()
            assert parser is mock_parser
            assert ts._parser is mock_parser

    def test_reuses_existing(self) -> None:
        ts = LiteparseToolset()
        existing = MagicMock()
        ts._parser = existing
        assert ts._get_parser() is existing


# ── parse_document ────────────────────────────────────────────────────────────


class TestParseDocument:
    @pytest.mark.asyncio
    async def test_not_installed(self) -> None:
        ts = LiteparseToolset()
        ctx = _ctx()
        with patch("pydantic_deep.toolsets.liteparse._HAS_LITEPARSE", False):
            result = await ts.tools["parse_document"].function(ctx, path="/doc.pdf")
        assert result == _NOT_INSTALLED_MSG

    @pytest.mark.asyncio
    async def test_file_not_found(self) -> None:
        ts = LiteparseToolset()
        backend = MagicMock()
        backend._read_bytes.return_value = None
        ctx = _ctx(backend)
        with patch("pydantic_deep.toolsets.liteparse._HAS_LITEPARSE", True):
            result = await ts.tools["parse_document"].function(ctx, path="/missing.pdf")
        assert "File not found" in result
        assert "/missing.pdf" in result

    @pytest.mark.asyncio
    async def test_success(self) -> None:
        ts = LiteparseToolset()
        backend = MagicMock()
        backend._read_bytes.return_value = b"%PDF-1.4 fake content"
        ctx = _ctx(backend)

        mock_result = MagicMock()
        mock_result.num_pages = 3
        mock_result.text = "Hello world"

        mock_parser = MagicMock()
        mock_parser.parse_async = AsyncMock(return_value=mock_result)
        ts._parser = mock_parser

        with patch("pydantic_deep.toolsets.liteparse._HAS_LITEPARSE", True):
            result = await ts.tools["parse_document"].function(ctx, path="/doc.pdf")

        assert "[3 page(s)]" in result
        assert "Hello world" in result
        mock_parser.parse_async.assert_called_once_with(
            b"%PDF-1.4 fake content",
            ocr_enabled=True,
            ocr_language="en",
            ocr_server_url=None,
            dpi=150,
            max_pages=10_000,
        )

    @pytest.mark.asyncio
    async def test_cli_not_found_error(self) -> None:
        ts = LiteparseToolset()
        backend = MagicMock()
        backend._read_bytes.return_value = b"data"
        ctx = _ctx(backend)

        mock_parser = MagicMock()
        mock_parser.parse_async = AsyncMock(side_effect=LiteparseCliNotFoundError("CLI missing"))
        ts._parser = mock_parser

        with patch("pydantic_deep.toolsets.liteparse._HAS_LITEPARSE", True):
            result = await ts.tools["parse_document"].function(ctx, path="/doc.pdf")

        assert "LiteParse CLI not found" in result
        assert "CLI missing" in result

    @pytest.mark.asyncio
    async def test_generic_exception(self) -> None:
        ts = LiteparseToolset()
        backend = MagicMock()
        backend._read_bytes.return_value = b"data"
        ctx = _ctx(backend)

        mock_parser = MagicMock()
        mock_parser.parse_async = AsyncMock(side_effect=RuntimeError("boom"))
        ts._parser = mock_parser

        with patch("pydantic_deep.toolsets.liteparse._HAS_LITEPARSE", True):
            result = await ts.tools["parse_document"].function(ctx, path="/doc.pdf")

        assert "Parse error" in result
        assert "boom" in result


# ── screenshot_document ───────────────────────────────────────────────────────


class TestScreenshotDocument:
    @pytest.mark.asyncio
    async def test_not_installed(self) -> None:
        ts = LiteparseToolset()
        ctx = _ctx()
        with patch("pydantic_deep.toolsets.liteparse._HAS_LITEPARSE", False):
            result = await ts.tools["screenshot_document"].function(ctx, path="/doc.pdf")
        assert result == _NOT_INSTALLED_MSG

    @pytest.mark.asyncio
    async def test_file_not_found(self) -> None:
        ts = LiteparseToolset()
        backend = MagicMock()
        backend._read_bytes.return_value = None
        ctx = _ctx(backend)
        with patch("pydantic_deep.toolsets.liteparse._HAS_LITEPARSE", True):
            result = await ts.tools["screenshot_document"].function(ctx, path="/missing.pdf")
        assert "File not found" in result

    @pytest.mark.asyncio
    async def test_success(self) -> None:
        ts = LiteparseToolset()
        backend = MagicMock()
        backend._read_bytes.return_value = b"pdfdata"
        ctx = _ctx(backend)

        shot1 = MagicMock()
        shot1.page_num = 1
        shot1.image_bytes = b"png1"
        shot2 = MagicMock()
        shot2.page_num = 2
        shot2.image_bytes = b"png2"

        ss_result = MagicMock()
        ss_result.screenshots = [shot1, shot2]
        ss_result.__iter__ = MagicMock(return_value=iter([shot1, shot2]))

        mock_parser = MagicMock()
        mock_parser.screenshot_async = AsyncMock(return_value=ss_result)
        ts._parser = mock_parser

        with patch("pydantic_deep.toolsets.liteparse._HAS_LITEPARSE", True):
            result = await ts.tools["screenshot_document"].function(
                ctx, path="/doc.pdf", output_dir="/screenshots"
            )

        assert "Generated 2 screenshot(s)" in result
        assert "/screenshots/page_1.png" in result
        assert "/screenshots/page_2.png" in result
        backend.write.assert_any_call("/screenshots/page_1.png", b"png1")
        backend.write.assert_any_call("/screenshots/page_2.png", b"png2")

    @pytest.mark.asyncio
    async def test_no_screenshots_generated(self) -> None:
        ts = LiteparseToolset()
        backend = MagicMock()
        backend._read_bytes.return_value = b"pdfdata"
        ctx = _ctx(backend)

        ss_result = MagicMock()
        ss_result.screenshots = []

        mock_parser = MagicMock()
        mock_parser.screenshot_async = AsyncMock(return_value=ss_result)
        ts._parser = mock_parser

        with patch("pydantic_deep.toolsets.liteparse._HAS_LITEPARSE", True):
            result = await ts.tools["screenshot_document"].function(ctx, path="/doc.pdf")

        assert result == "No screenshots generated."

    @pytest.mark.asyncio
    async def test_screenshots_without_bytes(self) -> None:
        """Screenshots with no image_bytes are skipped."""
        ts = LiteparseToolset()
        backend = MagicMock()
        backend._read_bytes.return_value = b"pdfdata"
        ctx = _ctx(backend)

        shot = MagicMock()
        shot.page_num = 1
        shot.image_bytes = None  # no bytes

        ss_result = MagicMock()
        ss_result.screenshots = [shot]
        ss_result.__iter__ = MagicMock(return_value=iter([shot]))

        mock_parser = MagicMock()
        mock_parser.screenshot_async = AsyncMock(return_value=ss_result)
        ts._parser = mock_parser

        with patch("pydantic_deep.toolsets.liteparse._HAS_LITEPARSE", True):
            result = await ts.tools["screenshot_document"].function(ctx, path="/doc.pdf")

        assert result == "No screenshots saved."

    @pytest.mark.asyncio
    async def test_target_pages_forwarded(self) -> None:
        ts = LiteparseToolset()
        backend = MagicMock()
        backend._read_bytes.return_value = b"pdfdata"
        ctx = _ctx(backend)

        shot = MagicMock()
        shot.page_num = 1
        shot.image_bytes = b"png"
        ss_result = MagicMock()
        ss_result.screenshots = [shot]
        ss_result.__iter__ = MagicMock(return_value=iter([shot]))

        mock_parser = MagicMock()
        mock_parser.screenshot_async = AsyncMock(return_value=ss_result)
        ts._parser = mock_parser

        with patch("pydantic_deep.toolsets.liteparse._HAS_LITEPARSE", True):
            await ts.tools["screenshot_document"].function(ctx, path="/doc.pdf", target_pages="1-3")

        call_kwargs = mock_parser.screenshot_async.call_args.kwargs
        assert call_kwargs["target_pages"] == "1-3"

    @pytest.mark.asyncio
    async def test_cli_not_found_error(self) -> None:
        ts = LiteparseToolset()
        backend = MagicMock()
        backend._read_bytes.return_value = b"data"
        ctx = _ctx(backend)

        mock_parser = MagicMock()
        mock_parser.screenshot_async = AsyncMock(side_effect=LiteparseCliNotFoundError("no CLI"))
        ts._parser = mock_parser

        with patch("pydantic_deep.toolsets.liteparse._HAS_LITEPARSE", True):
            result = await ts.tools["screenshot_document"].function(ctx, path="/doc.pdf")

        assert "LiteParse CLI not found" in result

    @pytest.mark.asyncio
    async def test_generic_exception(self) -> None:
        ts = LiteparseToolset()
        backend = MagicMock()
        backend._read_bytes.return_value = b"data"
        ctx = _ctx(backend)

        mock_parser = MagicMock()
        mock_parser.screenshot_async = AsyncMock(side_effect=OSError("disk full"))
        ts._parser = mock_parser

        with patch("pydantic_deep.toolsets.liteparse._HAS_LITEPARSE", True):
            result = await ts.tools["screenshot_document"].function(ctx, path="/doc.pdf")

        assert "Screenshot error" in result
        assert "disk full" in result


# ── create_deep_agent integration ─────────────────────────────────────────────


class TestCreateDeepAgentLiteparse:
    def test_include_liteparse_adds_toolset(self) -> None:
        from pydantic_ai.models.test import TestModel as _TestModel

        from pydantic_deep import create_deep_agent

        agent = create_deep_agent(model=_TestModel(), include_liteparse=True)
        toolset_ids = [ts.id for ts in agent._user_toolsets if hasattr(ts, "id")]
        assert "deep-liteparse" in toolset_ids

    def test_exclude_liteparse_default(self) -> None:
        from pydantic_ai.models.test import TestModel as _TestModel

        from pydantic_deep import create_deep_agent

        agent = create_deep_agent(model=_TestModel())
        toolset_ids = [ts.id for ts in agent._user_toolsets if hasattr(ts, "id")]
        assert "deep-liteparse" not in toolset_ids
