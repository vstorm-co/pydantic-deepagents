"""Runtime system-prompt providers for the deep agent.

`create_deep_agent` registers a single `@agent.instructions` hook that joins the
output of an ordered list of *instruction providers* - one per feature that
contributes a runtime prompt section (uploads, todos, filesystem, subagents,
web tools).

Which providers are active is decided once, in `build_instruction_providers`,
rather than re-checking feature flags on every model request. Toolset-owned
prompts are emitted automatically by pydantic-ai's `CombinedToolset`; this
module only covers sections that need runtime context or live outside a
toolset's own `get_instructions`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from pydantic_ai_backends import get_console_system_prompt
from pydantic_ai_todo import TODO_SYSTEM_PROMPT
from subagents_pydantic_ai import get_subagent_system_prompt

if TYPE_CHECKING:
    from pydantic_ai import RunContext

    from pydantic_deep.deps import DeepAgentDeps
    from pydantic_deep.types import SubAgentConfig

InstructionProvider = Callable[["RunContext[DeepAgentDeps]"], str]
"""Returns a prompt section for the current run, or `""` to contribute nothing."""


def uploads_section(ctx: RunContext[DeepAgentDeps]) -> str:
    """Summarise the files the user uploaded into the run's backend."""
    return ctx.deps.get_uploads_summary()


def todo_section(_ctx: RunContext[DeepAgentDeps]) -> str:
    """Emit the static todo workflow prompt.

    The instructions open the provider's prompt-cache prefix, so re-rendering
    them with the live task list invalidates the whole cached prefix on every
    mutating todo call. The list itself is already in the (append-only,
    cache-friendly) message history — `write_todos` carries it in its own tool
    call — and `read_todos` is there for an explicit check.
    """
    return TODO_SYSTEM_PROMPT


def current_todos_section(ctx: RunContext[DeepAgentDeps]) -> str:
    """Append the run's live task list to the prompt.

    Opt-in only (`include_current_todos=True`): every mutation rewrites the
    system prompt and costs the provider's cached prefix.
    """
    return ctx.deps.get_todo_prompt()


def make_console_section(edit_format: str) -> InstructionProvider:
    """Emit the filesystem/console tool prompt for the given edit format."""

    def provider(ctx: RunContext[DeepAgentDeps]) -> str:
        prompt: str = get_console_system_prompt(edit_format=edit_format)  # type: ignore[arg-type,unused-ignore]
        return prompt

    return provider


def make_subagent_section(configs: Sequence[SubAgentConfig]) -> InstructionProvider:
    """Emit the subagent-delegation prompt for the available specialists."""
    prompt_configs = list(configs)

    def provider(ctx: RunContext[DeepAgentDeps]) -> str:
        return get_subagent_system_prompt(prompt_configs) if prompt_configs else ""

    return provider


def lean_todo_section(_ctx: RunContext[DeepAgentDeps]) -> str:
    """Behavioral todo guidance without re-listing the self-describing tools.

    Used when tool search is on: the todo tools carry their own schemas, so the
    prompt only needs the *policy* for using them, not an inventory.
    """
    return (
        "## Task Tracking\n\n"
        "For work spanning several steps, track it with the todo tools: keep exactly "
        "one task `in_progress`, mark each `completed` as soon as it's done, and "
        "re-check the list before picking the next step. Skip todos for trivial, "
        "one-shot tasks."
    )


def make_lean_subagent_section(configs: Sequence[SubAgentConfig]) -> InstructionProvider:
    """Behavioral delegation guidance plus the roster — but not the full tool
    schema, which the model gets when it discovers the `task` tool."""
    names = [str(c.get("name", "")) for c in configs if c.get("name")]
    roster = ", ".join(names)

    def provider(ctx: RunContext[DeepAgentDeps]) -> str:
        if not roster:
            return ""
        return (
            "## Subagents\n\n"
            "Specialist subagents are available via the `task` tool. Delegate "
            "self-contained or parallel subtasks, giving each a complete brief — "
            "they don't share your context. Work directly for simple, sequential, "
            "or single-file work.\n\n"
            f"Available: {roster}."
        )

    return provider


def web_tools_section(*, web_search: bool, web_fetch: bool) -> str:
    """Render the web-tools availability prompt for the enabled web tools."""
    lines = ["## Web Tools\n\nYou have access to the web:"]
    if web_search:
        lines.append("- **web search** - search the internet for current information, news, docs")
    if web_fetch:
        lines.append("- **web fetch** - fetch and read any URL as Markdown")
    lines.append(
        "\nWhen the user asks you to look something up online, visit a website, "
        "or check current information - use these tools. Do NOT refuse."
    )
    return "\n".join(lines)


def build_instruction_providers(
    *,
    include_todo: bool,
    include_filesystem: bool,
    edit_format: str,
    include_subagents: bool,
    subagents: Sequence[SubAgentConfig],
    web_search: bool,
    web_fetch: bool,
    tool_search: bool = False,
    include_current_todos: bool = False,
) -> list[InstructionProvider]:
    """Assemble the ordered instruction providers for the enabled features.

    With `tool_search` on, the self-describing tools are deferred/discovered, so
    the verbose per-tool enumerations are replaced with lean *behavioral*
    sections — the prompt describes how to use the tools, not what they are.
    The console section is kept verbatim either way: it carries the hashline
    edit-format spec the model needs to call `edit_file` correctly.

    The todo section is static unless `include_current_todos` is set, so that
    todo mutations don't rewrite the prompt-cache prefix mid-run.
    """
    providers: list[InstructionProvider] = [uploads_section]
    if include_todo:
        providers.append(lean_todo_section if tool_search else todo_section)
        if include_current_todos:
            providers.append(current_todos_section)
    if include_filesystem:
        providers.append(make_console_section(edit_format))
    if include_subagents:
        providers.append(
            make_lean_subagent_section(subagents)
            if tool_search
            else make_subagent_section(subagents)
        )
    if web_search or web_fetch:
        web = web_tools_section(web_search=web_search, web_fetch=web_fetch)
        providers.append(lambda _ctx: web)
    return providers


def render_instructions(
    ctx: RunContext[DeepAgentDeps],
    providers: Sequence[InstructionProvider],
) -> str:
    """Join every provider's non-empty section into the dynamic system prompt."""
    sections = (provider(ctx) for provider in providers)
    return "\n\n".join(section for section in sections if section)
