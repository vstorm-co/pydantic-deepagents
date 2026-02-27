# pydantic-deep Full Example Application

A complete demonstration of **every** pydantic-deep feature in a web application.

## Features Demonstrated

| # | Feature | Description |
|---|---------|-------------|
| 1 | **DockerSandbox** | Full backend with file ops + code execution in isolated containers |
| 2 | **Custom Tools** | 5 mock GitHub tools (repos, issues, PRs, users, stats) via `FunctionToolset` |
| 3 | **Code Execution** | Python code execution in isolated Docker sandbox |
| 4 | **Human-in-the-Loop** | `interrupt_on` — execute commands require approval dialog |
| 5 | **Skills** | Data analysis, code review, test generator skills from SKILL.md files |
| 6 | **Programmatic Skills** | `Skill` dataclass instance (quick-reference card) |
| 7 | **Subagents** | joke-generator + code-reviewer subagent delegation |
| 8 | **General-Purpose Subagent** | Built-in general-purpose subagent enabled |
| 9 | **File Uploads** | Support for CSV, PDF, TXT, JSON, Python, image files |
| 10 | **Multi-user Sessions** | Isolated Docker containers per user via `SessionManager` |
| 11 | **WebSocket Streaming** | Real-time streaming of text, thinking, and tool events |
| 12 | **BASE_PROMPT** | Instructions extend `BASE_PROMPT` from pydantic-deep |
| 13 | **Hooks** | `audit_logger` (POST_TOOL_USE, background) + `safety_gate` (PRE_TOOL_USE) |
| 14 | **Middleware** | `AuditMiddleware` (tool stats) + `PermissionMiddleware` (path blocking) |
| 15 | **Eviction Processor** | `eviction_token_limit=20000` — large tool outputs saved to files |
| 16 | **Patch Tool Calls** | `patch_tool_calls=True` — fixes orphaned tool calls in history |
| 17 | **Sliding Window** | `SlidingWindowProcessor` — zero-cost conversation trimming |
| 18 | **Context Files** | `context_files=["/workspace/DEEP.md"]` — workspace context loaded into prompt |
| 19 | **Image Support** | `image_support=True` — multimodal read_file for images |
| 20 | **RuntimeConfig** | `python-datascience` runtime with pre-installed data science packages |
| 21 | **TODO List** | Task planning with inline progress widget in chat |
| 22 | **Config Panel** | Frontend tab showing all active features and live tool usage stats |

## Running the Application

### Prerequisites

```bash
# Install dependencies
cd examples/full_app
pip install fastapi uvicorn python-multipart

# Or with uv
uv add fastapi uvicorn python-multipart
```

### Start the Server

```bash
cd examples/full_app
uvicorn app:app --reload --port 8080
```

Then open http://localhost:8080 in your browser.

## Usage Examples

### 1. GitHub Queries (Mock Data)
```
"List my GitHub repositories"
"Show open issues in pydantic-deep"
"Get stats for the ml-pipeline repo"
```

### 2. Data Analysis with Skills
```
1. Upload a CSV file using the sidebar
2. "Load the data-analysis skill"
3. "Analyze the uploaded sales.csv file and create a visualization"
```

### 3. Code Review (Subagent)
```
"Review the code in /workspace/script.py"
```
The agent delegates to the `code-reviewer` subagent for quality and security analysis.

### 4. Joke Generator (Subagent)
```
"Tell me a joke about Python programming"
```

### 5. Code Execution (Human-in-the-Loop)
```
"Write a Python script that generates the first 10 prime numbers and save it to primes.py"
"Run the primes.py script"
```
Execute commands trigger an approval dialog before running.

### 6. Safety Gate (Hook)
```
"Run rm -rf /"
```
The `safety_gate` hook blocks dangerous shell patterns before execution.

### 7. Permission Middleware
```
"Read /etc/passwd"
```
The `PermissionMiddleware` blocks access to sensitive system paths.

### 8. Image Support
```
1. Upload a PNG/JPG image
2. "What's in this image?"
```

### 9. List Available Skills
```
"List available skills"
```
Shows data-analysis, code-review, test-generator, and quick-reference skills.

### 10. Config Panel
Click the **Config** tab in the sidebar to view all active features, hooks, middleware, processors, subagents, skills, and live tool usage statistics.

## Project Structure

```
full_app/
├── app.py                  # FastAPI backend with all features wired
├── audit_middleware.py      # AuditMiddleware + PermissionMiddleware
├── github_tools.py          # Mock GitHub tools (FunctionToolset)
├── skills/
│   ├── data-analysis/
│   │   └── SKILL.md         # Data analysis skill
│   ├── code-review/
│   │   ├── SKILL.md         # Code review skill
│   │   └── example_review.md
│   └── test-generator/
│       └── SKILL.md         # Test generator skill
├── static/
│   ├── index.html           # Frontend HTML
│   ├── styles.css           # Styles (incl. config panel, hook events)
│   └── app.js               # Frontend JS (WebSocket, config panel, middleware events)
├── workspace/
│   └── DEEP.md              # Context file seeded into containers
└── README.md                # This file
```

## Sample Data

Create a test CSV file:

```csv
date,product,category,sales,quantity
2024-01-01,Widget A,Electronics,150.00,3
2024-01-01,Widget B,Electronics,200.00,2
2024-01-02,Gadget X,Accessories,75.50,5
2024-01-02,Widget A,Electronics,150.00,2
2024-01-03,Gadget Y,Accessories,120.00,4
2024-01-03,Widget B,Electronics,400.00,4
2024-01-04,Widget A,Electronics,300.00,6
2024-01-04,Gadget X,Accessories,151.00,10
```

