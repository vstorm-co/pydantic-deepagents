<h1 align="center">Pydantic Deep Agents</h1>

<p align="center">
  <img src="assets/cli_demo.gif" alt="Pydantic Deep Agents CLI demo" width="800">
</p>

<p align="center">
  <b>The batteries-included deep agent harness for Python.</b><br>
  Terminal AI assistant out of the box — or build production agents with one function call.
</p>

<p align="center">
  <a href="https://vstorm-co.github.io/pydantic-deepagents/">Docs</a> &middot;
  <a href="https://pypi.org/project/pydantic-deep/">PyPI</a> &middot;
  <a href="#-cli--terminal-ai-assistant">CLI</a> &middot;
  <a href="#-framework--build-your-own-agent">Framework</a> &middot;
  <a href="#-deepresearch--reference-app">DeepResearch</a> &middot;
  <a href="https://vstorm-co.github.io/pydantic-deepagents/examples/">Examples</a>
</p>

<p align="center">
  <a href="https://pypi.org/project/pydantic-deep/"><img src="https://img.shields.io/pypi/v/pydantic-deep.svg" alt="PyPI version"></a>
  <a href="https://pepy.tech/projects/pydantic-deep"><img src="https://static.pepy.tech/badge/pydantic-deep/month" alt="PyPI Downloads"></a>
  <a href="https://github.com/vstorm-co/pydantic-deep/stargazers"><img src="https://img.shields.io/github/stars/vstorm-co/pydantic-deep?style=flat&logo=github&color=yellow" alt="GitHub Stars"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10+-blue?logo=python&logoColor=white" alt="Python 3.10+"></a>
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License: MIT"></a>
  <a href="https://coveralls.io/github/vstorm-co/pydantic-deepagents?branch=main"><img src="https://coveralls.io/repos/github/vstorm-co/pydantic-deepagents/badge.svg?branch=main" alt="Coverage Status"></a>
  <a href="https://github.com/vstorm-co/pydantic-deepagents/actions/workflows/ci.yml"><img src="https://github.com/vstorm-co/pydantic-deepagents/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://www.bestpractices.dev/projects/12495"><img src="https://www.bestpractices.dev/projects/12495/badge" alt="OpenSSF Best Practices"></a>
  <a href="https://github.com/vstorm-co/pydantic-deep/blob/main/SECURITY.md"><img src="https://img.shields.io/badge/security-policy-blueviolet?logo=shieldsdotio&logoColor=white" alt="Security Policy"></a>
  <a href="https://github.com/pydantic/pydantic-ai"><img src="https://img.shields.io/badge/Powered%20by-Pydantic%20AI-E92063?logo=pydantic&logoColor=white" alt="Pydantic AI"></a>
  <a href="https://x.com/Kacper95682155"><img src="https://img.shields.io/badge/X-000000?logo=x&logoColor=white" alt="X"></a>
</p>

---

## What's New

- **2026-04-12** &nbsp;**v0.3.8** — Stuck loop detection, context limit warnings for the model, expanded context file discovery (CLAUDE.md, .cursorrules, etc.), eviction & orphan repair migrated to capabilities hooks.
- **2026-04-11** &nbsp;**v0.3.6** — One-command installer + self-update: `curl -fsSL .../install.sh | bash` installs everything automatically. New `pydantic-deep update` command. Startup update notifications with 24-hour PyPI cache.
- **2026-04-10** &nbsp;**v0.3.5** — Headless runner (`pydantic-deep run`), Docker sandbox with named workspaces, browser automation via Playwright, Harbor adapter for Terminal Bench evaluation.

> Full history: [CHANGELOG.md](CHANGELOG.md)

---

## The Agent Harness

Pydantic Deep Agents is an **agent harness** — the complete infrastructure that wraps an LLM and makes it a functional autonomous agent. The model provides intelligence; the harness provides planning, tools, memory, sandboxed execution, and unlimited context.

