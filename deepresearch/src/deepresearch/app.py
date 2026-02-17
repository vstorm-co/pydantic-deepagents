"""DeepResearch — full-featured autonomous research agent with web search via MCP.

Features:
- MCP tools for web search (Tavily, Brave) and URL reading (Jina)
- Research-specific system prompt with TODO-based planning
- Shell execution (sandboxed in Docker) with human-in-the-loop approval
- Subagents (code-reviewer, general-purpose, dynamic agent factory)
- Plan mode (ask_user question flow)
- Skills (research-methodology, report-writing, quick-reference)
- Hooks (audit logger, safety gate)
- Middleware (AuditMiddleware, PermissionMiddleware)
- Image support (multimodal attachments)
- Docker sandbox per user for file operations
- WebSocket streaming for real-time updates
- Checkpointing (rewind/fork)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from fastapi import (  # noqa: E402
    FastAPI,
    File,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic_ai import (  # noqa: E402
    BinaryContent,
    FinalResultEvent,
    PartDeltaEvent,
    PartStartEvent,
    TextPartDelta,
    ThinkingPartDelta,
    ToolCallPartDelta,
)
from pydantic_ai._agent_graph import End, UserPromptNode  # noqa: E402
from pydantic_ai.agent import Agent  # noqa: E402
from pydantic_ai.messages import (  # noqa: E402
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
from pydantic_ai.tools import (  # noqa: E402
    DeferredToolRequests,
    DeferredToolResults,
    ToolApproved,
    ToolDenied,
)
from pydantic_ai.toolsets import AbstractToolset  # noqa: E402

from pydantic_deep import (  # noqa: E402
    DeepAgentDeps,
    InMemoryCheckpointStore,
    RewindRequested,
    SessionManager,
    fork_from_checkpoint,
)

from .agent import create_research_agent  # noqa: E402
from .config import (  # noqa: E402
    APP_DIR,
    EXCALIDRAW_CANVAS_URL,
    SKILLS_DIR,
    STATIC_DIR,
    WORKSPACE_DIR,
    WORKSPACES_DIR,
    create_mcp_servers,
)
from .middleware import AuditMiddleware, PermissionMiddleware  # noqa: E402

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

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

# Create directories
WORKSPACE_DIR.mkdir(exist_ok=True)
WORKSPACES_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Attachment helpers
# ---------------------------------------------------------------------------

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

_PREVIEW_LINES = 15
_PREVIEW_CHARS = 800

_CONTENT_TYPES: dict[str, str] = {
    "html": "text/html",
    "htm": "text/html",
    "css": "text/css",
    "js": "application/javascript",
    "json": "application/json",
    "svg": "image/svg+xml",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "pdf": "application/pdf",
}


def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if n != int(n) else f"{n} {unit}"
        n /= 1024  # type: ignore[assignment]
    return f"{n:.1f} TB"


def _build_file_summary(name: str, path: str, data: bytes, media_type: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    size = len(data)
    summary = f"- **{name}** ({_fmt_size(size)}) — path: `{path}`"

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

        preview_lines = lines[:_PREVIEW_LINES]
        preview = "\n".join(preview_lines)
        if len(preview) > _PREVIEW_CHARS:
            preview = preview[:_PREVIEW_CHARS] + "..."
        truncated = line_count > _PREVIEW_LINES or len(preview) >= _PREVIEW_CHARS

        summary += f"\n  ```\n{preview}\n  ```"
        if truncated:
            remaining = line_count - _PREVIEW_LINES
            summary += (
                f"\n  *(preview — {remaining} more lines,"
                f' use `read_file("{path}")` for full content)*'
            )
    else:
        summary += f" — binary ({media_type}), use `read_file` to inspect"

    return summary


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

audit_mw = AuditMiddleware()
permission_mw = PermissionMiddleware()


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
    # Background task push notification tracking
    _notified_tasks: set[str] = field(default_factory=set)
    _injected_tasks: set[str] = field(default_factory=set)


# ---------------------------------------------------------------------------
# JSONL Event Persistence
# ---------------------------------------------------------------------------


def _log_event(session: UserSession | None, event: dict[str, Any]) -> None:
    """Append a WebSocket event to the session's JSONL event log."""
    if session is None:
        return
    events_dir = WORKSPACES_DIR / session.session_id
    events_dir.mkdir(parents=True, exist_ok=True)
    events_file = events_dir / "events.jsonl"
    event_with_ts = {**event, "_ts": datetime.now(timezone.utc).isoformat()}
    try:
        with open(events_file, "a") as f:
            f.write(json.dumps(event_with_ts, default=str) + "\n")
    except Exception:
        pass


def _save_session_meta(session: UserSession, title: str | None = None) -> None:
    """Write or update session metadata to meta.json."""
    meta_dir = WORKSPACES_DIR / session.session_id
    meta_dir.mkdir(parents=True, exist_ok=True)
    meta_file = meta_dir / "meta.json"
    now = datetime.now(timezone.utc).isoformat()

    if meta_file.exists():
        try:
            existing = json.loads(meta_file.read_text())
        except Exception:
            existing = {}
        existing["updated_at"] = now
        existing["message_count"] = len(session.message_history)
        if title:
            existing["title"] = title
        meta_file.write_text(json.dumps(existing))
    else:
        meta = {
            "session_id": session.session_id,
            "created_at": now,
            "updated_at": now,
            "title": title or "New Session",
            "message_count": len(session.message_history),
        }
        meta_file.write_text(json.dumps(meta))


