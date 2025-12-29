# pydantic-deep Research Assistant

A comprehensive research assistant application showcasing advanced pydantic-deep features for scientific research workflows.

## Features Demonstrated

| Feature | Description |
|---------|-------------|
| **Paper Analysis Tools** | Extract metadata, references, and sections from PDFs |
| **Fact Checking Tools** | Verify claims using local files and web search (Serper API) |
| **DockerSandbox Backend** | Isolated Python execution environment with file operations |
| **Data Analysis Skill** | Comprehensive CSV analysis with pandas and matplotlib |
| **Fact Checking Skill** | Multi-source verification workflow with citation tracking |
| **File Uploads** | Support for PDF, CSV, TXT, JSON, Python, and more |
| **Citation System** | Interactive citation links: `[[citation:path|quote]]` |
| **TODO List Management** | Real-time task tracking visible to users |
| **Multi-user Sessions** | Isolated Docker containers per user via SessionManager |
| **WebSocket Streaming** | Real-time streaming of text, thinking, and tool events |

## Running the Application

### Prerequisites

```bash
# Install dependencies
pip install ".[examples]"

# Or with uv
uv sync --extra examples
```

### Configuration

Create a `.env` file (copy from `.env_example`).

Edit `.env` to set your API keys.

Edit `config.yaml` to customize behavior.

### Start the Server

```bash
cd examples/research_assistant
uvicorn app:app --reload --port 8080

# Or with uv
uv run uvicorn app:app --reload --port 8080
```

Then open http://localhost:8080 in your browser.

## Usage Examples

### 1. Paper Analysis
```
1. Upload a scientific paper (PDF) using the sidebar
2. "Extract metadata from paper.pdf"
3. "What are the key findings in the methodology section?"
4. "Extract all references from the paper"
```

### 2. Data Analysis with Citations
```
1. Upload a CSV file (e.g., sales.csv, research_data.csv)
2. "Load the data-analysis skill"
3. "Analyze sales.csv and create a visualization showing trends over time"
```

### 3. Fact Checking with Multi-Source Verification
```
1. Upload relevant research papers or documents
2. "Load the fact-checking skill"
3. "Verify the claim: 'Transformers use self-attention mechanisms'"
4. Agent will search local files, web, and Google Scholar
5. All findings will have interactive citation links
```


## Project Structure

```
research_assistant/
├── app.py                  # FastAPI backend with WebSocket streaming
├── paper_tools.py          # Paper analysis tools (PDFs)
├── fact_check_tools.py     # Fact-checking tools (local + web search)
├── config.yaml             # Runtime configuration
├── .env                    # Environment variables (API keys)
├── .env_example            # Example environment file
├── skills/
│   ├── data-analysis/
│   │   └── SKILL.md        # Data analysis skill definition
│   └── fact-checking/
│       └── SKILL.md        # Fact-checking skill definition
├── static/
│   ├── index.html          # Frontend HTML
│   ├── styles.css          # Styles
│   └── app.js              # Frontend JavaScript with WebSocket client
├── workspace/              # Agent's workspace directory (created on startup)
└── README.md               # This file
```


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
    include_skills=True,
    include_execute=True,  # Force include - backend provided via deps
    toolsets=[paper_toolset, fact_check_toolset],
    skill_directories=[{"path": str(SKILLS_DIR), "recursive": True}],
    interrupt_on={
        "execute": True,  # Require approval for code execution
        "write_file": False,
    },
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

## Citation System

The research assistant uses a special citation format for interactive source linking:

```
[[citation:path_or_url|quote]]
```

**Examples:**
- Local file: `[[citation:/uploads/paper.pdf|The model achieves 95% accuracy]]`
- Web source: `[[citation:https://arxiv.org/abs/1234.5678|Attention is all you need]]`

The frontend renders these as clickable links that highlight the source.


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


## License

Same as pydantic-deep project. See main LICENSE file.
