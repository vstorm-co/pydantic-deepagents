# Project Overview: pydantic-deep

> **Package Name:** `pydantic-deep`  
> **Version:** 0.3.3  
> **License:** MIT  
> **Python Requirement:** >= 3.10

---

## What is pydantic-deep?

**pydantic-deep** is a **Deep Agent framework** built on top of Pydantic AI. It implements the "deep agent pattern" — the same architecture powering Claude Code, Manus AI, and Devin.

The project is four things in one:

1. **Python Framework** — Build autonomous agents with planning, filesystem access, subagent delegation, skills, memory, checkpointing, and teams
2. **CLI** — Terminal AI assistant (`pydantic-deep chat`)
3. **ACP Adapter** — Editor integration (Zed) via Agent Client Protocol
4. **DeepResearch** — A full-featured research agent with web UI

---

## Core Purpose

pydantic-deep provides a single high-level factory function (`create_deep_agent`) that assembles a fully-featured autonomous coding agent. The framework emphasizes:

- **Modularity** — Components can be independently enabled/disabled
- **Composability** — Capabilities combine in predictable ways
- **Extensibility** — Easy to add new tools, skills, and capabilities

---

## Technology Stack

| Component | Technology |
|-----------|------------|
| Language | Python >= 3.10 |
| Core Framework | pydantic-ai-slim >= 1.74.0 |
| Build Tool | hatchling |
| Data Models | pydantic >= 2.0 |

### Key Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `pydantic-ai-todo` | >= 0.2.1 | Task planning with dependencies |
| `pydantic-ai-backend` | >= 0.2.2 | File storage backends (StateBackend, LocalBackend, DockerSandbox) |
| `summarization-pydantic-ai` | >= 0.1.3 | Context compression / summarization |
| `subagents-pydantic-ai` | >= 0.2.1 | Multi-agent delegation |
| `pydantic-ai-shields` | >= 0.3.1 | Cost tracking, input/tool/output shields |
| `pydantic` | >= 2.0 | Data models |
| `chardet` | >= 5.0.0 | Character encoding detection |

---

## Key Features

### Planning
Task tracking with subtasks, dependencies, and cycle detection.

### Filesystem
Full file operations including:
- `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`, `execute`
- Docker sandbox support
- Permission system

### Subagents
- Synchronous and asynchronous delegation
- Background tasks
- Soft and hard cancellation

### Summarization
- LLM-based summaries
- Zero-cost sliding window option

### Cost Tracking
Token and USD budgets with automatic enforcement.

### Hooks
Claude Code-style lifecycle hooks — run shell commands on tool events.

### Checkpointing
Save, rewind, and fork conversation state.

### Skills
Domain-specific skills loaded from `SKILL.md` files.

### Context Files
Auto-discover and inject `AGENTS.md`, `SOUL.md`.

### Memory
Persistent `MEMORY.md` across sessions.

### Teams
Multi-agent teams with:
- Shared TODOs
- Task claiming
- Dependency tracking

### Web
Built-in `WebSearch` and `WebFetch` capabilities.

---

## Project Structure

