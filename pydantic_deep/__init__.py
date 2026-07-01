"""pydantic-deep: Deep agent framework built on pydantic-ai.

This library provides a deep agent framework with:
- Planning via TodoToolset
- Filesystem operations via create_console_toolset (from pydantic-ai-backend)
- Subagent delegation via SubAgentToolset
- Multiple backend options for file storage
- Structured output support via output_type
- History processing/summarization for long conversations

Example:
    ```python
    from pydantic import BaseModel
    from pydantic_deep import (
        create_deep_agent, DeepAgentDeps, LocalBackend, create_console_toolset
    )
    from pydantic_ai_summarization import create_summarization_processor

    # Create agent with file tools
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        instructions="You are a helpful coding assistant",
    )

    # With structured output and summarization
    class Analysis(BaseModel):
        summary: str
        issues: list[str]

    agent = create_deep_agent(
        output_type=Analysis,
        history_processors=[
            create_summarization_processor(
                trigger=("tokens", 100000),
                keep=("messages", 20),
            )
        ],
    )

    # Create dependencies with LocalBackend
    deps = DeepAgentDeps(backend=LocalBackend(root_dir="."))

    # Run agent
    result = await agent.run("Create a Python script", deps=deps)
    print(result.output)
    ```
"""

from pydantic_ai_backends import (
    BUILTIN_RUNTIMES,
    BackendProtocol,
    BaseSandbox,
    CompositeBackend,
    ConsoleDeps,
    DockerSandbox,
    EditResult,
    ExecuteResponse,
    FileData,
    FileInfo,
    GrepMatch,
    LocalBackend,
    RuntimeConfig,
    SandboxProtocol,
    SessionManager,
    StateBackend,
    WriteResult,
    create_console_toolset,
    get_console_system_prompt,
    get_runtime,
)
from pydantic_ai_shields import (
    BudgetExceededError,
    CostInfo,
    CostTracking,
    InputBlocked,
    OutputBlocked,
    ToolBlocked,
)
from pydantic_ai_summarization import (
    ContextManagerCapability,
    LimitWarnerCapability,
    SlidingWindowCapability,
    SlidingWindowProcessor,
    SummarizationCapability,
    SummarizationProcessor,
    create_sliding_window_processor,
    create_summarization_processor,
)

