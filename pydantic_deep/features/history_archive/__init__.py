"""History-archive feature — BM25 search over the persisted message archive.

A toolset-only slice: `toolset.py` (`create_history_search_toolset` plus the
BM25 ranking helpers). Enabled by default when `context_manager=True`.
"""

from pydantic_deep.features.history_archive.toolset import (
    SEARCH_HISTORY_DESCRIPTION,
    create_history_search_toolset,
)

__all__ = [
    "SEARCH_HISTORY_DESCRIPTION",
    "create_history_search_toolset",
]
