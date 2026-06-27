"""Browser feature — Playwright-backed navigation/interaction tools + lifecycle.

A vertical slice: `toolset.py` (BrowserToolset + the 10 browser tools and their
descriptions), `capability.py` (BrowserCapability — launch/close lifecycle).
"""

from pydantic_deep.features.browser.capability import (
    BROWSER_INSTRUCTIONS,
    BrowserCapability,
)
from pydantic_deep.features.browser.toolset import (
    DEFAULT_MAX_CONTENT_TOKENS,
    DEFAULT_TIMEOUT_MS,
    BrowserToolset,
)

__all__ = [
    "BROWSER_INSTRUCTIONS",
    "DEFAULT_MAX_CONTENT_TOKENS",
    "DEFAULT_TIMEOUT_MS",
    "BrowserCapability",
    "BrowserToolset",
]
