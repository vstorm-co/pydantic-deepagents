"""Deprecated import location for the history-archive feature.

The implementation moved to :mod:`pydantic_deep.features.history_archive` (see
the CHANGELOG). This module re-exports the public names for backward
compatibility and will be removed in the next minor release. Import from
``pydantic_deep.features.history_archive`` instead.
"""

from __future__ import annotations

import warnings

from pydantic_deep.features.history_archive.toolset import (
    SEARCH_HISTORY_DESCRIPTION,
    _bm25_rank,
    _compute_idf,
    _format_message,
    _format_messages,
    _load_messages,
    _tokenize,
    create_history_search_toolset,
)

__all__ = [
    "SEARCH_HISTORY_DESCRIPTION",
    "_bm25_rank",
    "_compute_idf",
    "_format_message",
    "_format_messages",
    "_load_messages",
    "_tokenize",
    "create_history_search_toolset",
]

warnings.warn(
    "pydantic_deep.processors.history_archive has moved to "
    "pydantic_deep.features.history_archive; update your imports "
    "(this shim will be removed in the next minor release).",
    DeprecationWarning,
    stacklevel=2,
)
