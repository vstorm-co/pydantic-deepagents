"""Main agent factory for pydantic-deep."""

from __future__ import annotations

import contextvars
import os
import warnings
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from pydantic_ai import Agent, UsageLimits
from pydantic_ai._agent_graph import HistoryProcessor
from pydantic_ai.capabilities import (
    AbstractCapability,
    ProcessHistory,
    Thinking,
    WebFetch,
    WebSearch,
)
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.models import Model
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.output import OutputSpec
from pydantic_ai.tools import DeferredToolRequests, Tool
from pydantic_ai.toolsets.function import FunctionToolset
from pydantic_ai_backends import (
    BackendProtocol,
    SandboxProtocol,
    StateBackend,
    create_console_toolset,
    ensure_async,
)
from pydantic_ai_shields import CostTracking
from pydantic_ai_summarization import ContextManagerCapability, LimitWarnerCapability
from pydantic_ai_todo import create_todo_toolset
from subagents_pydantic_ai import (
    DynamicAgentRegistry,
    UsageLimitsFactory,
    create_subagent_toolset,
)

# `overload` from typing_extensions (not typing): its registry is readable via
# get_overloads() on every Python version, whereas typing.overload only
# registers overloads on 3.11+. The DeepAgentSpec drift-guard test relies on it.
from typing_extensions import overload

from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.features.checkpointing import (
    CheckpointMiddleware,
    CheckpointStore,
    CheckpointToolset,
    InMemoryCheckpointStore,
)
from pydantic_deep.features.context import ContextToolset
from pydantic_deep.features.eviction import EvictionCapability
from pydantic_deep.features.forking import create_fork_toolset
from pydantic_deep.features.forking.capability import LiveForkCapability
from pydantic_deep.features.forking.coordinator import _PerBranchCostTracking
from pydantic_deep.features.history_archive import create_history_search_toolset
from pydantic_deep.features.hooks import HookEvent, HooksCapability
from pydantic_deep.features.improve import ImproveToolset
from pydantic_deep.features.liteparse import LiteparseToolset
from pydantic_deep.features.memory import (
    DEFAULT_MAX_MEMORY_LINES,
    DEFAULT_MEMORY_DIR,
    DEFAULT_PIN_END_MARKER,
    AgentMemoryToolset,
)
from pydantic_deep.features.message_queue import MessageQueueCapability
from pydantic_deep.features.monitoring import create_monitor_toolset
from pydantic_deep.features.patch import PatchToolCallsCapability
from pydantic_deep.features.periodic_reminder import (
    PeriodicReminderCapability,
    PeriodicReminderConfig,
)
from pydantic_deep.features.plan import (
    PLANNER_DESCRIPTION,
    PLANNER_INSTRUCTIONS,
    create_plan_toolset,
)
from pydantic_deep.features.skills import Skill, SkillsToolset
from pydantic_deep.features.skills.backend import BackendSkillsDirectory
from pydantic_deep.features.stuck_loop import StuckLoopDetection
from pydantic_deep.features.teams import create_team_toolset
from pydantic_deep.features.tool_search import ToolSearch, defer_situational_toolsets
from pydantic_deep.instructions import build_instruction_providers, render_instructions
from pydantic_deep.models import (
    DEFAULT_IMPROVE_MODEL,
    DEFAULT_MODEL,
    DEFAULT_SUMMARIZATION_MODEL,
)
from pydantic_deep.prompts import BASE_PROMPT
from pydantic_deep.styles import OutputStyle, format_style_prompt, resolve_style
from pydantic_deep.subagents import BUILTIN_SUBAGENTS
from pydantic_deep.types import SubAgentConfig

if TYPE_CHECKING:
    from pydantic_ai import RunContext
    from pydantic_ai.capabilities.abstract import ValidatedToolArgs
    from pydantic_ai.messages import ToolCallPart
    from pydantic_ai.tools import ToolDefinition
    from pydantic_ai.toolsets import AbstractToolset

    from pydantic_deep.features.checkpointing import CheckpointFrequency
    from pydantic_deep.features.message_queue import MessageQueue

OutputDataT = TypeVar("OutputDataT")


DEFAULT_INSTRUCTIONS = BASE_PROMPT

# Substrings that mark a permanent auth/permission failure - these must NOT trigger
# fallback (the next model would fail with the same error).
_AUTH_ERROR_MARKERS = ("401", "403", "unauthorized", "forbidden")

# Per-asyncio-context hop counter used by _fallback_on to track which hop in the
# fallback chain is currently in flight.  ContextVar is correct for concurrent
# asyncio tasks (each task gets its own copy).  For sequential `await agent.run()`
# calls in the same coroutine without a task boundary the counter persists; in that
# case it resets automatically once the chain is fully exhausted.
_fallback_hop_cv: contextvars.ContextVar[int] = contextvars.ContextVar(
    "_pd_fallback_hop", default=0
)


class _HopResettingFallbackModel(FallbackModel):
    """`FallbackModel` that zeroes the per-context fallback hop counter at the
    start of every request.

    `_fallback_on` tracks which hop of the chain is in flight via
    :data:`_fallback_hop_cv` (a side-channel counter - `FallbackModel` does
    not tell `fallback_on` which model failed, and inferring it from the
    exception's `model_name` is unreliable when models share a name). The
    counter is only safe within a single `request`; a *partial* recovery
    (primary fails, a fallback succeeds) leaves it `> 0` and that stale value
    leaks into the next request in the same coroutine context, mis-attributing
    the `MODEL_FALLBACK_TRIGGERED` `primary→fallback` pairs (and possibly
    skipping a real hop). Resetting at each request boundary closes that leak
    while keeping `ContextVar`'s per-task isolation for concurrent runs.
    """

    async def request(self, *args: Any, **kwargs: Any) -> Any:
        _fallback_hop_cv.set(0)
        return await super().request(*args, **kwargs)

    @asynccontextmanager
    async def request_stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        _fallback_hop_cv.set(0)
        async with super().request_stream(*args, **kwargs) as response:
            yield response