from pydantic_deep._text import NUM_CHARS_PER_TOKEN, create_content_preview
from pydantic_deep.agent import create_deep_agent, create_default_deps, run_with_files
from pydantic_deep.capabilities import (
    BrowserCapability,
    ContextFilesCapability,
    LLMReminderGenerator,
    MemoryCapability,
    PeriodicReminderCapability,
    PeriodicReminderConfig,
    ReminderGenerator,
    SkillsCapability,
    StuckLoopDetection,
    StuckLoopError,
    make_config_for_mode,
)
from pydantic_deep.deps import DEFAULT_USAGE_LIMITS as DEFAULT_USAGE_LIMITS
from pydantic_deep.deps import DeepAgentDeps, unwrap_backend
from pydantic_deep.features.browser import BrowserToolset
from pydantic_deep.features.checkpointing import (
    Checkpoint,
    CheckpointMiddleware,
    CheckpointStore,
    CheckpointToolset,
    FileCheckpointStore,
    InMemoryCheckpointStore,
    RewindRequested,
    fork_from_checkpoint,
)
from pydantic_deep.features.context import (
    DEFAULT_CONTEXT_FILENAMES,
    DEFAULT_MAX_CONTEXT_CHARS,
    SUBAGENT_CONTEXT_ALLOWLIST,
    ContextFile,
    ContextToolset,
    discover_context_files,
    format_context_prompt,
    load_context_files,
)
from pydantic_deep.features.eviction import (
    BINARY_PRUNED_TEMPLATE,
    DEFAULT_EVICTION_PATH,
    DEFAULT_MAX_BINARY_CONTENT,
    DEFAULT_TOKEN_LIMIT,
    EVICTION_MESSAGE_TEMPLATE,
    EvictionCapability,
)
from pydantic_deep.features.forking import (
    JUDGE_SYSTEM_PROMPT,
    BranchOverlay,
    ForkBranchLimitError,
    ForkCoordinator,
    ForkDepthLimitError,
    ForkStateStore,
    InMemoryForkStateStore,
    JudgeAgent,
    build_diff_report,
    clone_for_branch,
    compute_confidence,
    count_retry_parts,
    count_stuck_loop_hits,
    create_fork_toolset,
)
from pydantic_deep.features.forking.capability import LiveForkCapability
from pydantic_deep.features.forking.types import (
    BranchChange,
    BranchCost,
    BranchDiffAgreement,
    BranchDiffOperation,
    BranchDiffReport,
    BranchIsolation,
    BranchOutcome,
    BranchSpec,
    BranchState,
    BranchStatus,
    ConfidenceSignals,
    DiffSummary,
    FileChange,
    FlushError,
    FlushReport,
    ForkCostSummary,
    ForkHandle,
    JudgeVerdict,
    MergeResult,
    MergeStrategy,
    PathDiff,
    PendingApprovalRequest,
    ResolveOutcome,
)
from pydantic_deep.features.hooks import (
    DEFAULT_BLOCKED_COMMANDS,
    DEFAULT_BLOCKED_READ_PATHS,
    DEFAULT_BLOCKED_WRITE_PATHS,
    DEFAULT_SECRET_PATTERNS,
    EXIT_ALLOW,
    EXIT_DENY,
    Hook,
    HookEvent,
    HookInput,
    HookResult,
    HooksCapability,
    default_security_hook,
)
from pydantic_deep.features.liteparse import (
    PARSE_DOCUMENT_DESCRIPTION,
    SCREENSHOT_DOCUMENT_DESCRIPTION,
    LiteparseToolset,
)
from pydantic_deep.features.memory import (
    DEFAULT_MAX_MEMORY_LINES,
    DEFAULT_MEMORY_DIR,
    DEFAULT_MEMORY_FILENAME,
    DEFAULT_PIN_END_MARKER,
    AgentMemoryToolset,
    MemoryAccessError,
    MemoryFile,
    format_memory_prompt,
    get_memory_path,
    load_memory,
)
from pydantic_deep.features.monitoring import (
    MonitorEvent,
    MonitorInfo,
    MonitorManager,
    create_monitor_toolset,
)
from pydantic_deep.features.patch import (
    CANCELLED_MESSAGE,
    PatchToolCallsCapability,
    patch_tool_calls_processor,
)
from pydantic_deep.features.plan import PlanOption
from pydantic_deep.features.skills import (
    BackendSkillResource,
    BackendSkillScript,
    BackendSkillScriptExecutor,
    BackendSkillsDirectory,
    CallableSkillScriptExecutor,
    FileBasedSkillResource,
    FileBasedSkillScript,
    LocalSkillScriptExecutor,
    Skill,
    SkillException,
    SkillNotFoundError,
    SkillResource,
    SkillResourceLoadError,
    SkillResourceNotFoundError,
    SkillScript,
    SkillScriptExecutionError,
    SkillsDirectory,
    SkillValidationError,
    SkillWrapper,
)
from pydantic_deep.features.teams import (
    AgentTeam,
    SharedTodoItem,
    SharedTodoList,
    TeamMember,
    TeamMemberHandle,
    TeamMemberSpec,
    TeamMessage,
    TeamMessageBus,
    create_team_toolset,
)
from pydantic_deep.goal import (
    DEFAULT_GOAL_MODEL,
    GoalEvaluation,
    GoalEvaluator,
    GoalState,
    build_goal_transcript,
    format_goal_status,
    goal_continue_directive,
    parse_goal_command,
)
from pydantic_deep.mcp import (
    BUILTIN_MCP_NAMES,
    MCPAuth,
    MCPConfigError,
    MCPNotInstalledError,
    MCPProbeResult,
    MCPRegistry,
    MCPServerConfig,
    auth_satisfied,
    build_mcp_server,
    builtin_mcp_servers,
    parse_mcp_servers,
    probe_mcp_server,
)
from pydantic_deep.prompts import BASE_PROMPT
from pydantic_deep.spec import DeepAgent, DeepAgentSpec
from pydantic_deep.styles import (
    BUILTIN_STYLES,
    OutputStyle,
    discover_styles,
    format_style_prompt,
    load_style_from_file,
    resolve_style,
)
from pydantic_deep.toolsets import SkillsToolset, SubAgentToolset, TodoToolset, create_plan_toolset
from pydantic_deep.types import (
    BrowseResult,
    CompiledSubAgent,
    ResponseFormat,
    SubAgentConfig,
    Todo,
    UploadedFile,
)

