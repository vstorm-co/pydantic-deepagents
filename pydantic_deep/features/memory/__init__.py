"""Memory feature - agents that remember across runs.

Memory is the harness `Memory` capability over a `FileStore` in the run's
workspace (`store.py`): `{memory_dir}/{namespace}/{agent_name}/MEMORY.md` and any
topic files beside it. `service.py` keeps the layout's defaults and path helper.

pydantic-deep's own memory - `AgentMemoryToolset`, `MemoryCapability` and their
helpers - is deprecated: still importable, with a `DeprecationWarning`, and no
longer used by `create_deep_agent`.
"""

from __future__ import annotations

import importlib
import warnings
from typing import Any

from pydantic_deep.features.memory.service import (
    DEFAULT_MEMORY_DIR,
    DEFAULT_MEMORY_FILENAME,
    get_memory_path,
)
from pydantic_deep.features.memory.store import (
    MEMORY_CAPABILITY_ID,
    MemoryNamespace,
    build_memory_capability,
)

_DEPRECATED: dict[str, str] = {
    "AgentMemoryToolset": "toolset",
    "READ_MEMORY_DESCRIPTION": "toolset",
    "UPDATE_MEMORY_DESCRIPTION": "toolset",
    "WRITE_MEMORY_DESCRIPTION": "toolset",
    "MemoryCapability": "capability",
    "DEFAULT_MAX_MEMORY_LINES": "service",
    "DEFAULT_PIN_END_MARKER": "service",
    "format_memory_prompt": "service",
    "load_memory": "service",
    "MemoryAccessError": "types",
    "MemoryFile": "types",
}
"""pydantic-deep's own memory API, by name and the module that still holds it."""


def deprecated_memory_name(name: str, *, stacklevel: int = 3) -> Any:
    """The deprecated memory object called `name`, after warning that it is.

    Raises:
        AttributeError: `name` is not a deprecated memory name.
    """
    module = _DEPRECATED.get(name)
    if module is None:
        raise AttributeError(name)
    warnings.warn(
        f"{name} is deprecated: memory is now the harness `Memory` capability, "
        "which `create_deep_agent(include_memory=True)` adds and "
        "`build_memory_capability()` builds. The `update_memory` tool is "
        "`write_memory(old_text=...)` there.",
        DeprecationWarning,
        stacklevel=stacklevel,
    )
    return getattr(importlib.import_module(f"{__name__}.{module}"), name)


def __getattr__(name: str) -> Any:
    try:
        value = deprecated_memory_name(name)
    except AttributeError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    # Kept, so the warning is given once: `from ... import` reads the name twice.
    globals()[name] = value
    return value


__all__ = [
    "DEFAULT_MEMORY_DIR",
    "DEFAULT_MEMORY_FILENAME",
    "MEMORY_CAPABILITY_ID",
    "MemoryNamespace",
    "build_memory_capability",
    "get_memory_path",
]
