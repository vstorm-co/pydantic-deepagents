"""Deprecated import location for the memory feature.

The implementation moved to :mod:`pydantic_deep.features.memory` (see the
CHANGELOG). This module re-exports the public names for backward compatibility
and will be removed in the next minor release. Import from
``pydantic_deep.features.memory`` or the top-level ``pydantic_deep`` instead.
"""

from __future__ import annotations

import warnings

from pydantic_deep.features.memory.service import (
    DEFAULT_MAX_MEMORY_LINES,
    DEFAULT_MEMORY_DIR,
    DEFAULT_MEMORY_FILENAME,
    DEFAULT_PIN_END_MARKER,
    _select_recent_lines,
    format_memory_prompt,
    get_memory_path,
    load_memory,
)
from pydantic_deep.features.memory.toolset import (
    READ_MEMORY_DESCRIPTION,
    UPDATE_MEMORY_DESCRIPTION,
    WRITE_MEMORY_DESCRIPTION,
    AgentMemoryToolset,
)
from pydantic_deep.features.memory.types import MemoryAccessError, MemoryFile

__all__ = [
    "DEFAULT_MAX_MEMORY_LINES",
    "DEFAULT_MEMORY_DIR",
    "DEFAULT_MEMORY_FILENAME",
    "DEFAULT_PIN_END_MARKER",
    "READ_MEMORY_DESCRIPTION",
    "UPDATE_MEMORY_DESCRIPTION",
    "WRITE_MEMORY_DESCRIPTION",
    "AgentMemoryToolset",
    "MemoryAccessError",
    "MemoryFile",
    "_select_recent_lines",
    "format_memory_prompt",
    "get_memory_path",
    "load_memory",
]

warnings.warn(
    "pydantic_deep.toolsets.memory has moved to pydantic_deep.features.memory; "
    "update your imports (this shim will be removed in the next minor release).",
    DeprecationWarning,
    stacklevel=2,
)
