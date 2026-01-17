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
    from pydantic_deep.processors import create_summarization_processor

    # Create agent with file tools
    agent = create_deep_agent(
        model="openai:gpt-4.1",
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

from pydantic_deep.agent import create_deep_agent, create_default_deps, run_with_files
from pydantic_deep.deps import DeepAgentDeps
from pydantic_deep.processors import (
    SummarizationProcessor,
    create_summarization_processor,
)
from pydantic_deep.toolsets import SkillsToolset, SubAgentToolset, TodoToolset
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
    # Toolsets
    "TodoToolset",
    "create_console_toolset",
    "get_console_system_prompt",
    "ConsoleDeps",
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
