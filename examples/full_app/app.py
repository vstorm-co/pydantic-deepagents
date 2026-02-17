"""Full-featured example application with FastAPI backend and WebSocket streaming.

This example demonstrates ALL pydantic-deep features:

Core:
- DockerSandbox for file operations and code execution
- RuntimeConfig (python-datascience) for pre-installed packages
- BASE_PROMPT as foundation for agent instructions
- Custom tools (mock GitHub tools via FunctionToolset)

Toolsets:
- Console toolset (ls, read_file, write_file, edit_file, glob, grep, execute)
- Todo toolset (task planning and tracking)
- Subagent toolset (joke-generator, code-reviewer, general-purpose)
- Skills toolset (data-analysis, code-review, test-generator, quick-reference)
- Context toolset (DEEP.md auto-injection)

Processors:
- EvictionProcessor (large tool output → file reference)
- SlidingWindowProcessor (conversation length management)
- PatchToolCallsProcessor (orphaned tool call repair)

Middleware & Hooks:
- AuditMiddleware (tool usage tracking)
- PermissionMiddleware (sensitive path blocking)
- Hook: audit_logger (POST_TOOL_USE, background)
- Hook: safety_gate (PRE_TOOL_USE, blocks dangerous commands)

Other:
- Human-in-the-loop approval for execute
- Image support (multimodal read_file)
- File uploads with metadata tracking
- WebSocket streaming for real-time events
- Multi-user support with SessionManager

Run with:
    cd examples/full_app
    uvicorn app:app --reload --port 8080
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Import our custom tools and middleware
from audit_middleware import AuditMiddleware, PermissionMiddleware
from fastapi import FastAPI, File, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from github_tools import GITHUB_SYSTEM_PROMPT, create_github_toolset
from pydantic_ai import (
    BinaryContent,
    FinalResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPartDelta,
    ThinkingPartDelta,
    ToolCallPartDelta,
)
from pydantic_ai._agent_graph import End, UserPromptNode
from pydantic_ai.agent import Agent
from pydantic_ai.messages import (
    FunctionToolCallEvent,
    FunctionToolResultEvent,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.tools import (
    DeferredToolRequests,
    DeferredToolResults,
    ToolApproved,
    ToolDenied,
)
from subagents_pydantic_ai import DynamicAgentRegistry, create_agent_factory_toolset

from pydantic_deep import (
    BASE_PROMPT,
    DeepAgentDeps,
    Hook,
    HookEvent,
    HookInput,
    HookResult,
    InMemoryCheckpointStore,
    RewindRequested,
    SessionManager,
    Skill,
    create_deep_agent,
    create_sliding_window_processor,
    fork_from_checkpoint,
)
from pydantic_deep.types import SubAgentConfig

# Configure logging — INFO for libraries, DEBUG only for our app
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# Silence noisy libraries
for _lib in (
    "chardet",
    "charset_normalizer",
    "multipart",
    "httpcore",
    "httpx",
    "docker",
    "urllib3",
):
    logging.getLogger(_lib).setLevel(logging.WARNING)

# Paths
APP_DIR = Path(__file__).parent
WORKSPACE_DIR = APP_DIR / "workspace"
WORKSPACES_DIR = APP_DIR / "workspaces"  # Per-session persistent storage
SKILLS_DIR = APP_DIR / "skills"
STATIC_DIR = APP_DIR / "static"

# Create directories if they don't exist
WORKSPACE_DIR.mkdir(exist_ok=True)
WORKSPACES_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Attachment helpers
# ---------------------------------------------------------------------------

# Extensions we can safely decode as text for preview
_TEXT_EXTS = {
    "txt",
    "md",
    "csv",
    "tsv",
    "json",
    "jsonl",
    "py",
    "js",
    "ts",
    "jsx",
    "tsx",
    "html",
    "htm",
    "css",
    "xml",
    "yaml",
    "yml",
    "toml",
    "ini",
    "cfg",
    "conf",
    "sh",
    "bash",
    "zsh",
    "sql",
    "r",
    "rb",
    "go",
    "rs",
    "java",
    "c",
    "cpp",
    "h",
    "hpp",
    "cs",
    "swift",
    "kt",
    "lua",
    "log",
    "env",
    "gitignore",
    "dockerfile",
}

_PREVIEW_LINES = 15  # Max lines in preview
_PREVIEW_CHARS = 800  # Max chars in preview


def _fmt_size(n: int) -> str:
    """Format byte size for display."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if n != int(n) else f"{n} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} TB"


def _build_file_summary(name: str, path: str, data: bytes, media_type: str) -> str:
    """Build a metadata + preview summary for a non-image file."""
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    size = len(data)
    summary = f"- **{name}** ({_fmt_size(size)}) — path: `{path}`"

    # Try to decode as text for metadata + preview
    if ext in _TEXT_EXTS or media_type.startswith("text/"):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            try:
                text = data.decode("latin-1")
            except Exception:
                return summary + " — binary file, use `read_file` to inspect"

        lines = text.splitlines()
        char_count = len(text)
        line_count = len(lines)
        summary += f" — {line_count} lines, {char_count} chars"

        # Build a small preview
        preview_lines = lines[:_PREVIEW_LINES]
        preview = "\n".join(preview_lines)
        if len(preview) > _PREVIEW_CHARS:
            preview = preview[:_PREVIEW_CHARS] + "…"
        truncated = line_count > _PREVIEW_LINES or len(preview) >= _PREVIEW_CHARS

        summary += f"\n  ```\n{preview}\n  ```"
        if truncated:
            remaining = line_count - _PREVIEW_LINES
            summary += (
                f"\n  *(preview — {remaining} more lines,"
                f' use `read_file("{path}")` for full content)*'
            )
    else:
        # Binary non-image (e.g. zip, docx, xlsx)
        summary += f" — binary ({media_type}), use `read_file` to inspect"

    return summary


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------


@dataclass
class UserSession:
    """Per-user session state."""

    session_id: str
    deps: DeepAgentDeps
    message_history: list[ModelMessage] = field(default_factory=list)
    pending_approval_state: dict[str, Any] = field(default_factory=dict)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    running_task: asyncio.Task[None] | None = field(default=None)
    latest_todos: list[dict[str, Any]] = field(default_factory=list)
    pending_questions: dict[str, asyncio.Future[str]] = field(default_factory=dict)
    checkpoint_store: InMemoryCheckpointStore = field(default_factory=InMemoryCheckpointStore)


def create_ask_user_callback(websocket: WebSocket, session: UserSession) -> Any:
    """Create an ask_user callback that sends questions via WebSocket.

    When the planner subagent calls ask_user(), this callback:
    1. Sends the question + options to the frontend via WebSocket
    2. Waits for the user's response (via asyncio.Future)
    3. Returns the answer to the agent

    The WebSocket handler resolves the Future when it receives a
    'question_answer' message from the frontend.
    """

    async def callback(question: str, options: list[dict[str, str]]) -> str:
        question_id = str(uuid.uuid4())
        future: asyncio.Future[str] = asyncio.get_event_loop().create_future()
        session.pending_questions[question_id] = future

        logger.info(f"ASK_USER: {question} (options: {len(options)})")

        await websocket.send_json(
            {
                "type": "ask_user_question",
                "question_id": question_id,
                "question": question,
                "options": options,
            }
        )

        # Block until the user responds (the WS handler resolves the Future)
        answer = await future
        logger.info(f"ASK_USER answer: {answer}")
        return answer

    return callback


