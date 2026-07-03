"""System prompts for pydantic-deep agents.

The single source of truth for the agent's system prompt. Import the builder to
assemble a prompt, or individual fragments to compose your own:

    from pydantic_deep.prompts import build_system_prompt, BASE_PROMPT
    from pydantic_deep.prompts import fragments

``BASE_PROMPT`` is the default interactive prompt; ``build_system_prompt`` builds
context-specific variants (non-interactive/benchmark, lean, working directory).
"""

from __future__ import annotations

from pydantic_deep.prompts import fragments
from pydantic_deep.prompts.builder import BASE_PROMPT, build_system_prompt

__all__ = ["BASE_PROMPT", "build_system_prompt", "fragments"]