```
pydantic-deepagents/
├── pydantic_deep/              # Core framework package
│   ├── __init__.py             # Public API re-exports
│   ├── agent.py                # create_deep_agent() factory
│   ├── deps.py                 # DeepAgentDeps dependency container
│   ├── spec.py                 # YAML/JSON declarative agent spec
│   ├── types.py                # Type definitions and re-exports
│   ├── prompts.py              # BASE_PROMPT default system prompt
│   ├── styles.py               # Output styles (concise, explanatory, etc.)
│   ├── subagents.py            # Built-in subagent definitions (research)
│   ├── capabilities/           # pydantic-ai capability adapters
│   │   ├── context.py          # ContextFilesCapability
│   │   ├── hooks.py            # HooksCapability (lifecycle hooks)
│   │   ├── memory.py           # MemoryCapability
│   │   ├── plan.py             # PlanCapability
│   │   ├── skills.py           # SkillsCapability
│   │   └── teams.py            # TeamCapability
│   ├── processors/             # History processing pipeline
│   │   ├── eviction.py         # Large tool output eviction
│   │   ├── history_archive.py  # Conversation history search
│   │   └── patch.py            # Orphaned tool call repair
│   ├── toolsets/               # Tool collections
│   │   ├── checkpointing.py    # Checkpoint tools + middleware
│   │   ├── context.py          # Context file injection
│   │   ├── memory.py           # Persistent memory tools
│   │   ├── teams.py            # Multi-agent team tools
│   │   ├── plan/               # Interactive planning tools
│   │   └── skills/             # Skill discovery, loading, execution
│   └── bundled_skills/         # Built-in skills (10 skill packs)
├── apps/
│   ├── cli/                    # Terminal AI assistant (Typer + Rich)
│   ├── acp/                    # Editor integration (Agent Client Protocol)
│   └── deepresearch/           # Research agent with web UI (FastAPI)
├── examples/                   # 14 standalone example scripts
├── docs/                       # Documentation (MkDocs)
└── tests/                      # Test suite
```

---

## Getting Started

### Installation

```bash
pip install pydantic-deep
```

### Quick Start

```python
from pydantic_deep import create_deep_agent, create_default_deps

agent = create_deep_agent(model="anthropic:claude-sonnet-4-6")
deps = create_default_deps()
result = await agent.run("Explain the architecture of this project", deps=deps)
print(result.output)
```

### CLI Usage

```bash
pydantic-deep chat
```

---

## Architecture Summary

The framework follows a **layered architecture**:

```
Toolsets → Capabilities → Processors → Agent Factory
```

Each layer is composable and can be independently enabled/disabled via boolean flags in `create_deep_agent()`.

### Core Components

1. **Agent Factory** (`agent.py`) — The entry point that assembles the agent with all configured capabilities
2. **Dependency Container** (`deps.py`) — `DeepAgentDeps` manages all state and configuration
3. **Capabilities** — Modular feature adapters that extend agent behavior
4. **Toolsets** — Collections of tools available to the agent
5. **Processors** — History processing pipeline for managing context

### State Flow

All state flows through `DeepAgentDeps`, a dependency injection container that provides:
- Configuration options
- Backend storage instances
- Planning state
- Memory state
- Team coordination state
- Cost tracking accumulators

The system is built on pydantic-ai's `Agent`, which provides the core LLM interaction loop.

---

## System Context Diagram (C4 Level 1)

```
┌─────────────────────────────────────────────────────────────┐
│                        External Users                        │
├─────────────┬─────────────────┬─────────────────────────────┤
│  Developer  │  CLI User       │  Editor User (Zed)          │
│  (Python)   │  (Terminal)     │  (ACP Protocol)             │
└──────┬──────┴────────┬────────┴────────────┬────────────────┘
       │               │                     │
       ▼               ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│                     pydantic-deep                            │
│                                                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐ │
│  │ Framework   │  │ CLI App     │  │ ACP Adapter         │ │
│  │ (API)       │  │ (Typer)     │  │ (Editor Integration) │ │
│  └──────┬──────┘  └──────┬──────┘  └──────────┬──────────┘ │
│         │                │                     │            │
│         ▼                ▼                     ▼            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Core Agent (pydantic-ai)                │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Capabilities: Planning | Filesystem | Subagents |   │  │
│  │  Memory | Skills | Teams | Checkpointing | Web       │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                    │           │           │
                    ▼           ▼           ▼
        ┌───────────────┐ ┌─────────┐ ┌──────────────┐
        │ LLM Providers │ │ Storage │ │ Web Services │
        │ (Anthropic,   │ │ Backends│ │ (Search,     │
        │  OpenAI, etc) │ │         │ │  Fetch)      │
        └───────────────┘ └─────────┘ └──────────────┘
```

---

## Related Documentation

- [C4 Level 2: Container View](./2-container-view.md)
- [C4 Level 3: Component View](./3-component-view.md)
- [Architecture Deep Dive](../architecture/)
- [API Reference](../api/)
- [Getting Started Guide](../installation.md)