def _persist_history(session: UserSession) -> None:
    """Serialize message_history to disk for agent continuity on reload."""
    from pydantic import TypeAdapter

    history_dir = WORKSPACES_DIR / session.session_id
    history_dir.mkdir(parents=True, exist_ok=True)
    history_file = history_dir / "history.json"
    try:
        ta = TypeAdapter(list[ModelMessage])
        history_file.write_bytes(ta.dump_json(session.message_history))
    except Exception as e:
        logger.warning(f"Failed to persist history: {e}")


def _restore_history(session_id: str) -> list[ModelMessage] | None:
    """Restore message_history from disk if available."""
    from pydantic import TypeAdapter

    history_file = WORKSPACES_DIR / session_id / "history.json"
    if not history_file.exists():
        return None
    try:
        ta = TypeAdapter(list[ModelMessage])
        return ta.validate_json(history_file.read_bytes())
    except Exception as e:
        logger.warning(f"Failed to restore history for {session_id}: {e}")
        return None


def _extract_title(user_prompt: str | list[Any]) -> str:
    """Extract a session title from the first user message."""
    if isinstance(user_prompt, str):
        text = user_prompt
    elif isinstance(user_prompt, list):
        text = next((p for p in user_prompt if isinstance(p, str)), "")
    else:
        text = str(user_prompt)
    text = text.strip().split("\n")[0]
    return text[:60] if text else "New Session"


def _get_task_manager() -> Any | None:
    """Find the TaskManager from the agent's subagent toolset."""
    if agent is None:
        return None
    for ts in agent.toolsets:
        tm = getattr(ts, "task_manager", None)
        if tm is not None:
            return tm
    return None


async def _monitor_background_tasks(websocket: WebSocket, session: UserSession) -> None:
    """Poll TaskManager for newly completed/failed tasks and push notifications via WebSocket."""
    from subagents_pydantic_ai.types import TaskStatus

    task_manager = _get_task_manager()
    if task_manager is None:
        return

    try:
        while True:
            await asyncio.sleep(1)
            for task_id, handle in list(task_manager.handles.items()):
                if task_id in session._notified_tasks:
                    continue
                if handle.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                    session._notified_tasks.add(task_id)
                    duration = None
                    if handle.started_at and handle.completed_at:
                        duration = (handle.completed_at - handle.started_at).total_seconds()
                    result_preview = None
                    if handle.result:
                        result_preview = handle.result[:2000]
                    try:
                        await websocket.send_json(
                            {
                                "type": "background_task_completed",
                                "task_id": task_id,
                                "subagent_name": handle.subagent_name,
                                "status": handle.status.value,
                                "description": handle.description,
                                "result_preview": result_preview,
                                "error": handle.error,
                                "duration_seconds": duration,
                            }
                        )
                    except Exception:
                        return  # WebSocket closed
    except asyncio.CancelledError:
        return


def _collect_completed_task_results(session: UserSession) -> str | None:
    """Collect results from completed background tasks that haven't been injected yet."""
    from subagents_pydantic_ai.types import TaskStatus

    task_manager = _get_task_manager()
    if task_manager is None:
        return None

    parts: list[str] = []
    for task_id, handle in list(task_manager.handles.items()):
        if task_id in session._injected_tasks:
            continue
        if handle.status == TaskStatus.COMPLETED and handle.result:
            session._injected_tasks.add(task_id)
            duration = ""
            if handle.started_at and handle.completed_at:
                secs = (handle.completed_at - handle.started_at).total_seconds()
                duration = f" ({secs:.1f}s)"
            parts.append(
                f"- **{handle.subagent_name}**{duration}: {handle.description}\n"
                f"  Result: {handle.result[:1000]}"
            )
        elif handle.status == TaskStatus.FAILED and handle.error:
            session._injected_tasks.add(task_id)
            parts.append(
                f"- **{handle.subagent_name}** (FAILED): {handle.description}\n"
                f"  Error: {handle.error[:500]}"
            )

    if not parts:
        return None

    return (
        "**Note**: The following background tasks have completed since your last message:\n\n"
        + "\n".join(parts)
    )