<table>
<tr>
<td><b>🔧 Tool-calling</b></td>
<td>File read/write/edit, shell execution, glob, grep, web search, web fetch, browser automation — wired up and ready.</td>
</tr>
<tr>
<td><b>🧠 Persistent memory</b></td>
<td>MEMORY.md persists across sessions. Auto-injected into the system prompt. Each agent has isolated memory by default.</td>
</tr>
<tr>
<td><b>♾️ Unlimited context</b></td>
<td>Auto-summarization when approaching the token budget. LLM-based or zero-cost sliding window. Never hits a context wall.</td>
</tr>
<tr>
<td><b>🤝 Multi-agent / swarm</b></td>
<td>Spawn subagents for parallel workstreams. Shared TODO lists with claiming. Peer-to-peer message bus. Full team coordination.</td>
</tr>
<tr>
<td><b>🐳 Sandboxed execution</b></td>
<td>Docker sandbox with named workspaces. Installed packages persist between sessions. Project dir mounted at /workspace.</td>
</tr>
<tr>
<td><b>🗂️ Plan Mode</b></td>
<td>Dedicated planner subagent asks clarifying questions and structures the work before execution begins. Headless-compatible.</td>
</tr>
<tr>
<td><b>🔖 Checkpoints</b></td>
<td>Save conversation state at any point. Rewind to any checkpoint. Fork sessions to explore alternative approaches.</td>
</tr>
<tr>
<td><b>📚 Skills system</b></td>
<td>Domain-specific knowledge loaded on demand from SKILL.md files. Built-in skills: code-review, refactor, test-writer, git-workflow, and more.</td>
</tr>
<tr>
<td><b>🔌 MCP</b></td>
<td>Connect any Model Context Protocol server via pydantic-ai's native MCP capability.</td>
</tr>
<tr>
<td><b>⚡ Lifecycle hooks</b></td>
<td>Claude Code-style PRE_TOOL_USE / POST_TOOL_USE hooks. Shell commands or Python handlers. Audit logging, safety gates.</td>
</tr>
<tr>
<td><b>📐 Structured output</b></td>
<td>Type-safe Pydantic model responses via <code>output_type</code>. No JSON parsing. No <code>dict["key"]</code>. Full IDE autocomplete.</td>
</tr>
<tr>
<td><b>🔄 Stuck loop detection</b></td>
<td>Detects repeated identical tool calls, A-B-A-B alternating patterns, and no-op calls. Warns the model or stops the run.</td>
</tr>
<tr>
<td><b>⚠️ Context limit warnings</b></td>
<td>Model receives URGENT/CRITICAL warnings when approaching context limits (70%), well before auto-compression (90%).</td>
</tr>
<tr>
<td><b>💰 Cost tracking</b></td>
<td>Real-time token and USD cost tracking per run and cumulative. Hard budget limits with <code>BudgetExceededError</code>.</td>
</tr>
<tr>
<td><b>✨ Self-improving</b></td>
<td><code>/improve</code> analyzes past sessions and proposes updates to MEMORY.md, SOUL.md, and AGENTS.md.</td>
</tr>
<tr>
<td><b>🏷️ 100% type-safe</b></td>
<td>Pyright strict + MyPy strict. 100% test coverage. Every public API is fully typed — safe to use in production.</td>
</tr>
</table>