# Global state - shared agent (stateless) and session manager
agent: Agent[DeepAgentDeps, str] | None = None
session_manager: SessionManager | None = None
user_sessions: dict[str, UserSession] = {}  # session_id -> UserSession


# ---------------------------------------------------------------------------
# Hooks (Claude Code-style lifecycle hooks)
# ---------------------------------------------------------------------------


async def audit_logger_handler(hook_input: HookInput) -> HookResult:
    """Background POST_TOOL_USE hook: logs all tool calls.

    Demonstrates handler hooks - async Python functions that receive
    HookInput and return HookResult. This one runs in the background
    (fire-and-forget) so it doesn't block the agent.
    """
    args_preview = str(hook_input.tool_input)[:200]
    logger.info(f"HOOK AUDIT: {hook_input.tool_name}({args_preview})")
    return HookResult(allow=True)


async def safety_gate_handler(hook_input: HookInput) -> HookResult:
    """PRE_TOOL_USE hook: blocks dangerous commands in execute tool.

    Demonstrates blocking hooks - returns allow=False to prevent
    the tool from executing. Only matches the 'execute' tool
    (via the matcher parameter on the Hook).
    """
    command = hook_input.tool_input.get("command", "")

    # Block dangerous patterns
    dangerous_patterns = [
        r"rm\s+-rf\s+/",
        r"rm\s+-rf\s+\*",
        r"mkfs\.",
        r"dd\s+if=.*of=/dev/",
        r"chmod\s+-R\s+777\s+/",
        r":\(\)\{",  # fork bomb
    ]

    for pattern in dangerous_patterns:
        if re.search(pattern, command):
            return HookResult(
                allow=False,
                reason=f"BLOCKED: Command matches dangerous pattern. "
                f"The command '{command}' was blocked for safety.",
            )

    return HookResult(allow=True)


HOOKS = [
    # Background audit logger - fires after every tool completes
    Hook(
        event=HookEvent.POST_TOOL_USE,
        handler=audit_logger_handler,
        background=True,
    ),
    # Safety gate - blocks dangerous execute commands (blocking, not background)
    Hook(
        event=HookEvent.PRE_TOOL_USE,
        handler=safety_gate_handler,
        matcher="execute",  # Only matches the 'execute' tool
        timeout=5,
    ),
]


# ---------------------------------------------------------------------------
# Middleware (pydantic-ai-middleware integration)
# ---------------------------------------------------------------------------

# Module-level instances so app.py and WebSocket handler can access stats
audit_mw = AuditMiddleware()
permission_mw = PermissionMiddleware()


# ---------------------------------------------------------------------------
# Subagent configurations
# ---------------------------------------------------------------------------

SUBAGENT_CONFIGS: list[SubAgentConfig] = [
    {
        "name": "joke-generator",
        "description": "Generates jokes on any topic. Use for jokes or entertainment.",
        "instructions": """You are a professional comedian and joke writer.

Your task is to generate funny, clever jokes on the requested topic.

Guidelines:
- Generate 2-3 jokes per request
- Include different styles: puns, one-liners, observational humor
- Keep it clean and appropriate
- Be creative and original

Format your response as:
1. [First joke]
2. [Second joke]
3. [Third joke]

Always end with a brief explanation of why each joke is funny (for educational purposes).
""",
    },
    {
        "name": "code-reviewer",
        "description": (
            "Reviews Python code for quality, security, and best practices. "
            "Delegate code review tasks to this subagent."
        ),
        "instructions": """You are a code review expert. When reviewing code:

1. Read the entire file before making comments
2. Check for security issues first (injection, hardcoded secrets)
3. Review code structure and design patterns
4. Check error handling completeness
5. Verify type hints and documentation

Format your review as:
## Summary
[Brief overall assessment]

## Critical Issues
- [Security or major bugs]

## Improvements
- [Suggested improvements]

## Good Practices
- [Positive aspects]
""",
    },
]


# ---------------------------------------------------------------------------
# Programmatic skills (Skill dataclass instances)
# ---------------------------------------------------------------------------

PROGRAMMATIC_SKILLS = [
    Skill(
        name="quick-reference",
        description="Quick reference card for workspace commands and shortcuts",
        content="""\
# Quick Reference

## File Operations
- `read_file(path)` — Read a file (use offset/limit for large files)
- `write_file(path, content)` — Create or overwrite a file
- `edit_file(path, old_string, new_string)` — Edit specific parts of a file
- `glob(pattern)` — Find files matching a pattern (e.g., `*.py`, `/workspace/**/*.csv`)
- `grep(pattern, paths)` — Search file contents with regex

## Code Execution
- `execute(command)` — Run a shell command in the Docker sandbox
- Python 3.12 with pandas, numpy, matplotlib, scikit-learn, seaborn, plotly pre-installed

## Subagents
- `delegate_task(agent, task)` — Delegate work to a specialized subagent
- Available: joke-generator, code-reviewer, general-purpose

## TODO Management
- `write_todos(todos)` — Create or update task list
- `read_todos()` — Get current task list

## Tips
- Use `/workspace/` for all generated files
- Use `/uploads/` to access uploaded files
- Save charts as PNG or interactive HTML to `/workspace/`
- Load skills with `list_skills()` → `load_skill(name)` for domain knowledge
""",
    ),
]


# ---------------------------------------------------------------------------
# System instructions (extends BASE_PROMPT)
# ---------------------------------------------------------------------------

