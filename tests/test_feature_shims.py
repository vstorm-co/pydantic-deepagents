"""Backward-compat shims for moved feature modules (reorg option C).

Each feature moved to `pydantic_deep.features.<name>`; the old deep import
paths remain as deprecation shims that re-export the public names. These tests
assert the shims still resolve the names and emit a DeprecationWarning.
"""

from __future__ import annotations

import importlib

import pytest

import pydantic_deep
from pydantic_deep.features import context as context_feature
from pydantic_deep.features import memory as memory_feature


class TestMemoryShim:
    def test_toolsets_memory_reexports_and_warns(self) -> None:
        import pydantic_deep.toolsets.memory as shim

        with pytest.warns(DeprecationWarning, match="features.memory"):
            importlib.reload(shim)

        # Names resolve to the canonical feature objects.
        assert shim.AgentMemoryToolset is memory_feature.AgentMemoryToolset
        assert shim.MemoryFile is memory_feature.MemoryFile
        assert shim.MemoryAccessError is memory_feature.MemoryAccessError
        assert shim.load_memory is memory_feature.load_memory
        assert shim.get_memory_path is memory_feature.get_memory_path
        assert shim.format_memory_prompt is memory_feature.format_memory_prompt
        assert shim.DEFAULT_MEMORY_DIR == memory_feature.DEFAULT_MEMORY_DIR
        # Private helper preserved for back-compat.
        assert callable(shim._select_recent_lines)

    def test_capabilities_memory_reexports_and_warns(self) -> None:
        import pydantic_deep.capabilities.memory as shim

        with pytest.warns(DeprecationWarning, match="features.memory"):
            importlib.reload(shim)

        assert shim.MemoryCapability is memory_feature.MemoryCapability

    def test_top_level_exports_stable(self) -> None:
        # The blessed top-level surface keeps working unchanged.
        assert pydantic_deep.AgentMemoryToolset is memory_feature.AgentMemoryToolset
        assert pydantic_deep.MemoryCapability is memory_feature.MemoryCapability
        assert pydantic_deep.MemoryFile is memory_feature.MemoryFile


class TestContextShim:
    def test_toolsets_context_reexports_and_warns(self) -> None:
        import pydantic_deep.toolsets.context as shim

        with pytest.warns(DeprecationWarning, match="features.context"):
            importlib.reload(shim)

        assert shim.ContextToolset is context_feature.ContextToolset
        assert shim.ContextFile is context_feature.ContextFile
        assert shim.load_context_files is context_feature.load_context_files
        assert shim.format_context_prompt is context_feature.format_context_prompt
        assert shim.DEFAULT_CONTEXT_FILENAMES == context_feature.DEFAULT_CONTEXT_FILENAMES
        assert callable(shim._discover_and_load)

    def test_capabilities_context_reexports_and_warns(self) -> None:
        import pydantic_deep.capabilities.context as shim

        with pytest.warns(DeprecationWarning, match="features.context"):
            importlib.reload(shim)

        assert shim.ContextFilesCapability is context_feature.ContextFilesCapability

    def test_top_level_exports_stable(self) -> None:
        assert pydantic_deep.ContextToolset is context_feature.ContextToolset
        assert pydantic_deep.ContextFilesCapability is context_feature.ContextFilesCapability
        assert pydantic_deep.ContextFile is context_feature.ContextFile
