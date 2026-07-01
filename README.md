<h1 align="center">Pydantic Deep Agents</h1>

<p align="center">
  <b>Open-source Claude Code — that you can also build on.</b><br>
  A self-hosted <b>terminal AI assistant</b> <i>and</i> the <b>Python framework</b> behind it.<br>
  Use it today, or ship your own agent in <b>one function call</b>. Any model. 100% type-safe. MIT.
</p>

<p align="center">
  <img src="assets/cli_demo_v2.gif" alt="Pydantic Deep Agents CLI demo" width="800">
</p>

<p align="center">
  <a href="https://vstorm-co.github.io/pydantic-deepagents/">Docs</a> &middot;
  <a href="https://pypi.org/project/pydantic-deep/">PyPI</a> &middot;
  <a href="#-live-run-forking--the-feature-no-one-else-has">Forking</a> &middot;
  <a href="#-why-pydantic-deep">Why</a> &middot;
  <a href="#-cli--terminal-ai-assistant">CLI</a> &middot;
  <a href="#-framework--build-your-own-agent">Framework</a> &middot;
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

**Pydantic Deep Agents is two things in one repo:**

🖥️ **A terminal AI assistant** — a self-hosted, open-source alternative to Claude Code. Install it, point it at any model, and it plans, edits files, runs commands, searches the web, remembers across sessions, spawns sub-agents, and connects to MCP servers. Almost everything Claude Code does — on the model *you* choose.

🐍 **A Python framework** — the *exact same harness* behind a single function call. `create_deep_agent()` hands a model a filesystem, shell, planning, memory, sub-agents, sandboxed execution, MCP, and unlimited context. Build your own assistant, research agent, or coding tool without rewiring the plumbing every time.