MAIN_INSTRUCTIONS = f"""{BASE_PROMPT}

## Application-Specific Capabilities

1. **File Operations**: Read, write, edit, and search files in the workspace
2. **GitHub Integration**: Query repos, issues, PRs, and users (mock data for demo)
3. **Code Execution**: Execute Python code in an isolated Docker sandbox \
(pre-installed: pandas, numpy, matplotlib, scikit-learn, seaborn, plotly)
4. **Data Analysis**: Load the 'data-analysis' skill for comprehensive CSV analysis
5. **Code Review**: Delegate to the 'code-reviewer' subagent for code quality review
6. **Entertainment**: Delegate to the 'joke-generator' subagent for humor
7. **Quick Reference**: Load the 'quick-reference' skill for command shortcuts
8. **Dynamic Agents**: Create new specialized agents at runtime with `create_agent(name, description, instructions)`, then delegate tasks to them. Use `list_agents()` to see created agents, `remove_agent(name)` to delete them. Allowed models: openai:gpt-4.1, openai:gpt-4o-mini, openai:gpt-4.1-mini.
9. **Plan Mode**: For complex tasks, delegate to the 'planner' subagent which will \
analyze the codebase, ask clarifying questions with options, and create a step-by-step \
implementation plan. Trigger when the user says 'use plan mode' or for tasks requiring \
architectural decisions and multi-file changes. The plan is saved to a markdown file.

## Task Management with TODO List

Use the TODO list **only for multi-step tasks** (3+ steps). Do NOT create TODOs for simple
requests like running a command, reading a file, or answering a question — just do them directly.

When a task has multiple steps:
1. Use `write_todos` to break it down
2. Keep exactly ONE todo as "in_progress" at a time
3. Mark completed immediately after finishing each step
4. **Complete ALL todos before responding** — never stop early to describe what you'd do next

Example of when to use TODOs:
```
User: "Create a script that analyzes sales data"
→ YES: 3 steps (read data, write script, execute & verify)
```

Example of when NOT to use TODOs:
```
User: "Run ls -la"
→ NO: just run the command directly

User: "What files are in the workspace?"
→ NO: just list them

User: "Tell me a joke"
→ NO: just delegate to subagent
```

## Error Handling - BE AUTONOMOUS

**CRITICAL**: When something fails, FIX IT YOURSELF. Don't ask for permission to fix obvious issues.

Examples of things you should fix automatically WITHOUT asking:
- Missing Python modules → `pip install <module>` and retry
- File not found → check the path, create the file if needed
- Syntax errors in code → fix the code and retry
- Permission errors → try alternative approaches
- Command not found → install the tool or use alternatives

**NEVER** say things like:
- "Would you like me to install...?"
- "Should I fix this error?"
- "Do you want me to retry?"

**ALWAYS** just fix the problem and continue. Only ask the user if:
- You've tried multiple approaches and all failed
- The error requires a decision about business logic or design
- You need information only the user can provide (credentials, preferences, etc.)

## Shell Commands & Code Execution

You have an `execute` tool for running shell commands. **Always use it** when the user asks
to run a command. The tool may require user approval (human-in-the-loop) — that's expected,
just call it and wait for approval. Never refuse to run a command or say you can't — use `execute`.

## Guidelines

- When asked to analyze data, first load the 'data-analysis' skill for best practices
- When asked for jokes or entertainment, delegate to the 'joke-generator' subagent
- When asked to review code, delegate to the 'code-reviewer' subagent
- For GitHub queries, use the appropriate github_* tools
- For code execution, write the code to a file first, then execute it

## File Locations

- Uploaded files are in: /uploads/
- Your workspace is: /workspace/
- Save generated files (charts, reports) to /workspace/

{GITHUB_SYSTEM_PROMPT}
"""


# ---------------------------------------------------------------------------
# Agent creation (ALL features wired here)
# ---------------------------------------------------------------------------


def create_agent() -> Agent[DeepAgentDeps, str]:
    """Create the shared agent with ALL pydantic-deep features.

    This demonstrates every parameter of create_deep_agent():
    - BASE_PROMPT + custom instructions
    - Hooks (audit logger + safety gate)
    - Middleware (audit + permissions)
    - Eviction processor (large tool outputs)
    - Patch tool calls processor (orphan repair)
    - Sliding window processor (conversation trimming)
    - Context files (DEEP.md)
    - Image support
    - Multiple subagents + general-purpose + dynamic agent factory
    - Skills (filesystem + programmatic)
    - Human-in-the-loop (execute approval)
    """
    # Custom GitHub toolset
    github_toolset = create_github_toolset(id="github")

    # Dynamic agent factory — lets the agent create new specialized agents at runtime
    agent_registry = DynamicAgentRegistry()
    factory_toolset = create_agent_factory_toolset(
        registry=agent_registry,
        allowed_models=["openai:gpt-4.1", "openai:gpt-4o-mini", "openai:gpt-4.1-mini"],
        default_model="openai:gpt-4.1-mini",
        max_agents=5,
        id="agent-factory",
    )

    # Sliding window processor for long conversations
    sliding_window = create_sliding_window_processor(
        trigger=("messages", 50),  # Trigger when > 50 messages
        keep=("messages", 30),  # Keep last 30 messages
    )

    return create_deep_agent(
        model="openai:gpt-4.1",
        instructions=MAIN_INSTRUCTIONS,
        backend=None,  # Backend comes from deps at runtime (per-session Docker container)
        # --- Toolsets ---
        include_todo=True,
        include_filesystem=True,
        include_subagents=True,
        include_skills=True,
        include_execute=True,  # Force include - backend provided via deps at runtime
        toolsets=[github_toolset, factory_toolset],
        # --- Subagents (joke-generator + code-reviewer + general-purpose + dynamic) ---
        subagents=SUBAGENT_CONFIGS,
        include_general_purpose_subagent=True,
        max_nesting_depth=2,  # Subagents can spawn their own subagents (2 levels deep)
        subagent_registry=agent_registry,  # Share registry so task() can find dynamic agents
        # --- Skills (filesystem directory + programmatic Skill instances) ---
        skills=PROGRAMMATIC_SKILLS,
        skill_directories=[{"path": str(SKILLS_DIR), "recursive": True}],
        # --- Hooks (Claude Code-style lifecycle hooks) ---
        hooks=HOOKS,
        # --- Middleware (pydantic-ai-middleware integration) ---
        middleware=[audit_mw, permission_mw],
        # --- Processors ---
        eviction_token_limit=20000,  # Save tool outputs > 20K tokens to files
        patch_tool_calls=True,  # Fix orphaned tool calls on resume
        history_processors=[sliding_window],
        # --- Context files (DEEP.md auto-injection into system prompt) ---
        context_files=["/workspace/DEEP.md"],
        # --- Image support (multimodal read_file) ---
        image_support=True,
        # --- Checkpointing (conversation save/rewind/fork) ---
        include_checkpoints=True,
        checkpoint_frequency="every_turn",
        max_checkpoints=50,
        # --- Human-in-the-loop ---
        interrupt_on={
            "execute": True,
            "write_file": False,
        },
    )


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

# Default DEEP.md content to seed into new sessions
_DEEP_MD_PATH = APP_DIR / "workspace" / "DEEP.md"


