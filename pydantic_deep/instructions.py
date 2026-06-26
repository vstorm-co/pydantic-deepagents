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
from pydantic_ai_todo import get_todo_system_prompt
from subagents_pydantic_ai import get_subagent_system_prompt

if TYPE_CHECKING:
    from pydantic_ai import RunContext

    from pydantic_deep.agent import _DepsTodoProxy
    from pydantic_deep.deps import DeepAgentDeps
    from pydantic_deep.types import SubAgentConfig

InstructionProvider = Callable[["RunContext[DeepAgentDeps]"], str]
"""Returns a prompt section for the current run, or `""` to contribute nothing."""


def uploads_section(ctx: RunContext[DeepAgentDeps]) -> str:
    """Summarise the files the user uploaded into the run's backend."""
    return ctx.deps.get_uploads_summary()


def make_todo_section(todo_proxy: _DepsTodoProxy) -> InstructionProvider:
    """Bind the per-run todo proxy and emit the todo-list prompt section."""

    def provider(ctx: RunContext[DeepAgentDeps]) -> str:
        todo_proxy._deps = ctx.deps
        return get_todo_system_prompt(todo_proxy)

    return provider


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
    todo_proxy: _DepsTodoProxy | None,
    include_filesystem: bool,
    edit_format: str,
    include_subagents: bool,
    subagents: Sequence[SubAgentConfig],
    web_search: bool,
    web_fetch: bool,
) -> list[InstructionProvider]:
    """Assemble the ordered instruction providers for the enabled features."""
    providers: list[InstructionProvider] = [uploads_section]
    if include_todo and todo_proxy is not None:
        providers.append(make_todo_section(todo_proxy))
    if include_filesystem:
        providers.append(make_console_section(edit_format))
    if include_subagents:
        providers.append(make_subagent_section(subagents))
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
