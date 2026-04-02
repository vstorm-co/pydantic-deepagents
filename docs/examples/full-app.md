# Full Application Example

Complete FastAPI app with WebSocket streaming, Docker, uploads, and more.

## Source Code

:material-file-code: `examples/full_app/`

This is a comprehensive example demonstrating all pydantic-deep features in a production-like setup.

## Features

| Feature | Description |
|---------|-------------|
| **DockerSandbox** | Isolated file operations and code execution |
| **WebSocket Streaming** | Real-time events and text deltas |
| **Human-in-the-Loop** | Approval UI for execute commands |
| **File Uploads** | PDF/CSV processing |
| **Skills** | Data analysis skill |
| **Subagents** | Joke generator for entertainment |
| **Multi-User** | SessionManager for isolated sessions |
| **Custom Tools** | Mock GitHub integration |

## Project Structure

```
examples/full_app/
├── app.py              # FastAPI application
├── github_tools.py     # Custom GitHub tools (mock)
├── skills/
│   └── data-analysis/
│       └── SKILL.md    # Data analysis skill
├── static/
│   ├── index.html      # Web UI
│   └── styles.css      # Styling
└── workspace/          # Persistent storage
```

## Running the Example

```bash
# Navigate to the example directory
cd examples/full_app

# Install dependencies (if needed)
uv pip install fastapi uvicorn websockets python-multipart

# Start Docker (required for sandbox)
docker pull python:3.12-slim

# Run the application
uvicorn app:app --reload --port 8080

# Open in browser
open http://localhost:8080
```

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      Web Browser                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │  Chat UI    │  │  File List  │  │  TODO List  │         │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │
└─────────┼────────────────┼────────────────┼─────────────────┘
          │                │                │
          ▼                ▼                ▼
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Backend                           │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  WebSocket /ws/chat                                  │    │
│  │  - Streaming responses                               │    │
│  │  - Tool call events                                  │    │
│  │  - Approval requests                                 │    │
│  └─────────────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  REST Endpoints                                      │    │
│  │  - POST /upload (file uploads)                       │    │
│  │  - GET /files (list files)                          │    │
│  │  - GET /todos (todo list)                           │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│                    pydantic-deep Agent                       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │ TodoToolset  │  │ FilesysToolst│  │ SubAgentTlst │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
│  ┌──────────────┐  ┌──────────────┐                        │
│  │ SkillsToolst │  │ GitHub Tools │                        │
│  └──────────────┘  └──────────────┘                        │
└─────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────┐
│                    SessionManager                            │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  User Session 1 → DockerSandbox (Container A)       │    │
│  │  User Session 2 → DockerSandbox (Container B)       │    │
│  │  User Session 3 → DockerSandbox (Container C)       │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

## Key Implementation Details

### Agent Creation

```python
def create_agent() -> Agent[DeepAgentDeps, str]:
    """Create the shared agent (stateless - can be used by all sessions)."""
    github_toolset = create_github_toolset(id="github")

    return create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        instructions=MAIN_INSTRUCTIONS,
        backend=None,  # Backend comes from deps at runtime

        # Toolsets
        include_todo=True,
        include_filesystem=True,
        include_subagents=True,
        include_skills=True,
        include_execute=True,
        toolsets=[github_toolset],

        # Subagents
        subagents=SUBAGENT_CONFIGS,
        include_builtin_subagents=False,

        # Skills
        skill_directories=[{"path": str(SKILLS_DIR), "recursive": True}],

        # Human-in-the-loop
        interrupt_on={"execute": True},
    )
```

### Session Management

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent, session_manager

    # Create shared agent
    agent = create_agent()

    # Create session manager for Docker containers
    session_manager = SessionManager(
        default_runtime=None,
        default_idle_timeout=3600,
        workspace_root="./workspaces",  # Persistent storage for user files
    )
    session_manager.start_cleanup_loop(interval=300)

    yield

    # Cleanup
    await session_manager.shutdown()
```

With `workspace_root`, each session gets persistent storage at `./workspaces/{session_id}/workspace/`, so user files survive container restarts and app reboots.

### WebSocket Streaming

```python
@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()

    async with agent.iter(message, deps=session.deps) as run:
        async for node in run:
            if Agent.is_model_request_node(node):
                # Stream text deltas
                async with node.stream(run.ctx) as request_stream:
                    async for event in request_stream:
                        if isinstance(event, PartDeltaEvent):
                            await websocket.send_json({
                                "type": "text_delta",
                                "content": event.delta.content_delta,
                            })

            elif Agent.is_call_tools_node(node):
                # Stream tool events
                async with node.stream(run.ctx) as handle_stream:
                    async for event in handle_stream:
                        if isinstance(event, FunctionToolCallEvent):
                            await websocket.send_json({
                                "type": "tool_start",
                                "tool_name": event.part.tool_name,
                            })