async def get_or_create_session(session_id: str) -> UserSession:
    """Get existing session or create a new one with isolated Docker container."""
    global session_manager, user_sessions

    if session_id in user_sessions:
        return user_sessions[session_id]

    # Create new sandbox via SessionManager
    assert session_manager is not None
    sandbox = await session_manager.get_or_create(session_id)

    # Seed workspace with DEEP.md context file (demonstrates context_files feature)
    if _DEEP_MD_PATH.exists():
        deep_md_content = _DEEP_MD_PATH.read_text()
        sandbox.write("/workspace/DEEP.md", deep_md_content)

    # Create per-session checkpoint store
    cp_store = InMemoryCheckpointStore()

    # Create deps with the user's sandbox and checkpoint store
    deps = DeepAgentDeps(backend=sandbox, checkpoint_store=cp_store)

    # Create and store session
    session = UserSession(session_id=session_id, deps=deps, checkpoint_store=cp_store)
    user_sessions[session_id] = session

    logger.info(f"Created new session: {session_id}")
    return session


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared agent and session manager on startup."""
    global agent, session_manager

    # Create shared agent (stateless) with ALL features
    agent = create_agent()

    # Create session manager for per-user Docker containers
    # Uses python-datascience runtime (pre-installed: pandas, numpy, matplotlib, etc.)
    # NOTE: Change to "python-datascience" for pre-installed pandas/numpy/matplotlib
    # (first run will take a few minutes to build the Docker image)
    session_manager = SessionManager(
        default_runtime=None,  # Uses python:3.12-slim for fast startup
        default_idle_timeout=3600,  # 1 hour idle timeout
        workspace_root=WORKSPACES_DIR,  # Persistent storage for user files
    )
    session_manager.start_cleanup_loop(interval=300)  # Cleanup every 5 min

    print("=" * 60)
    print("pydantic-deep Full Demo — ALL features enabled")
    print("=" * 60)
    print(f"  Skills directory : {SKILLS_DIR}")
    print(f"  Workspaces       : {WORKSPACES_DIR}")
    rt = session_manager._default_runtime  # type: ignore[attr-defined]
    print(f"  Runtime          : {rt or 'python:3.12-slim (default)'}")
    print(f"  Hooks            : {len(HOOKS)} (audit_logger, safety_gate)")
    print("  Middleware       : AuditMiddleware, PermissionMiddleware")
    print("  Processors       : eviction(20K), sliding_window(50→30), patch_tool_calls")
    print("  Checkpointing    : every_tool, max=50")
    print("  Context files    : /workspace/DEEP.md")
    print("  Image support    : enabled")
    print(
        "  Subagents        : joke-generator, code-reviewer, planner, general-purpose + dynamic factory"
    )
    print("  Skills           : data-analysis, code-review, test-generator, quick-reference")
    print("=" * 60)
    yield

    # Shutdown all sessions
    count = await session_manager.shutdown()
    print(f"Shutdown complete. Stopped {count} sessions.")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="pydantic-deep Full Example",
    description="Full-featured example demonstrating ALL pydantic-deep capabilities",
    lifespan=lifespan,
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main HTML page."""
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text())
    return HTMLResponse(content="<h1>Frontend not found. Check static/index.html</h1>")


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):  # noqa: C901
    """WebSocket endpoint for streaming chat with the agent.

    Session ID is sent in the first message. Each session_id gets its own
    isolated Docker container and message history.

    Protocol:
    1. Client connects to /ws/chat
    2. Client sends first message with session_id: {"session_id": "xxx", "message": "..."}
    3. Server streams responses with various event types:
       - {"type": "start"} - Agent run started
       - {"type": "text_delta", "content": "..."} - Streaming text chunk
       - {"type": "thinking_delta", "content": "..."} - Thinking text chunk
       - {"type": "tool_call_start", ...} - Tool call starting (args streaming)
       - {"type": "tool_args_delta", ...} - Streaming tool args
       - {"type": "tool_start", "tool_name": "...", "args": {...}} - Tool executing
       - {"type": "tool_output", "tool_name": "...", "output": "..."} - Tool result
       - {"type": "todos_update", "todos": [...]} - Task list update
       - {"type": "approval_required", "requests": [...]} - Human approval needed
       - {"type": "middleware_event", ...} - Middleware audit event
       - {"type": "response", "content": "..."} - Final response
       - {"type": "done"} - Agent run complete
       - {"type": "error", "content": "..."} - Error occurred
    """
    global agent

    await websocket.accept()

    if agent is None:
        await websocket.send_json({"type": "error", "content": "Agent not initialized"})
        return

    session: UserSession | None = None
    incoming: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def _reader() -> None:
        """Read WebSocket messages into a queue so we can process them concurrently."""
        try:
            while True:
                data = await websocket.receive_text()
                await incoming.put(json.loads(data))
        except WebSocketDisconnect:
            await incoming.put({"__disconnect": True})

    reader_task = asyncio.create_task(_reader())

    try:
        while True:
            message_data = await incoming.get()

            if message_data.get("__disconnect"):
                break

            # Get session_id from message (required for first message, optional after)
            session_id = message_data.get("session_id")
            if session is None:
                if not session_id:
                    session_id = str(uuid.uuid4())
                    await websocket.send_json({"type": "session_created", "session_id": session_id})
                session = await get_or_create_session(session_id)
                # Set up ask_user callback so planner subagent can ask questions
                session.deps.ask_user = create_ask_user_callback(websocket, session)
                logger.info(f"WebSocket connected for session: {session_id}")

            # Handle question answers (from planner ask_user)
            question_answer = message_data.get("question_answer")
            if question_answer and session:
                qid = question_answer.get("question_id", "")
                answer = question_answer.get("answer", "")
                if qid in session.pending_questions:
                    session.pending_questions[qid].set_result(answer)
                    del session.pending_questions[qid]
                    logger.info(f"Resolved question {qid}: {answer}")
                continue

            user_message = message_data.get("message", "")
            approval_response = message_data.get("approval")
            cancel_request = message_data.get("cancel")
            attachments = message_data.get("attachments", [])

            # Handle cancel request
            if cancel_request:
                if session.running_task and not session.running_task.done():
                    logger.info(f"Cancelling agent run for session {session.session_id}")
                    session.cancel_event.set()
                    session.running_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await session.running_task
                    session.running_task = None
                    await websocket.send_json({"type": "cancelled"})
                    await websocket.send_json({"type": "done"})
                continue

            # Handle approval response
            if approval_response is not None:
                await handle_approval(websocket, session, approval_response)
                continue

            if not user_message and not attachments:
                await websocket.send_json({"type": "error", "content": "Empty message"})
                continue

            # Build the user prompt (multimodal if attachments present)
            user_prompt: str | list[str | BinaryContent] = user_message
            if attachments:
                import base64 as b64

                prompt_parts: list[str | BinaryContent] = []
                file_summaries: list[str] = []

                for att in attachments:
                    name = att.get("name", "file")
                    media_type = att.get("type", "application/octet-stream")
                    data = b64.b64decode(att["data"])

                    # Save to container first
                    upload_path = session.deps.upload_file(name, data)
                    logger.info(f"Attachment saved: {name} ({len(data)} bytes) -> {upload_path}")

                    if media_type.startswith("image/"):
                        # Images: send as BinaryContent so model can see them
                        prompt_parts.append(BinaryContent(data=data, media_type=media_type))
                        file_summaries.append(
                            f"- **{name}** (image, {_fmt_size(len(data))})"
                            f" — path: `{upload_path}` — sent inline for visual analysis"
                        )
                    else:
                        # Non-image files: save to container, give agent metadata + preview
                        file_summaries.append(
                            _build_file_summary(name, upload_path, data, media_type)
                        )

                # Compose the text prompt
                files_block = "\n".join(file_summaries)
                if user_message:
                    text = (
                        f"{user_message}\n\n"
                        f"**Attached files:**\n{files_block}\n\n"
                        f"Use `read_file` to access full file contents if needed."
                    )
                else:
                    text = (
                        f"I've attached the following files:\n{files_block}\n\n"
                        f"Use `read_file` to access full contents. "
                        f"What would you like to do with them?"
                    )

                prompt_parts.insert(0, text)
                user_prompt = prompt_parts

            # Cancel any previous run
            if session.running_task and not session.running_task.done():
                session.cancel_event.set()
                session.running_task.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await session.running_task

            session.cancel_event.clear()
            session.running_task = asyncio.create_task(
                _run_agent_task(websocket, session, user_prompt)
            )

    finally:
        reader_task.cancel()
        if session and session.running_task and not session.running_task.done():
            session.running_task.cancel()
        if session:
            logger.info(f"WebSocket disconnected for session: {session.session_id}")