try:
    from importlib.metadata import version

    __version__ = version("pydantic-deep")
except Exception:  # pragma: no cover
    __version__ = "0.0.0"

__all__ = [
    # Main entry points
    "BASE_PROMPT",
    "create_deep_agent",
    "create_default_deps",
    "run_with_files",
    "DeepAgentDeps",
    "DEFAULT_USAGE_LIMITS",
    "unwrap_backend",
    "DeepAgent",
    "DeepAgentSpec",
    # Goal-completion loop engine
    "DEFAULT_GOAL_MODEL",
    "GoalEvaluation",
    "GoalEvaluator",
    "GoalState",
    "build_goal_transcript",
    "format_goal_status",
    "goal_continue_directive",
    "parse_goal_command",
    # MCP (Model Context Protocol) client support
    "MCPServerConfig",
    "MCPAuth",
    "MCPRegistry",
    "MCPProbeResult",
    "MCPConfigError",
    "MCPNotInstalledError",
    "build_mcp_server",
    "probe_mcp_server",
    "auth_satisfied",
    "builtin_mcp_servers",
    "BUILTIN_MCP_NAMES",
    "parse_mcp_servers",
    # Backends (from pydantic-ai-backend)
    "BackendProtocol",
    "SandboxProtocol",
    "LocalBackend",
    "StateBackend",
    "CompositeBackend",
    "BaseSandbox",
    "DockerSandbox",
    # Runtimes
    "RuntimeConfig",
    "BUILTIN_RUNTIMES",
    "get_runtime",
    # Session Management
    "SessionManager",
    # Capabilities (pydantic-ai AbstractCapability)
    "BrowserCapability",
    "SkillsCapability",
    "ContextFilesCapability",
    "MemoryCapability",
    "StuckLoopDetection",
    "StuckLoopError",
    "PeriodicReminderCapability",
    "PeriodicReminderConfig",
    "ReminderGenerator",
    "LLMReminderGenerator",
    "make_config_for_mode",
    "HooksCapability",
    "ContextManagerCapability",
    "SummarizationCapability",
    "SlidingWindowCapability",
    "LimitWarnerCapability",
    "CostTracking",
    # Toolsets
    "BrowserToolset",
    "LiteparseToolset",
    "PARSE_DOCUMENT_DESCRIPTION",
    "SCREENSHOT_DOCUMENT_DESCRIPTION",
    "TodoToolset",
    "create_console_toolset",
    "get_console_system_prompt",
    "ConsoleDeps",
    "SubAgentToolset",
    "SkillsToolset",
    "create_plan_toolset",
    # Skills types
    "Skill",
    "SkillResource",
    "SkillScript",
    "SkillWrapper",
    "SkillsDirectory",
    # Skills local
    "FileBasedSkillResource",
    "FileBasedSkillScript",
    "LocalSkillScriptExecutor",
    "CallableSkillScriptExecutor",
    # Skills backend
    "BackendSkillResource",
    "BackendSkillScript",
    "BackendSkillScriptExecutor",
    "BackendSkillsDirectory",
    # Skills exceptions
    "SkillException",
    "SkillNotFoundError",
    "SkillValidationError",
    "SkillResourceNotFoundError",
    "SkillResourceLoadError",
    "SkillScriptExecutionError",
    # Context files
    "ContextToolset",
    "ContextFile",
    "load_context_files",
    "discover_context_files",
    "format_context_prompt",
    "DEFAULT_CONTEXT_FILENAMES",
    "DEFAULT_MAX_CONTEXT_CHARS",
    "SUBAGENT_CONTEXT_ALLOWLIST",
    # Memory (persistent agent memory)
    "AgentMemoryToolset",
    "MemoryAccessError",
    "MemoryFile",
    "load_memory",
    "get_memory_path",
    "format_memory_prompt",
    "DEFAULT_MEMORY_DIR",
    "DEFAULT_MEMORY_FILENAME",
    "DEFAULT_MAX_MEMORY_LINES",
    "DEFAULT_PIN_END_MARKER",
    # Eviction
    "EvictionCapability",
    "create_content_preview",
    "NUM_CHARS_PER_TOKEN",
    "DEFAULT_TOKEN_LIMIT",
    "DEFAULT_EVICTION_PATH",
    "DEFAULT_MAX_BINARY_CONTENT",
    "EVICTION_MESSAGE_TEMPLATE",
    "BINARY_PRUNED_TEMPLATE",
    # Processors (from summarization-pydantic-ai)
    "SummarizationProcessor",
    "SlidingWindowProcessor",
    "create_summarization_processor",
    "create_sliding_window_processor",
    # Hooks (Claude Code-style lifecycle hooks)
    "DEFAULT_BLOCKED_COMMANDS",
    "DEFAULT_BLOCKED_READ_PATHS",
    "DEFAULT_BLOCKED_WRITE_PATHS",
    "DEFAULT_SECRET_PATTERNS",
    "Hook",
    "HookEvent",
    "HookInput",
    "HookResult",
    "EXIT_ALLOW",
    "EXIT_DENY",
    "default_security_hook",
    # Checkpointing
    "Checkpoint",
    "CheckpointStore",
    "InMemoryCheckpointStore",
    "FileCheckpointStore",
    "CheckpointMiddleware",
    "CheckpointToolset",
    "RewindRequested",
    "fork_from_checkpoint",
    # Teams (parallel subagents and agent teams)
    "AgentTeam",
    "SharedTodoItem",
    "SharedTodoList",
    "TeamMember",
    "TeamMemberHandle",
    "TeamMemberSpec",
    "TeamMessage",
    "TeamMessageBus",
    "create_team_toolset",
    "MonitorManager",
    "MonitorEvent",
    "MonitorInfo",
    "create_monitor_toolset",
    "PlanOption",
    # Output styles
    "OutputStyle",
    "BUILTIN_STYLES",
    "resolve_style",
    "load_style_from_file",
    "discover_styles",
    "format_style_prompt",
    # Patch tool calls processor
    "PatchToolCallsCapability",
    "patch_tool_calls_processor",
    "CANCELLED_MESSAGE",
    # Shields (from pydantic-ai-shields)
    "CostInfo",
    "BudgetExceededError",
    "InputBlocked",
    "ToolBlocked",
    "OutputBlocked",
    # Types
    "BrowseResult",
    "FileData",
    "FileInfo",
    "WriteResult",
    "EditResult",
    "ExecuteResponse",
    "GrepMatch",
    "Todo",
    "SubAgentConfig",
    "CompiledSubAgent",
    "UploadedFile",
    "ResponseFormat",
    # Live Run Forking - coordinator, isolation, diff, and public types
    "LiveForkCapability",
    "ForkCoordinator",
    "ForkStateStore",
    "InMemoryForkStateStore",
    "BranchOverlay",
    "build_diff_report",
    "clone_for_branch",
    "create_fork_toolset",
    "ForkBranchLimitError",
    "ForkDepthLimitError",
    "BranchSpec",
    "BranchIsolation",
    "BranchState",
    "BranchStatus",
    "BranchCost",
    "ForkCostSummary",
    "ForkHandle",
    "MergeStrategy",
    "MergeResult",
    "FlushError",
    "FlushReport",
    "PendingApprovalRequest",
    "FileChange",
    "BranchDiffReport",
    "PathDiff",
    "BranchChange",
    "DiffSummary",
    "BranchDiffAgreement",
    "BranchDiffOperation",
    # Live Run Forking - autonomous judge for unattended merge resolution
    "JudgeAgent",
    "JudgeVerdict",
    "ConfidenceSignals",
    "BranchOutcome",
    "ResolveOutcome",
    "JUDGE_SYSTEM_PROMPT",
    "compute_confidence",
    "count_retry_parts",
    "count_stuck_loop_hits",
]
