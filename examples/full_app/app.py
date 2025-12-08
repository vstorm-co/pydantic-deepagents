"""Full-featured example application with FastAPI backend and WebSocket streaming.

This example demonstrates all pydantic-deep features:
- DockerSandbox for file operations and code execution
- Custom tools (mock GitHub tools)
- WebSocket streaming for real-time events
- Human-in-the-loop approval for execute
- Skills (data analysis)
- Subagents (joke generator - unrelated to main task)
- File uploads (PDF/CSV)
- Multi-user support with SessionManager

Run with:
    cd examples/full_app
    uvicorn app:app --reload --port 8080
"""

from __future__ import annotations

import json
import logging
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Import our custom GitHub tools
from github_tools import GITHUB_SYSTEM_PROMPT, create_github_toolset
from pydantic_ai import (
    FinalResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPartDelta,
    ThinkingPartDelta,
    ToolCallPartDelta,
)
from pydantic_ai._agent_graph import End, UserPromptNode
from pydantic_ai.agent import Agent
from pydantic_ai.messages import FunctionToolCallEvent, FunctionToolResultEvent, ModelMessage
from pydantic_ai.tools import (
    DeferredToolRequests,
    DeferredToolResults,
    ToolApproved,
)

from pydantic_deep import (
    DeepAgentDeps,
    SessionManager,
    create_deep_agent,
)
from pydantic_deep.types import SubAgentConfig

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Paths
APP_DIR = Path(__file__).parent
WORKSPACE_DIR = APP_DIR / "workspace"
SKILLS_DIR = APP_DIR / "skills"
STATIC_DIR = APP_DIR / "static"

# Create workspace if it doesn't exist
WORKSPACE_DIR.mkdir(exist_ok=True)


@dataclass
class UserSession:
    """Per-user session state."""

    session_id: str
    deps: DeepAgentDeps
    message_history: list[ModelMessage] = field(default_factory=list)
    pending_approval_state: dict[str, Any] = field(default_factory=dict)


# Global state - shared agent (stateless) and session manager
agent: Agent[DeepAgentDeps, str] | None = None
session_manager: SessionManager | None = None
user_sessions: dict[str, UserSession] = {}  # session_id -> UserSession


# Subagent configurations
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
]

# System instructions for the main agent
MAIN_INSTRUCTIONS = """You are a powerful AI assistant with multiple capabilities:

## Your Capabilities

1. **File Operations**: You can read, write, edit, and search files in the workspace
2. **GitHub Integration**: Query repos, issues, PRs, and users (mock data for demo)
3. **Code Execution**: You can execute Python code in a Docker sandbox
4. **Data Analysis**: Load the 'data-analysis' skill for comprehensive CSV analysis
5. **Entertainment**: Delegate to the 'joke-generator' subagent for humor

## Task Management with TODO List

**IMPORTANT**: You MUST use the TODO list to track your progress on tasks!

When you receive a task:
1. **First**, use `write_todos` to create a task list breaking down the work into steps
2. **During work**, update todos as you complete them (mark as "completed") or start them (mark as "in_progress")
3. **Always** keep exactly ONE todo as "in_progress" at any time
4. **Mark completed** immediately after finishing each step - don't batch completions

Example workflow:
```
User: "Create a script that analyzes sales data"

1. write_todos([
     {{"content": "Read and understand the data file", "status": "in_progress"}},
     {{"content": "Write analysis script", "status": "pending"}},
     {{"content": "Execute and verify results", "status": "pending"}}
   ])
2. [Read the file]
3. write_todos([...first completed, second in_progress...])
4. [Write the script]
5. write_todos([...second completed, third in_progress...])
6. [Execute]
7. write_todos([...all completed...])
```

The user can see your TODO list in real-time, so keep it updated!

## Error Handling - BE AUTONOMOUS

**CRITICAL**: When something fails, FIX IT YOURSELF. Do NOT ask the user for permission to fix obvious issues.

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

When you encounter an error:
1. Analyze what went wrong
2. Fix it immediately (install packages, correct code, etc.)
3. Retry the operation
4. Continue with the task

## Guidelines

- When asked to analyze data, first load the 'data-analysis' skill for best practices
- When asked for jokes or entertainment, delegate to the 'joke-generator' subagent
- For GitHub queries, use the appropriate github_* tools
- For code execution, write the code to a file first, then execute it
- Briefly explain what you're doing, but don't over-explain

## File Locations

- Uploaded files are in: /uploads/
- Your workspace is: /workspace/
- Save generated files (charts, reports) to /workspace/

{github_prompt}
"""


