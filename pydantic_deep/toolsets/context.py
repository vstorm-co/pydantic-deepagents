"""Deprecated import location for the context-files feature.

The implementation moved to :mod:`pydantic_deep.features.context` (see the
CHANGELOG). This module re-exports the public names for backward compatibility
and will be removed in the next minor release. Import from
``pydantic_deep.features.context`` or the top-level ``pydantic_deep`` instead.
"""

from __future__ import annotations

import warnings

from pydantic_deep.features.context.service import (
    DEFAULT_CONTEXT_FILENAMES,
    DEFAULT_MAX_CONTEXT_CHARS,
    SUBAGENT_CONTEXT_ALLOWLIST,
    _discover_and_load,
    discover_context_files,
    format_context_prompt,
    load_context_files,
)
from pydantic_deep.features.context.toolset import ContextToolset
from pydantic_deep.features.context.types import ContextFile

__all__ = [
    "DEFAULT_CONTEXT_FILENAMES",
    "DEFAULT_MAX_CONTEXT_CHARS",
    "SUBAGENT_CONTEXT_ALLOWLIST",
    "ContextFile",
    "ContextToolset",
    "_discover_and_load",
    "discover_context_files",
    "format_context_prompt",
    "load_context_files",
]

warnings.warn(
    "pydantic_deep.toolsets.context has moved to pydantic_deep.features.context; "
    "update your imports (this shim will be removed in the next minor release).",
    DeprecationWarning,
    stacklevel=2,
)