Built natively on **[pydantic-ai](https://github.com/pydantic/pydantic-ai)** — uses the Capabilities API directly, inherits all pydantic-ai streaming, multi-model support, and Pydantic validation automatically.

---

## 🖥️ CLI — Terminal AI Assistant

A Claude Code-style terminal AI assistant that works with **any model and any provider.**

### Install (macOS & Linux)

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/pydantic-deep/main/install.sh | bash
```

No Python setup required — the script installs uv and the CLI automatically. Then:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
pydantic-deep
```

> **Windows / manual:** `pip install "pydantic-deep[cli]"` &nbsp;·&nbsp; **Update:** `pydantic-deep update`

### Model & Provider Support

Works with any model that supports tool-calling:

| Provider | Example models |
|----------|----------------|
| **Anthropic** | `anthropic:claude-opus-4-6`, `claude-sonnet-4-6` |
| **OpenAI** | `openai:gpt-5.4`, `gpt-4.1` |
| **OpenRouter** | `openrouter:anthropic/claude-opus-4-6` (200+ models) |
| **Google Gemini** | `google-gla:gemini-2.5-pro` |
| **Ollama (local)** | `ollama:qwen3`, `ollama:llama3.3` |
| **Any OpenAI-compatible** | Custom base URL via env |

Switch model anytime: `pydantic-deep config set model openai:gpt-5.4` or `/model` in the TUI.

### What you get in the TUI

| | Feature |
|:-:|---------|
| 💬 | Streaming chat with tool call visualization |
| 📁 | File read / write / edit, shell execution, glob, grep |
| 🧠 | Persistent memory and self-improvement across sessions |
| 🗂️ | Task planning, plan mode, and subagent delegation |
| ♾️ | Context compression for unlimited conversations |
| 🔖 | Checkpoints — save, rewind, and fork any session |
| 🌐 | Web search & fetch built-in |
| 🖥️ | Browser automation via Playwright (`--browser`) |
| 🐳 | Docker sandbox — sandboxed execution with named workspaces |
| 💭 | Extended thinking — `minimal` / `low` / `medium` / `high` / `xhigh` |
| 💰 | Real-time cost and token tracking per session |
| 🛡️ | Tool approval dialogs — approve, auto-approve, or deny per tool call |
| @ | `@filename` file references · `!command` shell passthrough |
| ✨ | `/improve`, `/skills`, `/diff`, `/model`, `/theme`, `/compact`, and more |

### Usage

```bash
# Interactive TUI (default)
pydantic-deep
pydantic-deep tui --model openrouter:anthropic/claude-opus-4-6

# Headless deep agent — benchmarks, CI/CD, scripted automation
pydantic-deep run "Fix the failing test in test_auth.py"
pydantic-deep run --task-file task.md --json
pydantic-deep run "Refactor utils.py" --no-web-search --thinking false

# Docker sandbox — sandboxed execution, project dir mounted at /workspace
pydantic-deep tui --sandbox docker
pydantic-deep tui --workspace ml-env     # named workspace, packages persist

# Browser automation (requires pydantic-deep[browser])
pydantic-deep tui --browser
pydantic-deep run "Go to example.com and summarize the content" --browser

# Config & skills
pydantic-deep config set model anthropic:claude-sonnet-4-6
pydantic-deep skills list
pydantic-deep update                     # update to latest version
```

> See [CLI docs](docs/cli/index.md) for the full reference.

---

## 🐍 Framework — Build Your Own Agent

```bash
pip install pydantic-deep
```

One function call gives you a production deep agent with planning, tool-calling, multi-agent delegation, persistent memory, unlimited context, and cost tracking. Everything is a toggle:

```python
from pydantic_ai_backends import StateBackend
from pydantic_deep import create_deep_agent, create_default_deps

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    include_todo=True,          # Task planning with subtasks and dependencies
    include_subagents=True,     # Multi-agent swarm — delegate to subagents
    include_skills=True,        # Domain-specific skills from SKILL.md files
    include_memory=True,        # Persistent memory across sessions
    include_plan=True,          # Structured planning before execution
    include_teams=True,         # Agent teams with shared TODO lists + message bus
    web_search=True,            # Tool-calling: web search
    web_fetch=True,             # Tool-calling: web fetch
    thinking="high",            # Extended thinking / reasoning effort
    context_manager=True,       # Unlimited context via auto-summarization
    cost_tracking=True,         # Token/USD budget enforcement
    include_checkpoints=True,   # Save, rewind, and fork conversations
)

deps = create_default_deps(StateBackend())
result = await agent.run("Build a REST API for user auth", deps=deps)
```

### Structured Output

Type-safe responses with Pydantic models — no JSON parsing, no `dict["key"]`:

```python
from pydantic import BaseModel

class CodeReview(BaseModel):
    summary: str
    issues: list[str]
    score: int

agent = create_deep_agent(output_type=CodeReview)
result = await agent.run("Review the auth module", deps=deps)
print(result.output.score)  # fully typed
```

### Multi-Agent Swarm

Spawn isolated subagents for parallel workstreams. Each subagent is a full deep agent with its own tool-calling, memory, and context:

```python
agent = create_deep_agent(
    subagents=[
        {
            "name": "researcher",
            "description": "Researches topics using web search",
            "instructions": "Search the web, synthesize findings, cite sources.",
        },
        {
            "name": "code-reviewer",
            "description": "Reviews code for quality, security, and performance",
            "instructions": "Check for security issues, N+1 queries, missing tests...",
        },
    ],
)
# Main agent delegates: task(description="Review auth.py", subagent_type="code-reviewer")
```

### Unlimited Context

Auto-summarization keeps long-running agents within the token budget:

```python
from pydantic_deep import create_summarization_processor

processor = create_summarization_processor(
    trigger=("tokens", 100000),  # compress at 100k tokens
    keep=("messages", 20),       # keep last 20 messages verbatim
)
agent = create_deep_agent(history_processors=[processor])
```

### Claude Code-Style Lifecycle Hooks

```python
from pydantic_deep import Hook, HookEvent

agent = create_deep_agent(
    hooks=[
        Hook(
            event=HookEvent.PRE_TOOL_USE,
            command="echo 'Tool: $TOOL_NAME args: $TOOL_INPUT' >> /tmp/audit.log",
        ),
    ],
)
```

### MCP Servers

```python
from pydantic_ai.capabilities import MCP

agent = create_deep_agent(
    capabilities=[MCP(url="https://mcp.example.com/api")],
)
```

### Context Files

Pydantic Deep Agents auto-discovers and injects project-specific context into every conversation:

| File | Purpose | Who Sees It |
|------|---------|-------------|
| `AGENTS.md` | Project conventions, architecture, instructions | Main agent + all subagents |
| `CLAUDE.md` | Claude Code project instructions | Main agent + all subagents |
| `SOUL.md` | Agent personality, style, communication preferences | Main agent only |
| `.cursorrules` | Cursor editor conventions | Main agent only |
| `.github/copilot-instructions.md` | GitHub Copilot instructions | Main agent only |
| `CONVENTIONS.md` | Project coding conventions | Main agent only |
| `CODING_GUIDELINES.md` | Coding guidelines | Main agent only |
| `MEMORY.md` | Persistent memory — read/write/update tools | Per-agent (isolated) |

Compatible with Claude Code, Cursor, GitHub Copilot, and other agent frameworks. `AGENTS.md` follows the [agents.md spec](https://agents.md/).

> See the full [API reference](https://vstorm-co.github.io/pydantic-deepagents/api/toolsets/) for all options.

---

## 🔬 DeepResearch — Reference App

A full-featured research deep agent with web UI — built entirely on Pydantic Deep Agents.

<table>
<tr>
<td width="50%">
<a href="apps/deepresearch/"><img src="assets/planner_asks_question.png" alt="Planner subagent asks clarifying questions"></a>
<p align="center"><b>Plan Mode</b> — planner asks clarifying questions</p>
</td>
<td width="50%">
<a href="apps/deepresearch/"><img src="assets/spawn_subagents_deepresearch.png" alt="Parallel subagent research"></a>
<p align="center"><b>Multi-Agent Swarm</b> — 5 subagents researching in parallel</p>
</td>
</tr>
<tr>
<td width="50%">
<a href="apps/deepresearch/"><img src="assets/excalidraw_in_deepresearch.png" alt="Excalidraw canvas"></a>
<p align="center"><b>Excalidraw Canvas</b> — live diagrams synced with agent</p>
</td>
<td width="50%">
<a href="apps/deepresearch/"><img src="assets/display_files_deepresearch.png" alt="File browser"></a>
<p align="center"><b>File Browser</b> — workspace files with inline preview</p>
</td>
</tr>
</table>

Web search (Tavily, Brave, Jina), sandboxed code execution, Excalidraw diagrams, plan mode, report export.

```bash
cd apps/deepresearch && uv sync && cp .env.example .env
uv run deepresearch    # → http://localhost:8080
```

> See [apps/deepresearch/README.md](apps/deepresearch/README.md) for full setup.

---

## Architecture

Pydantic Deep Agents uses pydantic-ai's native **Capabilities API** for all cross-cutting concerns — hooks, memory, skills, context files, teams, and plan mode are all first-class pydantic-ai capabilities.

### Capabilities

| Capability | Package | What It Does |
|-----------|---------|--------------|
| **CostTracking** | [pydantic-ai-shields](https://github.com/vstorm-co/pydantic-ai-shields) | Token/USD budget enforcement and real-time cost callbacks |
| **ContextManagerCapability** | [summarization-pydantic-ai](https://github.com/vstorm-co/summarization-pydantic-ai) | Unlimited context via auto-summarization |
| **LimitWarnerCapability** | [summarization-pydantic-ai](https://github.com/vstorm-co/summarization-pydantic-ai) | URGENT/CRITICAL warnings when context limits approach |
| **StuckLoopDetection** | pydantic-deep | Detects and breaks repetitive agent loops |
| **EvictionCapability** | pydantic-deep | Intercepts large tool outputs before they enter history |
| **PatchToolCallsCapability** | pydantic-deep | Fixes orphaned tool calls/results in history |
| **HooksCapability** | pydantic-deep | Claude Code-style PRE/POST_TOOL_USE lifecycle hooks |
| **CheckpointMiddleware** | pydantic-deep | Save, rewind, and fork conversation state |
| **WebSearch / WebFetch** | pydantic-ai built-in | Tool-calling: web search and URL fetching |
| **SkillsCapability** | pydantic-deep | Domain-specific skills from SKILL.md files |
| **MemoryCapability** | pydantic-deep | Persistent memory across sessions |
| **TeamCapability** | pydantic-deep | Multi-agent swarm — shared TODOs, message bus |
| **PlanCapability** | pydantic-deep | Structured planning before execution |

### Modular Packages

Every component is a standalone package — use only what you need:

| Package | What It Does |
|---------|--------------|
| [pydantic-ai-backend](https://github.com/vstorm-co/pydantic-ai-backend) | File storage, Docker sandbox, console toolset |
| [pydantic-ai-todo](https://github.com/vstorm-co/pydantic-ai-todo) | Task planning with subtasks and dependencies |
| [subagents-pydantic-ai](https://github.com/vstorm-co/subagents-pydantic-ai) | Sync/async delegation, background tasks, cancellation |
| [summarization-pydantic-ai](https://github.com/vstorm-co/summarization-pydantic-ai) | LLM summaries or zero-cost sliding window |
| [pydantic-ai-shields](https://github.com/vstorm-co/pydantic-ai-shields) | Cost tracking, input/output/tool blocking |

```
                         Pydantic Deep Agents
+---------------------------------------------------------------------+
|                                                                     |
|   +----------+ +----------+ +----------+ +----------+ +---------+   |
|   | Planning | |Filesystem| | Subagents| |  Skills  | |  Teams  |   |
|   +----+-----+ +----+-----+ +----+-----+ +----+-----+ +----+----+   |
|        |            |            |            |            |        |
|        +------------+-----+------+------------+------------+        |
|                           |                                         |
|                           v                                         |
|  Summarization --> +------------------+ <-- Capabilities            |
|  Checkpointing --> |    Deep Agent    | <-- Hooks                   |
|  Cost Tracking --> |   (pydantic-ai)  | <-- Memory                  |
|  Loop Detect   --> |                  | <-- Limit Warner            |
|                    +--------+---------+                             |
|                             |                                       |
|           +-----------------+-----------------+                     |
|           v                 v                 v                     |
|    +------------+    +------------+    +------------+               |
|    |   State    |    |   Local    |    |   Docker   |               |
|    |  Backend   |    |  Backend   |    |  Sandbox   |               |
|    +------------+    +------------+    +------------+               |
|                                                                     |
+---------------------------------------------------------------------+
```

---

## Full Feature List

<details>
<summary><b>Expand</b></summary>

### Tool-Calling

- `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`, `execute` — full filesystem access
- Docker sandbox with named workspaces — sandboxed execution, packages persist between sessions
- Web search (DuckDuckGo, Tavily, Brave) and web fetch
- Browser automation via Playwright — `navigate`, `click`, `type_text`, `screenshot`, `execute_js`, and more

### Deep Agent Architecture

- **Planning** — Task tracking with subtasks, dependencies, and cycle detection
- **Subagents / Multi-agent swarm** — Sync/async delegation, background task management, soft/hard cancellation
- **Agent Teams** — Shared TODO lists with claiming and dependency tracking, peer-to-peer message bus
- **Plan Mode** — Dedicated planner subagent for structured planning before execution
- **Persistent memory** — MEMORY.md that persists across sessions, auto-injected into system prompt
- **Self-improving** — `/improve` analyzes past sessions, proposes updates to context files

### Context & Memory

- **Unlimited context** — Auto-summarization when approaching token budget (LLM-based or sliding window)
- **Context limit warnings** — Model receives URGENT/CRITICAL messages when approaching 70% context usage
- **Eviction capability** — Intercepts large tool outputs via `after_tool_execute` before they enter history
- **Context files** — Auto-discover and inject AGENTS.md, CLAUDE.md, SOUL.md, .cursorrules, copilot-instructions, CONVENTIONS.md, CODING_GUIDELINES.md
- **Checkpoints** — Save state, rewind or fork conversations. In-memory and file-based stores. Per-run isolation via `for_run()`

### Reliability

- **Stuck loop detection** — Detects repeated identical calls, A-B-A-B alternating, and no-op patterns. Warns or stops the agent
- **Orphan repair** — Fixes orphaned tool calls/results in conversation history before each model request
- **Context limit warnings** — Injects URGENT/CRITICAL messages so the model knows to wrap up

### Production Features

- **MCP** — Connect any Model Context Protocol server
- **Lifecycle hooks** — Claude Code-style PRE/POST_TOOL_USE. Shell commands or Python handlers
- **Structured output** — Type-safe responses with Pydantic models via `output_type`
- **Cost tracking** — Token/USD budgets with automatic enforcement and real-time callbacks
- **Streaming** — Full streaming support for real-time responses
- **Image support** — Multi-modal analysis with image inputs
- **Human-in-the-loop** — Confirmation workflows for sensitive operations
- **Output styles** — Built-in (concise, explanatory, formal, conversational) or custom

### CLI

- Interactive TUI (Textual) with streaming, tool visualization, session management
- Headless runner (`pydantic-deep run`) for CI/CD, benchmarks, scripted automation
- 20+ slash commands: `/improve`, `/compact`, `/diff`, `/model`, `/provider`, `/skills`, `/theme`, and more
- `@filename` file references, `!command` shell passthrough
- Tool approval dialogs with auto-approve
- Debug logging per session

</details>

---

## Contributing

```bash
git clone https://github.com/vstorm-co/pydantic-deepagents.git
cd pydantic-deepagents
make install
make test   # 100% coverage required
make all    # lint + typecheck + test
```

---

## Vstorm OSS Ecosystem

**pydantic-deepagents** is part of a broader open-source ecosystem for production AI agents:

| Project | Description | |
|---------|-------------|---|
| **[full-stack-ai-agent-template](https://github.com/vstorm-co/full-stack-ai-agent-template)** | Zero to production AI app in 30 minutes. FastAPI + Next.js 15, 6 AI frameworks (incl. pydantic-deep), RAG pipeline, 75+ config options. | [![Stars](https://img.shields.io/github/stars/vstorm-co/full-stack-ai-agent-template?style=flat&logo=github&color=yellow)](https://github.com/vstorm-co/full-stack-ai-agent-template) |
| **[pydantic-ai-shields](https://github.com/vstorm-co/pydantic-ai-shields)** | Drop-in guardrails for Pydantic AI agents. 5 infra + 5 content shields. | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-ai-shields?style=flat&logo=github&color=yellow)](https://github.com/vstorm-co/pydantic-ai-shields) |
| **[pydantic-ai-subagents](https://github.com/vstorm-co/pydantic-ai-subagents)** | Declarative multi-agent orchestration with token tracking. | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-ai-subagents?style=flat&logo=github&color=yellow)](https://github.com/vstorm-co/pydantic-ai-subagents) |
| **[pydantic-ai-summarization](https://github.com/vstorm-co/pydantic-ai-summarization)** | Smart context compression for long-running agents. | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-ai-summarization?style=flat&logo=github&color=yellow)](https://github.com/vstorm-co/pydantic-ai-summarization) |
| **[pydantic-ai-backend](https://github.com/vstorm-co/pydantic-ai-backend)** | Sandboxed execution for AI agents. Docker + Daytona. | [![Stars](https://img.shields.io/github/stars/vstorm-co/pydantic-ai-backend?style=flat&logo=github&color=yellow)](https://github.com/vstorm-co/pydantic-ai-backend) |
| **[content-skills](https://github.com/vstorm-co/content-skills)** | Claude Code content studio — blog, social, slides, video, infographics — all brand-aware. | [![Stars](https://img.shields.io/github/stars/vstorm-co/content-skills?style=flat&logo=github&color=yellow)](https://github.com/vstorm-co/content-skills) |
| **[production-stack-skills](https://github.com/vstorm-co/production-stack-skills)** | Claude Code skills for production-grade FastAPI, PostgreSQL, Docker, and observability. | [![Stars](https://img.shields.io/github/stars/vstorm-co/production-stack-skills?style=flat&logo=github&color=yellow)](https://github.com/vstorm-co/production-stack-skills) |

> **Want the full stack?** Use [full-stack-ai-agent-template](https://github.com/vstorm-co/full-stack-ai-agent-template) — it ships pydantic-deep integrated with FastAPI, Next.js, auth, WebSocket streaming, and RAG out of the box.

Browse all projects at [oss.vstorm.co](https://oss.vstorm.co)

---

## Star History

<p align="center">
  <a href="https://www.star-history.com/#vstorm-co/pydantic-deepagents&type=date">
    <img src="https://api.star-history.com/svg?repos=vstorm-co/pydantic-deepagents&type=date" alt="Star History" width="600">
  </a>
</p>

---

## License

MIT — see [LICENSE](LICENSE)

---

<div align="center">

### Need help shipping AI agents in production?

<p>We're <a href="https://vstorm.co"><b>Vstorm</b></a> — an Applied Agentic AI Engineering Consultancy<br>with 30+ production agent implementations. Pydantic Deep Agents is what we build them with.</p>

<a href="https://vstorm.co/contact-us/">
  <img src="https://img.shields.io/badge/Talk%20to%20us%20%E2%86%92-0066FF?style=for-the-badge&logoColor=white" alt="Talk to us">
</a>

<br><br>

Made with **care** by <a href="https://vstorm.co"><b>Vstorm</b></a>

</div>