def create_ask_user_callback(websocket: WebSocket, session: UserSession) -> Any:
    """Create an ask_user callback that sends questions via WebSocket.

    When the planner subagent calls ask_user(), this callback:
    1. Sends the question + options to the frontend via WebSocket
    2. Waits for the user's response (via asyncio.Future)
    3. Returns the answer to the agent
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

        answer = await future
        logger.info(f"ASK_USER answer: {answer}")
        return answer

    return callback


# Global state
agent: Agent[DeepAgentDeps, str] | None = None
session_manager: SessionManager | None = None
user_sessions: dict[str, UserSession] = {}

# ---------------------------------------------------------------------------
# Context file
# ---------------------------------------------------------------------------

_DEEP_MD_PATH = APP_DIR / "workspace" / "DEEP.md"
_MEMORY_MD_PATH = APP_DIR / "workspace" / "MEMORY.md"


# ---------------------------------------------------------------------------
# Excalidraw canvas isolation — save/restore per session
# ---------------------------------------------------------------------------

_current_canvas_session: str | None = None


async def _save_canvas(session_id: str) -> None:
    """Save current canvas elements to disk for the given session."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{EXCALIDRAW_CANVAS_URL}/api/elements")
            if resp.status_code == 200:
                data = resp.json()
                elements = data.get("elements", [])
                canvas_file = WORKSPACES_DIR / session_id / "canvas.json"
                canvas_file.parent.mkdir(parents=True, exist_ok=True)
                canvas_file.write_text(json.dumps(elements))
                logger.info(f"Canvas SAVE: {len(elements)} elements for session {session_id}")
            else:
                logger.warning(f"Canvas SAVE failed: GET /api/elements returned {resp.status_code}")
    except Exception as e:
        logger.warning(f"Canvas SAVE error for session {session_id}: {e}")


async def _load_canvas(session_id: str) -> None:
    """Clear canvas and load saved elements for the given session."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            # Clear canvas
            clear_resp = await client.delete(f"{EXCALIDRAW_CANVAS_URL}/api/elements/clear")
            logger.info(f"Canvas CLEAR: status={clear_resp.status_code}")

            # Load saved elements
            canvas_file = WORKSPACES_DIR / session_id / "canvas.json"
            if canvas_file.exists():
                elements = json.loads(canvas_file.read_text())
                if elements:
                    load_resp = await client.post(
                        f"{EXCALIDRAW_CANVAS_URL}/api/elements/batch",
                        json={"elements": elements},
                    )
                    logger.info(
                        f"Canvas LOAD: {len(elements)} elements for session {session_id} "
                        f"(status={load_resp.status_code})"
                    )
                else:
                    logger.info(f"Canvas LOAD: no elements saved for session {session_id}")
            else:
                logger.info(f"Canvas LOAD: no canvas.json for session {session_id} (fresh session)")
    except Exception as e:
        logger.warning(f"Canvas LOAD error for session {session_id}: {e}")


async def _switch_canvas_session(session_id: str) -> None:
    """Switch canvas to a different session (save old, load new)."""
    global _current_canvas_session
    logger.info(f"Canvas SWITCH: {_current_canvas_session!r} -> {session_id!r}")
    if _current_canvas_session == session_id:
        logger.info("Canvas SWITCH: same session, skipping")
        return
    if _current_canvas_session is not None:
        await _save_canvas(_current_canvas_session)
    await _load_canvas(session_id)
    _current_canvas_session = session_id
    logger.info(f"Canvas SWITCH: done, now on session {session_id}")


async def get_or_create_session(session_id: str) -> UserSession:
    """Get existing session or create a new one with isolated Docker container."""
    global session_manager, user_sessions

    if session_id in user_sessions:
        return user_sessions[session_id]

    assert session_manager is not None
    sandbox = await session_manager.get_or_create(session_id)

    # Seed workspace with context files
    if _DEEP_MD_PATH.exists():
        sandbox.write("/workspace/DEEP.md", _DEEP_MD_PATH.read_text())
    if _MEMORY_MD_PATH.exists():
        sandbox.write("/workspace/MEMORY.md", _MEMORY_MD_PATH.read_text())

    cp_store = InMemoryCheckpointStore()
    deps = DeepAgentDeps(backend=sandbox, checkpoint_store=cp_store)

    session = UserSession(session_id=session_id, deps=deps, checkpoint_store=cp_store)

    # Restore message history from disk if available
    restored = _restore_history(session_id)
    if restored:
        session.message_history = restored
        logger.info(f"Restored {len(restored)} messages for session {session_id}")

    # Restore todos from meta if available
    meta_file = WORKSPACES_DIR / session_id / "meta.json"
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text())
            session.latest_todos = meta.get("todos", [])
        except Exception:
            pass

    user_sessions[session_id] = session

    logger.info(f"Created new session: {session_id}")
    return session


def _get_failed_server_names(
    exc: BaseException,
    servers: list[AbstractToolset],
) -> set[str]:
    """Extract MCP server prefixes that likely caused a startup failure.

    When we can't pinpoint the exact server, return all prefixes so the
    retry removes every MCP server (the app still works without them).
    """
    all_names = {getattr(s, "tool_prefix", "") for s in servers} - {""}
    # If only one MCP server, it's obviously the culprit
    if len(all_names) == 1:
        return all_names
    # For ExceptionGroup, check if error mentions docker/excalidraw
    msg = str(exc).lower()
    matched: set[str] = set()
    for name in all_names:
        if name.lower() in msg:
            matched.add(name)
    if "docker" in msg or "stdio" in msg or "broken" in msg:
        # Likely the Docker-based Excalidraw server
        for s in servers:
            if getattr(s, "tool_prefix", "") == "excalidraw":
                matched.add("excalidraw")
    return matched or all_names


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize agent with MCP servers and session manager."""
    global agent, session_manager

    mcp_servers = create_mcp_servers()
    agent = create_research_agent(mcp_servers=mcp_servers, middleware=[audit_mw, permission_mw])

    session_manager = SessionManager(
        default_runtime="python-datascience",
        default_idle_timeout=3600,
        workspace_root=WORKSPACES_DIR,
    )
    session_manager.start_cleanup_loop(interval=300)

    def _print_banner(servers: list) -> None:
        names = [getattr(s, "tool_prefix", "unknown") for s in servers]
        print("=" * 60)
        print("DeepResearch — Full-Featured Research Agent")
        print("=" * 60)
        print(f"  MCP servers    : {', '.join(names) or 'none'}")
        print(f"  Skills         : {SKILLS_DIR}")
        print(f"  Workspaces     : {WORKSPACES_DIR}")
        print("  Runtime        : python-datascience")
        print("  Hooks          : audit_logger, safety_gate")
        print("  Middleware     : AuditMiddleware, PermissionMiddleware")
        print("  Subagents      : code-reviewer, general-purpose + dynamic factory")
        print("  Execute        : enabled (human-in-the-loop)")
        print("  Image support  : enabled")
        print("  Plan mode      : enabled (ask_user)")
        print("=" * 60)

    _print_banner(mcp_servers)

    # Start MCP server connections — retry without failing servers
    try:
        async with agent:
            yield
    except Exception as exc:
        failed = _get_failed_server_names(exc, mcp_servers)
        logger.warning(
            "MCP server startup failed (%s) — retrying without them",
            ", ".join(failed) or "unknown",
        )
        # Rebuild agent without problematic MCP servers
        remaining = [s for s in mcp_servers if getattr(s, "tool_prefix", "") not in failed]
        agent = create_research_agent(mcp_servers=remaining, middleware=[audit_mw, permission_mw])
        _print_banner(remaining)
        async with agent:
            yield

    # Shutdown
    count = await session_manager.shutdown()
    print(f"Shutdown complete. Stopped {count} sessions.")