def _save_partial_history(session: UserSession) -> None:
    """Save user message + partial agent response to history on cancel.

    When the user cancels mid-response, `result.all_messages()` never runs
    because CancelledError interrupts `agent.iter()`. Without this, the
    next message has no context of what was said before the cancel.
    """
    user_msg = getattr(session, "_current_user_message", None)
    streamed = getattr(session, "_streamed_text", "")

    if not user_msg:
        return

    # Append the user's message
    session.message_history.append(ModelRequest(parts=[UserPromptPart(content=user_msg)]))

    # Append whatever the agent had streamed so far (may be empty)
    if streamed:
        session.message_history.append(
            ModelResponse(parts=[TextPart(content=streamed + "\n\n[Response interrupted]")])
        )

    logger.info(
        f"Saved partial history: user_msg={user_msg[:60]!r}, "
        f"streamed={len(streamed)} chars, "
        f"history now {len(session.message_history)} messages"
    )

    # Clean up tracking attrs
    session._streamed_text = ""  # type: ignore[attr-defined]
    session._current_user_message = None  # type: ignore[attr-defined]


async def _run_agent_task(
    websocket: WebSocket,
    session: UserSession,
    user_prompt: str | list[str | BinaryContent],
) -> None:
    """Wrapper that runs the agent and sends done/error."""
    try:
        await run_agent_with_streaming(websocket, session, user_prompt)
    except asyncio.CancelledError:
        logger.info(f"Agent run cancelled for session {session.session_id}")
        # Save partial history so the agent retains context after cancel
        _save_partial_history(session)
        raise
    except RewindRequested as rw:
        logger.info(f"Rewind requested to checkpoint '{rw.label}' ({rw.checkpoint_id})")
        session.message_history = rw.messages
        try:
            await websocket.send_json(
                {
                    "type": "checkpoint_rewind",
                    "checkpoint_id": rw.checkpoint_id,
                    "label": rw.label,
                    "message_count": len(rw.messages),
                }
            )
            await websocket.send_json({"type": "done"})
        except Exception:
            pass
    except Exception as e:
        logger.exception("Error in agent run")
        try:
            await websocket.send_json({"type": "error", "content": str(e)})
            await websocket.send_json({"type": "done"})
        except Exception:
            pass
    finally:
        session.running_task = None


async def run_agent_with_streaming(
    websocket: WebSocket,
    session: UserSession,
    user_prompt: str | list[str | BinaryContent],
    deferred_results: DeferredToolResults | None = None,
) -> None:
    """Run agent with streaming and handle DeferredToolRequests."""
    global agent

    # Extract text portion for logging and cancel recovery
    if isinstance(user_prompt, str):
        text_preview = user_prompt[:100] if user_prompt else "(continuation)"
    else:
        text_parts = [p for p in user_prompt if isinstance(p, str)]
        text_preview = (
            text_parts[0][:100] if text_parts else "(multimodal)"
        ) + f" + {sum(1 for p in user_prompt if isinstance(p, BinaryContent))} files"

    logger.info(f"=== Starting agent run for session {session.session_id} ===")
    logger.info(f"User prompt: {text_preview}")
    logger.info(f"Deferred results: {deferred_results is not None}")
    logger.info(f"Message history length: {len(session.message_history)}")

    # Send start event
    await websocket.send_json({"type": "start"})

    # Track streamed text for cancel recovery (store only text part)
    session._streamed_text = ""  # type: ignore[attr-defined]
    cancel_text = (
        user_prompt
        if isinstance(user_prompt, str)
        else " ".join(p for p in user_prompt if isinstance(p, str))
    )
    session._current_user_message = cancel_text  # type: ignore[attr-defined]

    # Use iter() for streaming execution with session's message history
    assert agent is not None
    async with agent.iter(
        user_prompt if deferred_results is None else None,
        deps=session.deps,
        message_history=session.message_history,
        deferred_tool_results=deferred_results,
    ) as run:
        node_count = 0
        async for node in run:
            node_count += 1
            logger.debug(f"Node {node_count}: {type(node).__name__}")
            await process_node(websocket, node, run, session)

        # Get the final result
        result = run.result
        logger.info(f"Agent finished after {node_count} nodes")
        logger.info(f"Result output type: {type(result.output).__name__}")

        # Emit latest checkpoint once per invocation
        if session.checkpoint_store:
            try:
                all_cps = await session.checkpoint_store.list_all()
                if all_cps:
                    latest_cp = all_cps[-1]
                    await websocket.send_json(
                        {
                            "type": "checkpoint_saved",
                            "checkpoint_id": latest_cp.id,
                            "label": latest_cp.label,
                            "turn": latest_cp.turn,
                            "message_count": latest_cp.message_count,
                            "metadata": latest_cp.metadata,
                        }
                    )
            except Exception:
                pass

    # Check if we got DeferredToolRequests (needs approval)
    if isinstance(result.output, DeferredToolRequests):
        logger.info(f"Got DeferredToolRequests with {len(result.output.approvals)} approvals")
        # Store state for continuation in session
        session.pending_approval_state = {
            "message_history": result.all_messages(),
            "approvals": result.output.approvals,
        }

        # Send approval request to frontend
        approval_requests = []
        for call in result.output.approvals:
            logger.info(f"  Approval needed: {call.tool_name}({call.args})")
            approval_requests.append(
                {
                    "tool_call_id": call.tool_call_id,
                    "tool_name": call.tool_name,
                    "args": call.args if isinstance(call.args, dict) else str(call.args),
                }
            )

        await websocket.send_json(
            {
                "type": "approval_required",
                "requests": approval_requests,
            }
        )
        return

    # Update session's message history for next request
    session.message_history = result.all_messages()
    logger.info(f"Updated message history to {len(session.message_history)} messages")

    # Send final response
    logger.info(f"Sending response: {str(result.output)[:200]}...")
    await websocket.send_json(
        {
            "type": "response",
            "content": str(result.output),
        }
    )

    # Send completion event
    await websocket.send_json({"type": "done"})
    logger.info("=== Agent run complete ===")


async def handle_approval(
    websocket: WebSocket, session: UserSession, approval_response: dict
) -> None:
    """Handle approval response from frontend and continue agent."""
    if not session.pending_approval_state:
        await websocket.send_json({"type": "error", "content": "No pending approval"})
        return

    # Build approval results — ALL deferred tool calls must have a result
    approvals: dict[str, ToolApproved | ToolDenied] = {}
    for tool_call_id, approved in approval_response.items():
        if approved:
            approvals[tool_call_id] = ToolApproved()
        else:
            approvals[tool_call_id] = ToolDenied("User denied this tool call.")

    # Restore message history from pending state
    session.message_history = session.pending_approval_state["message_history"]

    # Clear pending state
    session.pending_approval_state = {}

    # Continue agent with approvals
    try:
        await run_agent_with_streaming(
            websocket,
            session,
            "",  # No new message
            deferred_results=DeferredToolResults(approvals=approvals),
        )
    except Exception as e:
        await websocket.send_json({"type": "error", "content": str(e)})


# ---------------------------------------------------------------------------
# Streaming helpers
# ---------------------------------------------------------------------------