```

### Human-in-the-Loop

```python
if isinstance(result.output, DeferredToolRequests):
    # Send approval request to frontend
    await websocket.send_json({
        "type": "approval_required",
        "requests": [
            {
                "tool_call_id": call.tool_call_id,
                "tool_name": call.tool_name,
                "args": call.args,
            }
            for call in result.output.approvals
        ],
    })

# Handle approval response
approval_response = message_data.get("approval")
if approval_response:
    approvals = {
        tool_id: ToolApproved() if approved else ToolDenied()
        for tool_id, approved in approval_response.items()
    }
    await agent.run(
        None,
        deps=session.deps,
        message_history=session.message_history,
        deferred_tool_results=DeferredToolResults(approvals=approvals),
    )
```

### File Uploads

```python
@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    session_id: str = Query(""),
):
    session = await get_or_create_session(session_id)
    content = await file.read()

    # Upload to session's Docker container
    path = session.deps.upload_file(file.filename, content)

    return {"path": path, "size": len(content)}
```

## WebSocket Protocol

### Client → Server

```json
// Send message
{"session_id": "abc123", "message": "Create a script"}

// Send approval
{"approval": {"tool_call_id_1": true, "tool_call_id_2": false}}
```

### Server → Client

```json
// Text streaming
{"type": "text_delta", "content": "I'll create"}

// Tool call
{"type": "tool_start", "tool_name": "write_file", "args": {...}}

// Tool result
{"type": "tool_output", "tool_name": "write_file", "output": "Created..."}

// Approval needed
{"type": "approval_required", "requests": [...]}

// TODO update
{"type": "todos_update", "todos": [...]}

// Complete
{"type": "done"}
```

## REST Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Serve web UI |
| `/ws/chat` | WebSocket | Chat with streaming |
| `/upload` | POST | Upload file |
| `/files` | GET | List files |
| `/files/content/{path}` | GET | Get file content |
| `/files/binary/{path}` | GET | Get binary file |
| `/todos` | GET | Get TODO list |
| `/reset` | POST | Reset session |
| `/session/new` | POST | Create new session |
| `/sessions` | GET | List sessions |
| `/health` | GET | Health check |

## Custom GitHub Tools

The example includes mock GitHub tools:

```python
def create_github_toolset(id: str) -> FunctionToolset:
    toolset = FunctionToolset()

    @toolset.tool
    async def github_list_repos(ctx: RunContext[DeepAgentDeps]) -> str:
        """List popular repositories."""
        return json.dumps(MOCK_REPOS)

    @toolset.tool
    async def github_list_issues(
        ctx: RunContext[DeepAgentDeps],
        repo: str,
    ) -> str:
        """List issues for a repository."""
        return json.dumps(MOCK_ISSUES)

    return toolset
```

## Skills

The data-analysis skill (`skills/data-analysis/SKILL.md`):

```markdown
---
name: data-analysis
version: "1.0"
description: Comprehensive data analysis and visualization
triggers:
  - analyze data
  - create chart
  - data visualization
---

# Data Analysis Skill

You are a data analysis expert. When analyzing data:

1. Load and explore the data structure
2. Calculate summary statistics
3. Identify patterns and outliers
4. Create visualizations
5. Provide actionable insights
```

## Deployment Considerations

### Docker Requirements

- Docker must be running
- Pull required images: `docker pull python:3.12-slim`
- Consider resource limits for containers

### Scaling

- Agent is stateless (shared across sessions)
- Each session gets isolated Docker container
- SessionManager handles container lifecycle
- Consider container pool for faster startup

### Security

- Containers provide isolation
- Human-in-the-loop for execute
- Session cleanup on idle timeout
- CORS configured for local development

## Next Steps

- [Docker Sandbox](docker-sandbox.md) - Sandbox details
- [Docker Runtimes](docker-runtimes.md) - Pre-configured environments
- [Human-in-the-Loop](human-in-the-loop.md) - Approval workflows
- [Streaming](streaming.md) - Streaming concepts