def _wrap_with_fallback_and_hooks(
    primary: str | Model,
    fallbacks: list[str | Model],
    fallback_hooks: list[Any],
    backend: BackendProtocol,
) -> FallbackModel:
    """Build a FallbackModel with auth-error filtering and optional hook dispatch.

    Auth errors (401/403/unauthorized/forbidden) always return False so the
    original exception propagates without triggering a fallback.

    Hook dispatch (MODEL_FALLBACK_TRIGGERED) fires only when there is a subsequent
    model to try; the final model's failure is silently returned as True (chain
    exhausted) without emitting a spurious event.
    """

    hooks_cap = HooksCapability(hooks=fallback_hooks)
    async_backend = ensure_async(backend)
    # Build a flat list of model names for accurate from/to reporting.
    model_chain: list[str] = [primary if isinstance(primary, str) else str(primary)] + [
        f if isinstance(f, str) else str(f) for f in fallbacks
    ]
    total_models = len(model_chain)

    async def _fallback_on(exc: Exception) -> bool:
        if not isinstance(exc, ModelAPIError):
            return False
        message = str(exc).lower()
        if any(marker in message for marker in _AUTH_ERROR_MARKERS):
            return False
        hop = _fallback_hop_cv.get()
        # The counter is normally zeroed per request by _HopResettingFallbackModel
        # (closing the partial-recovery leak). This guard is a belt-and-suspenders
        # reset for the chain-fully-exhausted case when _fallback_on is driven
        # without going through request() (e.g. in direct unit tests).
        if hop >= total_models:
            hop = 0
        _fallback_hop_cv.set(hop + 1)
        # Only fire the hook when there is actually a next model to fall back to.
        if hop < len(fallbacks):
            await hooks_cap.dispatch_model_fallback(
                model_chain[hop], model_chain[hop + 1], exc, async_backend
            )
        return True

    return _HopResettingFallbackModel(primary, *fallbacks, fallback_on=_fallback_on)


class _DepsTodoProxy:
    """Proxy that delegates todo reads/writes to the current run's DeepAgentDeps.

    Implements `TodoStorageProtocol` so it can be passed as `storage`
    to `create_todo_toolset()`.  The proxy is bound to a specific
    `DeepAgentDeps` instance at the start of each model turn (inside
    `dynamic_instructions`), ensuring the toolset always operates on
    the correct deps object.

    The bound deps is stored in a :class:`contextvars.ContextVar` rather than a
    plain attribute, so that concurrent runs of the *same* agent instance (e.g.
    `asyncio.gather(agent.run(deps=A), agent.run(deps=B))`) each see their own
    deps.  `asyncio` copies the current context when a task is created, so the
    ContextVar set inside one run's `dynamic_instructions` never leaks into a
    sibling run's `read_todos` / `write_todos` calls.
    """

    def __init__(self) -> None:
        self._deps_var: contextvars.ContextVar[DeepAgentDeps | None] = contextvars.ContextVar(
            "deep_todo_proxy_deps", default=None
        )

    @property
    def _deps(self) -> DeepAgentDeps | None:
        return self._deps_var.get()

    @_deps.setter
    def _deps(self, value: DeepAgentDeps | None) -> None:
        self._deps_var.set(value)

    @property
    def todos(self) -> list[Any]:
        deps = self._deps_var.get()
        if deps is None:
            return []
        return deps.todos

    @todos.setter
    def todos(self, value: list[Any]) -> None:
        deps = self._deps_var.get()
        if deps is not None:
            deps.todos = list(value)


class _TodoProxyBinder(AbstractCapability[DeepAgentDeps]):
    """Bind the shared todo proxy to the running deps in the tool's own context.

    The todo tools are ``tool_plain`` (no ``RunContext``), so the shared
    :class:`_DepsTodoProxy` is their only channel to the per-run deps.
    pydantic-ai runs each tool in its own ``contextvars`` context, so a binding
    done in ``dynamic_instructions`` lands in a different context and never
    reaches the tools. Binding here — right before each tool runs, in the tool's
    own context — keeps the proxy's per-run isolation while ensuring todo writes
    actually land on ``deps.todos``.
    """

    def __init__(self, proxy: _DepsTodoProxy) -> None:
        self._proxy = proxy

    async def before_tool_execute(
        self,
        ctx: RunContext[DeepAgentDeps],
        *,
        call: ToolCallPart,
        tool_def: ToolDefinition,
        args: ValidatedToolArgs,
    ) -> ValidatedToolArgs:
        self._proxy._deps = ctx.deps
        return args


def _make_default_deep_agent_factory(
    *,
    model: str | Model | None,
    edit_format: Any,
    context_files: Any,
    context_discovery: Any,
    memory_dir: Any,
    web_search: bool,
    web_fetch: bool,
) -> Callable[[dict[str, Any]], Any]:
    """Build the default subagent factory closure.

    Extracted to module scope (rather than nested in `create_deep_agent`) so
    the factory can be unit-tested in isolation without relying on the caller's
    subagent-config dicts being mutated - those dicts are now shallow-copied
    before any `agent_factory` / toolset injection.
    """

    def _factory(cfg: dict[str, Any]) -> Any:
        """Create a deep agent for subagent execution."""
        task_instructions = cfg.get("instructions") or ""
        instructions = (
            DEFAULT_INSTRUCTIONS + "\n\n" + task_instructions
            if task_instructions
            else DEFAULT_INSTRUCTIONS
        )
        return create_deep_agent(
            model=cfg.get("model", model),
            instructions=instructions,
            include_filesystem=True,
            include_execute=True,
            include_todo=True,
            web_search=web_search,
            web_fetch=web_fetch,
            thinking=False,  # Save tokens on subagents
            include_subagents=False,
            include_skills=False,
            include_plan=False,
            include_teams=False,
            include_monitoring=False,
            include_builtin_subagents=False,
            context_manager=False,
            cost_tracking=False,
            include_memory=False,
            memory_dir=memory_dir,
            context_files=context_files,
            context_discovery=context_discovery,
            edit_format=edit_format,
            extra_toolsets=tuple(cfg.get("toolsets") or []),
        )

    return _factory


def _inject_subagent_context_toolset(sa_config: SubAgentConfig) -> None:
    """Append a per-subagent `ContextToolset` when the config sets `context_files`.

    Mutates `sa_config` in place. `create_deep_agent` only ever calls this on
    a shallow copy of the caller's config, so the caller's dict is never touched.
    """
    per_sa_files = sa_config.get("context_files")
    if not per_sa_files:
        return
    existing = list(sa_config.get("toolsets", []))
    existing.append(ContextToolset(context_files=per_sa_files))
    sa_config["toolsets"] = existing


