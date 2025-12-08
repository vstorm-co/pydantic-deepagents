# pydantic-deep Full Example Application

A complete demonstration of all pydantic-deep features in a web application.

## Features Demonstrated

| Feature | Description |
|---------|-------------|
| **DockerSandbox** | Full backend with file ops + code execution |
| **Custom Tools** | 5 mock GitHub tools (repos, issues, PRs, users, stats) |
| **Code Execution** | Python code execution in isolated container |
| **interrupt_on** | Execute commands require approval |
| **Skills** | Data analysis skill for CSV files |
| **Subagents** | Joke generator (unrelated to demonstrate delegation) |
| **File Uploads** | Support for CSV, PDF, TXT, JSON, Python files |
| **Multi-user Sessions** | Isolated Docker containers per user via SessionManager |
| **WebSocket Streaming** | Real-time streaming of text, thinking, and tool events |

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

### 2. Data Analysis
```
1. Upload a CSV file using the sidebar
2. "Load the data-analysis skill"
3. "Analyze the uploaded sales.csv file and create a visualization"
```

### 3. Joke Generator (Subagent)
```
"Tell me a joke about Python programming"
"I need some programming humor"
```

### 4. Code Execution
```
"Write a Python script that generates the first 10 prime numbers and save it to primes.py"
"Run the primes.py script"
```

### 5. File Operations
```
"Create a README.md file in the workspace"
"List all files in the workspace"
"Read the contents of /workspace/primes.py"
```

## Project Structure

```
full_app/
├── app.py              # FastAPI backend with WebSocket streaming
├── github_tools.py     # Mock GitHub tools (FunctionToolset)
├── skills/
│   └── data-analysis/
│       └── SKILL.md    # Data analysis skill definition
├── static/
│   ├── index.html      # Frontend HTML
│   ├── styles.css      # Styles
│   └── app.js          # Frontend JavaScript with WebSocket client
├── workspace/          # Agent's workspace directory (created on startup)
└── README.md           # This file
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
| `/files/download/{path}` | GET | Download a file from workspace |
| `/todos` | GET | Get agent's todo list |
| `/reset` | POST | Reset a specific session |
| `/session/new` | POST | Create a new session |
| `/sessions` | GET | List all active sessions |
| `/health` | GET | Health check |

## Configuration

The agent is configured in `app.py`:

```python
agent = create_deep_agent(
    model="openai:gpt-4.1",
    instructions=MAIN_INSTRUCTIONS,
    backend=None,  # Backend comes from deps at runtime (per-session)
    include_todo=True,
    include_filesystem=True,
    include_subagents=True,
    include_skills=True,
    include_execute=True,  # Force include - backend provided via deps
    toolsets=[github_toolset],
    subagents=SUBAGENT_CONFIGS,
    include_general_purpose_subagent=False,
    skill_directories=[{"path": str(SKILLS_DIR), "recursive": True}],
    interrupt_on={"execute": True, "write_file": False},
)
```

Session management uses `SessionManager` for multi-user isolation:

```python
session_manager = SessionManager(
    default_runtime=None,  # Uses python:3.12-slim
    default_idle_timeout=3600,  # 1 hour
)
session_manager.start_cleanup_loop(interval=300)  # Cleanup every 5 min
```

## Customization

### Adding More Tools

Edit `github_tools.py` to add more mock tools or create real API integrations.

### Adding Skills

Create a new directory under `skills/` with a `SKILL.md` file containing YAML frontmatter and instructions.

### Adding Subagents

Add more `SubAgentConfig` entries to the `SUBAGENT_CONFIGS` list in `app.py`.

### Using Pre-configured Runtimes

For faster startup with pre-installed packages, use a built-in runtime:

```python
session_manager = SessionManager(
    default_runtime="python-datascience",  # pandas, numpy, matplotlib pre-installed
)
```

Available built-in runtimes:
- `python-minimal` - Clean Python 3.12
- `python-datascience` - pandas, numpy, matplotlib, scikit-learn, seaborn
- `python-web` - FastAPI, SQLAlchemy, httpx
- `node-minimal` - Clean Node.js 20
- `node-react` - TypeScript, Vite, React

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
| `done` | Agent run complete |
| `error` | Error occurred |
