"""Main agent factory for pydantic-deep."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, TypeVar, overload

from pydantic_ai import Agent
from pydantic_ai._agent_graph import HistoryProcessor
from pydantic_ai.capabilities import AbstractCapability
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
from pydantic_deep.types import SubAgentConfig

if TYPE_CHECKING:
    from pydantic_ai.toolsets import AbstractToolset

OutputDataT = TypeVar("OutputDataT")


DEFAULT_MODEL = "anthropic:claude-opus-4-6"
DEFAULT_SUBAGENT_MODEL = "anthropic:claude-sonnet-4-6"
DEFAULT_SUMMARIZATION_MODEL = "anthropic:claude-haiku-4-5-20251001"

DEFAULT_INSTRUCTIONS = BASE_PROMPT


class _DepsTodoProxy:
    """Proxy that delegates todo reads/writes to the current run's DeepAgentDeps.

    Implements ``TodoStorageProtocol`` so it can be passed as ``storage``
    to ``create_todo_toolset()``.  The proxy is bound to a specific
    ``DeepAgentDeps`` instance at the start of each model turn (inside
    ``dynamic_instructions``), ensuring the toolset always operates on
    the correct deps object.
    """

    def __init__(self) -> None:
        self._deps: DeepAgentDeps | None = None

    @property
    def todos(self) -> list[Any]:
        if self._deps is None:
            return []
        return self._deps.todos

    @todos.setter
    def todos(self, value: list[Any]) -> None:
        if self._deps is not None:
            self._deps.todos = list(value)


@overload
def create_deep_agent(
    model: str | Model | None = None,
    model_settings: dict[str, Any] | None = None,
    summarization_model: str | None = None,
    instructions: str | None = None,
    output_style: str | Any | None = None,
    styles_dir: str | list[str] | None = None,
    tools: Sequence[Tool[DeepAgentDeps] | Any] | None = None,
    toolsets: Sequence[AbstractToolset[DeepAgentDeps]] | None = None,
    capabilities: Sequence[AbstractCapability[Any]] | None = None,
    subagents: list[SubAgentConfig] | None = None,
    skill_directories: list[dict[str, Any]]
    | list[str]
    | list[BackendSkillsDirectory]
    | None = None,
    backend: BackendProtocol | None = None,
    include_todo: bool = True,
    include_filesystem: bool = True,
    include_subagents: bool = True,
    include_skills: bool = True,
    include_builtin_subagents: bool = True,
    include_plan: bool = True,
    max_nesting_depth: int = 1,
    subagent_registry: Any | None = None,
    subagent_extra_toolsets: Sequence[AbstractToolset[Any]] | None = None,
    include_execute: bool | None = None,
    interrupt_on: dict[str, bool] | None = None,
    output_type: None = None,
    history_processors: Sequence[HistoryProcessor[DeepAgentDeps]] | None = None,
    eviction_token_limit: int | None = 20_000,
    edit_format: str = "hashline",
    context_manager: bool = True,
    context_manager_max_tokens: int | None = None,
    on_context_update: Any | None = None,
    on_before_compress: Any | None = None,
    on_after_compress: Any | None = None,
    on_eviction: Any | None = None,
    context_files: list[str] | None = None,
    context_discovery: bool = False,
    include_memory: bool = True,
    memory_dir: str | None = None,
    retries: int = 3,
    hooks: list[Any] | None = None,
    patch_tool_calls: bool = True,
    include_checkpoints: bool = False,
    checkpoint_frequency: str = "every_tool",
    max_checkpoints: int = 20,
    checkpoint_store: Any | None = None,
    include_teams: bool = False,
    include_improve: bool = False,
    stuck_loop_detection: bool = True,
    web_search: bool = True,
    web_fetch: bool = True,
    thinking: bool | str = "high",
    include_history_archive: bool = True,
    history_messages_path: str = ".pydantic-deep/messages.json",
    cost_tracking: bool = True,
    cost_budget_usd: float | None = None,
    on_cost_update: Any | None = None,
    middleware: Sequence[Any] | None = None,
    plans_dir: str | None = None,
    instrument: bool | None = None,
    **agent_kwargs: Any,
) -> Agent[DeepAgentDeps, str]: ...


@overload
def create_deep_agent(
    model: str | Model | None = None,
    model_settings: dict[str, Any] | None = None,
    summarization_model: str | None = None,
    instructions: str | None = None,
    output_style: str | Any | None = None,
    styles_dir: str | list[str] | None = None,
    tools: Sequence[Tool[DeepAgentDeps] | Any] | None = None,
    toolsets: Sequence[AbstractToolset[DeepAgentDeps]] | None = None,
    capabilities: Sequence[AbstractCapability[Any]] | None = None,
    subagents: list[SubAgentConfig] | None = None,
    skill_directories: list[dict[str, Any]]
    | list[str]
    | list[BackendSkillsDirectory]
    | None = None,
    backend: BackendProtocol | None = None,
    include_todo: bool = True,
    include_filesystem: bool = True,
    include_subagents: bool = True,
    include_skills: bool = True,
    include_builtin_subagents: bool = True,
    include_plan: bool = True,
    max_nesting_depth: int = 1,
    subagent_registry: Any | None = None,
    subagent_extra_toolsets: Sequence[AbstractToolset[Any]] | None = None,
    include_execute: bool | None = None,
    interrupt_on: dict[str, bool] | None = None,
    *,
    output_type: OutputSpec[OutputDataT],
    history_processors: Sequence[HistoryProcessor[DeepAgentDeps]] | None = None,
    eviction_token_limit: int | None = 20_000,
    edit_format: str = "hashline",
    context_manager: bool = True,
    context_manager_max_tokens: int | None = None,
    on_context_update: Any | None = None,
    on_before_compress: Any | None = None,
    on_after_compress: Any | None = None,
    on_eviction: Any | None = None,
    context_files: list[str] | None = None,
    context_discovery: bool = False,
    include_memory: bool = True,
    memory_dir: str | None = None,
    retries: int = 3,
    hooks: list[Any] | None = None,
    patch_tool_calls: bool = True,
    include_checkpoints: bool = False,
    checkpoint_frequency: str = "every_tool",
    max_checkpoints: int = 20,
    checkpoint_store: Any | None = None,
    include_teams: bool = False,
    include_improve: bool = False,
    stuck_loop_detection: bool = True,
    web_search: bool = True,
    web_fetch: bool = True,
    thinking: bool | str = "high",
    include_history_archive: bool = True,
    history_messages_path: str = ".pydantic-deep/messages.json",
    cost_tracking: bool = True,
    cost_budget_usd: float | None = None,
    on_cost_update: Any | None = None,
    middleware: Sequence[Any] | None = None,
    plans_dir: str | None = None,
    instrument: bool | None = None,
    **agent_kwargs: Any,
) -> Agent[DeepAgentDeps, OutputDataT]: ...


def create_deep_agent(  # noqa: C901
    model: str | Model | None = None,
    model_settings: dict[str, Any] | None = None,
    summarization_model: str | None = None,
    instructions: str | None = None,
    output_style: str | Any | None = None,
    styles_dir: str | list[str] | None = None,
    tools: Sequence[Tool[DeepAgentDeps] | Any] | None = None,
    toolsets: Sequence[AbstractToolset[DeepAgentDeps]] | None = None,
    capabilities: Sequence[AbstractCapability[Any]] | None = None,
    subagents: list[SubAgentConfig] | None = None,
    skill_directories: list[dict[str, Any]]
    | list[str]
    | list[BackendSkillsDirectory]
    | None = None,
    backend: BackendProtocol | None = None,
    include_todo: bool = True,
    include_filesystem: bool = True,
    include_subagents: bool = True,
    include_skills: bool = True,
    include_builtin_subagents: bool = True,
    include_plan: bool = True,
    max_nesting_depth: int = 1,
    subagent_registry: Any | None = None,
    subagent_extra_toolsets: Sequence[AbstractToolset[Any]] | None = None,
    include_execute: bool | None = None,
    interrupt_on: dict[str, bool] | None = None,
    output_type: OutputSpec[OutputDataT] | None = None,
    history_processors: Sequence[HistoryProcessor[DeepAgentDeps]] | None = None,
    eviction_token_limit: int | None = 20_000,
    edit_format: str = "hashline",
    context_manager: bool = True,
    context_manager_max_tokens: int | None = None,
    on_context_update: Any | None = None,
    on_before_compress: Any | None = None,
    on_after_compress: Any | None = None,
    on_eviction: Any | None = None,
    context_files: list[str] | None = None,
    context_discovery: bool = False,
    include_memory: bool = True,
    memory_dir: str | None = None,
    retries: int = 3,
    hooks: list[Any] | None = None,
    patch_tool_calls: bool = True,
    include_checkpoints: bool = False,
    checkpoint_frequency: str = "every_tool",
    max_checkpoints: int = 20,
    checkpoint_store: Any | None = None,
    include_teams: bool = False,
    include_improve: bool = False,
    stuck_loop_detection: bool = True,
    web_search: bool = True,
    web_fetch: bool = True,
    thinking: bool | str = "high",
    include_history_archive: bool = True,
    history_messages_path: str = ".pydantic-deep/messages.json",
    cost_tracking: bool = True,
    cost_budget_usd: float | None = None,
    on_cost_update: Any | None = None,
    middleware: Sequence[Any] | None = None,
    plans_dir: str | None = None,
    instrument: bool | None = None,
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
        model: Model to use (default: anthropic:claude-opus-4-6).
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
        capabilities: Additional capabilities to register.
        subagents: Subagent configurations for the task tool.
        skill_directories: Directories to discover skills from.
            Accepts plain string paths or BackendSkillsDirectory instances.
        backend: File storage backend (default: StateBackend).
        include_todo: Whether to include the todo toolset.
        include_filesystem: Whether to include the filesystem toolset.
        include_subagents: Whether to include the subagent toolset.
        include_skills: Whether to include the skills toolset.
        include_builtin_subagents: Whether to include built-in subagents (research).
        include_plan: Whether to include the built-in 'planner' subagent that
            provides Claude Code-style plan mode. The planner analyzes code,
            asks clarifying questions via ``ask_user``, and creates step-by-step
            implementation plans saved to markdown files. Requires
            ``include_subagents=True``. Defaults to True.
        max_nesting_depth: Maximum subagent nesting depth. 1 (default) means
            subagents can spawn one level of their own subagents. Set to 0
            to disable nested delegation.
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
            Tool outputs exceeding this limit are saved to files and
            replaced with a preview + file reference. Defaults to 20,000.
            Set to None to disable eviction.
        context_manager: Whether to enable the ContextManagerMiddleware for
            automatic token tracking and auto-compression. When True (default),
            the middleware monitors token usage and triggers LLM-based
            summarization when approaching the token budget. Also provides
            tool output truncation when middleware wrapping is active.
        context_manager_max_tokens: Maximum token budget for the conversation.
            When None (default), auto-detected from genai-prices based on
            the model name. Falls back to 200,000 if model is not found.
            Used by ContextManagerMiddleware to calculate usage percentage and
            determine when to trigger auto-compression. Defaults to 200,000.
        on_context_update: Callback for context usage updates. Called with
            ``(percentage, current_tokens, max_tokens)`` before each model call.
            Supports both sync and async callables. Useful for UI display.
            When True, reading image files (.png, .jpg, .jpeg, .gif, .webp)
            returns a BinaryContent object that multimodal models can see,
            instead of garbled text. Defaults to False.
        summarization_model: Model to use for LLM-based context compression
            summaries. Defaults to ``anthropic:claude-haiku-4-5-20251001``. When set,
            the middleware uses its own default. Passed through to
            ``ContextManagerMiddleware.summarization_model``.
        context_files: List of paths to context files in the backend
            (e.g., ["/project/DEEP.md", "/project/SOUL.md"]).
            Files are loaded from the runtime backend (ctx.deps.backend)
            and injected into the system prompt. Missing files are
            silently skipped.
        context_discovery: Whether to auto-discover context files at the
            backend root (/). Scans for AGENTS.md, SOUL.md.
            Defaults to False.
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
            DockerSandbox). Adds HooksCapability to the agent.
        cost_tracking: Whether to enable automatic cost tracking via
            CostTracking capability (from pydantic-ai-shields). When True
            (default), token usage and USD costs are tracked across runs.
        cost_budget_usd: Maximum allowed cumulative cost in USD.
            When exceeded, the next run raises BudgetExceededError.
            None (default) means unlimited.
        on_cost_update: Callback for cost updates after each run.
            Called with a CostInfo object containing run and cumulative
            token/cost data. Supports sync and async callables.
        patch_tool_calls: Whether to enable PatchToolCallsProcessor that
            fixes orphaned tool calls in message history. Useful when
            resuming interrupted conversations. Defaults to True.
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
        include_improve: Whether to include the self-improvement toolset
            (``improve`` and ``get_improvement_status`` tools).
            When True, adds tools for spawning agent teams, assigning
            tasks via shared todo lists, messaging teammates, and
            dissolving teams. Defaults to False.
        web_search: Whether to include the ``WebSearch`` capability.
            Defaults to True.
        web_fetch: Whether to include the ``WebFetch`` capability.
            Defaults to True.
        thinking: Thinking/reasoning effort level. ``True`` enables with
            provider default, ``False`` disables, or a string level:
            ``"minimal"``, ``"low"``, ``"medium"``, ``"high"``, ``"xhigh"``.
            Defaults to ``"high"``.
        include_history_archive: Whether to persist full conversation history
            before context compression discards messages. Adds a
            ``search_conversation_history`` tool so the agent can look up
            details from before compression. Only active when
            ``context_manager=True``. Defaults to True.
        history_messages_path: Path to the messages.json file that stores
            the full conversation history. Defaults to
            ``".pydantic-deep/messages.json"``.
        middleware: List of additional AbstractCapability instances to
            include. These extend the agent with custom lifecycle hooks.
        plans_dir: Directory to save plan files from the planner subagent.
            Defaults to ``/plans`` (relative to backend root).
        model_settings: Provider-specific model settings (temperature, thinking,
            etc.). Passed directly to the pydantic-ai Agent. Common keys:
            ``temperature``, ``max_tokens``, ``anthropic_thinking``,
            ``openai_reasoning_effort``. See pydantic-ai ModelSettings docs.
        instrument: Enable OpenTelemetry/Logfire instrumentation. When True,
            the agent emits spans for LLM calls, tool invocations, and token
            usage. Requires ``logfire`` or OpenTelemetry SDK. None (default)
            means no instrumentation.
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

    # Build effective subagents list (user-provided + built-ins)
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

    # Built-in research subagent (deep agent with web + filesystem)
    if include_builtin_subagents and include_subagents:
        from pydantic_deep.subagents import RESEARCH_SUBAGENT

        # Only add if user hasn't already defined a "research" subagent
        existing_names = {sa["name"] for sa in effective_subagents}
        if RESEARCH_SUBAGENT["name"] not in existing_names:
            effective_subagents.append(SubAgentConfig(**RESEARCH_SUBAGENT))

    def _set_toolset_retries(toolset: AbstractToolset[DeepAgentDeps], max_retries: int) -> None:
        """Set max_retries on a FunctionToolset and all its registered tools."""
        from pydantic_ai.toolsets.function import FunctionToolset

        if isinstance(toolset, FunctionToolset):  # pragma: no branch
            toolset.max_retries = max_retries
            for tool in toolset.tools.values():
                tool.max_retries = max_retries

    # Build toolsets list
    all_toolsets: list[AbstractToolset[DeepAgentDeps]] = []

    _todo_proxy: _DepsTodoProxy | None = None
    if include_todo:
        _todo_proxy = _DepsTodoProxy()
        todo_toolset = create_todo_toolset(storage=_todo_proxy, id="deep-todo")
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
            image_support=True,
            edit_format=edit_format,  # type: ignore[arg-type,unused-ignore]
        )
        _set_toolset_retries(console_toolset, retries)
        all_toolsets.append(console_toolset)

    _subagent_task_manager: Any | None = None
    subagent_toolset: Any | None = None
    if include_subagents:
        # Subagents use the same model as the main agent
        subagent_model = model

        # Deep agent factory for subagents — subagents are full deep agents
        # with filesystem, web, memory, eviction, and patch support
        _sub_model = subagent_model
        _sub_edit_fmt = edit_format
        _sub_extra = list(subagent_extra_toolsets) if subagent_extra_toolsets else []
        _sub_context_files = context_files
        _sub_context_discovery = context_discovery
        _sub_memory = include_memory
        _sub_memory_dir = memory_dir
        _sub_web_search = web_search
        _sub_web_fetch = web_fetch

        def _default_deep_agent_factory(cfg: dict[str, Any]) -> Any:
            """Create a deep agent for subagent execution."""
            return create_deep_agent(
                model=cfg.get("model", _sub_model),
                instructions=cfg["instructions"],
                include_filesystem=True,
                include_execute=True,
                include_todo=True,
                web_search=_sub_web_search,
                web_fetch=_sub_web_fetch,
                thinking=False,  # Save tokens on subagents
                include_subagents=False,
                include_skills=False,
                include_plan=False,
                include_teams=False,
                include_builtin_subagents=False,
                context_manager=False,
                cost_tracking=False,
                include_memory=_sub_memory,
                memory_dir=_sub_memory_dir,
                context_files=_sub_context_files,
                context_discovery=_sub_context_discovery,
                edit_format=_sub_edit_fmt,
                subagent_extra_toolsets=_sub_extra or None,
            )

        # Inject agent_factory on subagents that don't have one already
        for sa_config in effective_subagents:
            if (
                sa_config.get("agent") is None and sa_config.get("agent_factory") is None
            ):  # pragma: no branch
                sa_config["agent_factory"] = _default_deep_agent_factory

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
            include_general_purpose=False,  # We use our own built-in subagents
            max_nesting_depth=max_nesting_depth,
            registry=subagent_registry,
        )
        all_toolsets.append(subagent_toolset)
        _subagent_task_manager = getattr(subagent_toolset, "task_manager", None)

    # Skills toolset
    skills_toolset = None
    if include_skills:
        # Normalize skill_directories to list[str | BackendSkillsDirectory]
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

        skills_toolset = SkillsToolset(
            id="deep-skills",
            directories=directories,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
        )
        all_toolsets.append(skills_toolset)  # type: ignore[arg-type]

    # Context toolset
    context_toolset = None
    if context_files or context_discovery:
        from pydantic_deep.toolsets.context import ContextToolset

        context_toolset = ContextToolset(
            context_files=context_files,
            context_discovery=context_discovery,
            is_subagent=False,
        )
        all_toolsets.append(context_toolset)

    # Memory toolset
    memory_toolset = None
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

        # Wire teams to subagent execution engine when both are enabled
        _team_kwargs: dict[str, Any] = {}
        if include_subagents and _subagent_task_manager is not None:
            _team_registry = subagent_registry
            if _team_registry is None:
                from subagents_pydantic_ai import DynamicAgentRegistry

                _team_registry = DynamicAgentRegistry()
            _team_kwargs["registry"] = _team_registry
            _team_kwargs["task_manager"] = _subagent_task_manager

            # Get the task() tool function from the subagent toolset
            if subagent_toolset is not None:  # pragma: no branch
                _task_tool = subagent_toolset.tools.get("task")
                if _task_tool is not None:
                    _team_kwargs["task_fn"] = _task_tool.function

            # Factory that creates deep agents for team members
            _team_model = model
            _team_edit_fmt = edit_format

            def _deep_agent_factory(cfg: dict[str, Any]) -> Any:  # pragma: no cover
                return create_deep_agent(
                    model=cfg.get("model", _team_model),
                    instructions=cfg["instructions"],
                    include_filesystem=True,
                    include_todo=True,
                    include_subagents=False,
                    include_skills=False,
                    include_plan=False,
                    include_teams=False,
                    context_manager=False,
                    cost_tracking=False,
                    edit_format=_team_edit_fmt,
                )

            _team_kwargs["agent_factory"] = _deep_agent_factory

        team_toolset = create_team_toolset(**_team_kwargs)
        all_toolsets.append(team_toolset)

    # Build base instructions — always include BASE_PROMPT, append user instructions
    base_instructions = DEFAULT_INSTRUCTIONS
    if instructions:
        base_instructions = base_instructions + "\n\n" + instructions

    # Improve toolset (self-improvement from session analysis)
    if include_improve:
        from pathlib import Path as _Path

        from pydantic_deep.toolsets.improve import ImproveToolset

        _improve_sessions = _Path(".pydantic-deep/sessions")
        if backend is not None:  # pragma: no branch
            _wd = getattr(backend, "root_dir", None)
            if _wd:  # pragma: no branch
                _improve_sessions = _Path(str(_wd)) / ".pydantic-deep" / "sessions"

        improve_toolset = ImproveToolset(
            sessions_dir=_improve_sessions,
            working_dir=_Path("."),
            model=model if isinstance(model, str) else "openrouter:anthropic/claude-sonnet-4",
        )
        all_toolsets.append(improve_toolset)

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

    # patch_tool_calls capability is added later (see capabilities section below).
    _patch_tool_calls = patch_tool_calls

    # Eviction capability is added later (see capabilities section below).
    # Previously this was a history processor; now it uses after_tool_execute
    # to intercept large outputs before they enter message history.
    _eviction_token_limit = eviction_token_limit
    _on_eviction = on_eviction

    # Resolve history_messages_path to absolute for the middleware
    abs_messages_path: str | None = None
    if include_history_archive and context_manager:
        import os

        if os.path.isabs(history_messages_path):  # pragma: no cover
            abs_messages_path = history_messages_path
        elif hasattr(backend, "root_dir"):
            abs_messages_path = str(backend.root_dir / history_messages_path)  # type: ignore[union-attr,operator,unused-ignore]
        else:
            abs_messages_path = os.path.join(os.getcwd(), history_messages_path)

        # Register the search tool (reads the same file the middleware writes to)
        from pydantic_deep.processors.history_archive import create_history_search_toolset

        all_toolsets.append(create_history_search_toolset(abs_messages_path))

    # Context manager capability (token tracking + auto-compression)
    context_mw: Any | None = None
    limit_warner: Any | None = None
    if context_manager:
        from pydantic_ai_summarization import ContextManagerCapability, LimitWarnerCapability

        _cm_kwargs: dict[str, Any] = {
            "on_usage_update": on_context_update,
        }
        if context_manager_max_tokens:
            _cm_kwargs["max_tokens"] = context_manager_max_tokens
        _cm_kwargs["summarization_model"] = summarization_model or DEFAULT_SUMMARIZATION_MODEL
        if on_before_compress is not None:
            _cm_kwargs["on_before_compress"] = on_before_compress
        if on_after_compress is not None:
            _cm_kwargs["on_after_compress"] = on_after_compress
        _cm_kwargs["include_compact_tool"] = True
        context_mw = ContextManagerCapability(**_cm_kwargs)

        # Warn the model before context limits are hit.
        # warning_threshold=0.7 means URGENT at 70%, well before
        # auto-compression kicks in at compress_threshold (default 0.9).
        limit_warner = LimitWarnerCapability(
            max_context_tokens=context_mw._resolved_max_tokens,
            warning_threshold=0.7,
        )

    # Cost tracking capability
    cost_cap: Any | None = None
    if cost_tracking:
        from pydantic_ai_shields import CostTracking

        model_name = model if isinstance(model, str) else None
        cost_cap = CostTracking(
            model_name=model_name,
            budget_usd=cost_budget_usd,
            on_cost_update=on_cost_update,
        )

    if all_processors:
        agent_create_kwargs["history_processors"] = all_processors

    # Build effective model_settings with prompt caching defaults.
    # Anthropic-specific keys are silently ignored by non-Anthropic models,
    # so we always set them — no provider detection needed.
    effective_model_settings: dict[str, Any] = {
        "anthropic_cache_instructions": True,
        "anthropic_cache_tool_definitions": True,
        "anthropic_cache_messages": True,
    }
    # User-provided settings override defaults
    if model_settings:  # pragma: no cover
        effective_model_settings.update(model_settings)
    agent_create_kwargs["model_settings"] = effective_model_settings

    # Apply instrumentation
    if instrument is not None:  # pragma: no cover
        agent_create_kwargs["instrument"] = instrument

    # Build capabilities list
    all_capabilities: list[Any] = []

    if _patch_tool_calls:
        from pydantic_deep.processors.patch import PatchToolCallsCapability

        all_capabilities.append(PatchToolCallsCapability())

    if _eviction_token_limit is not None:
        from pydantic_deep.processors.eviction import EvictionCapability

        all_capabilities.append(
            EvictionCapability(
                backend=backend,
                token_limit=_eviction_token_limit,
                on_eviction=_on_eviction,
            )
        )

    if hooks is not None:
        from pydantic_deep.capabilities.hooks import HooksCapability

        all_capabilities.append(HooksCapability(hooks=hooks))

    if include_checkpoints:
        from pydantic_deep.toolsets.checkpointing import (
            CheckpointMiddleware as _CheckpointCap,
        )

        all_capabilities.append(
            _CheckpointCap(
                store=_cp_store,
                frequency=checkpoint_frequency,
                max_checkpoints=max_checkpoints,
            )
        )

    if stuck_loop_detection:
        from pydantic_deep.capabilities.stuck_loop import StuckLoopDetection

        all_capabilities.append(StuckLoopDetection())

    if middleware:
        all_capabilities.extend(middleware)

    if context_mw is not None:
        all_capabilities.append(context_mw)

    if limit_warner is not None:
        all_capabilities.append(limit_warner)

    if cost_cap is not None:
        all_capabilities.append(cost_cap)

    if web_search:  # pragma: no cover
        from pydantic_ai.capabilities import WebSearch

        all_capabilities.append(WebSearch())

    if web_fetch:  # pragma: no cover
        from pydantic_ai.capabilities import WebFetch

        all_capabilities.append(WebFetch())

    if thinking is not False:  # pragma: no cover
        from pydantic_ai.capabilities import Thinking

        effort: Any = thinking if isinstance(thinking, str) else True
        all_capabilities.append(Thinking(effort=effort))

    # Add user-provided capabilities
    if capabilities:
        all_capabilities.extend(capabilities)

    # Add user-provided tools
    if tools:
        agent_create_kwargs["tools"] = tools

    if all_capabilities:
        agent_create_kwargs["capabilities"] = all_capabilities

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

        if include_todo and _todo_proxy is not None:
            _todo_proxy._deps = ctx.deps
            todo_prompt = get_todo_system_prompt(_todo_proxy)
            if todo_prompt:
                parts.append(todo_prompt)

        if include_filesystem:
            console_prompt = get_console_system_prompt(edit_format=edit_format)  # type: ignore[arg-type,unused-ignore]
            if console_prompt:
                parts.append(console_prompt)

        # NOTE: Toolset get_instructions() are called automatically by
        # pydantic-ai's CombinedToolset since v1.74.0.

        if include_subagents:
            # Build configs list for prompt generation
            prompt_configs: list[SubAgentConfig] = list(effective_subagents or [])
            if prompt_configs:
                subagent_prompt = get_subagent_system_prompt(prompt_configs)
                if subagent_prompt:
                    parts.append(subagent_prompt)

        if web_search or web_fetch:
            web_lines = ["## Web Tools\n\nYou have access to the web:"]
            if web_search:
                web_lines.append(
                    "- **web search** — search the internet for current information, news, docs"
                )
            if web_fetch:
                web_lines.append("- **web fetch** — fetch and read any URL as Markdown")
            web_lines.append(
                "\nWhen the user asks you to look something up online, visit a website, "
                "or check current information — use these tools. Do NOT refuse."
            )
            parts.append("\n".join(web_lines))

        return "\n\n".join(parts) if parts else ""

    # Expose context middleware for CLI /compact and /context commands
    agent._context_middleware = context_mw  # type: ignore[attr-defined]
    agent._task_manager = _subagent_task_manager  # type: ignore[attr-defined]
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
    # Upload files (batch)
    if files:
        deps.upload_files(files, upload_dir=upload_dir)

    # Run agent
    result = await agent.run(query, deps=deps)
    return result.output