def _inject_subagent_memory_toolset(sa_config: SubAgentConfig, memory_dir: str | None) -> None:
    """Append a per-subagent `AgentMemoryToolset` unless disabled via `extra.memory=False`.

    Mutates `sa_config` in place (a shallow copy by the time it is called).
    """
    extra = sa_config.get("extra", {})
    # Memory enabled by default; can be disabled via extra.memory=False
    if not extra.get("memory", True):
        return
    mem = AgentMemoryToolset(
        agent_name=sa_config["name"],
        memory_dir=memory_dir or DEFAULT_MEMORY_DIR,
        max_lines=extra.get("memory_max_lines", DEFAULT_MAX_MEMORY_LINES),
        max_tokens=extra.get("memory_max_tokens"),
        pin_marker=extra.get("memory_pin_marker", DEFAULT_PIN_END_MARKER),
    )
    existing = list(sa_config.get("toolsets", []))
    existing.append(mem)
    sa_config["toolsets"] = existing


def _inject_subagent_extra_toolsets(
    sa_config: SubAgentConfig, extra_toolsets: Sequence[Any]
) -> None:
    """Append `subagent_extra_toolsets` to a subagent's `toolsets` list.

    Mutates `sa_config` in place (a shallow copy by the time it is called).
    """
    if not extra_toolsets:
        return
    existing = list(sa_config.get("toolsets", []))
    existing.extend(extra_toolsets)
    sa_config["toolsets"] = existing


def _set_toolset_retries(toolset: AbstractToolset[DeepAgentDeps], max_retries: int) -> None:
    """Set `max_retries` on a `FunctionToolset` and all its registered tools."""
    if isinstance(toolset, FunctionToolset):  # pragma: no branch
        toolset.max_retries = max_retries
        for tool in toolset.tools.values():
            tool.max_retries = max_retries


def _build_console_toolset(
    *,
    interrupt_on: dict[str, bool],
    include_execute: bool | None,
    backend: BackendProtocol,
    edit_format: str,
    retries: int,
) -> AbstractToolset[DeepAgentDeps]:
    """Build the filesystem/console toolset with approval gating resolved.

    Write/edit are gated when `interrupt_on` asks for them; execute is gated
    whenever any interrupt is enabled (the approval channel only exists then),
    unless `interrupt_on` sets it explicitly. `include_execute`, when not `None`,
    forces the execute tool on or off; otherwise it is auto-detected from whether
    the backend is a `SandboxProtocol`.
    """
    require_write_approval = interrupt_on.get("write_file", False) or interrupt_on.get(
        "edit_file", False
    )
    require_execute_approval = interrupt_on.get("execute", any(interrupt_on.values()))
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
    _set_toolset_retries(console_toolset, retries)  # type: ignore[arg-type,unused-ignore]
    return console_toolset  # type: ignore[no-any-return,unused-ignore]


def _build_context_capabilities(
    *,
    on_context_update: Any | None,
    context_manager_max_tokens: int | None,
    summarization_model: str | None,
    on_before_compress: Any | None,
    on_after_compress: Any | None,
) -> tuple[ContextManagerCapability, LimitWarnerCapability]:
    """Build the context-manager + limit-warner capability pair.

    Optional callbacks are only forwarded when set, so they never override the
    capability's own defaults. The limit warner fires at 70% of the resolved
    token budget — well before auto-compression kicks in at 90%.
    """
    kwargs: dict[str, Any] = {
        "on_usage_update": on_context_update,
        "summarization_model": summarization_model or DEFAULT_SUMMARIZATION_MODEL,
        "include_compact_tool": True,
    }
    if context_manager_max_tokens:
        kwargs["max_tokens"] = context_manager_max_tokens
    if on_before_compress is not None:
        kwargs["on_before_compress"] = on_before_compress
    if on_after_compress is not None:
        kwargs["on_after_compress"] = on_after_compress
    context_mw = ContextManagerCapability(**kwargs)
    limit_warner = LimitWarnerCapability(
        max_context_tokens=context_mw._resolved_max_tokens,
        warning_threshold=0.7,
    )
    return context_mw, limit_warner


@overload
def create_deep_agent(
    model: str | Model | None = None,
    fallback_model: str | Model | list[str | Model] | None = None,
    model_settings: dict[str, Any] | None = None,
    summarization_model: str | None = None,
    instructions: str | None = None,
    output_style: str | OutputStyle | None = None,
    styles_dir: str | list[str] | None = None,
    tools: Sequence[Tool[DeepAgentDeps] | Any] | None = None,
    toolsets: Sequence[AbstractToolset[DeepAgentDeps]] | None = None,
    extra_toolsets: Sequence[AbstractToolset[Any]] | None = None,
    mcp_servers: Sequence[AbstractToolset[Any]] | None = None,
    capabilities: Sequence[AbstractCapability[Any]] | None = None,
    subagents: list[SubAgentConfig] | None = None,
    skill_directories: list[dict[str, Any]]
    | list[str]
    | list[BackendSkillsDirectory]
    | None = None,
    skills: list[Skill] | None = None,
    backend: BackendProtocol | None = None,
    include_todo: bool = True,
    include_filesystem: bool = True,
    include_subagents: bool = True,
    include_skills: bool = True,
    include_builtin_subagents: bool = True,
    include_plan: bool = True,
    max_nesting_depth: int = 1,
    subagent_registry: DynamicAgentRegistry | None = None,
    subagent_extra_toolsets: Sequence[AbstractToolset[Any]] | None = None,
    subagent_usage_limits: UsageLimits | UsageLimitsFactory | None = None,
    include_execute: bool | None = None,
    interrupt_on: dict[str, bool] | None = None,
    output_type: None = None,
    history_processors: Sequence[HistoryProcessor[DeepAgentDeps]] | None = None,
    eviction_token_limit: int | None = 20_000,
    max_binary_content: int | None = 3,
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
    checkpoint_frequency: CheckpointFrequency = "every_tool",
    max_checkpoints: int = 20,
    checkpoint_store: CheckpointStore | None = None,
    include_teams: bool = False,
    include_monitoring: bool = True,
    include_improve: bool = False,
    include_liteparse: bool = False,
    stuck_loop_detection: bool = True,
    periodic_reminder: PeriodicReminderConfig | bool | None = None,
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
    message_queue: MessageQueue | None = None,
    forking: bool | LiveForkCapability = False,
    tool_search: bool = False,
    instrument: bool | None = None,
    **agent_kwargs: Any,
) -> Agent[DeepAgentDeps, str]: ...


