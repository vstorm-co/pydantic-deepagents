"""Assemble the agent system prompt from fragments.

This is the single place the static system prompt is built. Runtime sections
that need live context (filesystem/console spec, todo list, subagent roster, web
tools, skills, memory, uploaded files) are contributed separately by instruction
providers and toolsets — see :mod:`pydantic_deep.instructions`.
"""

from __future__ import annotations

from pydantic_deep.prompts import fragments as f

# Core sections, in prompt order. Always present for a full (non-lean) build.
_CORE: tuple[str, ...] = (
    f.IDENTITY,
    f.HARNESS,
    f.COMMUNICATION,
    f.PROACTIVENESS,
    f.DOING_TASKS,
    f.CODE_STYLE,
    f.TOOL_USAGE,
    f.TASK_MANAGEMENT,
    f.ACTING_WITH_CARE,
    f.SECURITY,
    f.VERIFICATION,
)

# Extra sections added only when running non-interactively (benchmarks, CI,
# scripted automation) — autonomy, exact-match discipline, absolute paths.
_NON_INTERACTIVE: tuple[str, ...] = (
    f.AUTONOMY,
    f.EXACTNESS,
    f.PATH_HANDLING,
)


def build_system_prompt(
    *,
    non_interactive: bool = False,
    lean: bool = False,
    working_dir: str | None = None,
    forking: bool = True,
) -> str:
    """Build the agent's static system prompt.

    Args:
        non_interactive: Running with no user to answer questions (benchmarks,
            CI, scripts). Adds the autonomy, exactness, and path-handling
            sections.
        lean: With ``non_interactive``, use the minimal benchmark prompt only.
        working_dir: Absolute root the agent operates in. Appended as a
            working-directory section when given.
        forking: Include the forking section (the ``fork_run`` workflow).

    Returns:
        The assembled system prompt.
    """
    if non_interactive and lean:
        sections: list[str] = [f.LEAN]
    else:
        sections = list(_CORE)
        if forking:
            sections.append(f.FORKING)
        if non_interactive:
            sections.extend(_NON_INTERACTIVE)

    if working_dir:
        sections.append(f.working_directory(working_dir))

    return "\n\n".join(sections)


#: The default interactive system prompt. Kept as a module-level constant for
#: back-compat (``from pydantic_deep.prompts import BASE_PROMPT``) and reused as
#: the base for subagents and team members.
BASE_PROMPT = build_system_prompt()

__all__ = ["BASE_PROMPT", "build_system_prompt"]
