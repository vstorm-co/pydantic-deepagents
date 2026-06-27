# DeepResearch

DeepResearch is the flagship reference app — an autonomous research assistant you run in your browser. Ask it a question, and it plans the work, fans out parallel sub-agents across the web, executes code in a sandbox, and draws diagrams on a live canvas as it thinks. It's a full FastAPI web app built entirely on pydantic-deep, and it's the best place to see the framework's pieces working together at once.

!!! info "It's a reference, not a product"
    DeepResearch lives in `apps/deepresearch/` and is meant to be read and forked.
    This page is a guided tour of *what it shows you* and *how to run it* — the
    app's own `README.md` is the full manual.

## What it demonstrates

Every headline feature of pydantic-deep is wired into one app here. Each links to the guide that teaches it on its own:

- **Plan mode** — a `planner` sub-agent asks you clarifying questions *before* it dives into complex research, then saves a plan. See [Plan mode](../advanced/plan-mode.md).
- **Parallel sub-agents** — `code-reviewer`, `general-purpose`, and a dynamic agent factory let the lead agent spawn a fleet of researchers that work simultaneously. See [Sub-agents](../learn/subagents.md).
- **Web search & fetch** — Tavily, Brave, and Jina for search; Firecrawl and Playwright for scraping JS-heavy pages. See [Web search & MCP](../learn/web-and-mcp.md).
- **Code execution in a sandbox** — Python with pandas, numpy, matplotlib, and scikit-learn pre-installed, isolated per user. See [Backends](../concepts/backends.md).
- **A live Excalidraw canvas** — the agent draws flowcharts and architecture diagrams into a side panel that syncs in real time, over MCP. See [Model Context Protocol](../learn/web-and-mcp.md).
- **Skills, checkpointing, hooks, and middleware** — research-methodology and report-writing skills, rewind/fork of any turn, safety gates that block dangerous shell commands, and audit logging.

!!! tip "Per-user Docker sandboxes"
    A `SessionManager` spins up an isolated Docker container per user, so code
    execution and file writes never touch the host. This is the
    [`DockerSandbox`](../concepts/backends.md) backend doing the heavy lifting.

## Prerequisites

You'll need a few things on your machine before the first run:

- **Python 3.12+**
- **uv** — `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Node.js 20+** — MCP servers launch via `npx`
- **Docker** — for the per-user sandbox containers and the Excalidraw canvas
- **An OpenAI or Anthropic API key**, plus at least one search key (Tavily recommended)

## Run it

Four steps take you from a clone to a running app.

### 1. Install

```bash
cd apps/deepresearch
uv sync
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env — add your model API key and at least one search key
```

The essentials: `MODEL_NAME` (defaults to `anthropic:claude-sonnet-4-6`) and a search provider such as `TAVILY_API_KEY`. Everything else is optional — DeepResearch runs without any MCP server, though search keys are what make the research actually good.

### 3. Start the canvas

Make sure Docker Desktop is running, then bring up the Excalidraw canvas:

```bash
docker compose up -d excalidraw-canvas
```

### 4. Launch

```bash
uv run deepresearch
```

Open [http://localhost:8080](http://localhost:8080) and ask a research question.

!!! example "Check it"
    Try *"Compare the top three open-source vector databases and draw me a
    decision tree."* Watch the planner ask a clarifying question, sub-agents
    appear in parallel, and a diagram materialize on the canvas — all streamed
    live over a WebSocket.

!!! note "No Docker for the canvas?"
    You can skip Excalidraw and still get full research, code execution, and
    sub-agents:

    ```bash
    EXCALIDRAW_ENABLED=0 uv run deepresearch
    ```

## How it fits together

The shape of the app is worth knowing if you plan to fork it:

- **`app.py`** — the FastAPI server and the `/ws/chat` WebSocket that streams every agent step to the browser.
- **`agent.py`** — the agent factory: it calls [`create_deep_agent()`][pydantic_deep.create_deep_agent] and layers on hooks, sub-agents, skills, and the research system prompt.
- **`config.py`** — MCP server definitions, model selection, and paths.
- **`middleware.py`** — audit logging and permission blocking.
- **`skills/`** — markdown skill files the agent loads on demand.
- **`workspace/DEEP.md`** — a context file injected into every session.

The browser talks to FastAPI over a WebSocket; FastAPI drives a single pydantic-deep agent that owns the console toolset, todo toolset, sub-agent toolset, skills, checkpoints, and the MCP servers — all the same building blocks you assemble yourself in the Learn track.

## Recap

- DeepResearch is a FastAPI web app that shows the whole of pydantic-deep working together — planning, parallel sub-agents, web tools, sandboxed code, and a live diagram canvas.
- It's built with the exact factory and toolsets from the Learn guides; reading `agent.py` is a great way to see how they compose in a real app.
- Run it in four steps — `uv sync`, configure `.env`, start the canvas, `uv run deepresearch` — then open `localhost:8080`.

Where to go next:

- [Plan mode →](../advanced/plan-mode.md)
- [Sub-agents →](../learn/subagents.md)
- [Web search & MCP →](../learn/web-and-mcp.md)
- [Backends →](../concepts/backends.md)
