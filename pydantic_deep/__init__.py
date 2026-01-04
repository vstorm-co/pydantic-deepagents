"""pydantic-deep: Deep agent framework built on pydantic-ai.

This library provides a deep agent framework with:
- Planning via TodoToolset
- Filesystem operations via FilesystemToolset
- Subagent delegation via SubAgentToolset
- Multiple backend options for file storage
- Structured output support via output_type
- History processing/summarization for long conversations

Example:
    ```python
    from pydantic import BaseModel
    from pydantic_deep import create_deep_agent, DeepAgentDeps, StateBackend
    from pydantic_deep.processors import create_summarization_processor

    # Create agent with all capabilities
    agent = create_deep_agent(
        model="openai:gpt-4.1",
        instructions="You are a helpful coding assistant",
        interrupt_on={"execute": True},
    )

    # With structured output
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

    # Create dependencies
    deps = DeepAgentDeps(backend=StateBackend())

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
    DockerSandbox,
    EditResult,
    ExecuteResponse,
    FileData,
    FileInfo,
    FilesystemBackend,
    GrepMatch,
    LocalSandbox,
    RuntimeConfig,
    SandboxProtocol,
    SessionManager,
    StateBackend,
    WriteResult,
    get_runtime,
)

from pydantic_deep.agent import create_deep_agent, create_default_deps, run_with_files
from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.guardrails import (
    CostLimitGuardrail,
    GuardrailContext,
    GuardrailManager,
    GuardrailProtocol,
    GuardrailResult,
    GuardrailViolation,
    IterationLimitGuardrail,
    OutputValidationGuardrail,
    TokenBudgetGuardrail,
    ToolCall,
    ToolChainValidationGuardrail,
    ToolLoopDetectionGuardrail,
    create_production_guardrails,
    create_safe_agent_guardrails,
)
from pydantic_deep.processors import (
    SummarizationProcessor,
    create_summarization_processor,
)
from pydantic_deep.streaming import (
    StreamEvent,
    StreamEventType,
    collect_stream_result,
    run_stream,
    run_stream_with_tools,
    stream_text,
    stream_tool_calls,
)
from pydantic_deep.toolsets import FilesystemToolset, SkillsToolset, SubAgentToolset, TodoToolset
from pydantic_deep.testing import (
    FixtureFile,
    FixtureValidationError,
    RecordedInteraction,
    RecordedRequest,
    RecordedResponse,
    Recorder,
    ReplayMismatchError,
    Replayer,
    create_fixture,
    get_current_recorder,
    get_current_replayer,
    record_mode,
    replay_mode,
    validate_fixture,
)
from pydantic_deep.tracing import (
    ConsoleExporter,
    InMemoryExporter,
    OpenTelemetryExporter,
    StructuredFileExporter,
    TraceContext,
    TraceExporterProtocol,
)
from pydantic_deep.types import (
    CompiledSubAgent,
    ResponseFormat,
    Skill,
    SkillDirectory,
    SkillFrontmatter,
    SubAgentConfig,
    Todo,
    UploadedFile,
)

__version__ = "0.1.0"

__all__ = [
    # Main entry points
    "create_deep_agent",
    "create_default_deps",
    "run_with_files",
    "DeepAgentDeps",
    # Backends
    "BackendProtocol",
    "SandboxProtocol",
    "StateBackend",
    "FilesystemBackend",
    "CompositeBackend",
    "BaseSandbox",
    "DockerSandbox",
    "LocalSandbox",
    # Runtimes
    "RuntimeConfig",
    "BUILTIN_RUNTIMES",
    "get_runtime",
    # Session Management
    "SessionManager",
    # Toolsets
    "TodoToolset",
    "FilesystemToolset",
    "SubAgentToolset",
    "SkillsToolset",
    # Processors
    "SummarizationProcessor",
    "create_summarization_processor",
    # Guardrails
    "GuardrailManager",
    "GuardrailProtocol",
    "GuardrailContext",
    "GuardrailResult",
    "GuardrailViolation",
    "ToolCall",
    "TokenBudgetGuardrail",
    "CostLimitGuardrail",
    "IterationLimitGuardrail",
    "ToolChainValidationGuardrail",
    "OutputValidationGuardrail",
    "ToolLoopDetectionGuardrail",
    "create_safe_agent_guardrails",
    "create_production_guardrails",
    # Tracing
    "TraceContext",
    "ConsoleExporter",
    "InMemoryExporter",
    "OpenTelemetryExporter",
    "StructuredFileExporter",
    "TraceExporterProtocol",
    # Streaming
    "run_stream",
    "run_stream_with_tools",
    "stream_text",
    "stream_tool_calls",
    "collect_stream_result",
    "StreamEvent",
    "StreamEventType",
    # Testing
    "Recorder",
    "Replayer",
    "RecordedRequest",
    "RecordedResponse",
    "RecordedInteraction",
    "FixtureFile",
    "FixtureValidationError",
    "ReplayMismatchError",
    "record_mode",
    "replay_mode",
    "create_fixture",
    "validate_fixture",
    "get_current_recorder",
    "get_current_replayer",
    # Types
    "FileData",
    "FileInfo",
    "WriteResult",
    "EditResult",
    "ExecuteResponse",
    "GrepMatch",
    "Todo",
    "SubAgentConfig",
    "CompiledSubAgent",
    "Skill",
    "SkillDirectory",
    "SkillFrontmatter",
    "UploadedFile",
    "ResponseFormat",
]
