"""Workspaces and run contexts for driving deep-agent features in tests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel
from pydantic_ai.usage import RunUsage
from pydantic_ai.workspaces import Workspace, WorkspaceRef
from pydantic_ai_backends import StateBackend
from pydantic_ai_backends.workspaces import StateWorkspaceBackend


class Document(StateBackend):
    """A `StateBackend` with the text-friendly `write` tests seed files with."""

    def write(self, path: str, content: str | bytes) -> None:
        self.write_bytes(path, content.encode() if isinstance(content, str) else content)


def as_workspace(state: StateBackend) -> Workspace:
    """`state` as an in-memory workspace: files only, no commands."""
    backend = StateWorkspaceBackend({"doc": state}, ref=WorkspaceRef(provider="state", id="doc"))
    return Workspace(backend)


def state_workspace(files: Mapping[str, str | bytes] | None = None) -> Workspace:
    """An in-memory workspace holding `files`: files only, no commands."""
    state = Document()
    for path, content in (files or {}).items():
        state.write(path, content)
    return as_workspace(state)


def run_context(
    deps: Any = None, workspace: Workspace | None = None, **fields: Any
) -> RunContext[Any]:
    """A run context whose tools reach `workspace`."""
    ctx = RunContext(deps=deps, model=TestModel(), usage=RunUsage(), **fields)
    if workspace is not None:
        ctx.workspace = workspace
    return ctx