async def _stream_model_request(
    websocket: WebSocket, node: Any, run: Any, session: UserSession
) -> None:
    """Stream text chunks from a ModelRequestNode."""
    await websocket.send_json({"type": "status", "content": "Generating response..."})

    # Track current tool call being streamed (for args streaming)
    current_tool_name: str | None = None
    current_tool_call_id: str | None = None

    async with node.stream(run.ctx) as request_stream:
        final_result_found = False

        # First, iterate through events to find deltas and final result marker
        async for event in request_stream:
            if isinstance(event, PartStartEvent):
                logger.debug(f"     PartStartEvent: {event.part!r}")
                # Check if this is a tool call part starting
                if hasattr(event.part, "tool_name"):
                    current_tool_name = event.part.tool_name
                    current_tool_call_id = getattr(event.part, "tool_call_id", None)
                    # Send tool_call_start event
                    await websocket.send_json(
                        {
                            "type": "tool_call_start",
                            "tool_name": current_tool_name,
                            "tool_call_id": current_tool_call_id,
                        }
                    )
            elif isinstance(event, PartDeltaEvent):
                await _handle_part_delta(websocket, event, current_tool_name, session)
            elif isinstance(event, FinalResultEvent):
                logger.debug(f"     FinalResultEvent: tool_name={event.tool_name}")
                final_result_found = True
                break  # Stop iterating events, switch to streaming text

        # If final result was found, stream the text output
        # Note: stream_text() yields cumulative text, so we compute deltas
        if final_result_found:
            previous_text = ""
            async for cumulative_text in request_stream.stream_text():
                # Extract only the new part (delta)
                delta = cumulative_text[len(previous_text) :]
                if delta:
                    await websocket.send_json({"type": "text_delta", "content": delta})
                    # Track for cancel recovery
                    session._streamed_text += delta  # type: ignore[attr-defined]
                previous_text = cumulative_text


async def _handle_part_delta(
    websocket: WebSocket,
    event: PartDeltaEvent,
    current_tool_name: str | None,
    session: UserSession,
) -> None:
    """Handle streaming delta events."""
    if isinstance(event.delta, TextPartDelta):
        await websocket.send_json({"type": "text_delta", "content": event.delta.content_delta})
        # Track for cancel recovery
        session._streamed_text += event.delta.content_delta  # type: ignore[attr-defined]
    elif isinstance(event.delta, ThinkingPartDelta):
        await websocket.send_json({"type": "thinking_delta", "content": event.delta.content_delta})
    elif isinstance(event.delta, ToolCallPartDelta):
        # Stream tool call arguments as they come in
        await websocket.send_json(
            {
                "type": "tool_args_delta",
                "tool_name": current_tool_name,
                "args_delta": event.delta.args_delta,
            }
        )


async def _stream_tool_calls(
    websocket: WebSocket, node: Any, run: Any, session: UserSession
) -> None:
    """Stream tool call events from a CallToolsNode."""
    tool_names_by_id: dict[str, str] = {}

    async with node.stream(run.ctx) as handle_stream:
        async for event in handle_stream:
            logger.debug(f"     Event type: {type(event).__name__}")

            if isinstance(event, FunctionToolCallEvent):
                tool_name = event.part.tool_name
                tool_args = event.part.args
                tool_call_id = event.part.tool_call_id
                logger.info(f"  TOOL CALL: {tool_name}({tool_args})")

                if tool_call_id:
                    tool_names_by_id[tool_call_id] = tool_name

                await websocket.send_json(
                    {
                        "type": "tool_start",
                        "tool_name": tool_name,
                        "args": tool_args if isinstance(tool_args, dict) else str(tool_args),
                    }
                )

                # Send todos update immediately from tool args (the internal
                # _storage.todos is not accessible, so we read directly from
                # the LLM's write_todos call arguments)
                if tool_name == "write_todos":
                    try:
                        args_dict = (
                            tool_args if isinstance(tool_args, dict) else json.loads(tool_args)
                        )
                        todos_data = args_dict.get("todos", [])
                        session.latest_todos = todos_data
                        logger.info(
                            f"  Sending todos_update from tool args: {len(todos_data)} todos"
                        )
                        await websocket.send_json({"type": "todos_update", "todos": todos_data})
                    except Exception as e:
                        logger.warning(f"Failed to parse write_todos args: {e}")

            elif isinstance(event, FunctionToolResultEvent):
                tool_call_id = event.tool_call_id
                tool_name = tool_names_by_id.get(tool_call_id, "unknown")
                result_content = event.result.content
                logger.info(f"  TOOL RESULT: {tool_name} -> {str(result_content)[:100]}...")

                await websocket.send_json(
                    {
                        "type": "tool_output",
                        "tool_name": tool_name,
                        "output": str(result_content),
                    }
                )

                # Note: todos_update is sent from FunctionToolCallEvent (above)
                # because _storage.todos inside the toolset is not accessible
                # from session.deps.todos

                # Send middleware audit event (demonstrates real-time middleware stats)
                stats = audit_mw.get_stats()
                await websocket.send_json(
                    {
                        "type": "middleware_event",
                        "event": "tool_audit",
                        "tool_name": tool_name,
                        "total_calls": stats.call_count,
                        "tools_breakdown": dict(stats.tools_used),
                    }
                )


