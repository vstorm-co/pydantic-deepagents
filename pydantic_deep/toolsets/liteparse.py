"""LiteParse document parsing toolset.

Provides tools for parsing PDFs, DOCX, images and other documents using the
LiteParse Node.js CLI via the ``liteparse`` Python package.

Requirements:
    - Node.js >= 18 installed on the system
    - LiteParse CLI: ``npm install -g @llamaindex/liteparse``
    - Python package: ``pip install pydantic-deep[liteparse]``
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.toolsets import FunctionToolset

_HAS_LITEPARSE = False

try:
    from liteparse import LiteParse as _LiteParse
    from liteparse.types import CLINotFoundError as _CLINotFoundError

    _HAS_LITEPARSE = True
except ImportError:  # pragma: no cover

    class _LiteParse:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None: ...  # pragma: no cover

    class _CLINotFoundError(Exception):  # type: ignore[no-redef]
        pass  # pragma: no cover


_NOT_INSTALLED_MSG = (
    "LiteParse is not installed. "
    "Run: pip install pydantic-deep[liteparse] "
    "and npm install -g @llamaindex/liteparse"
)

PARSE_DOCUMENT_DESCRIPTION = """\
Parse a document (PDF, DOCX, XLSX, PPTX, images, etc.) and extract its text content.

Returns the full text of the document with spatial layout preserved. Supports OCR for
scanned documents. Pass the path to the file in the backend filesystem.

Supported formats: PDF, DOCX, XLSX, PPTX, PNG, JPG, TIFF, and more."""

SCREENSHOT_DOCUMENT_DESCRIPTION = """\
Generate page screenshots from a document (PDF or images).

Saves screenshot images to the backend and returns a list of their paths. Useful for
visual inspection or passing pages to a multimodal model.

Args:
    path: Path to the document in the backend filesystem.
    output_dir: Backend directory to save screenshots (default: /screenshots).
    target_pages: Pages to screenshot, e.g. "1-5" or "1,3,5". None means all pages."""


class LiteparseToolset(FunctionToolset[Any]):
    """Toolset for parsing documents with LiteParse.

    Provides tools to extract text and generate screenshots from PDFs, DOCX, and other
    document formats using the LiteParse Node.js CLI.

    Requirements:
        - Node.js >= 18 on the system
        - LiteParse CLI (auto-installed via npm on first use if ``install_if_not_available=True``)
        - ``pip install pydantic-deep[liteparse]``

    Tools:
        - ``parse_document``: Extract text content from a document
        - ``screenshot_document``: Generate page screenshots saved to the backend
    """

    def __init__(
        self,
        *,
        ocr_enabled: bool = True,
        ocr_language: str = "en",
        ocr_server_url: str | None = None,
        dpi: int = 150,
        max_pages: int = 10_000,
        install_if_not_available: bool = True,
        descriptions: dict[str, str] | None = None,
    ) -> None:
        """Initialize LiteparseToolset.

        Args:
            ocr_enabled: Enable OCR for scanned documents. Defaults to True.
            ocr_language: OCR language code (e.g. "en", "fr", "de"). Defaults to "en".
            ocr_server_url: URL of HTTP OCR server. Uses built-in Tesseract if not set.
            dpi: Rendering DPI — higher gives better OCR quality but is slower. Defaults to 150.
            max_pages: Maximum pages to parse per document. Defaults to 10,000.
            install_if_not_available: Auto-install CLI via npm on first use. Defaults to True.
            descriptions: Optional dict to override tool descriptions.
                Keys: ``parse_document``, ``screenshot_document``.
        """
        super().__init__(id="deep-liteparse")
        self._ocr_enabled = ocr_enabled
        self._ocr_language = ocr_language
        self._ocr_server_url = ocr_server_url
        self._dpi = dpi
        self._max_pages = max_pages
        self._install_if_not_available = install_if_not_available
        self._parser: Any = None

        descs = descriptions or {}

        @self.tool(description=descs.get("parse_document", PARSE_DOCUMENT_DESCRIPTION))
        async def parse_document(ctx: RunContext[Any], path: str) -> str:
            """Extract text content from a document.

            Args:
                path: Path to the document in the backend filesystem.
            """
            if not _HAS_LITEPARSE:
                return _NOT_INSTALLED_MSG
            backend = ctx.deps.backend
            file_bytes: bytes | None = backend._read_bytes(path)
            if not file_bytes:
                return f"File not found: {path}"
            try:
                parser = self._get_parser()
                result = await parser.parse_async(
                    file_bytes,
                    ocr_enabled=self._ocr_enabled,
                    ocr_language=self._ocr_language,
                    ocr_server_url=self._ocr_server_url,
                    dpi=self._dpi,
                    max_pages=self._max_pages,
                )
                return f"[{result.num_pages} page(s)]\n\n{result.text}"
            except _CLINotFoundError as exc:
                return f"LiteParse CLI not found: {exc}"
            except Exception as exc:
                return f"Parse error: {exc}"

        @self.tool(description=descs.get("screenshot_document", SCREENSHOT_DOCUMENT_DESCRIPTION))
        async def screenshot_document(
            ctx: RunContext[Any],
            path: str,
            output_dir: str = "/screenshots",
            target_pages: str | None = None,
        ) -> str:
            """Generate page screenshots from a document.

            Args:
                path: Path to the document in the backend filesystem.
                output_dir: Backend directory where screenshots are saved.
                target_pages: Pages to screenshot, e.g. "1-5" or "1,3,5". None for all.
            """
            if not _HAS_LITEPARSE:
                return _NOT_INSTALLED_MSG
            backend = ctx.deps.backend
            file_bytes = backend._read_bytes(path)
            if not file_bytes:
                return f"File not found: {path}"
            try:
                parser = self._get_parser()
                with tempfile.TemporaryDirectory(prefix="liteparse_ss_") as tmpdir:
                    filename = Path(path).name
                    tmp_input = Path(tmpdir) / filename
                    tmp_input.write_bytes(file_bytes)

                    ss_result = await parser.screenshot_async(
                        tmp_input,
                        output_dir=tmpdir,
                        target_pages=target_pages,
                        dpi=self._dpi,
                        load_bytes=True,
                    )

                    if not ss_result.screenshots:
                        return "No screenshots generated."

                    saved: list[str] = []
                    for screenshot in ss_result:
                        if screenshot.image_bytes:
                            out_path = (
                                f"{output_dir.rstrip('/')}/page_{screenshot.page_num}.png"
                            )
                            backend.write(out_path, screenshot.image_bytes)
                            saved.append(out_path)

                    if not saved:
                        return "No screenshots saved."

                    return f"Generated {len(saved)} screenshot(s):\n" + "\n".join(saved)
            except _CLINotFoundError as exc:
                return f"LiteParse CLI not found: {exc}"
            except Exception as exc:
                return f"Screenshot error: {exc}"

    def _get_parser(self) -> Any:
        """Lazy-initialize the LiteParse parser instance."""
        if self._parser is None:
            self._parser = _LiteParse(
                install_if_not_available=self._install_if_not_available
            )
        return self._parser
