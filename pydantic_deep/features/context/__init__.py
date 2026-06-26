"""Context-files feature — discover & inject project docs (AGENTS.md, SOUL.md, …).

A vertical slice: `capability.py` (ContextFilesCapability), `toolset.py`
(ContextToolset), `service.py` (discovery/load/format + defaults), `types.py`
(ContextFile).
"""

from pydantic_deep.features.context.capability import ContextFilesCapability
from pydantic_deep.features.context.service import (
    DEFAULT_CONTEXT_FILENAMES,
    DEFAULT_MAX_CONTEXT_CHARS,
    SUBAGENT_CONTEXT_ALLOWLIST,
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
    "ContextFilesCapability",
    "ContextToolset",
    "discover_context_files",
    "format_context_prompt",
    "load_context_files",
]