async def process_node(websocket: WebSocket, node: Any, run: Any, session: UserSession) -> None:
    """Process a node and send appropriate WebSocket events with streaming."""
    if isinstance(node, UserPromptNode):
        logger.debug("  -> UserPromptNode")
        await websocket.send_json({"type": "status", "content": "Processing user prompt..."})

    elif Agent.is_model_request_node(node):
        logger.debug("  -> ModelRequestNode: streaming tokens")
        await _stream_model_request(websocket, node, run, session)

    elif Agent.is_call_tools_node(node):
        logger.debug(f"  -> CallToolsNode with {len(node.model_response.parts)} parts")
        await _stream_tool_calls(websocket, node, run, session)

    elif isinstance(node, End):
        await websocket.send_json({"type": "status", "content": "Completed!"})


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),  # noqa: B008
    session_id: str = Query(
        "", description="Session ID (optional, will create new if not provided)"
    ),
):
    """Upload a file (CSV, PDF, etc.) to a specific session."""
    try:
        # Generate session_id if not provided or empty
        if not session_id:
            session_id = str(uuid.uuid4())

        # Get or create session
        session = await get_or_create_session(session_id)

        content = await file.read()
        filename = file.filename or "uploaded_file"

        logger.info(f"Uploading file: {filename} ({len(content)} bytes) to session {session_id}")

        # Upload to the session's backend (Docker container)
        path = session.deps.upload_file(filename, content)
        logger.info(f"File uploaded to: {path}")

        # Verify the file exists in the container (if backend supports execute)
        if hasattr(session.deps.backend, "execute"):
            verify_result = session.deps.backend.execute(f'ls -la "{path}"')  # type: ignore[union-attr]
            logger.info(f"Verify upload: {verify_result.output.strip()}")

        return JSONResponse(
            content={
                "status": "success",
                "filename": filename,
                "path": path,
                "size": len(content),
                "session_id": session_id,
            }
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/files")
async def list_files(session_id: str = Query(..., description="Session ID")):
    """List files in workspace and uploads for a specific session."""
    if session_id not in user_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = user_sessions[session_id]

    files: dict[str, list[str]] = {
        "workspace": [],
        "uploads": [],
    }

    # List workspace files from container (if backend supports execute)
    if hasattr(session.deps.backend, "execute"):
        result = session.deps.backend.execute("find /workspace -type f 2>/dev/null")  # type: ignore[union-attr]
        if result.exit_code == 0:
            files["workspace"] = [f for f in result.output.strip().split("\n") if f]

    # List uploads from deps
    files["uploads"] = list(session.deps.uploads.keys())

    return JSONResponse(content=files)


@app.get("/files/download/{filepath:path}")
async def download_file(filepath: str, session_id: str = Query(..., description="Session ID")):
    """Download a file from a session's workspace."""
    if session_id not in user_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = user_sessions[session_id]

    # Read file from container
    result = session.deps.backend.read(f"/workspace/{filepath}")
    if "Error:" in result:
        raise HTTPException(status_code=404, detail="File not found")

    # Return as downloadable response
    return JSONResponse(
        content={
            "filename": filepath.split("/")[-1],
            "content": result,
        }
    )


@app.get("/files/content/{filepath:path}")
async def get_file_content(filepath: str, session_id: str = Query(..., description="Session ID")):
    """Get file content for preview (supports any path in the container).

    Args:
        filepath: Full path to file (e.g., /workspace/script.py or /uploads/data.csv)
        session_id: Session ID
    """
    if session_id not in user_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = user_sessions[session_id]

    # Decode the path if it was URL-encoded
    import urllib.parse

    decoded_path = urllib.parse.unquote(filepath)

    # Ensure path starts with /
    if not decoded_path.startswith("/"):
        decoded_path = "/" + decoded_path

    logger.debug(f"Reading file: {decoded_path} for session {session_id}")

    # Read file from container
    try:
        result = session.deps.backend.read(decoded_path)

        # Check for error patterns in result
        if result.startswith("Error:") or "No such file" in result:
            raise HTTPException(status_code=404, detail=f"File not found: {decoded_path}")

        return JSONResponse(
            content={
                "path": decoded_path,
                "filename": decoded_path.split("/")[-1],
                "content": result,
                "size": len(result),
            }
        )
    except Exception as e:
        if "404" in str(e) or "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=f"File not found: {decoded_path}") from e
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/files/binary/{filepath:path}")
async def get_file_binary(filepath: str, session_id: str = Query(..., description="Session ID")):
    """Get binary file content (for images, etc.).

    Args:
        filepath: Full path to file (e.g., /workspace/chart.png)
        session_id: Session ID
    """
    from fastapi.responses import Response

    if session_id not in user_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = user_sessions[session_id]

    # Decode the path if it was URL-encoded
    import urllib.parse

    decoded_path = urllib.parse.unquote(filepath)

    # Ensure path starts with /
    if not decoded_path.startswith("/"):
        decoded_path = "/" + decoded_path

    logger.debug(f"Reading binary file: {decoded_path} for session {session_id}")

    # Get file extension for content type
    ext = decoded_path.split(".")[-1].lower()
    content_types = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "svg": "image/svg+xml",
        "webp": "image/webp",
        "ico": "image/x-icon",
        "pdf": "application/pdf",
    }
    content_type = content_types.get(ext, "application/octet-stream")

    try:
        # Read binary file from container using base64
        if hasattr(session.deps.backend, "execute"):
            # Use quotes around path to handle spaces
            result = session.deps.backend.execute(f'base64 "{decoded_path}"')
            logger.debug(f"base64 command exit code: {result.exit_code}")

            if result.exit_code != 0:
                logger.error(f"base64 failed: {result.output}")
                raise HTTPException(status_code=404, detail=f"File not found: {decoded_path}")

            import base64

            # Clean the output - remove any whitespace/newlines that base64 adds
            b64_output = result.output.strip().replace("\n", "").replace("\r", "").replace(" ", "")

            # Fix padding if needed
            padding_needed = len(b64_output) % 4
            if padding_needed:
                b64_output += "=" * (4 - padding_needed)

            binary_content = base64.b64decode(b64_output)
            return Response(content=binary_content, media_type=content_type)
        else:
            raise HTTPException(
                status_code=500, detail="Backend does not support binary file reading"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error reading binary file: {decoded_path}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/todos")
async def get_todos(session_id: str = Query(..., description="Session ID")):
    """Get current todo list for a specific session."""
    if session_id not in user_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = user_sessions[session_id]

    return JSONResponse(
        content={
            "todos": session.latest_todos,
        }
    )


@app.get("/checkpoints")
async def list_checkpoints(session_id: str = Query(..., description="Session ID")):
    """List all checkpoints for a session."""
    if session_id not in user_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = user_sessions[session_id]
    all_cps = await session.checkpoint_store.list_all()

    return JSONResponse(
        content={
            "checkpoints": [
                {
                    "id": cp.id,
                    "label": cp.label,
                    "turn": cp.turn,
                    "message_count": cp.message_count,
                    "created_at": cp.created_at.isoformat(),
                    "metadata": cp.metadata,
                }
                for cp in all_cps
            ]
        }
    )


@app.post("/checkpoints/{checkpoint_id}/rewind")
async def rewind_to_checkpoint(
    checkpoint_id: str,
    session_id: str = Query(..., description="Session ID"),
):
    """Rewind a session to a specific checkpoint."""
    if session_id not in user_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = user_sessions[session_id]
    cp = await session.checkpoint_store.get(checkpoint_id)
    if cp is None:
        raise HTTPException(status_code=404, detail="Checkpoint not found")

    session.message_history = list(cp.messages)
    logger.info(
        f"Session {session_id} rewound to checkpoint '{cp.label}' ({cp.message_count} messages)"
    )

    return JSONResponse(
        content={
            "status": "rewound",
            "checkpoint_id": cp.id,
            "label": cp.label,
            "message_count": cp.message_count,
        }
    )


@app.post("/checkpoints/{checkpoint_id}/fork")
async def fork_from_checkpoint_endpoint(
    checkpoint_id: str,
    session_id: str = Query(..., description="Source session ID"),
):
    """Fork a new session from a checkpoint."""
    if session_id not in user_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = user_sessions[session_id]
    messages = await fork_from_checkpoint(session.checkpoint_store, checkpoint_id)

    # Create a new session with the forked messages
    new_session_id = str(uuid.uuid4())
    new_session = await get_or_create_session(new_session_id)
    new_session.message_history = messages

    logger.info(
        f"Forked session {new_session_id} from checkpoint {checkpoint_id} ({len(messages)} messages)"
    )

    return JSONResponse(
        content={
            "new_session_id": new_session_id,
            "message_count": len(messages),
        }
    )


@app.get("/history")
async def get_history(session_id: str = Query(..., description="Session ID")):
    """Return conversation history for a session as renderable messages.

    Used by the frontend to display previous messages when loading a
    forked session in a new tab.
    """
    if session_id not in user_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = user_sessions[session_id]
    rendered: list[dict[str, Any]] = []

    for msg in session.message_history:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart):
                    content = (
                        part.content if isinstance(part.content, str) else "(multimodal input)"
                    )
                    rendered.append({"role": "user", "content": content})
                elif isinstance(part, ToolReturnPart):
                    # Skip tool returns — they're shown as part of the tool call flow
                    pass
        elif isinstance(msg, ModelResponse):
            text_parts = [p.content for p in msg.parts if isinstance(p, TextPart) and p.content]
            tool_calls = [
                {
                    "tool_name": p.tool_name,
                    "args": p.args if isinstance(p.args, str) else json.dumps(p.args or {}),
                }
                for p in msg.parts
                if isinstance(p, ToolCallPart)
            ]
            if text_parts:
                rendered.append({"role": "assistant", "content": "\n\n".join(text_parts)})
            if tool_calls:
                for tc in tool_calls:
                    rendered.append(
                        {
                            "role": "tool_call",
                            "tool_name": tc["tool_name"],
                            "args": tc["args"],
                        }
                    )

    return JSONResponse(content={"messages": rendered})