Both run on **[Pydantic AI](https://github.com/pydantic/pydantic-ai)**, work with **any model** (Claude, GPT, Gemini, local), and are **100% type-safe** and MIT-licensed — and they share one trick nothing else has: [**Live Run Forking**](#-live-run-forking--the-feature-no-one-else-has), splitting a single run into parallel branches an AI judge merges back together.

## Two ways to use it

### 🖥️ 1. Use the assistant

A Claude-Code-style TUI in your terminal, on **any** model — no Python setup (the script installs `uv` + the CLI for you):

```bash
curl -fsSL https://raw.githubusercontent.com/vstorm-co/pydantic-deep/main/install.sh | bash
pydantic-deep
```

> Windows / manual: `pip install "pydantic-deep[cli]"`

### 🐍 2. Build your own

One function call gives you a full deep agent:

```bash
pip install pydantic-deep
```

```python
from pydantic_deep import create_deep_agent

agent = create_deep_agent(model="anthropic:claude-sonnet-4-6")
result = await agent.run("Build a REST API for auth")
```

---

## ⑂ Live Run Forking — the feature no one else has

Claude Code can't do this. Aider can't. LangGraph and CrewAI can't. **It's the reason to use pydantic-deep.**

When an agent hits a fork in the road — "should I refactor this with a decorator or a context manager?" — most tools force one bet. Pydantic Deep Agents lets the run **branch**:

```
                                  ┌──  branch A: "use a decorator"      ── tests: 8/8 ✓  conf 0.71
   agent.run("refactor auth") ──┬─┼──  branch B: "use a context manager" ── tests: 6/8 ✗  conf 0.42
       (shared history)         │ └──  branch C: "extract a base class"   ── tests: 8/8 ✓  conf 0.55
                                │
                                └──►  ⚖️  AI judge weighs quality + tests + consistency
                                          → adopts branch A, continues the run
```

Each branch is **fully isolated**: a copy-on-write filesystem overlay (reads fall through to the parent, writes stay local), its own steering message, and its own `budget_usd` cap. The coordinator resolves the fork with one of four acceptance modes — `manual`, `auto`, `auto_with_fallback` (default), or `vote` — and the winning branch's history is adopted as the parent run's continuation.

**Framework — opt in with one flag:**

```python
agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    forking=True,                 # gives the agent: fork_run, inspect_branches,
)                                 # merge_or_select, diff_branches, fork_cost, terminate_branch
```

**Or run a real test command against every branch and let exit codes decide the winner:**

```python
from pydantic_deep import LiveForkCapability

agent = create_deep_agent(
    forking=LiveForkCapability(test_command="pytest -q", test_timeout_s=120),
)
# confidence = quality_spread·0.4 + test_pass_ratio·0.4 + internal_consistency·0.2
```

**CLI — fork an in-flight conversation, watch branches stream live, merge the best:**

```
/fork                 # split the current run into N parallel branches
>>A try a decorator   # steer branch A
>>B use a contextmgr  # steer branch B
/merge                # resolve — manual picker, AI judge, or vote
```

Live per-branch panels stream each approach side by side; a judge screen scores them; you accept, review the diff, or decline. Configure branch count, budgets, per-branch models, and merge strategy with `/fork-config`.

> 📖 Full reference: [docs/capabilities/live-fork.md](docs/capabilities/live-fork.md)

---

## 🆚 Why pydantic-deep?

The only tool that is **a terminal assistant** *and* **a Python framework** *and* can **fork its own runs** — without giving up type safety or your choice of model.

| | **Pydantic&nbsp;Deep** | Claude&nbsp;Code | Aider | LangGraph | CrewAI |
|---|:---:|:---:|:---:|:---:|:---:|
| Terminal TUI assistant | ✅ | ✅ | ✅ | — | — |
| Python framework / library | ✅ | — | ~ | ✅ | ✅ |
| **Live run forking + AI judge** | ✅ | — | — | — | — |
| Multi-agent swarm + message bus | ✅ | ~ | — | ✅ | ✅ |
| Any model / any provider | ✅ | Anthropic | ✅ | ✅ | ✅ |
| Sandboxed Docker execution | ✅ | — | ~ | DIY | DIY |
| Persistent memory + skills | ✅ | ✅ | — | DIY | ~ |
| Type-safe structured output | ✅ | — | — | ~ | ~ |
| MCP servers | ✅ | ✅ | — | ~ | ~ |
| Self-hosted, open source | ✅ MIT | — | ✅ | ✅ | ✅ |

<sub>✅ first-class · ~ partial / via extensions · — not available · DIY you wire it yourself. Comparison reflects each project as of 2026-06; corrections welcome via PR.</sub>

---

## What's New

- **2026-06-01** &nbsp;**v0.3.24** — **Live Run Forking** — split an in-flight `agent.run()` into N parallel branches with copy-on-write isolation, per-branch budgets, a test-runner hook, and four merge modes (`manual` / `auto` / `auto_with_fallback` / `vote`). Opt in with `forking=True`.
- **2026-06-01** &nbsp;**v0.3.23** — **MCP client support** (framework + CLI). Connect GitHub, Figma (OAuth), Context7, DeepWiki, or any custom server. Import servers straight from Claude Code. New interactive `/mcp` command. Plus a full CLI presentation pass: clipboard image paste, real `+/-` diffs, tool icons, turn summaries.
- **2026-06-01** &nbsp;**v0.3.23** — **Automatic fallback-model retry** — `fallback_model=` wraps your primary in a `FallbackModel` chain; fires on API errors but never on auth errors. Plus a batteries-included **security hook preset** (`default_security_hook()`) and three new output styles (`markdown`, `json-only`, `bullet`).
- **2026-04-22** &nbsp;**v0.3.17** — LiteParse document parsing (`include_liteparse=True`) — PDFs, DOCX, XLSX, PPTX, and images with optional OCR, all local.
- **2026-04-10** &nbsp;**v0.3.5** — Headless runner (`pydantic-deep run`), Docker sandbox with named workspaces, browser automation via Playwright.

> Full history: [CHANGELOG.md](CHANGELOG.md)

---

## The Agent Harness

Pydantic Deep Agents is an **agent harness** — the complete infrastructure that wraps an LLM and makes it a functional autonomous agent. The model provides intelligence; the harness provides planning, tools, memory, sandboxed execution, unlimited context, and — uniquely — the ability to fork.

<table>
<tr>
<td><b>⑂ Live run forking</b></td>
<td>Split a run into N isolated branches, each trying a different approach. AI judge or test results pick the winner. <b>No other agent framework has this.</b></td>
</tr>
<tr>
<td><b>🔧 Tool-calling</b></td>
<td>File read/write/edit, shell execution, glob, grep, web search, web fetch, browser automation — wired up and ready.</td>
</tr>
<tr>
<td><b>🤝 Multi-agent / swarm</b></td>
<td>Spawn subagents for parallel workstreams. Shared TODO lists with claiming. Peer-to-peer message bus. Full team coordination.</td>
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
<td>Domain-specific knowledge loaded on demand from SKILL.md files. Built-in: code-review, refactor, test-writer, git-workflow, and more.</td>
</tr>
<tr>
<td><b>📄 Document parsing</b></td>
<td>Parse PDFs, DOCX, XLSX, PPTX, and images with optional OCR via LiteParse. Runs locally — no cloud services required.</td>
</tr>
<tr>
<td><b>🔌 MCP</b></td>
<td>Connect any Model Context Protocol server — GitHub, Figma (OAuth), Context7, DeepWiki, or custom. Import straight from Claude Code.</td>
</tr>
<tr>
<td><b>⚡ Lifecycle hooks + security preset</b></td>
<td>Claude Code-style PRE/POST_TOOL_USE hooks. Shell or Python handlers. <code>default_security_hook()</code> blocks destructive commands out of the box.</td>
</tr>
<tr>
<td><b>📐 Structured output</b></td>
<td>Type-safe Pydantic model responses via <code>output_type</code>. No JSON parsing. No <code>dict["key"]</code>. Full IDE autocomplete.</td>
</tr>
<tr>
<td><b>🔁 Fallback models</b></td>
<td>Primary model fails? <code>fallback_model=</code> hops to the next in the chain — on API errors, never on auth errors.</td>
</tr>
<tr>
<td><b>🔄 Stuck loop detection</b></td>
<td>Detects repeated identical tool calls, A-B-A-B alternating patterns, and no-op calls. Warns the model or stops the run.</td>
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

A Claude Code-style terminal AI assistant that works with **any model and any provider** — and forks.

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
| ⑂ | **Live run forking** — split a run into branches, stream them side by side, merge the winner |
| 💬 | Streaming chat with tool call visualization, icons, and real `+/-` diffs |
| 📁 | File read / write / edit, shell execution, glob, grep |
| 🤝 | Task planning, plan mode, and subagent delegation |
| 🧠 | Persistent memory and self-improvement across sessions |
| ♾️ | Context compression for unlimited conversations |
| 🔖 | Checkpoints — save, rewind, and fork any session |
| 🔌 | MCP servers via `/mcp` — GitHub, Figma (OAuth), and more; import from Claude Code |
| 🌐 | Web search & fetch built-in · 🖥️ browser automation via Playwright (`--browser`) |
| 🐳 | Docker sandbox — sandboxed execution with named workspaces |
| 💭 | Extended thinking — `minimal` / `low` / `medium` / `high` / `xhigh` |
| 📋 | Clipboard image paste (`Ctrl+V` / `/paste`) — multimodal prompts |
| 💰 | Real-time cost and token tracking per session |
| 🛡️ | Tool approval dialogs — approve, auto-approve, or deny per tool call |
| @ | `@filename` file references · `!command` shell passthrough |
| ✨ | `/fork`, `/merge`, `/improve`, `/skills`, `/mcp`, `/model`, `/theme`, `/compact`, and more |

### Usage

```bash
# Interactive TUI (default)
pydantic-deep
pydantic-deep tui --model openrouter:anthropic/claude-opus-4-6

# Headless deep agent — benchmarks, CI/CD, scripted automation
pydantic-deep run "Fix the failing test in test_auth.py"
pydantic-deep run --task-file task.md --json

# Docker sandbox — sandboxed execution, project dir mounted at /workspace
pydantic-deep tui --sandbox docker
pydantic-deep tui --workspace ml-env     # named workspace, packages persist

# Browser automation (requires pydantic-deep[browser])
pydantic-deep tui --browser

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

One function call gives you a production deep agent with planning, tool-calling, multi-agent delegation, persistent memory, unlimited context, forking, and cost tracking. Everything is a toggle:

```python
from pydantic_ai_backends import StateBackend
from pydantic_deep import create_deep_agent, create_default_deps

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    forking=True,               # ⑂ split a run into parallel branches + AI judge
    include_todo=True,          # Task planning with subtasks and dependencies
    include_subagents=True,     # Multi-agent swarm — delegate to subagents
    include_skills=True,        # Domain-specific skills from SKILL.md files
    include_memory=True,        # Persistent memory across sessions
    include_plan=True,          # Structured planning before execution
    include_teams=True,         # Agent teams with shared TODO lists + message bus
    include_liteparse=True,     # Document parsing — PDF, DOCX, XLSX + OCR
    web_search=True,            # Tool-calling: web search
    thinking="high",            # Extended thinking / reasoning effort
    context_manager=True,       # Unlimited context via auto-summarization
    cost_tracking=True,         # Token/USD budget enforcement
    fallback_model="openai:gpt-5.4",   # auto-retry if the primary model fails
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

### Claude Code-Style Lifecycle Hooks + Security Preset

```python
from pydantic_deep import create_deep_agent, default_security_hook, Hook, HookEvent

agent = create_deep_agent(
    hooks=[
        *default_security_hook(),   # blocks destructive shell, path traversal, secret leaks
        Hook(
            event=HookEvent.PRE_TOOL_USE,
            command="echo 'Tool: $TOOL_NAME args: $TOOL_INPUT' >> /tmp/audit.log",
        ),
    ],
)
```

### MCP Servers

Connect GitHub, Figma (OAuth), Context7, DeepWiki, or any custom server — auth handled for you:

```python
from pydantic_deep import create_deep_agent, build_mcp_server, MCPServerConfig

deepwiki = build_mcp_server(
    MCPServerConfig(name="deepwiki", transport="http", url="https://mcp.deepwiki.com/mcp")
)

agent = create_deep_agent(mcp_servers=[deepwiki])   # curated defaults via builtin_mcp_servers()
```

### Context Files

Pydantic Deep Agents auto-discovers and injects project-specific context into every conversation:

| File | Purpose | Who Sees It |
|------|---------|-------------|
| `AGENTS.md` | Project conventions, architecture, instructions | Main agent + all subagents |
| `CLAUDE.md` | Claude Code project instructions | Main agent + all subagents |
| `SOUL.md` | Agent personality, style, communication preferences | Main agent only |
| `.cursorrules` | Cursor editor conventions | Main agent only |
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

Pydantic Deep Agents uses pydantic-ai's native **Capabilities API** for all cross-cutting concerns — forking, hooks, memory, skills, context files, teams, and plan mode are all first-class pydantic-ai capabilities.

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
|  Forking       --> +------------------+ <-- Capabilities            |
|  Summarization --> |    Deep Agent    | <-- Hooks                   |
|  Checkpointing --> |   (pydantic-ai)  | <-- Memory                  |
|  Cost Tracking --> |                  | <-- MCP                     |
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

### Modular Packages

Every component is a standalone package — use only what you need:

| Package | What It Does |
|---------|--------------|
| [pydantic-ai-backend](https://github.com/vstorm-co/pydantic-ai-backend) | File storage, Docker sandbox, console toolset |
| [pydantic-ai-todo](https://github.com/vstorm-co/pydantic-ai-todo) | Task planning with subtasks and dependencies |
| [subagents-pydantic-ai](https://github.com/vstorm-co/subagents-pydantic-ai) | Sync/async delegation, background tasks, cancellation |
| [summarization-pydantic-ai](https://github.com/vstorm-co/summarization-pydantic-ai) | LLM summaries or zero-cost sliding window |
| [pydantic-ai-shields](https://github.com/vstorm-co/pydantic-ai-shields) | Cost tracking, input/output/tool blocking |

---

## Full Feature List

<details>
<summary><b>Expand</b></summary>

### Live Run Forking

- Split an in-flight `agent.run()` into N parallel branches sharing history up to the fork point
- Copy-on-write `BranchOverlay` filesystem isolation — reads fall through to parent, writes stay local
- Per-branch steering messages, per-branch `budget_usd` caps, aggregate budget enforcement
- Four merge modes: `manual`, `auto`, `auto_with_fallback` (default), `vote`
- Autonomous `JudgeAgent` with structured `JudgeVerdict`; `compute_confidence` blends quality, test pass ratio, and consistency
- Test-runner hook — run a shell command against each branch's snapshot; exit code feeds the judge
- Agent tools: `fork_run`, `inspect_branches`, `merge_or_select`, `terminate_branch`, `diff_branches`, `fork_cost`
- CLI: `/fork`, `/merge`, `/fork-config`, live per-branch streaming panels, judge screen, merge acceptance gate

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
- **Context files** — Auto-discover AGENTS.md, CLAUDE.md, SOUL.md, .cursorrules, copilot-instructions, and more
- **Checkpoints** — Save state, rewind or fork conversations. In-memory and file-based stores

### Production Features

- **MCP** — Connect any Model Context Protocol server; import from Claude Code; OAuth + keystore auth
- **Lifecycle hooks** — Claude Code-style PRE/POST_TOOL_USE. Shell commands or Python handlers
- **Security preset** — `default_security_hook()` blocks destructive commands, path traversal, secret leaks
- **Fallback models** — `fallback_model=` chains; fires on API errors, never on auth errors
- **Structured output** — Type-safe responses with Pydantic models via `output_type`
- **Cost tracking** — Token/USD budgets with automatic enforcement and real-time callbacks
- **Output styles** — Built-in (concise, explanatory, formal, conversational, markdown, json-only, bullet) or custom
- **Streaming · Image support · Human-in-the-loop confirmation workflows**

### CLI

- Interactive TUI (Textual) with streaming, tool visualization, live fork panels, session management
- Headless runner (`pydantic-deep run`) for CI/CD, benchmarks, scripted automation
- 25+ slash commands: `/fork`, `/merge`, `/mcp`, `/improve`, `/compact`, `/diff`, `/model`, `/skills`, `/theme`, and more
- `@filename` file references, `!command` shell passthrough, clipboard image paste
- Tool approval dialogs with auto-approve · debug logging per session

</details>

---

## Contributing

```bash
git clone https://github.com/vstorm-co/pydantic-deep.git
cd pydantic-deep
make install
make test   # 100% coverage required
make all    # lint + typecheck + test
```

See [CONTRIBUTING.md](CONTRIBUTING.md). Good first issues are [labeled here](https://github.com/vstorm-co/pydantic-deep/labels/good%20first%20issue).

---

## Vstorm OSS Ecosystem

**pydantic-deep** is part of a broader open-source ecosystem for production AI agents:

| Project | Description | Stars |
|---------|-------------|-------|
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

If pydantic-deep saved you from wiring an agent harness by hand — **[give it a ⭐](https://github.com/vstorm-co/pydantic-deep)**. It's the single biggest thing that helps the project grow.

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