def create_agent() -> Agent[DeepAgentDeps, str]:
    """Create the shared agent (stateless - can be used by all sessions)."""
    # Create the GitHub toolset
    github_toolset = create_github_toolset(id="github")

    # Create the main agent with all features
    # Include DeferredToolRequests as output type for human-in-the-loop
    # Note: backend=None because deps are provided per-session at runtime
    return create_deep_agent(
        model="openai:gpt-4.1",
        instructions=MAIN_INSTRUCTIONS.format(github_prompt=GITHUB_SYSTEM_PROMPT),
        backend=None,  # Backend comes from deps at runtime
        # Toolsets
        include_todo=True,
        include_filesystem=True,
        include_subagents=True,
        include_skills=True,
        include_execute=True,  # Force include execute - backend is provided via deps at runtime
        toolsets=[github_toolset],
        # Subagents
        subagents=SUBAGENT_CONFIGS,
        include_general_purpose_subagent=False,  # We only want our custom subagent
        # Skills
        skill_directories=[{"path": str(SKILLS_DIR), "recursive": True}],
        # Human-in-the-loop: require approval for execute
        interrupt_on={
            "execute": True,
            "write_file": False,
        },
    )


async def get_or_create_session(session_id: str) -> UserSession:
    """Get existing session or create a new one with isolated Docker container."""
    global session_manager, user_sessions

    if session_id in user_sessions:
        return user_sessions[session_id]

    # Create new sandbox via SessionManager
    assert session_manager is not None
    sandbox = await session_manager.get_or_create(session_id)

    # Create deps with the user's sandbox
    deps = DeepAgentDeps(backend=sandbox)

    # Create and store session
    session = UserSession(session_id=session_id, deps=deps)
    user_sessions[session_id] = session

    logger.info(f"Created new session: {session_id}")
    return session


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize shared agent and session manager on startup."""
    global agent, session_manager

    # Create shared agent (stateless)
    agent = create_agent()

    # Create session manager for per-user Docker containers
    session_manager = SessionManager(
        default_runtime=None,  # Will use default python:3.12-slim
        default_idle_timeout=3600,  # 1 hour idle timeout
    )
    session_manager.start_cleanup_loop(interval=300)  # Cleanup every 5 min

    print("Agent initialized (shared across sessions)")
    print(f"Skills directory: {SKILLS_DIR}")
    print("Session manager started with auto-cleanup")
    yield

    # Shutdown all sessions
    count = await session_manager.shutdown()
    print(f"Shutdown complete. Stopped {count} sessions.")


# Create FastAPI app
app = FastAPI(
    title="pydantic-deep Full Example",
    description="Full-featured example demonstrating all pydantic-deep capabilities",
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


# Routes
@app.get("/", response_class=HTMLResponse)
async def root():
    """Serve the main HTML page."""
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text())
    return HTMLResponse(content="<h1>Frontend not found. Check static/index.html</h1>")


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
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
       - {"type": "tool_start", "tool_name": "...", "args": {...}} - Tool called
       - {"type": "tool_output", "tool_name": "...", "output": "..."} - Tool result
       - {"type": "approval_required", "requests": [...]} - Human approval needed
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

    try:
        while True:
            # Wait for message from client
            data = await websocket.receive_text()
            message_data = json.loads(data)

            # Get session_id from message (required for first message, optional after)
            session_id = message_data.get("session_id")
            if session is None:
                if not session_id:
                    # Generate new session ID if not provided
                    session_id = str(uuid.uuid4())
                    await websocket.send_json({"type": "session_created", "session_id": session_id})
                session = await get_or_create_session(session_id)
                logger.info(f"WebSocket connected for session: {session_id}")

            user_message = message_data.get("message", "")
            approval_response = message_data.get("approval")  # For handling approvals

            # Handle approval response
            if approval_response is not None:
                await handle_approval(websocket, session, approval_response)
                continue

            if not user_message:
                await websocket.send_json({"type": "error", "content": "Empty message"})
                continue

            try:
                await run_agent_with_streaming(websocket, session, user_message)
            except Exception as e:
                logger.exception("Error in agent run")
                await websocket.send_json({"type": "error", "content": str(e)})

    except WebSocketDisconnect:
        if session:
            logger.info(f"WebSocket disconnected for session: {session.session_id}")
        # Note: We don't delete the session here - it can be reused


async def run_agent_with_streaming(
    websocket: WebSocket,
    session: UserSession,
    user_message: str,
    deferred_results: DeferredToolResults | None = None,
) -> None:
    """Run agent with streaming and handle DeferredToolRequests."""
    global agent

    logger.info(f"=== Starting agent run for session {session.session_id} ===")
    logger.info(f"User message: {user_message[:100] if user_message else '(continuation)'}")
    logger.info(f"Deferred results: {deferred_results is not None}")
    logger.info(f"Message history length: {len(session.message_history)}")

    # Send start event
    await websocket.send_json({"type": "start"})

    # Use iter() for streaming execution with session's message history
    assert agent is not None
    async with agent.iter(
        user_message if deferred_results is None else None,
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

    # Build approval results
    approvals: dict[str, ToolApproved] = {}
    for tool_call_id, approved in approval_response.items():
        if approved:
            approvals[tool_call_id] = ToolApproved()
        # If not approved, we just don't include it (will be denied)

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


async def _stream_model_request(websocket: WebSocket, node: Any, run: Any) -> None:
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
                await _handle_part_delta(websocket, event, current_tool_name)
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
                previous_text = cumulative_text


async def _handle_part_delta(
    websocket: WebSocket, event: PartDeltaEvent, current_tool_name: str | None
) -> None:
    """Handle streaming delta events."""
    if isinstance(event.delta, TextPartDelta):
        await websocket.send_json({"type": "text_delta", "content": event.delta.content_delta})
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

                # Send TODO update after write_todos or read_todos
                if tool_name in ("write_todos", "read_todos"):
                    await _send_todos_update(websocket, session)


async def _send_todos_update(websocket: WebSocket, session: UserSession) -> None:
    """Send current TODO list to frontend."""
    todos = [todo.model_dump() for todo in session.deps.todos]
    await websocket.send_json(
        {
            "type": "todos_update",
            "todos": todos,
        }
    )


async def process_node(
    websocket: WebSocket, node: Any, run: Any, session: UserSession
) -> None:
    """Process a node and send appropriate WebSocket events with streaming."""
    if isinstance(node, UserPromptNode):
        logger.debug("  -> UserPromptNode")
        await websocket.send_json({"type": "status", "content": "Processing user prompt..."})

    elif Agent.is_model_request_node(node):
        logger.debug("  -> ModelRequestNode: streaming tokens")
        await _stream_model_request(websocket, node, run)

    elif Agent.is_call_tools_node(node):
        logger.debug(f"  -> CallToolsNode with {len(node.model_response.parts)} parts")
        await _stream_tool_calls(websocket, node, run, session)

    elif isinstance(node, End):
        await websocket.send_json({"type": "status", "content": "Completed!"})


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),  # noqa: B008
    session_id: str = Query("", description="Session ID (optional, will create new if not provided)"),
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
            verify_result = session.deps.backend.execute(f"ls -la {path}")  # type: ignore[union-attr]
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
            raise HTTPException(status_code=500, detail="Backend does not support binary file reading")

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
            "todos": [todo.model_dump() for todo in session.deps.todos],
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)
