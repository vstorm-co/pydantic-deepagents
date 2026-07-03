"""Deprecated compatibility shim.

The system prompt now lives in one place — :mod:`pydantic_deep.prompts` — built
from fragments by :func:`pydantic_deep.prompts.build_system_prompt`. This module
forwards the old CLI entry points to it.
"""

from __future__ import annotations

from typing import Any

from pydantic_deep.prompts import build_system_prompt


def build_cli_instructions(
    *,
    non_interactive: bool = False,
    lean: bool = False,
    **_deprecated: Any,
) -> str:
    """Deprecated: use :func:`pydantic_deep.prompts.build_system_prompt`.

    Retained so existing callers keep working. Extra keyword arguments (the old
    ``include_execute`` / ``include_todo`` / ``include_subagents`` flags) are
    accepted and ignored.
    """
    return build_system_prompt(non_interactive=non_interactive, lean=lean)


#: The default (interactive) CLI system prompt.
CLI_SYSTEM_PROMPT = build_cli_instructions()

__all__ = ["CLI_SYSTEM_PROMPT", "build_cli_instructions"]
