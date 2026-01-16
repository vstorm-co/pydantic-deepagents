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
from pydantic_deep.processors import (
    SummarizationProcessor,
    create_summarization_processor,
)
from pydantic_deep.toolsets import FilesystemToolset, SkillsToolset, SubAgentToolset, TodoToolset
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

try:
    from importlib.metadata import version

    __version__ = version("pydantic-deep")
except Exception:  # pragma: no cover
    __version__ = "0.0.0"

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