app = FastAPI(title="DeepResearch", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    html_path = STATIC_DIR / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text())
    return HTMLResponse(content="<h1>Frontend not found. Check static/index.html</h1>")


# ---------------------------------------------------------------------------
# WebSocket chat
# ---------------------------------------------------------------------------


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):  # noqa: C901
    """WebSocket endpoint for streaming chat with the research agent."""
    global agent

    await websocket.accept()

    if agent is None:
        await websocket.send_json({"type": "error", "content": "Agent not initialized"})
        return

    session: UserSession | None = None
    incoming: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    monitor_task: asyncio.Task[None] | None = None

    async def _reader() -> None:
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

            # Session management
            session_id = message_data.get("session_id")
            if session is None:
                if not session_id:
                    session_id = str(uuid.uuid4())
                    await websocket.send_json({"type": "session_created", "session_id": session_id})
                session = await get_or_create_session(session_id)

                # Monkey-patch send_json to also log events to JSONL
                _original_send = websocket.send_json

                async def _logging_send(
                    data: Any,
                    _send: Any = _original_send,
                    _sess: Any = session,
                    **kwargs: Any,
                ) -> None:
                    await _send(data, **kwargs)
                    _log_event(_sess, data)

                websocket.send_json = _logging_send  # type: ignore[assignment]

                # Log session_created event
                _log_event(session, {"type": "session_created", "session_id": session_id})

                # Set up ask_user callback so planner subagent can ask questions
                session.deps.ask_user = create_ask_user_callback(websocket, session)
                # Start background task monitor for push notifications
                monitor_task = asyncio.create_task(_monitor_background_tasks(websocket, session))
                # Switch Excalidraw canvas to this session
                await _switch_canvas_session(session_id)
                # Tell the frontend canvas is ready (iframe can safely load now)
                await websocket.send_json({"type": "canvas_ready", "session_id": session_id})
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
                    # Cancel any pending ask_user futures so the agent unblocks
                    for _qid, fut in list(session.pending_questions.items()):
                        if not fut.done():
                            fut.cancel()
                    session.pending_questions.clear()
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
                continue

            # Log incoming user message
            _log_event(session, {"type": "user_message", "content": user_message})

            # Set session title from first user message
            meta_file = WORKSPACES_DIR / session.session_id / "meta.json"
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text())
                    if meta.get("title") == "New Session" and user_message:
                        _save_session_meta(session, title=_extract_title(user_message))
                except Exception:
                    pass
            else:
                _save_session_meta(
                    session, title=_extract_title(user_message) if user_message else None
                )

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
                        prompt_parts.append(BinaryContent(data=data, media_type=media_type))
                        file_summaries.append(
                            f"- **{name}** (image, {_fmt_size(len(data))})"
                            f" — path: `{upload_path}` — sent inline for visual analysis"
                        )
                    else:
                        file_summaries.append(
                            _build_file_summary(name, upload_path, data, media_type)
                        )

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
        if monitor_task is not None:
            monitor_task.cancel()
        if session and session.running_task and not session.running_task.done():
            session.running_task.cancel()
        if session:
            # Save canvas state on disconnect
            await _save_canvas(session.session_id)
            logger.info(f"WebSocket disconnected for session: {session.session_id}")