@overload
def create_deep_agent(
    model: str | Model | None = None,
    fallback_model: str | Model | list[str | Model] | None = None,
    model_settings: dict[str, Any] | None = None,
    summarization_model: str | None = None,
    instructions: str | None = None,
    output_style: str | OutputStyle | None = None,
    styles_dir: str | list[str] | None = None,
    tools: Sequence[Tool[DeepAgentDeps] | Any] | None = None,
    toolsets: Sequence[AbstractToolset[DeepAgentDeps]] | None = None,
    extra_toolsets: Sequence[AbstractToolset[Any]] | None = None,
    mcp_servers: Sequence[AbstractToolset[Any]] | None = None,
    capabilities: Sequence[AbstractCapability[Any]] | None = None,
    subagents: list[SubAgentConfig] | None = None,
    skill_directories: list[dict[str, Any]]
    | list[str]
    | list[BackendSkillsDirectory]
    | None = None,
    skills: list[Skill] | None = None,
    backend: BackendProtocol | None = None,
    include_todo: bool = True,
    include_filesystem: bool = True,
    include_subagents: bool = True,
    include_skills: bool = True,
    include_builtin_subagents: bool = True,
    include_plan: bool = True,
    max_nesting_depth: int = 1,
    subagent_registry: DynamicAgentRegistry | None = None,
    subagent_extra_toolsets: Sequence[AbstractToolset[Any]] | None = None,
    subagent_usage_limits: UsageLimits | UsageLimitsFactory | None = None,
    include_execute: bool | None = None,
    interrupt_on: dict[str, bool] | None = None,
    *,
    output_type: OutputSpec[OutputDataT],
    history_processors: Sequence[HistoryProcessor[DeepAgentDeps]] | None = None,
    eviction_token_limit: int | None = 20_000,
    max_binary_content: int | None = 3,
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
    checkpoint_frequency: CheckpointFrequency = "every_tool",
    max_checkpoints: int = 20,
    checkpoint_store: CheckpointStore | None = None,
    include_teams: bool = False,
    include_monitoring: bool = True,
    include_improve: bool = False,
    include_liteparse: bool = False,
    stuck_loop_detection: bool = True,
    periodic_reminder: PeriodicReminderConfig | bool | None = None,
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
    message_queue: MessageQueue | None = None,
    forking: bool | LiveForkCapability = False,
    tool_search: bool = False,
    instrument: bool | None = None,
    **agent_kwargs: Any,
) -> Agent[DeepAgentDeps, OutputDataT]: ...


