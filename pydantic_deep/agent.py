"""Main agent factory for pydantic-deep."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, TypeVar, overload

from pydantic_ai import Agent
from pydantic_ai._agent_graph import HistoryProcessor
from pydantic_ai.models import Model
from pydantic_ai.output import OutputSpec
from pydantic_ai.tools import DeferredToolRequests, Tool
from pydantic_ai_backends import (
    BackendProtocol,
    SandboxProtocol,
    StateBackend,
    create_console_toolset,
    get_console_system_prompt,
)
from pydantic_ai_todo import create_todo_toolset, get_todo_system_prompt
from subagents_pydantic_ai import create_subagent_toolset, get_subagent_system_prompt

from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.prompts import BASE_PROMPT
from pydantic_deep.toolsets.skills import SkillsToolset
from pydantic_deep.toolsets.skills.backend import BackendSkillsDirectory
from pydantic_deep.types import SkillDirectory, SubAgentConfig

if TYPE_CHECKING:
    from pydantic_ai.toolsets import AbstractToolset

    from pydantic_deep.toolsets.skills.types import Skill

OutputDataT = TypeVar("OutputDataT")


DEFAULT_MODEL = "openai:gpt-4.1"

DEFAULT_INSTRUCTIONS = BASE_PROMPT


@overload
def create_deep_agent(
    model: str | Model | None = None,
    instructions: str | None = None,
    output_style: str | Any | None = None,
    styles_dir: str | list[str] | None = None,
    tools: Sequence[Tool[DeepAgentDeps] | Any] | None = None,
    toolsets: Sequence[AbstractToolset[DeepAgentDeps]] | None = None,
    subagents: list[SubAgentConfig] | None = None,
    skills: list[Skill] | None = None,
    skill_directories: list[SkillDirectory]
    | list[str]
    | list[BackendSkillsDirectory]
    | None = None,
    backend: BackendProtocol | None = None,
    include_todo: bool = True,
    include_filesystem: bool = True,
    include_subagents: bool = True,
    include_skills: bool = True,
    include_general_purpose_subagent: bool = True,
    include_plan: bool = True,
    max_nesting_depth: int = 0,
    subagent_registry: Any | None = None,
    subagent_extra_toolsets: Sequence[AbstractToolset[Any]] | None = None,
    include_execute: bool | None = None,
    interrupt_on: dict[str, bool] | None = None,
    output_type: None = None,
    history_processors: Sequence[HistoryProcessor[DeepAgentDeps]] | None = None,
    eviction_token_limit: int | None = None,
    image_support: bool = False,
    edit_format: str = "hashline",
    context_manager: bool = True,
    context_manager_max_tokens: int = 200_000,
    on_context_update: Any | None = None,
    context_files: list[str] | None = None,
    context_discovery: bool = False,
    include_memory: bool = False,
    memory_dir: str | None = None,
    retries: int = 3,
    hooks: list[Any] | None = None,
    patch_tool_calls: bool = False,
    include_checkpoints: bool = False,
    checkpoint_frequency: str = "every_tool",
    max_checkpoints: int = 20,
    checkpoint_store: Any | None = None,
    include_teams: bool = False,
    cost_tracking: bool = True,
    cost_budget_usd: float | None = None,
    on_cost_update: Any | None = None,
    middleware: Sequence[Any] | None = None,
    permission_handler: Any | None = None,
    middleware_context: Any | None = None,
    plans_dir: str | None = None,
    model_settings: dict[str, Any] | None = None,
    **agent_kwargs: Any,
) -> Agent[DeepAgentDeps, str]: ...


@overload
def create_deep_agent(
    model: str | Model | None = None,
    instructions: str | None = None,
    output_style: str | Any | None = None,
    styles_dir: str | list[str] | None = None,
    tools: Sequence[Tool[DeepAgentDeps] | Any] | None = None,
    toolsets: Sequence[AbstractToolset[DeepAgentDeps]] | None = None,
    subagents: list[SubAgentConfig] | None = None,
    skills: list[Skill] | None = None,
    skill_directories: list[SkillDirectory]
    | list[str]
    | list[BackendSkillsDirectory]
    | None = None,
    backend: BackendProtocol | None = None,
    include_todo: bool = True,
    include_filesystem: bool = True,
    include_subagents: bool = True,
    include_skills: bool = True,
    include_general_purpose_subagent: bool = True,
    include_plan: bool = True,
    max_nesting_depth: int = 0,
    subagent_registry: Any | None = None,
    subagent_extra_toolsets: Sequence[AbstractToolset[Any]] | None = None,
    include_execute: bool | None = None,
    interrupt_on: dict[str, bool] | None = None,
    *,
    output_type: OutputSpec[OutputDataT],
    history_processors: Sequence[HistoryProcessor[DeepAgentDeps]] | None = None,
    eviction_token_limit: int | None = None,
    image_support: bool = False,
    edit_format: str = "hashline",
    context_manager: bool = True,
    context_manager_max_tokens: int = 200_000,
    on_context_update: Any | None = None,
    context_files: list[str] | None = None,
    context_discovery: bool = False,
    include_memory: bool = False,
    memory_dir: str | None = None,
    retries: int = 3,
    hooks: list[Any] | None = None,
    patch_tool_calls: bool = False,
    include_checkpoints: bool = False,
    checkpoint_frequency: str = "every_tool",
    max_checkpoints: int = 20,
    checkpoint_store: Any | None = None,
    include_teams: bool = False,
    cost_tracking: bool = True,
    cost_budget_usd: float | None = None,
    on_cost_update: Any | None = None,
    middleware: Sequence[Any] | None = None,
    permission_handler: Any | None = None,
    middleware_context: Any | None = None,
    plans_dir: str | None = None,
    model_settings: dict[str, Any] | None = None,
    **agent_kwargs: Any,
) -> Agent[DeepAgentDeps, OutputDataT]: ...


def create_deep_agent(  # noqa: C901
    model: str | Model | None = None,
    instructions: str | None = None,
    output_style: str | Any | None = None,
    styles_dir: str | list[str] | None = None,
    tools: Sequence[Tool[DeepAgentDeps] | Any] | None = None,
    toolsets: Sequence[AbstractToolset[DeepAgentDeps]] | None = None,
    subagents: list[SubAgentConfig] | None = None,
    skills: list[Skill] | None = None,
    skill_directories: list[SkillDirectory]
    | list[str]
    | list[BackendSkillsDirectory]
    | None = None,
    backend: BackendProtocol | None = None,
    include_todo: bool = True,
    include_filesystem: bool = True,
    include_subagents: bool = True,
    include_skills: bool = True,
    include_general_purpose_subagent: bool = True,
    include_plan: bool = True,
    max_nesting_depth: int = 0,
    subagent_registry: Any | None = None,
    subagent_extra_toolsets: Sequence[AbstractToolset[Any]] | None = None,
    include_execute: bool | None = None,
    interrupt_on: dict[str, bool] | None = None,
    output_type: OutputSpec[OutputDataT] | None = None,
    history_processors: Sequence[HistoryProcessor[DeepAgentDeps]] | None = None,
    eviction_token_limit: int | None = None,
    image_support: bool = False,
    edit_format: str = "hashline",
    context_manager: bool = True,
    context_manager_max_tokens: int = 200_000,
    on_context_update: Any | None = None,
    context_files: list[str] | None = None,
    context_discovery: bool = False,
    include_memory: bool = False,
    memory_dir: str | None = None,
    retries: int = 3,
    hooks: list[Any] | None = None,
    patch_tool_calls: bool = False,
    include_checkpoints: bool = False,
    checkpoint_frequency: str = "every_tool",
    max_checkpoints: int = 20,
    checkpoint_store: Any | None = None,
    include_teams: bool = False,
    cost_tracking: bool = True,
    cost_budget_usd: float | None = None,
    on_cost_update: Any | None = None,
    middleware: Sequence[Any] | None = None,
    permission_handler: Any | None = None,
    middleware_context: Any | None = None,
    plans_dir: str | None = None,
    model_settings: dict[str, Any] | None = None,
    **agent_kwargs: Any,
) -> Agent[DeepAgentDeps, OutputDataT] | Agent[DeepAgentDeps, str]:
    """Create a deep agent with planning, filesystem, subagent, and skills capabilities.

    This factory function creates a fully-configured Agent with:
    - Todo toolset for task planning and tracking
    - Filesystem toolset for file operations
    - Subagent toolset for task delegation
    - Skills toolset for modular capability extension
    - Dynamic system prompts based on current state
    - Optional structured output via output_type
    - Optional history processing (e.g., summarization)

    Args:
        model: Model to use (default: openai:gpt-4.1).
        instructions: Custom instructions for the agent.
        output_style: Output style to apply to agent responses. Can be a
            string name of a built-in style ("concise", "explanatory",
            "formal", "conversational"), a custom OutputStyle instance,
            or a string name to look up in styles_dir. None (default)
            means no style override.
        styles_dir: Directory or list of directories to discover custom
            output styles from. Style files are markdown files with
            YAML frontmatter (name, description) in the directory root.
        tools: Additional tools to register.
        toolsets: Additional toolsets to register.
        subagents: Subagent configurations for the task tool.
        skills: Pre-loaded skills to make available (new Skill dataclass instances).
        skill_directories: Directories to discover skills from.
            Accepts legacy SkillDirectory TypedDicts, plain string paths,
            or BackendSkillsDirectory instances for backend-based skills.
        backend: File storage backend (default: StateBackend).
        include_todo: Whether to include the todo toolset.
        include_filesystem: Whether to include the filesystem toolset.
        include_subagents: Whether to include the subagent toolset.
        include_skills: Whether to include the skills toolset.
        include_general_purpose_subagent: Whether to include a general-purpose subagent.
        include_plan: Whether to include the built-in 'planner' subagent that
            provides Claude Code-style plan mode. The planner analyzes code,
            asks clarifying questions via ``ask_user``, and creates step-by-step
            implementation plans saved to markdown files. Requires
            ``include_subagents=True``. Defaults to True.
        max_nesting_depth: Maximum subagent nesting depth. 0 (default) means
            subagents cannot spawn their own subagents. Set to 1+ to allow
            nested delegation (subagents creating subagents).
        subagent_registry: Optional DynamicAgentRegistry instance. When provided,
            the task tool will also look up dynamically created agents from
            the registry (created via create_agent_factory_toolset).
        include_execute: Whether to include the execute tool. If None (default),
            automatically determined based on whether backend is a SandboxProtocol.
            Set to True to force include even when backend is None (useful when
            backend is provided via deps at runtime).
        interrupt_on: Map of tool names to approval requirements.
            e.g., {"execute": True, "write_file": True}
        output_type: Structured output type (Pydantic model, dataclass, TypedDict).
            When specified, the agent will return this type instead of str.
        history_processors: Sequence of history processors to apply to messages
            before sending to the model. Useful for summarization, filtering, etc.
        eviction_token_limit: Token threshold for large tool output eviction.
            When set, tool outputs exceeding this limit are saved to files and
            replaced with a preview + file reference. None (default) disables
            eviction. Typical value: 20000.
        image_support: Whether to enable image file handling in read_file.
        context_manager: Whether to enable the ContextManagerMiddleware for
            automatic token tracking and auto-compression. When True (default),
            the middleware monitors token usage and triggers LLM-based
            summarization when approaching the token budget. Also provides
            tool output truncation when middleware wrapping is active.
        context_manager_max_tokens: Maximum token budget for the conversation.
            Used by ContextManagerMiddleware to calculate usage percentage and
            determine when to trigger auto-compression. Defaults to 200,000.
        on_context_update: Callback for context usage updates. Called with
            ``(percentage, current_tokens, max_tokens)`` before each model call.
            Supports both sync and async callables. Useful for UI display.
            When True, reading image files (.png, .jpg, .jpeg, .gif, .webp)
            returns a BinaryContent object that multimodal models can see,
            instead of garbled text. Defaults to False.
        context_files: List of paths to context files in the backend
            (e.g., ["/project/DEEP.md", "/project/SOUL.md"]).
            Files are loaded from the runtime backend (ctx.deps.backend)
            and injected into the system prompt. Missing files are
            silently skipped.
        context_discovery: Whether to auto-discover context files at the
            backend root (/). Scans for DEEP.md, AGENTS.md, CLAUDE.md,
            SOUL.md. Defaults to False.
        include_memory: Whether to include the agent memory toolset.
            When True, the main agent and all subagents get persistent
            memory stored as MEMORY.md files in the backend. Memory is
            auto-loaded into the system prompt and writable via tools
            (read_memory, write_memory, update_memory). Per-subagent
            memory can be disabled via ``extra={"memory": False}`` in
            SubAgentConfig. Defaults to False.
        memory_dir: Base directory for memory files in the backend.
            Each agent gets its own subdirectory:
            ``{memory_dir}/{agent_name}/MEMORY.md``.
            Defaults to ``/.deep/memory``.
        retries: Maximum number of retries for tool calls. Defaults to 3.
        hooks: List of Hook instances for Claude Code-style lifecycle hooks.
            Hooks execute shell commands or Python handlers on tool events
            (PRE_TOOL_USE, POST_TOOL_USE, POST_TOOL_USE_FAILURE). Command
            hooks require a SandboxProtocol backend (LocalBackend or
            DockerSandbox). Automatically wraps the agent with
            HooksMiddleware (requires pydantic-ai-middleware package).
        cost_tracking: Whether to enable automatic cost tracking via
            CostTrackingMiddleware. When True (default), token usage and
            USD costs are tracked across runs. Requires wrapping with
            MiddlewareAgent (triggered automatically). Disable with
            ``cost_tracking=False`` for plain Agent without middleware.
        cost_budget_usd: Maximum allowed cumulative cost in USD.
            When exceeded, the next run raises BudgetExceededError.
            None (default) means unlimited.
        on_cost_update: Callback for cost updates after each run.
            Called with a CostInfo object containing run and cumulative
            token/cost data. Supports sync and async callables.
        patch_tool_calls: Whether to enable PatchToolCallsProcessor that
            fixes orphaned tool calls in message history. Useful when
            resuming interrupted conversations. Defaults to False.
        include_checkpoints: Whether to enable conversation checkpointing.
            When True, adds CheckpointMiddleware (auto-saves snapshots)
            and CheckpointToolset (save_checkpoint, list_checkpoints,
            rewind_to tools). The checkpoint store is resolved from
            ``checkpoint_store`` param or ``deps.checkpoint_store`` at
            runtime. Defaults to False.
        checkpoint_frequency: When to auto-save checkpoints:
            ``"every_tool"`` (default) — after each tool call,
            ``"every_turn"`` — before each model request,
            ``"manual_only"`` — only via the save_checkpoint tool.
        max_checkpoints: Maximum number of checkpoints to keep.
            Oldest checkpoints are pruned when this limit is exceeded.
            Defaults to 20.
        checkpoint_store: Checkpoint storage backend. When None (default),
            uses InMemoryCheckpointStore. Can also be set per-session
            via ``deps.checkpoint_store``.
        include_teams: Whether to include the team management toolset.
            When True, adds tools for spawning agent teams, assigning
            tasks via shared todo lists, messaging teammates, and
            dissolving teams. Defaults to False.
        middleware: List of AgentMiddleware instances to wrap the agent with.
            Requires pydantic-ai-middleware package (install with
            ``pip install pydantic-deep[middleware]``). When provided, the
            agent is wrapped in a MiddlewareAgent with lifecycle hooks.
        permission_handler: Async callback for tool permission decisions.
            Called when middleware returns ToolDecision.ASK. Signature:
            ``async (tool_name, tool_args, reason) -> bool``.
        middleware_context: MiddlewareContext instance for sharing state
            between middleware hooks. Optional.
        plans_dir: Directory to save plan files from the planner subagent.
            Defaults to ``/plans`` (relative to backend root).
        model_settings: Provider-specific model settings (temperature, thinking,
            etc.). Passed directly to the pydantic-ai Agent. Common keys:
            ``temperature``, ``max_tokens``, ``anthropic_thinking``,
            ``openai_reasoning_effort``. See pydantic-ai ModelSettings docs.
        **agent_kwargs: Additional arguments passed to Agent constructor.

    Returns:
        Configured Agent instance. Returns Agent[DeepAgentDeps, OutputDataT] if
        output_type is specified, otherwise Agent[DeepAgentDeps, str].

    Example:
        ```python
        from pydantic import BaseModel
        from pydantic_deep import (
            create_deep_agent, DeepAgentDeps, StateBackend, create_summarization_processor
        )

        # Basic usage with string output
        agent = create_deep_agent(
            model="openai:gpt-4.1",
            instructions="You are a coding assistant",
        )

        # With structured output
        class CodeAnalysis(BaseModel):
            language: str
            issues: list[str]
            suggestions: list[str]

        agent = create_deep_agent(
            output_type=CodeAnalysis,
        )

        # Context management is ON by default (token tracking + auto-compression)
        # Disable it or customize:
        agent = create_deep_agent(context_manager=False)
        agent = create_deep_agent(
            context_manager_max_tokens=128_000,
            on_context_update=lambda pct, cur, mx: print(f"{pct:.0%} used"),
        )

        deps = DeepAgentDeps(backend=StateBackend())
        result = await agent.run("Analyze this code", deps=deps)
        ```
    """
    model = model or DEFAULT_MODEL
    backend = backend or StateBackend()
    interrupt_on = interrupt_on or {}

    # Build effective subagents list (user-provided + built-in planner)
    effective_subagents: list[SubAgentConfig] = list(subagents or [])
    if include_plan and include_subagents:
        from pydantic_deep.toolsets.plan import (
            PLANNER_DESCRIPTION,
            PLANNER_INSTRUCTIONS,
            create_plan_toolset,
        )

        _plans_dir = plans_dir or "/plans"
        plan_toolset = create_plan_toolset(plans_dir=_plans_dir)
        planner_config: SubAgentConfig = {
            "name": "planner",
            "description": PLANNER_DESCRIPTION,
            "instructions": PLANNER_INSTRUCTIONS,
            "toolsets": [plan_toolset],
        }
        effective_subagents.append(planner_config)

    def _set_toolset_retries(toolset: AbstractToolset[DeepAgentDeps], max_retries: int) -> None:
        """Set max_retries on a FunctionToolset and all its registered tools."""
        from pydantic_ai.toolsets.function import FunctionToolset

        if isinstance(toolset, FunctionToolset):  # pragma: no branch
            toolset.max_retries = max_retries
            for tool in toolset.tools.values():
                tool.max_retries = max_retries

    # Build toolsets list
    all_toolsets: list[AbstractToolset[DeepAgentDeps]] = []

    if include_todo:
        todo_toolset = create_todo_toolset(id="deep-todo")
        all_toolsets.append(todo_toolset)

    if include_filesystem:
        # Determine approval requirements from interrupt_on
        require_write_approval = interrupt_on.get("write_file", False) or interrupt_on.get(
            "edit_file", False
        )
        require_execute_approval = interrupt_on.get("execute", True)

        # Determine if execute should be included
        # If explicitly set, use that; otherwise auto-detect from backend type
        should_include_execute = (
            include_execute if include_execute is not None else isinstance(backend, SandboxProtocol)
        )

        console_toolset = create_console_toolset(
            id="deep-console",
            include_execute=should_include_execute,
            require_write_approval=require_write_approval,
            require_execute_approval=require_execute_approval,
            image_support=image_support,
            edit_format=edit_format,  # type: ignore[arg-type]
        )
        _set_toolset_retries(console_toolset, retries)
        all_toolsets.append(console_toolset)

    if include_subagents:
        # For subagents, convert model to string if it's a Model instance
        subagent_model = model if isinstance(model, str) else DEFAULT_MODEL

        # Create toolsets factory for subagents - they get console, todo, and extra tools
        _retries = retries  # capture for closure
        _sub_extra = list(subagent_extra_toolsets) if subagent_extra_toolsets else []

        def subagent_toolsets_factory(deps: DeepAgentDeps) -> list[Any]:  # pragma: no cover
            """Provide console, todo, extra, and context toolsets for subagents."""
            sub_console = create_console_toolset(
                include_execute=True,
                require_write_approval=False,
                require_execute_approval=False,
                image_support=image_support,
                edit_format=edit_format,  # type: ignore[arg-type]
            )
            _set_toolset_retries(sub_console, _retries)
            result: list[Any] = [sub_console, create_todo_toolset()]
            # Include extra toolsets (e.g., MCP servers for web search)
            result.extend(_sub_extra)
            if context_files or context_discovery:
                from pydantic_deep.toolsets.context import ContextToolset

                sub_context = ContextToolset(
                    context_files=context_files,
                    context_discovery=context_discovery,
                    is_subagent=True,
                )
                result.append(sub_context)
            return result

        # Inject per-subagent ContextToolset for configs with context_files
        if effective_subagents:  # pragma: no branch
            from pydantic_deep.toolsets.context import ContextToolset as _PerSubagentCtx

            for sa_config in effective_subagents:
                per_sa_files = sa_config.get("context_files")
                if per_sa_files:
                    per_sa_ctx = _PerSubagentCtx(context_files=per_sa_files)
                    existing_toolsets = list(sa_config.get("toolsets", []))
                    existing_toolsets.append(per_sa_ctx)
                    sa_config["toolsets"] = existing_toolsets

        # Inject per-subagent AgentMemoryToolset when include_memory=True
        if include_memory and effective_subagents:
            from pydantic_deep.toolsets.memory import (
                DEFAULT_MAX_MEMORY_LINES as _DEFAULT_MEM_LINES,
            )
            from pydantic_deep.toolsets.memory import (
                DEFAULT_MEMORY_DIR as _DEFAULT_MEM_DIR,
            )
            from pydantic_deep.toolsets.memory import (
                AgentMemoryToolset as _PerSubagentMem,
            )

            _sa_memory_dir = memory_dir or _DEFAULT_MEM_DIR
            for sa_config in effective_subagents:
                extra = sa_config.get("extra", {})
                # Memory enabled by default; can be disabled via extra.memory=False
                if not extra.get("memory", True):
                    continue
                sa_max_lines = extra.get("memory_max_lines", _DEFAULT_MEM_LINES)
                sa_memory = _PerSubagentMem(
                    agent_name=sa_config["name"],
                    memory_dir=_sa_memory_dir,
                    max_lines=sa_max_lines,
                )
                existing_toolsets = list(sa_config.get("toolsets", []))
                existing_toolsets.append(sa_memory)
                sa_config["toolsets"] = existing_toolsets

        subagent_toolset = create_subagent_toolset(
            id="deep-subagents",
            subagents=effective_subagents if effective_subagents else None,
            default_model=subagent_model,
            include_general_purpose=include_general_purpose_subagent,
            toolsets_factory=subagent_toolsets_factory,
            max_nesting_depth=max_nesting_depth,
            registry=subagent_registry,
        )
        all_toolsets.append(subagent_toolset)

    # Skills toolset
    skills_toolset = None
    if include_skills:
        # Convert legacy SkillDirectory dicts to string paths, pass through BackendSkillsDirectory
        directories: list[str | BackendSkillsDirectory] | None = None
        if skill_directories:
            directories = []
            for sd in skill_directories:
                if isinstance(sd, BackendSkillsDirectory):
                    directories.append(sd)
                elif isinstance(sd, dict):
                    directories.append(sd["path"])
                else:
                    directories.append(sd)

        # Convert legacy dict-style skills to Skill dataclass instances
        from pydantic_deep.toolsets.skills.types import Skill as SkillDataclass

        converted_skills: list[SkillDataclass] | None = None
        if skills:
            converted_skills = []
            for s in skills:
                if isinstance(s, dict):
                    converted_skills.append(
                        SkillDataclass(
                            name=s["name"],
                            description=s.get("description", ""),
                            content=s.get("content", ""),
                        )
                    )
                else:
                    converted_skills.append(s)

        skills_toolset = SkillsToolset(
            id="deep-skills",
            skills=converted_skills or None,
            directories=directories,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
        )
        all_toolsets.append(skills_toolset)  # type: ignore[arg-type]

    # Context toolset
    if context_files or context_discovery:
        from pydantic_deep.toolsets.context import ContextToolset

        context_toolset = ContextToolset(
            context_files=context_files,
            context_discovery=context_discovery,
            is_subagent=False,
        )
        all_toolsets.append(context_toolset)

    # Memory toolset
    if include_memory:
        from pydantic_deep.toolsets.memory import DEFAULT_MEMORY_DIR, AgentMemoryToolset

        _memory_dir = memory_dir or DEFAULT_MEMORY_DIR
        memory_toolset = AgentMemoryToolset(
            agent_name="main",
            memory_dir=_memory_dir,
        )
        all_toolsets.append(memory_toolset)

    # Add user-provided toolsets
    if toolsets:
        all_toolsets.extend(toolsets)

    # Checkpoint toolset (added before agent creation so it's in toolsets list)
    if include_checkpoints:
        from pydantic_deep.toolsets.checkpointing import (
            CheckpointToolset,
            InMemoryCheckpointStore,
        )

        _cp_store = checkpoint_store or InMemoryCheckpointStore()
        checkpoint_toolset = CheckpointToolset(store=_cp_store)
        all_toolsets.append(checkpoint_toolset)

    # Team toolset
    if include_teams:
        from pydantic_deep.toolsets.teams import create_team_toolset

        team_toolset = create_team_toolset()
        all_toolsets.append(team_toolset)

    # Build base instructions
    base_instructions = instructions or DEFAULT_INSTRUCTIONS

    # Inject output style into instructions
    if output_style is not None:
        from pydantic_deep.styles import format_style_prompt, resolve_style

        resolved = resolve_style(output_style, styles_dir)
        base_instructions = base_instructions + "\n\n" + format_style_prompt(resolved)

    # Build agent kwargs with optional output_type and history_processors
    agent_create_kwargs: dict[str, Any] = {
        "deps_type": DeepAgentDeps,
        "toolsets": all_toolsets,
        "instructions": base_instructions,
        "retries": retries,
    }

    # Determine if any tools require approval (interrupt_on has True values)
    has_interrupt_tools = any(interrupt_on.values())

    if output_type is not None:
        # If interrupt_on is used, combine output_type with DeferredToolRequests
        if has_interrupt_tools:
            agent_create_kwargs["output_type"] = [output_type, DeferredToolRequests]
        else:
            agent_create_kwargs["output_type"] = output_type
    elif has_interrupt_tools:
        # No custom output_type but interrupt_on is used
        agent_create_kwargs["output_type"] = [str, DeferredToolRequests]

    # Build combined history processors list
    all_processors: list[Any] = list(history_processors or [])

    if patch_tool_calls:
        from pydantic_deep.processors.patch import patch_tool_calls_processor

        all_processors.insert(0, patch_tool_calls_processor)

    if eviction_token_limit is not None:
        from pydantic_deep.processors.eviction import EvictionProcessor

        eviction = EvictionProcessor(backend=backend, token_limit=eviction_token_limit)
        # Eviction runs FIRST (before summarization reduces context)
        all_processors.insert(0, eviction)

    # Context manager middleware (token tracking + auto-compression)
    context_mw: Any | None = None
    if context_manager:
        from pydantic_ai_summarization import create_context_manager_middleware

        context_mw = create_context_manager_middleware(
            max_tokens=context_manager_max_tokens,
            on_usage_update=on_context_update,
        )
        all_processors.append(context_mw)

    # Cost tracking middleware
    cost_mw: Any | None = None
    if cost_tracking:
        from pydantic_ai_middleware import create_cost_tracking_middleware

        model_name = model if isinstance(model, str) else None
        cost_mw = create_cost_tracking_middleware(
            model_name=model_name,
            budget_limit_usd=cost_budget_usd,
            on_cost_update=on_cost_update,
        )

    if all_processors:
        agent_create_kwargs["history_processors"] = all_processors

    # Apply model_settings (explicit param takes priority over agent_kwargs)
    if model_settings is not None:
        agent_create_kwargs["model_settings"] = model_settings

    agent_create_kwargs.update(agent_kwargs)

    # Create the agent
    agent: Agent[DeepAgentDeps, Any] = Agent(
        model,
        **agent_create_kwargs,
    )

    # Add dynamic system prompts
    @agent.instructions
    def dynamic_instructions(ctx: Any) -> str:  # pragma: no cover
        """Generate dynamic instructions based on current state."""
        parts = []

        # Show uploaded files first (most relevant for user's current task)
        uploads_prompt = ctx.deps.get_uploads_summary()
        if uploads_prompt:
            parts.append(uploads_prompt)

        if include_todo:
            todo_prompt = get_todo_system_prompt(ctx.deps)
            if todo_prompt:
                parts.append(todo_prompt)

        if include_filesystem:
            console_prompt = get_console_system_prompt(edit_format=edit_format)  # type: ignore[arg-type]
            if console_prompt:
                parts.append(console_prompt)

        if include_subagents:
            # Build configs list for prompt generation
            prompt_configs: list[SubAgentConfig] = list(effective_subagents or [])
            if include_general_purpose_subagent:
                from subagents_pydantic_ai import DEFAULT_GENERAL_PURPOSE_DESCRIPTION

                prompt_configs.append(
                    SubAgentConfig(
                        name="general-purpose",
                        description=DEFAULT_GENERAL_PURPOSE_DESCRIPTION,
                        instructions="",
                    )
                )
            if prompt_configs:
                subagent_prompt = get_subagent_system_prompt(prompt_configs)
                if subagent_prompt:
                    parts.append(subagent_prompt)

        return "\n\n".join(parts) if parts else ""

    # Add user-provided tools
    if tools:
        for tool in tools:
            if isinstance(tool, Tool):
                agent.tool(tool.function)  # pragma: no cover
            else:
                agent.tool(tool)

    # Convert hooks to HooksMiddleware and merge into middleware list
    if hooks is not None:
        from pydantic_deep.middleware.hooks import HooksMiddleware

        hooks_mw = HooksMiddleware(hooks)
        middleware = list(middleware or []) + [hooks_mw]

    # Checkpoint middleware (toolset already added above before agent creation)
    if include_checkpoints:
        from pydantic_deep.toolsets.checkpointing import (
            CheckpointMiddleware as _CheckpointMW,
        )

        checkpoint_mw = _CheckpointMW(
            store=_cp_store,
            frequency=checkpoint_frequency,
            max_checkpoints=max_checkpoints,
        )
        middleware = list(middleware or []) + [checkpoint_mw]

    # Wrap with middleware if provided
    if middleware is not None or permission_handler is not None or cost_mw is not None:
        from pydantic_ai_middleware import MiddlewareAgent

        all_middleware = list(middleware) if middleware else []
        if context_mw is not None:
            all_middleware.append(context_mw)
        if cost_mw is not None:
            all_middleware.append(cost_mw)

        return MiddlewareAgent(  # type: ignore[no-any-return]
            agent=agent,
            middleware=all_middleware or None,
            context=middleware_context,
            permission_handler=permission_handler,
        )

    return agent


def create_default_deps(
    backend: BackendProtocol | None = None,
) -> DeepAgentDeps:
    """Create default dependencies for a deep agent.

    Args:
        backend: File storage backend (default: StateBackend).

    Returns:
        DeepAgentDeps instance.
    """
    resolved_backend: BackendProtocol = backend or StateBackend()
    return DeepAgentDeps(backend=resolved_backend)


async def run_with_files(
    agent: Agent[DeepAgentDeps, OutputDataT],
    query: str,
    deps: DeepAgentDeps,
    files: list[tuple[str, bytes]] | None = None,
    *,
    upload_dir: str = "/uploads",
) -> OutputDataT:
    """Run agent with file uploads.

    This is a convenience function that uploads files to the backend
    before running the agent. The files are accessible via file tools
    (read_file, grep, glob, execute).

    Args:
        agent: The agent to run.
        query: The user query/prompt.
        deps: Agent dependencies.
        files: List of (filename, content) tuples to upload.
        upload_dir: Directory to store uploads (default: "/uploads")

    Returns:
        Agent output (type depends on agent's output_type).

    Example:
        ```python
        from pydantic_deep import create_deep_agent, DeepAgentDeps, run_with_files
        from pydantic_ai_backends import StateBackend

        agent = create_deep_agent()
        deps = DeepAgentDeps(backend=StateBackend())

        with open("sales.csv", "rb") as f:
            result = await run_with_files(
                agent,
                "Analyze the sales data and find top products",
                deps,
                files=[("sales.csv", f.read())],
            )
        ```
    """
    # Upload files (synchronous)
    for name, content in files or []:
        deps.upload_file(name, content, upload_dir=upload_dir)

    # Run agent
    result = await agent.run(query, deps=deps)
    return result.output