def _save_partial_history(session: UserSession) -> None:
    """Save user message + partial agent response to history on cancel."""
    user_msg = getattr(session, "_current_user_message", None)
    streamed = getattr(session, "_streamed_text", "")

    if not user_msg:
        return

    session.message_history.append(ModelRequest(parts=[UserPromptPart(content=user_msg)]))

    if streamed:
        session.message_history.append(
            ModelResponse(parts=[TextPart(content=streamed + "\n\n[Response interrupted]")])
        )

    logger.info(
        f"Saved partial history: user_msg={user_msg[:60]!r}, "
        f"streamed={len(streamed)} chars, "
        f"history now {len(session.message_history)} messages"
    )

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
        _save_partial_history(session)
        _persist_history(session)
        _save_session_meta(session)
        raise
    except RewindRequested as rw:
        logger.info(f"Rewind requested to checkpoint '{rw.label}' ({rw.checkpoint_id})")
        session.message_history = rw.messages
        _persist_history(session)
        _save_session_meta(session)
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

    await websocket.send_json({"type": "start"})

    # Track streamed text for cancel recovery
    session._streamed_text = ""  # type: ignore[attr-defined]
    cancel_text = (
        user_prompt
        if isinstance(user_prompt, str)
        else " ".join(p for p in user_prompt if isinstance(p, str))
    )
    session._current_user_message = cancel_text  # type: ignore[attr-defined]

    # Prepend completed background task results to user prompt (Step 5)
    if deferred_results is None and user_prompt:
        task_results_note = _collect_completed_task_results(session)
        if task_results_note:
            if isinstance(user_prompt, str):
                user_prompt = f"{task_results_note}\n\n---\n\n{user_prompt}"
            elif isinstance(user_prompt, list):
                # Prepend to first text part
                for i, part in enumerate(user_prompt):
                    if isinstance(part, str):
                        user_prompt[i] = f"{task_results_note}\n\n---\n\n{part}"
                        break

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

        result = run.result
        logger.info(f"Agent finished after {node_count} nodes")

        # Emit latest checkpoint
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
        session.pending_approval_state = {
            "message_history": result.all_messages(),
            "approvals": result.output.approvals,
        }

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

    # Update session's message history
    session.message_history = result.all_messages()
    logger.info(f"Updated message history to {len(session.message_history)} messages")

    # Persist to disk
    _persist_history(session)
    _save_session_meta(session)

    await websocket.send_json({"type": "response", "content": str(result.output)})
    await websocket.send_json({"type": "done"})
    logger.info("=== Agent run complete ===")