def create_deep_agent(  # noqa: C901
    model: str | Model | None = None,
    fallback_model: str | Model | list[str | Model] | None = None,
    model_settings: dict[str, Any] | None = None,
    summarization_model: str | None = None,
    instructions: str | None = None,
    output_style: str | OutputStyle | None = None,
    styles_dir: str | list[str] | None = None,
    tools: Sequence[Tool[DeepAgentDeps] | Any] | None = None,
    toolsets: Sequence[AbstractToolset[DeepAgentDeps]] | None = None,
    extra_toolsets: Sequence[AbstractToolset[Any]] | None = None,
    mcp_servers: Sequence[AbstractToolset[Any]] | None = None,
    capabilities: Sequence[AbstractCapability[Any]] | None = None,
    subagents: list[SubAgentConfig] | None = None,
    skill_directories: list[dict[str, Any]]
    | list[str]
    | list[BackendSkillsDirectory]
    | None = None,
    skills: list[Skill] | None = None,
    backend: BackendProtocol | None = None,
    include_todo: bool = True,
    include_filesystem: bool = True,
    include_subagents: bool = True,
    include_skills: bool = True,
    include_builtin_subagents: bool = True,
    include_plan: bool = True,
    max_nesting_depth: int = 1,
    subagent_registry: DynamicAgentRegistry | None = None,
    subagent_extra_toolsets: Sequence[AbstractToolset[Any]] | None = None,
    subagent_usage_limits: UsageLimits | UsageLimitsFactory | None = None,
    include_execute: bool | None = None,
    interrupt_on: dict[str, bool] | None = None,
    output_type: OutputSpec[OutputDataT] | None = None,
    history_processors: Sequence[HistoryProcessor[DeepAgentDeps]] | None = None,
    eviction_token_limit: int | None = 20_000,
    max_binary_content: int | None = 3,
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
    checkpoint_frequency: CheckpointFrequency = "every_tool",
    max_checkpoints: int = 20,
    checkpoint_store: CheckpointStore | None = None,
    include_teams: bool = False,
    include_monitoring: bool = True,
    include_improve: bool = False,
    include_liteparse: bool = False,
    stuck_loop_detection: bool = True,
    periodic_reminder: PeriodicReminderConfig | bool | None = None,
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
    message_queue: MessageQueue | None = None,
    forking: bool | LiveForkCapability = False,
    tool_search: bool = False,
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
        fallback_model: One or more fallback models to try when the primary
            model fails with a transient error (rate limit, 5xx, timeout).
            Accepts a single model name/instance or an ordered list forming a
            fallback chain. Auth/permission errors (401/403) never trigger
            fallback. `None` (default) disables automatic fallback.
        instructions: System prompt for the agent. When provided, replaces the
            default `BASE_PROMPT` entirely. Use `BASE_PROMPT` from
            `pydantic_deep` to build on top of it:
            `instructions=f"{BASE_PROMPT}\\n\\nYour extra instructions"`.
        output_style: Output style to apply to agent responses. Can be a
            built-in style name (a key of `BUILTIN_STYLES`), a custom
            OutputStyle instance, or a name to look up in styles_dir. None
            (default) means no style override.
        styles_dir: Directory or list of directories to discover custom
            output styles from. Style files are markdown files with
            YAML frontmatter (name, description) in the directory root.
        tools: Additional tools to register.
        toolsets: Additional toolsets to register.
        extra_toolsets: Extra toolsets appended after the built-in set on the
            main agent only (not propagated to subagents).
        subagent_extra_toolsets: Extra toolsets made available to spawned
            subagents (not the main agent).
        edit_format: Edit strategy for the file-edit tool (default "hashline").
        mcp_servers: MCP server toolsets to attach (e.g. built via
            [`build_mcp_server`][pydantic_deep.mcp.build_mcp_server] or
            [`MCPRegistry.build_active`][pydantic_deep.mcp.MCPRegistry]).
        capabilities: Additional capabilities to register.
        subagents: Subagent configurations for the task tool.
        skill_directories: Directories to discover skills from.
            Accepts plain string paths or BackendSkillsDirectory instances.
        skills: Skill instances to register directly.
        backend: File storage backend (default: StateBackend).
        include_todo: Whether to include the todo toolset.
        include_filesystem: Whether to include the filesystem toolset.
        include_subagents: Whether to include the subagent toolset.
        include_skills: Whether to include the skills toolset.
        include_builtin_subagents: Whether to include built-in subagents (research).
        include_plan: Whether to include the built-in 'planner' subagent that
            provides Claude Code-style plan mode. The planner analyzes code,
            asks clarifying questions via `ask_user`, and creates step-by-step
            implementation plans saved to markdown files. Requires
            `include_subagents=True`. Defaults to True.
        max_nesting_depth: Maximum subagent nesting depth. 1 (default) means
            subagents can spawn one level of their own subagents. Set to 0
            to disable nested delegation.
        subagent_registry: Optional DynamicAgentRegistry instance. When provided,
            the task tool will also look up dynamically created agents from
            the registry (created via create_agent_factory_toolset).
        subagent_usage_limits: `UsageLimits` applied to delegated subagent
            `agent.run(...)` calls (including retries), forwarded to
            `create_subagent_toolset(usage_limits=...)`. Pass a single
            `UsageLimits` to use the same budget for every delegated run, or a
            `UsageLimitsFactory` (`(ctx, config) -> UsageLimits | None`) to
            resolve per-specialist limits by reading the selected
            `SubAgentConfig` — e.g. a small budget for lightweight specialists
            and a larger `request_limit` for heavy research/execution ones.
            `None` (default) leaves pydantic-ai's own default in place. Only
            takes effect when `include_subagents=True`.
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
        max_binary_content: Maximum number of multimodal binary parts
            (e.g. `BinaryContent` screenshots) to keep in model-visible
            history. Older binaries are written to the backend and replaced
            with a compact `read_file`-able text reference so the agent can
            still retrieve them on demand. Defaults to 3. Set to `None` to
            keep every binary in history. Only applies when
            `eviction_token_limit` is set.
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
            `(percentage, current_tokens, max_tokens)` before each model call.
            Supports both sync and async callables. Useful for UI display.
        on_before_compress: Optional callback invoked just before an automatic
            context compression runs.
        on_after_compress: Optional callback invoked just after a context
            compression completes.
        on_eviction: Optional callback invoked when a large tool output is
            evicted from history by `EvictionCapability`.
        stuck_loop_detection: Whether to enable `StuckLoopDetection`, which
            warns/errors on repetitive tool-call loops (default True).
        summarization_model: Model to use for LLM-based context compression
            summaries. Defaults to `anthropic:claude-haiku-4-5-20251001`. When set,
            the middleware uses its own default. Passed through to
            `ContextManagerMiddleware.summarization_model`.
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
            memory can be disabled via `extra={"memory": False}` in
            SubAgentConfig. Defaults to True.
        memory_dir: Base directory for memory files in the backend.
            Each agent gets its own subdirectory:
            `{memory_dir}/{agent_name}/MEMORY.md`.
            Defaults to `/.deep/memory`.
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
        patch_tool_calls: Whether to enable PatchToolCallsCapability that
            fixes orphaned tool calls in message history. Useful when
            resuming interrupted conversations. Defaults to True.
        include_checkpoints: Whether to enable conversation checkpointing.
            When True, adds CheckpointMiddleware (auto-saves snapshots)
            and CheckpointToolset (save_checkpoint, list_checkpoints,
            rewind_to tools). The checkpoint store is resolved from
            `checkpoint_store` param or `deps.checkpoint_store` at
            runtime. Defaults to False.
        checkpoint_frequency: When to auto-save checkpoints:
            `"every_tool"` (default) - after each tool call,
            `"every_turn"` - before each model request,
            `"manual_only"` - only via the save_checkpoint tool.
        max_checkpoints: Maximum number of checkpoints to keep.
            Oldest checkpoints are pruned when this limit is exceeded.
            Defaults to 20.
        checkpoint_store: Checkpoint storage backend. When None (default),
            uses InMemoryCheckpointStore. Can also be set per-session
            via `deps.checkpoint_store`.
        include_teams: Whether to include the team management toolset.
        include_improve: Whether to include the self-improvement toolset
            (`improve` and `get_improvement_status` tools).
            When True, adds tools for spawning agent teams, assigning
            tasks via shared todo lists, messaging teammates, and
            dissolving teams. Defaults to False.
        include_liteparse: Whether to include the LiteParse document parsing
            toolset (`parse_document`, `screenshot_document` tools).
            Requires Node.js >= 18 and the `liteparse` optional extra:
            `pip install pydantic-deep[liteparse]`.
            The Node.js CLI is auto-installed via npm on first use if
            `npm` is in PATH. Defaults to False.
        periodic_reminder: Inject a task reminder every N turns to keep the
            agent anchored on its original goal.
            `True` uses default settings (every 10 turns, system_reminder_tag
            style, zero-cost default generator).
            Pass a :class:`PeriodicReminderConfig` for full control.
            `None` or `False` disables the feature (default).
        web_search: Whether to include the `WebSearch` capability.
            Defaults to True.
        web_fetch: Whether to include the `WebFetch` capability.
            Defaults to True.
        thinking: Thinking/reasoning effort level. `True` enables with
            provider default, `False` disables, or a string level:
            `"minimal"`, `"low"`, `"medium"`, `"high"`, `"xhigh"`.
            Defaults to `"high"`.
        include_history_archive: Whether to persist full conversation history
            before context compression discards messages. Adds a
            `search_conversation_history` tool so the agent can look up
            details from before compression. Only active when
            `context_manager=True`. Defaults to True.
        history_messages_path: Path to the messages.json file that stores
            the full conversation history. Defaults to
            `".pydantic-deep/messages.json"`.
        middleware: List of additional AbstractCapability instances to
            include. These extend the agent with custom lifecycle hooks.
        plans_dir: Directory to save plan files from the planner subagent.
            Defaults to `/plans` (relative to backend root).
        message_queue: Optional :class:`MessageQueue` for mid-run message delivery.
            Steering messages are injected before the next LLM call via
            `MessageQueueCapability`; follow-ups are handled by
            :func:`run_with_queue`. `None` (default) disables the feature.
        forking: Enable Live Run Forking. `True` registers
            :class:`LiveForkCapability` with defaults (`max_branches=10`,
            `max_depth=2`, in-memory store) and the forking toolset
            (`fork_run`, `inspect_branches`, `merge_or_select`,
            `terminate_branch`, `diff_branches`, `fork_cost`). Pass a
            pre-configured :class:`LiveForkCapability` instance to customize
            limits or the fork state store. `False` (default) leaves
            forking off - the feature is opt-in because spawning parallel
            branches has cost implications. When enabled without
            `include_checkpoints=True`, `fork()` emits a runtime warning
            at call time since the `fork:<id>` / `post-fork:<id>` rewind
            anchors require a checkpoint store. Per-branch budgets are
            enforced via `BranchSpec.budget_usd`; fork-wide aggregate caps
            via :attr:`LiveForkCapability.aggregate_budget_usd`.
        model_settings: Provider-specific model settings (temperature, thinking,
            etc.). Passed directly to the pydantic-ai Agent. Common keys:
            `temperature`, `max_tokens`, `anthropic_thinking`,
            `openai_reasoning_effort`. See pydantic-ai ModelSettings docs.
        instrument: Enable OpenTelemetry/Logfire instrumentation. When True,
            the agent emits spans for LLM calls, tool invocations, and token
            usage. Requires `logfire` or OpenTelemetry SDK. None (default)
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

    if not include_skills and (skills or skill_directories):
        warnings.warn(
            "skills and skill_directories are ignored when include_skills=False",
            UserWarning,
            stacklevel=2,
        )

    model = model or DEFAULT_MODEL
    backend = backend or StateBackend()
    interrupt_on = interrupt_on or {}

    # Wrap primary model with FallbackModel when requested.
    if fallback_model is not None:
        _fallbacks: list[str | Model] = (
            list(fallback_model) if isinstance(fallback_model, list) else [fallback_model]
        )
        _fallback_hooks = [
            h for h in (hooks or []) if h.event == HookEvent.MODEL_FALLBACK_TRIGGERED
        ]
        model = _wrap_with_fallback_and_hooks(model, _fallbacks, _fallback_hooks, backend)

    # Build effective subagents list (user-provided + built-ins).
    # Shallow-copy each caller-provided config so the agent_factory / toolset
    # injection below never mutates the caller's dicts. The injection only
    # reassigns top-level keys ("agent_factory", "toolsets") and always rebuilds
    # the toolsets list rather than mutating it in place, so a shallow copy is
    # sufficient - a deep copy would needlessly duplicate live toolset/agent
    # objects. Without this, calling create_deep_agent twice with the same
    # subagents list would double the injected context/memory toolsets.
    effective_subagents: list[SubAgentConfig] = [SubAgentConfig(**sa) for sa in (subagents or [])]
    if include_plan and include_subagents:
        _plans_dir = plans_dir or "/plans"
        plan_toolset = create_plan_toolset(plans_dir=_plans_dir)
        planner_config: SubAgentConfig = {
            "name": "planner",
            "description": PLANNER_DESCRIPTION,
            "instructions": PLANNER_INSTRUCTIONS,
            "toolsets": [plan_toolset],
        }
        # Only add if user hasn't already defined a "planner" subagent
        existing_names = {sa["name"] for sa in effective_subagents}
        if planner_config["name"] not in existing_names:
            effective_subagents.append(planner_config)

    # Built-in subagents (each a full deep agent with web + filesystem): a
    # general-purpose implementer plus the research specialist. Without the
    # general-purpose one the agent has nothing to delegate actual build/file
    # work to and falls back to doing everything itself.
    if include_builtin_subagents and include_subagents:
        existing_names = {sa["name"] for sa in effective_subagents}
        for builtin in BUILTIN_SUBAGENTS:
            if builtin["name"] not in existing_names:
                effective_subagents.append(SubAgentConfig(**builtin))

    all_toolsets: list[AbstractToolset[DeepAgentDeps]] = []

    _todo_proxy: _DepsTodoProxy | None = None
    if include_todo:
        _todo_proxy = _DepsTodoProxy()
        todo_toolset = create_todo_toolset(storage=_todo_proxy, id="deep-todo")
        all_toolsets.append(todo_toolset)

    if include_filesystem:
        all_toolsets.append(
            _build_console_toolset(
                interrupt_on=interrupt_on,
                include_execute=include_execute,
                backend=backend,
                edit_format=edit_format,
                retries=retries,
            )
        )

    _subagent_task_manager: Any | None = None
    subagent_toolset: Any | None = None
    if include_subagents:
        subagent_model = model

        # Deep agent factory for subagents - subagents are full deep agents
        # with filesystem, web, memory, eviction, and patch support
        _sub_extra = list(subagent_extra_toolsets) if subagent_extra_toolsets else []
        _default_deep_agent_factory = _make_default_deep_agent_factory(
            model=subagent_model,
            edit_format=edit_format,
            context_files=context_files,
            context_discovery=context_discovery,
            memory_dir=memory_dir,
            web_search=web_search,
            web_fetch=web_fetch,
        )

        # Inject agent_factory + per-subagent context/memory/extra toolsets. These
        # operate on the shallow copies built above, never the caller's dicts.
        for sa_config in effective_subagents:
            if (
                sa_config.get("agent") is None and sa_config.get("agent_factory") is None
            ):  # pragma: no branch
                sa_config["agent_factory"] = _default_deep_agent_factory
            _inject_subagent_context_toolset(sa_config)
            if include_memory:
                _inject_subagent_memory_toolset(sa_config, memory_dir)
            _inject_subagent_extra_toolsets(sa_config, _sub_extra)

        subagent_toolset = create_subagent_toolset(
            id="deep-subagents",
            subagents=effective_subagents if effective_subagents else None,
            default_model=subagent_model,
            include_general_purpose=False,  # We use our own built-in subagents
            max_nesting_depth=max_nesting_depth,
            registry=subagent_registry,
            usage_limits=subagent_usage_limits,
        )
        all_toolsets.append(subagent_toolset)
        _subagent_task_manager = getattr(subagent_toolset, "task_manager", None)

    # Skills toolset
    skills_toolset = None
    if include_skills:
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
            skills=skills,
            directories=directories,  # type: ignore[arg-type]  # pyright: ignore[reportArgumentType]
        )
        all_toolsets.append(skills_toolset)

    # Context toolset
    context_toolset = None
    if context_files or context_discovery:
        context_toolset = ContextToolset(
            context_files=context_files,
            context_discovery=context_discovery,
            is_subagent=False,
        )
        all_toolsets.append(context_toolset)

    # Memory toolset
    memory_toolset = None
    if include_memory:
        _memory_dir = memory_dir or DEFAULT_MEMORY_DIR
        memory_toolset = AgentMemoryToolset(
            agent_name="main",
            memory_dir=_memory_dir,
        )
        all_toolsets.append(memory_toolset)

    # Add user-provided toolsets
    if toolsets:
        all_toolsets.extend(toolsets)

    # Extra toolsets from subagent configs (injected via config["toolsets"])
    if extra_toolsets:
        all_toolsets.extend(extra_toolsets)

    # MCP servers (each is an AbstractToolset connecting to an MCP server).
    if mcp_servers:
        all_toolsets.extend(mcp_servers)

    # Checkpoint toolset (added before agent creation so it's in toolsets list)
    if include_checkpoints:
        _cp_store = checkpoint_store or InMemoryCheckpointStore()
        checkpoint_toolset = CheckpointToolset(store=_cp_store)
        all_toolsets.append(checkpoint_toolset)

    # Team toolset
    if include_teams:
        # Wire teams to subagent execution engine when both are enabled
        _team_kwargs: dict[str, Any] = {}
        if include_subagents and _subagent_task_manager is not None:
            _team_registry = subagent_registry
            if _team_registry is None:
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
                _team_task_instructions = cfg.get("instructions") or ""
                _team_instructions = (
                    DEFAULT_INSTRUCTIONS + "\n\n" + _team_task_instructions
                    if _team_task_instructions
                    else DEFAULT_INSTRUCTIONS
                )
                return create_deep_agent(
                    model=cfg.get("model", _team_model),
                    instructions=_team_instructions,
                    include_filesystem=True,
                    include_todo=True,
                    include_subagents=False,
                    include_skills=False,
                    include_plan=False,
                    include_teams=False,
                    include_monitoring=False,
                    context_manager=False,
                    cost_tracking=False,
                    edit_format=_team_edit_fmt,
                )

            _team_kwargs["agent_factory"] = _deep_agent_factory

        team_toolset = create_team_toolset(**_team_kwargs)
        all_toolsets.append(team_toolset)

    # Monitor toolset (watch & react) — start_monitor / list_monitors / stop_monitor.
    # Needs a background-capable backend at runtime; the tools no-op gracefully
    # otherwise, so it's safe to include by default.
    if include_monitoring:
        all_toolsets.append(create_monitor_toolset())

    base_instructions = instructions if instructions is not None else DEFAULT_INSTRUCTIONS

    # Improve toolset (self-improvement from session analysis)
    if include_improve:
        _improve_sessions = Path(".pydantic-deep/sessions")
        if backend is not None:  # pragma: no branch
            _wd = getattr(backend, "root_dir", None)
            if _wd:  # pragma: no branch
                _improve_sessions = Path(str(_wd)) / ".pydantic-deep" / "sessions"

        improve_toolset = ImproveToolset(
            sessions_dir=_improve_sessions,
            working_dir=Path("."),
            model=model if isinstance(model, str) else DEFAULT_IMPROVE_MODEL,
        )
        all_toolsets.append(improve_toolset)

    # LiteParse document parsing toolset
    if include_liteparse:
        liteparse_toolset = LiteparseToolset()
        all_toolsets.append(liteparse_toolset)

    # Inject output style into instructions
    if output_style is not None:
        resolved = resolve_style(output_style, styles_dir)
        base_instructions = base_instructions + "\n\n" + format_style_prompt(resolved)

    agent_create_kwargs: dict[str, Any] = {
        "deps_type": DeepAgentDeps,
        "toolsets": all_toolsets,
        "instructions": base_instructions,
        "retries": retries,
    }

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

    all_processors: list[HistoryProcessor[DeepAgentDeps]] = list(history_processors or [])

    # Resolve history_messages_path to absolute for the middleware
    abs_messages_path: str | None = None
    if include_history_archive and context_manager:
        if os.path.isabs(history_messages_path):  # pragma: no cover
            abs_messages_path = history_messages_path
        elif hasattr(backend, "root_dir"):
            abs_messages_path = str(backend.root_dir / history_messages_path)  # type: ignore[union-attr,operator,unused-ignore]
        else:
            abs_messages_path = os.path.join(os.getcwd(), history_messages_path)

        # Register the search tool (reads the same file the middleware writes to)
        all_toolsets.append(create_history_search_toolset(abs_messages_path))

    # Context manager capability (token tracking + auto-compression)
    context_mw: ContextManagerCapability | None = None
    limit_warner: LimitWarnerCapability | None = None
    if context_manager:
        context_mw, limit_warner = _build_context_capabilities(
            on_context_update=on_context_update,
            context_manager_max_tokens=context_manager_max_tokens,
            summarization_model=summarization_model,
            on_before_compress=on_before_compress,
            on_after_compress=on_after_compress,
        )

    # Cost tracking capability
    cost_cap: Any | None = None
    if cost_tracking:
        model_name = model if isinstance(model, str) else None
        if forking:
            cost_cap = _PerBranchCostTracking(
                model_name=model_name,
                budget_usd=cost_budget_usd,
                on_cost_update=on_cost_update,
            )
        else:
            cost_cap = CostTracking(
                model_name=model_name,
                budget_usd=cost_budget_usd,
                on_cost_update=on_cost_update,
            )

    # Prompt caching cuts the dominant cost on multi-turn / subagent runs (the
    # large, mostly-identical prefix is re-sent every turn). Each provider reads
    # its own keys and ignores the other's, so we set both unconditionally — no
    # provider detection needed. NOTE: the direct-Anthropic keys do NOT apply on
    # the OpenRouter path (a common default), hence the parallel openrouter_* set.
    effective_model_settings: dict[str, Any] = {
        # Direct Anthropic provider.
        "anthropic_cache_instructions": True,
        "anthropic_cache_tool_definitions": True,
        "anthropic_cache_messages": True,
        # OpenRouter path (Anthropic/Gemini downstream).
        "openrouter_cache_instructions": True,
        "openrouter_cache_tool_definitions": True,
        "openrouter_cache_messages": True,
    }
    # User-provided settings override defaults
    if model_settings:  # pragma: no cover
        effective_model_settings.update(model_settings)
    agent_create_kwargs["model_settings"] = effective_model_settings

    if instrument is not None:  # pragma: no cover
        agent_create_kwargs["instrument"] = instrument

    all_capabilities: list[AbstractCapability[Any]] = []

    if _todo_proxy is not None:
        all_capabilities.append(_TodoProxyBinder(_todo_proxy))

    if patch_tool_calls:
        all_capabilities.append(PatchToolCallsCapability())

    if eviction_token_limit is not None:
        all_capabilities.append(
            EvictionCapability(
                backend=ensure_async(backend),
                token_limit=eviction_token_limit,
                max_binary_content=max_binary_content,
                on_eviction=on_eviction,
            )
        )

    if hooks is not None:
        all_capabilities.append(HooksCapability(hooks=hooks))

    if include_checkpoints:
        all_capabilities.append(
            CheckpointMiddleware(
                store=_cp_store,
                frequency=checkpoint_frequency,
                max_checkpoints=max_checkpoints,
            )
        )

    if stuck_loop_detection:
        # Polling tools are intentionally called many times with identical
        # arguments - exempt them so the detector doesn't fire on normal usage.
        _sld_ignore: set[str] = {"inspect_branches"} if forking else set()
        all_capabilities.append(StuckLoopDetection(ignore_tools=_sld_ignore))

    if message_queue is not None:
        all_capabilities.append(MessageQueueCapability(queue=message_queue))

    if periodic_reminder:
        _reminder_cfg = (
            periodic_reminder
            if isinstance(periodic_reminder, PeriodicReminderConfig)
            else PeriodicReminderConfig()
        )
        all_capabilities.append(PeriodicReminderCapability(config=_reminder_cfg))

    _fork_capability: Any = None
    if forking:
        if isinstance(forking, LiveForkCapability):
            _fork_capability = forking
        elif forking is True:
            _fork_capability = LiveForkCapability()
        else:
            raise TypeError(
                f"forking must be bool or LiveForkCapability, got {type(forking).__name__}"
            )
        all_capabilities.append(_fork_capability)
        all_toolsets.append(create_fork_toolset())

    if middleware:
        all_capabilities.extend(middleware)

    if context_mw is not None:
        all_capabilities.append(context_mw)

    if limit_warner is not None:
        all_capabilities.append(limit_warner)

    if cost_cap is not None:
        all_capabilities.append(cost_cap)

    # `local=` provides a fallback for models whose provider has no native web
    # tool. pydantic-ai 2.0 changed the default to `local=None` (no fallback),
    # so a model that lacks native `WebFetchTool` now errors instead of falling
    # back. We opt back into the local fallback to preserve pre-2.0 behaviour.
    if web_search:  # pragma: no cover
        all_capabilities.append(WebSearch(local="duckduckgo"))

    if web_fetch:  # pragma: no cover
        all_capabilities.append(WebFetch(local=True))

    if thinking is not False:  # pragma: no cover
        effort: Any = thinking if isinstance(thinking, str) else True
        all_capabilities.append(Thinking(effort=effort))

    # User-provided history processors are wrapped as ProcessHistory
    # capabilities — pydantic-ai 2.0 removed the `Agent(history_processors=...)`
    # parameter in favour of the capabilities API. They run after the built-in
    # history-affecting capabilities (context manager, eviction) so they operate
    # on the already-managed history.
    if all_processors:
        all_capabilities.extend(ProcessHistory(processor) for processor in all_processors)

    # Add user-provided capabilities
    if capabilities:
        all_capabilities.extend(capabilities)

    # Tool search: defer the situational tool surface (subagents, skills,
    # memory, MCP, …) so only the core read/edit/run/track loop is loaded
    # upfront. The model discovers the rest on demand, which cuts per-request
    # input tokens and sharpens tool selection. Opt-in (off by default).
    if tool_search:
        all_toolsets = defer_situational_toolsets(all_toolsets)
        agent_create_kwargs["toolsets"] = all_toolsets
        all_capabilities.append(ToolSearch())

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

    # Runtime system-prompt sections. Provider selection happens once here;
    # toolset-owned prompts are emitted automatically by CombinedToolset.
    instruction_providers = build_instruction_providers(
        include_todo=include_todo,
        todo_proxy=_todo_proxy,
        include_filesystem=include_filesystem,
        edit_format=edit_format,
        include_subagents=include_subagents,
        subagents=effective_subagents,
        web_search=web_search,
        web_fetch=web_fetch,
        tool_search=tool_search,
    )

    @agent.instructions
    def dynamic_instructions(ctx: RunContext[DeepAgentDeps]) -> str:  # pragma: no cover
        """Join every active instruction provider into the dynamic prompt."""
        return render_instructions(ctx, instruction_providers)

    # Expose context middleware for CLI /compact and /context commands
    agent._context_middleware = context_mw  # type: ignore[attr-defined]
    agent._task_manager = _subagent_task_manager  # type: ignore[attr-defined]
    if _fork_capability is not None:
        _fork_capability._agent_ref = agent
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
        await deps.upload_files(files, upload_dir=upload_dir)

    # Run agent
    result = await agent.run(query, deps=deps)
    return result.output
