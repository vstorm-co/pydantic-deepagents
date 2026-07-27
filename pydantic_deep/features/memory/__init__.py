"""Memory feature — persistent per-agent memory.

The primary surface is the harness `Memory` capability (from `pydantic-ai-harness`),
which stores memory in a pluggable `MemoryStore` (in-memory, file, SQLite, Postgres)
independent of the agent's `deps.backend`, injects `MEMORY.md` as user-role context,
supports multiple memory files, and provides `read_memory`/`write_memory`/
`delete_memory`/`search_memory` tools. Use `build_memory_store()` to map a directory
onto a store, and `create_deep_agent(include_memory=True, ...)` to wire it up.

The legacy backend-backed `MemoryCapability` / `AgentMemoryToolset` and their helper
functions remain here as deprecated back-compat shims.
"""

from pydantic_ai_harness.memory import (
    FileStore,
    InMemoryStore,
    Memory,
    MemoryStore,
    MemoryToolset,
    SearchableMemoryStore,
    SqliteMemoryStore,
)

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
from pydantic_deep.features.memory.store import (
    MEMORY_CAPABILITY_ID,
    build_memory_capability,
    build_memory_store,
    resolve_memory_dir,
    sanitize_agent_name,
)
from pydantic_deep.features.memory.toolset import (
    READ_MEMORY_DESCRIPTION,
    UPDATE_MEMORY_DESCRIPTION,
    WRITE_MEMORY_DESCRIPTION,
    AgentMemoryToolset,
)
from pydantic_deep.features.memory.types import MemoryAccessError, MemoryFile

__all__ = [
    "MEMORY_CAPABILITY_ID",
    "FileStore",
    "InMemoryStore",
    "Memory",
    "MemoryStore",
    "MemoryToolset",
    "SearchableMemoryStore",
    "SqliteMemoryStore",
    "build_memory_capability",
    "build_memory_store",
    "resolve_memory_dir",
    "sanitize_agent_name",
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