async def handle_approval(
    websocket: WebSocket, session: UserSession, approval_response: dict
) -> None:
    """Handle approval response from frontend and continue agent."""
    if not session.pending_approval_state:
        await websocket.send_json({"type": "error", "content": "No pending approval"})
        return

    approvals: dict[str, ToolApproved | ToolDenied] = {}
    for tool_call_id, approved in approval_response.items():
        if approved:
            approvals[tool_call_id] = ToolApproved()
        else:
            approvals[tool_call_id] = ToolDenied("User denied this tool call.")

    session.message_history = session.pending_approval_state["message_history"]
    session.pending_approval_state = {}

    try:
        await run_agent_with_streaming(
            websocket,
            session,
            "",
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
    await websocket.send_json({"type": "status", "content": "Researching..."})

    current_tool_name: str | None = None

    async with node.stream(run.ctx) as request_stream:
        final_result_found = False

        async for event in request_stream:
            if isinstance(event, PartStartEvent):
                if hasattr(event.part, "tool_name"):
                    current_tool_name = event.part.tool_name
                    current_tool_call_id = getattr(event.part, "tool_call_id", None)
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
                final_result_found = True
                break

        if final_result_found:
            previous_text = ""
            async for cumulative_text in request_stream.stream_text():
                delta = cumulative_text[len(previous_text) :]
                if delta:
                    await websocket.send_json({"type": "text_delta", "content": delta})
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
        session._streamed_text += event.delta.content_delta  # type: ignore[attr-defined]
    elif isinstance(event.delta, ThinkingPartDelta):
        await websocket.send_json({"type": "thinking_delta", "content": event.delta.content_delta})
    elif isinstance(event.delta, ToolCallPartDelta):
        await websocket.send_json(
            {
                "type": "tool_args_delta",
                "tool_name": current_tool_name,
                "args_delta": event.delta.args_delta,
            }
        )


async def _emit_todos_update(websocket: WebSocket, session: UserSession) -> None:
    """Emit todos_update WS event and persist to session meta."""
    todos_data = session.latest_todos
    await websocket.send_json({"type": "todos_update", "todos": todos_data})
    # Persist in session meta
    meta_dir = WORKSPACES_DIR / session.session_id
    meta_file = meta_dir / "meta.json"
    if meta_file.exists():
        try:
            meta = json.loads(meta_file.read_text())
            meta["todos"] = todos_data
            meta_file.write_text(json.dumps(meta))
        except Exception:
            pass


async def _stream_tool_calls(  # noqa: C901
    websocket: WebSocket, node: Any, run: Any, session: UserSession
) -> None:
    """Stream tool call events from a CallToolsNode."""
    tool_names_by_id: dict[str, str] = {}
    tool_args_by_id: dict[str, Any] = {}

    async with node.stream(run.ctx) as handle_stream:
        async for event in handle_stream:
            if isinstance(event, FunctionToolCallEvent):
                tool_name = event.part.tool_name
                tool_args = event.part.args
                tool_call_id = event.part.tool_call_id

                logger.info(f"  TOOL CALL: {tool_name}")

                if tool_call_id:
                    tool_names_by_id[tool_call_id] = tool_name
                    tool_args_by_id[tool_call_id] = tool_args

                await websocket.send_json(
                    {
                        "type": "tool_start",
                        "tool_name": tool_name,
                        "args": tool_args if isinstance(tool_args, dict) else str(tool_args),
                    }
                )

                # Send status update for long-running subagent tasks
                if tool_name == "task":
                    try:
                        args_dict = (
                            tool_args if isinstance(tool_args, dict) else json.loads(tool_args)
                        )
                        sa_type = args_dict.get("subagent_type", "general-purpose")
                        await websocket.send_json(
                            {"type": "status", "content": f"Running {sa_type} subagent..."}
                        )
                    except Exception:
                        pass

                # Live TODO updates (write_todos has full list in args)
                if tool_name == "write_todos":
                    try:
                        args_dict = (
                            tool_args if isinstance(tool_args, dict) else json.loads(tool_args)
                        )
                        todos_data = args_dict.get("todos", [])
                        session.latest_todos = todos_data
                        await _emit_todos_update(websocket, session)
                    except Exception:
                        pass

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

                # Live audit stats
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

                # Report file detection — auto-open preview
                if tool_name == "write_file":
                    try:
                        call_args = tool_args_by_id.get(tool_call_id, {})
                        if isinstance(call_args, str):
                            call_args = json.loads(call_args)
                        written_path = call_args.get("path", "")
                        if "report" in written_path.lower():
                            await websocket.send_json(
                                {"type": "report_updated", "path": written_path}
                            )
                    except Exception:
                        pass

                # Live TODO updates for incremental tools
                # (write_todos is handled at call time above; these need
                #  the result to confirm success before updating UI)
                result_str = str(result_content)
                if tool_name == "update_todo_status" and "not found" not in result_str:
                    try:
                        call_args = tool_args_by_id.get(tool_call_id, {})
                        if isinstance(call_args, str):
                            call_args = json.loads(call_args)
                        tid = call_args.get("todo_id", "")
                        new_status = call_args.get("status", "")
                        for todo in session.latest_todos:
                            if todo.get("id") == tid:
                                todo["status"] = new_status
                                break
                        await _emit_todos_update(websocket, session)
                    except Exception:
                        pass

                elif tool_name == "add_todo":
                    try:
                        # Extract ID from result: "Added todo '...' with ID: abc12345"
                        id_match = re.search(r"with ID:\s*(\w+)", result_str)
                        if id_match:
                            call_args = tool_args_by_id.get(tool_call_id, {})
                            if isinstance(call_args, str):
                                call_args = json.loads(call_args)
                            session.latest_todos.append(
                                {
                                    "id": id_match.group(1),
                                    "content": call_args.get("content", ""),
                                    "active_form": call_args.get("active_form", ""),
                                    "status": "pending",
                                }
                            )
                            await _emit_todos_update(websocket, session)
                    except Exception:
                        pass

                elif tool_name == "remove_todo" and "not found" not in result_str:
                    try:
                        call_args = tool_args_by_id.get(tool_call_id, {})
                        if isinstance(call_args, str):
                            call_args = json.loads(call_args)
                        tid = call_args.get("todo_id", "")
                        session.latest_todos = [
                            t for t in session.latest_todos if t.get("id") != tid
                        ]
                        await _emit_todos_update(websocket, session)
                    except Exception:
                        pass


async def process_node(websocket: WebSocket, node: Any, run: Any, session: UserSession) -> None:
    """Process a node and send appropriate WebSocket events."""
    if isinstance(node, UserPromptNode):
        await websocket.send_json({"type": "status", "content": "Processing..."})
    elif Agent.is_model_request_node(node):
        await _stream_model_request(websocket, node, run, session)
    elif Agent.is_call_tools_node(node):
        await _stream_tool_calls(websocket, node, run, session)
    elif isinstance(node, End):
        await websocket.send_json({"type": "status", "content": "Completed!"})


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------


@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),  # noqa: B008
    session_id: str = Query("", description="Session ID"),
):
    """Upload a file to a session's workspace."""
    try:
        if not session_id:
            session_id = str(uuid.uuid4())

        session = await get_or_create_session(session_id)
        content = await file.read()
        filename = file.filename or "uploaded_file"

        logger.info(f"Uploading file: {filename} ({len(content)} bytes) to session {session_id}")

        path = session.deps.upload_file(filename, content)
        logger.info(f"File uploaded to: {path}")

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
    """List files in workspace and uploads."""
    if session_id not in user_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = user_sessions[session_id]
    files: dict[str, list[str]] = {"workspace": [], "uploads": []}

    # Use 'find' via execute — ls_info has path quoting issues with DockerSandbox
    if hasattr(session.deps.backend, "execute"):
        for key, path in [("workspace", "/workspace"), ("uploads", "/uploads")]:
            try:
                result = session.deps.backend.execute(f"find {path} -type f 2>/dev/null")
                if result.exit_code == 0:
                    files[key] = [f for f in result.output.strip().split("\n") if f]
            except Exception:
                pass

    return JSONResponse(content=files)


