"""Liteparse feature — parse/screenshot documents via the optional liteparse dep.

A toolset-only slice: `toolset.py` (LiteparseToolset + tool descriptions).
"""

from pydantic_deep.features.liteparse.toolset import (
    PARSE_DOCUMENT_DESCRIPTION,
    SCREENSHOT_DOCUMENT_DESCRIPTION,
    LiteparseToolset,
)

__all__ = [
    "PARSE_DOCUMENT_DESCRIPTION",
    "SCREENSHOT_DOCUMENT_DESCRIPTION",
    "LiteparseToolset",
]
