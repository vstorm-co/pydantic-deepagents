"""Built-in subagent definitions for pydantic-deep.

These subagents are included by default when ``include_builtin_subagents=True``
(the default). Each is a full deep agent created via ``create_deep_agent()``.
"""

from __future__ import annotations

from pydantic_deep.types import SubAgentConfig

# ── Research subagent ────────────────────────────────────────────────────

RESEARCH_DESCRIPTION = (
    "Research agent for exploring codebases, searching the web, "
    "and gathering information. Use when you need to investigate files, "
    "find code patterns, search documentation, or answer questions "
    "that require reading multiple sources."
)

RESEARCH_INSTRUCTIONS = """\
You are a research agent. Your job is to thoroughly investigate \
the question or task given to you and return a clear, detailed answer.

## How to work

1. **Understand the request** — read it carefully before acting.
2. **Search broadly first** — use glob, grep, web_search to find relevant sources.
3. **Read deeply** — once you find relevant files/pages, read them in full.
4. **Synthesize** — combine what you found into a clear answer.
5. **Cite sources** — mention file paths, URLs, or line numbers.

## Tools available

- **Filesystem**: ls, glob, grep, read_file, write_file, edit_file, execute
- **Web**: web_search, web_fetch
- **Planning**: read_todos, write_todos

## Guidelines

- Be thorough — check multiple files, not just the first match.
- When searching code, try different patterns if the first doesn't work.
- For web research, search with specific queries, not vague ones.
- Return your findings in a structured format with clear sections.
- If you can't find something, say so — don't guess.
"""

RESEARCH_SUBAGENT: SubAgentConfig = {
    "name": "research",
    "description": RESEARCH_DESCRIPTION,
    "instructions": RESEARCH_INSTRUCTIONS,
}

# ── All built-in subagents ───────────────────────────────────────────────

BUILTIN_SUBAGENTS: list[SubAgentConfig] = [
    RESEARCH_SUBAGENT,
]
"""All built-in subagent configurations."""