@app.get("/files/content/{filepath:path}")
async def get_file_content(filepath: str, session_id: str = Query(..., description="Session ID")):
    """Get file content for preview."""
    if session_id not in user_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = user_sessions[session_id]

    import urllib.parse

    decoded_path = urllib.parse.unquote(filepath)
    if not decoded_path.startswith("/"):
        decoded_path = "/" + decoded_path

    try:
        result = session.deps.backend.read(decoded_path)
        if "Error:" in result and len(result) < 200:
            raise HTTPException(status_code=404, detail=f"File not found: {decoded_path}")
        return JSONResponse(content={"content": result, "path": decoded_path})
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/files/binary/{filepath:path}")
async def get_file_binary(filepath: str, session_id: str = Query(..., description="Session ID")):
    """Get binary file content (images, etc.)."""
    from fastapi.responses import Response

    if session_id not in user_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = user_sessions[session_id]

    import urllib.parse

    decoded_path = urllib.parse.unquote(filepath)
    if not decoded_path.startswith("/"):
        decoded_path = "/" + decoded_path

    ext = decoded_path.split(".")[-1].lower()
    content_type = _CONTENT_TYPES.get(ext, "application/octet-stream")

    try:
        result = session.deps.backend.read(decoded_path)
        if isinstance(result, bytes):
            return Response(content=result, media_type=content_type)
        return Response(content=result.encode("utf-8"), media_type=content_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/todos")
async def get_todos(session_id: str = Query(..., description="Session ID")):
    """Get current todo list."""
    if session_id not in user_sessions:
        raise HTTPException(status_code=404, detail="Session not found")
    return JSONResponse(content={"todos": user_sessions[session_id].latest_todos})


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

    new_session_id = str(uuid.uuid4())
    new_session = await get_or_create_session(new_session_id)
    new_session.message_history = messages

    return JSONResponse(
        content={
            "new_session_id": new_session_id,
            "message_count": len(messages),
        }
    )


@app.get("/history")
async def get_history(session_id: str = Query(..., description="Session ID")):
    """Return conversation history for a session."""
    if session_id not in user_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = user_sessions[session_id]
    rendered: list[dict[str, Any]] = []

    # Build a map of tool_call_id → tool_name for matching returns to calls
    tool_name_by_id: dict[str, str] = {}

    for msg in session.message_history:
        if isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, ToolCallPart):
                    tool_name_by_id[part.tool_call_id] = part.tool_name

    for msg in session.message_history:
        if isinstance(msg, ModelRequest):
            for part in msg.parts:
                if isinstance(part, UserPromptPart):
                    content = (
                        part.content if isinstance(part.content, str) else "(multimodal input)"
                    )
                    rendered.append({"role": "user", "content": content})
                elif isinstance(part, ToolReturnPart):
                    rendered.append(
                        {
                            "role": "tool_return",
                            "tool_name": tool_name_by_id.get(part.tool_call_id, ""),
                            "output": part.content
                            if isinstance(part.content, str)
                            else json.dumps(part.content or ""),
                        }
                    )
        elif isinstance(msg, ModelResponse):
            # Render tool calls FIRST, then text (matches streaming order)
            tool_calls = [
                {
                    "tool_name": p.tool_name,
                    "args": p.args if isinstance(p.args, str) else json.dumps(p.args or {}),
                }
                for p in msg.parts
                if isinstance(p, ToolCallPart)
            ]
            for tc in tool_calls:
                rendered.append(
                    {"role": "tool_call", "tool_name": tc["tool_name"], "args": tc["args"]}
                )
            text_parts = [p.content for p in msg.parts if isinstance(p, TextPart) and p.content]
            if text_parts:
                rendered.append({"role": "assistant", "content": "\n\n".join(text_parts)})

    return JSONResponse(content={"messages": rendered})