@app.get("/config")
async def get_config():
    """Return current agent configuration for the features panel.

    This endpoint exposes the full feature configuration so the frontend
    can display what's active in the Config tab.
    """
    return JSONResponse(
        content={
            "features": {
                "base_prompt": True,
                "runtime": "python-datascience",
                "hooks": [
                    {
                        "name": "audit_logger",
                        "event": "POST_TOOL_USE",
                        "background": True,
                        "description": "Logs all tool calls (fire-and-forget)",
                    },
                    {
                        "name": "safety_gate",
                        "event": "PRE_TOOL_USE",
                        "matcher": "execute",
                        "background": False,
                        "description": "Blocks dangerous shell commands",
                    },
                ],
                "middleware": [
                    {
                        "name": "AuditMiddleware",
                        "type": "tool_stats",
                        "description": "Tracks tool usage count, duration, breakdown",
                    },
                    {
                        "name": "PermissionMiddleware",
                        "type": "path_blocking",
                        "description": "Blocks access to /etc/passwd, .env, /root/, etc.",
                    },
                ],
                "processors": {
                    "eviction": {
                        "token_limit": 20000,
                        "description": "Large outputs → file reference",
                    },
                    "sliding_window": {
                        "trigger": "50 messages",
                        "keep": "30 messages",
                        "description": "Trims old conversation history",
                    },
                    "patch_tool_calls": True,
                },
                "checkpointing": {
                    "enabled": True,
                    "frequency": "every_turn",
                    "max_checkpoints": 50,
                    "description": "Auto-saves after every model turn, rewind/fork via Timeline tab",
                },
                "context_files": ["/workspace/DEEP.md"],
                "image_support": True,
                "subagents": [
                    "joke-generator",
                    "code-reviewer",
                    "general-purpose",
                    "planner (plan mode)",
                    "dynamic (via agent factory)",
                ],
                "skills": ["data-analysis", "code-review", "test-generator", "quick-reference"],
                "interrupt_on": {"execute": True, "write_file": False},
                "tool_stats": dict(audit_mw.get_stats().tools_used),
                "total_tool_calls": audit_mw.get_stats().call_count,
            }
        }
    )


@app.post("/reset")
async def reset(session_id: str = Query(..., description="Session ID")):
    """Reset a specific session."""
    global session_manager, user_sessions

    if session_id not in user_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    # Release the session's Docker container
    if session_manager:
        await session_manager.release(session_id)

    # Remove from user sessions
    del user_sessions[session_id]

    # Reset audit stats
    audit_mw.reset_stats()

    logger.info(f"Reset session: {session_id}")

    return JSONResponse(content={"status": "reset complete", "session_id": session_id})


@app.post("/session/new")
async def create_new_session():
    """Create a new session and return its ID."""
    session_id = str(uuid.uuid4())
    session = await get_or_create_session(session_id)

    return JSONResponse(
        content={
            "session_id": session.session_id,
            "status": "created",
        }
    )


@app.get("/sessions")
async def list_sessions():
    """List all active sessions."""
    return JSONResponse(
        content={
            "sessions": list(user_sessions.keys()),
            "count": len(user_sessions),
        }
    )


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "agent_ready": agent is not None,
        "session_count": len(user_sessions),
    }


@app.get("/preview/{session_id}/{filepath:path}")
async def preview_file(session_id: str, filepath: str):
    """Serve raw files from container for live preview.

    This endpoint serves files WITHOUT line numbers, with proper Content-Type,
    allowing HTML files to load relative CSS/JS/images naturally.

    Example: /preview/abc123/workspace/index.html
             -> loads HTML, which requests style.css
             -> browser resolves to /preview/abc123/workspace/style.css
    """
    from fastapi.responses import Response

    if session_id not in user_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = user_sessions[session_id]

    # Ensure path starts with /
    if not filepath.startswith("/"):
        filepath = "/" + filepath

    logger.debug(f"Preview file: {filepath} for session {session_id}")

    # Get file extension for content type
    ext = filepath.split(".")[-1].lower() if "." in filepath else ""
    content_types = {
        # Web
        "html": "text/html; charset=utf-8",
        "htm": "text/html; charset=utf-8",
        "css": "text/css; charset=utf-8",
        "js": "application/javascript; charset=utf-8",
        "mjs": "application/javascript; charset=utf-8",
        "json": "application/json; charset=utf-8",
        # Images
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "svg": "image/svg+xml",
        "webp": "image/webp",
        "ico": "image/x-icon",
        # Fonts
        "woff": "font/woff",
        "woff2": "font/woff2",
        "ttf": "font/ttf",
        "eot": "application/vnd.ms-fontobject",
        # Other
        "pdf": "application/pdf",
        "xml": "application/xml",
        "txt": "text/plain; charset=utf-8",
    }
    content_type = content_types.get(ext, "application/octet-stream")

    # Check if binary file
    binary_extensions = {
        "png",
        "jpg",
        "jpeg",
        "gif",
        "webp",
        "ico",
        "pdf",
        "woff",
        "woff2",
        "ttf",
        "eot",
    }
    is_binary = ext in binary_extensions

    try:
        if hasattr(session.deps.backend, "execute"):
            if is_binary:
                # Read binary file via base64
                result = session.deps.backend.execute(f'base64 "{filepath}"')
                if result.exit_code != 0:
                    raise HTTPException(status_code=404, detail=f"File not found: {filepath}")

                import base64

                b64_output = (
                    result.output.strip().replace("\n", "").replace("\r", "").replace(" ", "")
                )
                padding_needed = len(b64_output) % 4
                if padding_needed:
                    b64_output += "=" * (4 - padding_needed)

                binary_content = base64.b64decode(b64_output)
                return Response(content=binary_content, media_type=content_type)
            else:
                # Read text file - use cat WITHOUT -n (no line numbers)
                result = session.deps.backend.execute(f'cat "{filepath}"')
                if result.exit_code != 0:
                    raise HTTPException(status_code=404, detail=f"File not found: {filepath}")

                return Response(content=result.output, media_type=content_type)
        else:
            raise HTTPException(status_code=500, detail="Backend does not support file serving")

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error serving preview file: {filepath}")
        raise HTTPException(status_code=500, detail=str(e)) from e


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
