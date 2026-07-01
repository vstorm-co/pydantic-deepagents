"""Memory feature — persistent per-agent MEMORY.md.

A vertical slice: `capability.py` (MemoryCapability), `toolset.py`
(AgentMemoryToolset + tool descriptions), `service.py` (pure load/format/path
logic + defaults), `types.py` (MemoryFile, MemoryAccessError).
"""

from pydantic_deep.features.memory.capability import MemoryCapability
from pydantic_deep.features.memory.service import (
    DEFAULT_MAX_MEMORY_LINES,
    DEFAULT_MEMORY_DIR,
    DEFAULT_MEMORY_FILENAME,
    DEFAULT_PIN_END_MARKER,
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
    "MemoryCapability",
    "MemoryFile",
    "format_memory_prompt",
    "get_memory_path",
    "load_memory",
]