@app.get("/config")
async def get_config():
    """Return current agent configuration."""
    mcp_names = []
    if agent:
        for ts in agent.toolsets:
            prefix = getattr(ts, "tool_prefix", None)
            if prefix:
                mcp_names.append(prefix)

    return JSONResponse(
        content={
            "features": {
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
                "mcp_servers": mcp_names,
                "processors": {
                    "eviction": {
                        "token_limit": 20000,
                        "description": "Large outputs -> file reference",
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
                    "description": (
                        "Auto-saves after every model turn,"
                        " rewind/fork via Timeline tab"
                    ),
                },
                "context_files": ["/workspace/DEEP.md", "/workspace/MEMORY.md"],
                "image_support": True,
                "subagents": [
                    "code-reviewer",
                    "general-purpose",
                    "planner (plan mode)",
                    "dynamic (via agent factory)",
                ],
                "skills": ["research-methodology", "report-writing", "quick-reference"],
                "interrupt_on": {"execute": True, "write_file": False},
                "excalidraw_enabled": os.getenv("EXCALIDRAW_ENABLED", "1") == "1",
                "excalidraw_canvas_url": EXCALIDRAW_CANVAS_URL,
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

    if session_manager:
        await session_manager.release(session_id)

    del user_sessions[session_id]
    audit_mw.reset_stats()

    return JSONResponse(content={"status": "reset complete", "session_id": session_id})


@app.post("/session/new")
async def create_new_session():
    """Create a new session."""
    session_id = str(uuid.uuid4())
    session = await get_or_create_session(session_id)
    return JSONResponse(content={"session_id": session.session_id, "status": "created"})


@app.get("/sessions")
async def list_sessions():
    """List all persisted sessions, sorted by most recent."""
    sessions_list = []
    if WORKSPACES_DIR.exists():
        for d in WORKSPACES_DIR.iterdir():
            if not d.is_dir():
                continue
            meta_file = d / "meta.json"
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text())
                    sessions_list.append(meta)
                except Exception:
                    pass

    sessions_list.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
    return JSONResponse(content={"sessions": sessions_list})


@app.get("/sessions/{session_id}/events")
async def get_session_events(session_id: str):
    """Return all logged WebSocket events for replay."""
    events_file = WORKSPACES_DIR / session_id / "events.jsonl"
    if not events_file.exists():
        raise HTTPException(status_code=404, detail="No events found for this session")

    events = []
    try:
        with open(events_file) as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read events: {e}") from e

    return JSONResponse(content={"events": events})


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session and its data."""
    global session_manager, user_sessions

    # Release container if active
    if session_id in user_sessions:
        if session_manager:
            await session_manager.release(session_id)
        del user_sessions[session_id]

    # Remove files
    session_dir = WORKSPACES_DIR / session_id
    if session_dir.exists():
        shutil.rmtree(session_dir)
        return JSONResponse(content={"status": "deleted", "session_id": session_id})

    raise HTTPException(status_code=404, detail="Session not found")


@app.get("/health")
async def health():
    return {"status": "ok", "agent_ready": agent is not None, "session_count": len(user_sessions)}


# ---------------------------------------------------------------------------
# Export endpoint (Markdown, HTML, PDF)
# ---------------------------------------------------------------------------


@app.get("/export/{fmt}")
async def export_report(
    fmt: str,
    session_id: str = Query(..., description="Session ID"),
    filepath: str = Query("/workspace/report.md", description="Report file path"),
):
    """Export a report file in various formats (md, html, pdf)."""
    from fastapi.responses import Response

    if session_id not in user_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = user_sessions[session_id]

    # Read and strip line numbers from backend
    try:
        raw = session.deps.backend.read(filepath)
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        content = "\n".join(
            line.split("\t", 1)[1]
            if "\t" in line and line.split("\t")[0].strip().isdigit()
            else line
            for line in raw.split("\n")
        )
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Report not found: {e}") from e

    if fmt in ("md", "markdown"):
        return Response(
            content=content,
            media_type="text/markdown",
            headers={"Content-Disposition": "attachment; filename=report.md"},
        )

    def _md_to_html(md_content: str) -> str:
        import markdown as md_lib

        _css = (
            "body{font-family:system-ui;max-width:800px;margin:2rem auto;padding:0 1rem;"
            "line-height:1.6;}table{border-collapse:collapse;width:100%;}th,td{border:1px solid "
            "#ddd;padding:8px;}pre{background:#f5f5f5;padding:1rem;overflow-x:auto;border-radius:"
            "4px;}code{background:#f5f5f5;padding:2px 4px;border-radius:3px;}"
        )
        body = md_lib.markdown(md_content, extensions=["tables", "fenced_code"])
        return (
            f"<!DOCTYPE html>\n<html><head><meta charset='utf-8'>"
            f"<title>Research Report</title>\n<style>{_css}</style>\n"
            f"</head><body>{body}</body></html>"
        )

    if fmt == "html":
        try:
            return Response(
                content=_md_to_html(content),
                media_type="text/html",
                headers={"Content-Disposition": "attachment; filename=report.html"},
            )
        except ImportError as exc:
            raise HTTPException(
                status_code=501,
                detail=(
                    "HTML export requires 'markdown' package."
                    " Install: pip install markdown"
                ),
            ) from exc

    if fmt == "pdf":
        try:
            from weasyprint import HTML

            pdf_bytes = HTML(string=_md_to_html(content)).write_pdf()
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": "attachment; filename=report.pdf"},
            )
        except ImportError as exc:
            raise HTTPException(
                status_code=501,
                detail=(
                    "PDF export requires 'weasyprint' and 'markdown'."
                    " Install: pip install pydantic-deep[export]"
                ),
            ) from exc

    raise HTTPException(status_code=400, detail=f"Unsupported format: {fmt}. Use: md, html, pdf")


# ---------------------------------------------------------------------------
# Preview endpoint (for HTML/SVG live preview in file panel)
# ---------------------------------------------------------------------------


@app.get("/preview/{session_id}/{filepath:path}")
async def preview_file(session_id: str, filepath: str):
    """Serve raw files from container for live preview."""
    from fastapi.responses import Response

    if session_id not in user_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = user_sessions[session_id]

    if not filepath.startswith("/"):
        filepath = "/" + filepath

    ext = filepath.split(".")[-1].lower() if "." in filepath else ""
    content_type = _CONTENT_TYPES.get(ext, "text/plain")

    try:
        result = session.deps.backend.read(filepath)
        return Response(content=result, media_type=content_type)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main():
    """Run the DeepResearch server."""
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