Save as `sales.csv` and upload via the web interface.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Serve frontend |
| `/ws/chat` | WebSocket | Streaming chat with agent |
| `/upload` | POST | Upload a file (requires `session_id` query param) |
| `/files` | GET | List files (requires `session_id` query param) |
| `/files/content/{path}` | GET | Get file content for preview |
| `/files/binary/{path}` | GET | Get binary file (images) |
| `/files/download/{path}` | GET | Download a file from workspace |
| `/preview/{session_id}/{path}` | GET | Serve file for live HTML preview |
| `/config` | GET | Get active feature configuration (for Config panel) |
| `/todos` | GET | Get agent's todo list |
| `/reset` | POST | Reset a specific session |
| `/session/new` | POST | Create a new session |
| `/sessions` | GET | List all active sessions |
| `/health` | GET | Health check |

## Configuration

The agent is configured in `app.py` with **all** pydantic-deep features:

```python
agent = create_deep_agent(
    model="openai:gpt-4.1",
    instructions=MAIN_INSTRUCTIONS,
    backend=None,
    # Toolsets
    include_todo=True,
    include_filesystem=True,
    include_subagents=True,
    include_skills=True,
    include_execute=True,
    toolsets=[github_toolset],
    # Subagents
    subagents=SUBAGENT_CONFIGS,
    include_general_purpose_subagent=True,
    # Skills
    skills=PROGRAMMATIC_SKILLS,
    skill_directories=[{"path": str(SKILLS_DIR), "recursive": True}],
    # Hooks
    hooks=HOOKS,
    # Middleware
    middleware=[audit_mw, permission_mw],
    # Processors
    eviction_token_limit=20000,
    patch_tool_calls=True,
    history_processors=[sliding_window],
    # Context files
    context_files=["/workspace/DEEP.md"],
    # Image support
    image_support=True,
    # Human-in-the-loop
    interrupt_on={"execute": True, "write_file": False},
)
```

Session management with pre-configured runtime:

```python
session_manager = SessionManager(
    default_runtime="python-datascience",  # pandas, numpy, matplotlib pre-installed
    default_idle_timeout=3600,
    workspace_root=WORKSPACES_DIR,
)
session_manager.start_cleanup_loop(interval=300)
```

## Hooks

| Hook | Event | Description |
|------|-------|-------------|
| `audit_logger` | `POST_TOOL_USE` | Logs tool name + args (background, non-blocking) |
| `safety_gate` | `PRE_TOOL_USE` | Blocks dangerous shell patterns (`rm -rf /`, `mkfs.`, fork bombs) |

## Middleware

| Middleware | Description |
|------------|-------------|
| `AuditMiddleware` | Tracks tool usage stats (call count, duration, breakdown) — displayed in Config panel |
| `PermissionMiddleware` | Blocks file access to sensitive paths (`/etc/passwd`, `.env`, `/root/`, `/proc/`) |

## Customization

### Adding More Tools

Edit `github_tools.py` to add more mock tools or create real API integrations.

### Adding Skills

Create a new directory under `skills/` with a `SKILL.md` file containing YAML frontmatter and instructions.

### Adding Subagents

Add more `SubAgentConfig` entries to the `SUBAGENT_CONFIGS` list in `app.py`.

### Adding Hooks

Add more `Hook` entries to the `HOOKS` list in `app.py`.

### Adding Middleware

Create a new class extending `AgentMiddleware[DeepAgentDeps]` and add it to the `middleware` list.

### Using Pre-configured Runtimes

Available built-in runtimes:
- `python-minimal` — Clean Python 3.12
- `python-datascience` — pandas, numpy, matplotlib, scikit-learn, seaborn
- `python-web` — FastAPI, SQLAlchemy, httpx
- `node-minimal` — Clean Node.js 20
- `node-react` — TypeScript, Vite, React

## WebSocket Protocol

The `/ws/chat` endpoint uses the following message protocol:

### Client → Server

```json
{"session_id": "uuid", "message": "user query"}
{"approval": {"tool_call_id": true}}
```

### Server → Client

| Event Type | Description |
|------------|-------------|
| `session_created` | New session ID assigned |
| `start` | Agent run started |
| `status` | Status update message |
| `text_delta` | Streaming text chunk |
| `thinking_delta` | Streaming thinking content (reasoning models) |
| `tool_call_start` | Tool call beginning (streaming args) |
| `tool_args_delta` | Tool arguments streaming chunk |
| `tool_start` | Tool execution starting |
| `tool_output` | Tool result |
| `approval_required` | Human approval needed for tool |
| `response` | Final formatted response |
| `todos_update` | Updated TODO list |
| `middleware_event` | Tool usage stats from AuditMiddleware |
| `hook_event` | Hook fired/blocked event |
| `done` | Agent run complete |
| `error` | Error occurred |

---

<div align="center">

### Need help implementing this in your company?

<p>We're <a href="https://vstorm.co"><b>Vstorm</b></a> — an Applied Agentic AI Engineering Consultancy<br>with 30+ production AI agent implementations.</p>

<a href="https://vstorm.co/contact-us/">
  <img src="https://img.shields.io/badge/Talk%20to%20us%20%E2%86%92-0066FF?style=for-the-badge&logoColor=white" alt="Talk to us">
</a>

<br><br>

Made with ❤️ by <a href="https://vstorm.co"><b>Vstorm</b></a>

</div>
