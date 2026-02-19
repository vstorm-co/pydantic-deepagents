# pydantic-deep CLI

[![PyPI - Version](https://img.shields.io/pypi/v/pydantic-deep?label=%20)](https://pypi.org/project/pydantic-deep/#history)
[![PyPI - License](https://img.shields.io/pypi/l/pydantic-deep)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Coverage](https://coveralls.io/repos/github/vstorm-co/pydantic-deepagents/badge.svg?branch=main)](https://coveralls.io/github/vstorm-co/pydantic-deepagents?branch=main)

A Claude Code-style AI coding assistant for your terminal — powered by the [pydantic-deep](https://github.com/vstorm-co/pydantic-deepagents) framework and [pydantic-ai](https://github.com/pydantic/pydantic-ai).

## Quick Install

```bash
pip install pydantic-deep[cli]
pydantic-deep chat
```

## What is this?

The pydantic-deep CLI wraps the full [pydantic-deep](https://github.com/vstorm-co/pydantic-deepagents) agent framework into a terminal tool that works like Claude Code or LangChain's Deep Agents CLI. It gives an LLM full access to your local filesystem, shell, planning tools, and skills — so it can autonomously execute complex coding tasks.

Unlike simple chat wrappers, pydantic-deep implements the **deep agent architecture**: planning, subagent delegation, persistent memory, and context management — the same patterns powering Claude Code, Manus AI, and Devin.

**Key difference from LangChain's Deep Agents CLI:** pydantic-deep CLI reuses ~7,200 LOC of existing framework code and ships at ~1,400 LOC total. All features are enabled by default. Built on pydantic-ai instead of LangGraph.

## Usage

### Interactive Chat

```bash
pydantic-deep chat
pydantic-deep chat --model anthropic:claude-sonnet-4-20250514
```

### Non-Interactive (Benchmark Mode)

```bash
# stdout = response only (clean for piping), stderr = diagnostics
pydantic-deep run "Fix the failing tests in src/"
pydantic-deep run "Create a REST API with FastAPI" --model openai:gpt-4.1
pydantic-deep run "Refactor the auth module" --quiet
```

### Docker Sandbox

Run in an isolated Docker container:

```bash
pydantic-deep run "Build a web scraper" --sandbox --runtime python-web
pydantic-deep chat --sandbox --runtime python-datascience
```

| Runtime | Description |
|---------|-------------|
| `python-minimal` | Python 3.12 (default) |
| `python-datascience` | Python + numpy, pandas, matplotlib |
| `python-web` | Python + FastAPI, Django, Flask |
| `node-minimal` | Node.js 20 |
| `node-react` | Node.js + React, Next.js |

### Skills Management

```bash
pydantic-deep skills list                     # List built-in + user skills
pydantic-deep skills info code-review         # Show skill details
pydantic-deep skills create my-skill          # Scaffold a new SKILL.md
```

### Conversation Threads

```bash
pydantic-deep threads list                    # List saved sessions
pydantic-deep threads delete abc12345         # Delete by ID prefix
```

### Configuration

```bash
pydantic-deep config show
pydantic-deep config set model anthropic:claude-sonnet-4-20250514
```

Config file: `~/.pydantic-deep/config.toml`

```toml
model = "openai:gpt-4.1"
include_skills = true
include_plan = true
include_memory = true
include_checkpoints = true
shell_allow_list = ["python", "pip", "npm", "make"]
```

CLI arguments always override config file values.

## Built-in Skills

| Skill | Description |
|-------|-------------|
| `skill-creator` | Create new reusable skills from conversation context |
| `code-review` | Systematic code review for bugs, security, style, and performance |
| `test-writer` | Generate comprehensive test suites for existing code |
| `refactor` | Refactor code to improve structure and maintainability |
| `git-workflow` | Git operations: commits, branches, PRs, and conflict resolution |

Skills are `SKILL.md` files with YAML frontmatter. Create your own:

```bash
pydantic-deep skills create my-skill --dir ~/.pydantic-deep/skills
```

## What's Included

The CLI wraps the full pydantic-deep framework with **all features enabled by default**:

- **Planning** — TodoToolset for structured task breakdown
- **Filesystem** — read, write, edit, glob, grep, execute
- **Subagents** — parallel delegation to specialist agents
- **Skills** — 5 built-in + custom SKILL.md files
- **Persistent Memory** — MEMORY.md across sessions
- **Checkpointing** — save, rewind, and fork conversations
- **Context Discovery** — auto-inject DEEP.md, CLAUDE.md, SOUL.md
- **Context Management** — auto-compression when approaching token limits
- **Loop Detection** — break infinite tool call retries
- **Cost Tracking** — real-time token/USD display
- **Git Context** — branch, status, and directory tree in system prompt

## Architecture

```
pydantic_deep/cli/
├── main.py              — Typer entry (run, chat, skills, threads, config)
├── agent.py             — create_cli_agent() factory
├── prompts.py           — Modular system prompt (dynamic assembly)
├── config.py            — Config system (~/.pydantic-deep/config.toml)
├── non_interactive.py   — Headless execution (benchmark + sandbox)
├── interactive.py       — Chat loop (Rich formatting + sandbox)
├── local_context.py     — Git/directory context injection
├── middleware/
│   └── loop_detection.py
└── skills/              — Built-in SKILL.md files
    ├── skill-creator/
    ├── code-review/
    ├── test-writer/
    ├── refactor/
    └── git-workflow/
```

## Resources

- **[pydantic-deep SDK](https://github.com/vstorm-co/pydantic-deepagents)** — The underlying agent framework
- **[Documentation](https://vstorm-co.github.io/pydantic-deepagents/)** — Full docs
- **[DeepResearch](https://github.com/vstorm-co/pydantic-deepagents/tree/main/deepresearch)** — Full-featured reference app
- **[pydantic-ai](https://github.com/pydantic/pydantic-ai)** — The foundation

## Contributing

```bash
git clone https://github.com/vstorm-co/pydantic-deepagents.git
cd pydantic-deepagents
make install
make test   # 100% coverage required
make all    # lint + typecheck + test
```

See [CONTRIBUTING.md](https://github.com/vstorm-co/pydantic-deepagents/blob/main/CONTRIBUTING.md) for guidelines.

## License

MIT — see [LICENSE](https://github.com/vstorm-co/pydantic-deepagents/blob/main/LICENSE)
