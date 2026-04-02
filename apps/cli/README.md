<p align="center">
  <img src="../assets/baner.png" alt="pydantic-deep">
</p>

# Pydantic Deep Agents CLI

[![PyPI - Version](https://img.shields.io/pypi/v/pydantic-deep?label=%20)](https://pypi.org/project/pydantic-deep/#history)
[![PyPI - License](https://img.shields.io/pypi/l/pydantic-deep)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Coverage](https://coveralls.io/repos/github/vstorm-co/pydantic-deepagents/badge.svg?branch=main)](https://coveralls.io/github/vstorm-co/pydantic-deepagents?branch=main)

A Claude Code-style AI coding assistant for your terminal — powered by the [pydantic-deep](https://github.com/vstorm-co/pydantic-deepagents) framework and [pydantic-ai](https://github.com/pydantic/pydantic-ai).

<p align="center">
  <img src="../assets/cli_demo.gif" alt="pydantic-deep CLI demo" width="700">
</p>

## Quick Install

```bash
pip install pydantic-deep[cli]
pydantic-deep chat
```

## What is this?

The pydantic-deep CLI wraps the full [pydantic-deep](https://github.com/vstorm-co/pydantic-deepagents) agent framework into a terminal tool that works like Claude Code or LangChain's Deep Agents CLI. It gives an LLM full access to your local filesystem, shell, planning tools, and skills — so it can autonomously execute complex coding tasks.

Unlike simple chat wrappers, pydantic-deep implements the **deep agent architecture**: planning, subagent delegation, persistent memory, and context management — the same patterns powering Claude Code, Manus AI, and Devin.

## Usage

### Interactive Chat

```bash
pydantic-deep chat
pydantic-deep chat --model anthropic:claude-sonnet-4-20250514
```

Features: 17 slash commands (`/help`, `/compact`, `/context`, `/model`, ...), colored diff viewer for file approvals, visual progress bar, tool call timing, @file mentions, and Ctrl+V image paste.

### Non-Interactive (Benchmark Mode)

```bash
# stdout = response only (clean for piping), stderr = diagnostics
pydantic-deep run "Fix the failing tests in src/"
pydantic-deep run "Create a REST API with FastAPI" --model anthropic:claude-sonnet-4-6
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

### Custom Commands

Built-in slash commands loaded from `.md` files:

| Command | Description |
|---------|-------------|
| `/commit` | Stage and commit changes with a generated message |
| `/pr` | Create a pull request from current branch |
| `/review` | Review code changes for bugs, security, and style |
| `/test` | Generate or run tests for the current code |
| `/fix` | Find and fix bugs in the codebase |
| `/explain` | Explain how code works |

Three-scope discovery: built-in, user (`~/.pydantic-deep/commands/`), and project (`.pydantic-deep/commands/`).

### Configuration

```bash
pydantic-deep config show
pydantic-deep config set model anthropic:claude-sonnet-4-20250514
```

Config file: `~/.pydantic-deep/config.toml`

```toml
model = "anthropic:claude-sonnet-4-6"
include_skills = true
include_plan = true
include_memory = true
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
- **Context Discovery** — auto-inject AGENT.md into system prompt
- **Context Management** — auto-compression when approaching token limits
- **Custom Commands** — `/commit`, `/pr`, `/review`, `/test`, `/fix`, `/explain` + user/project commands
- **Loop Detection** — break infinite tool call retries
- **Cost Tracking** — real-time token/USD display
- **Git Context** — branch, status, and directory tree in system prompt
- **Rich Terminal UI** — colored diffs for file approvals, visual progress bar, tool timing

## Architecture

```
cli/
├── main.py              — Typer entry (run, chat, init, skills, threads, config)
├── agent.py             — create_cli_agent() factory
├── prompts.py           — Modular system prompt (dynamic assembly)
├── config.py            — Config system (~/.pydantic-deep/config.toml)
├── init.py              — Project initialization (pydantic-deep init)
├── non_interactive.py   — Headless execution (benchmark + sandbox)
├── interactive.py       — Chat loop (Rich streaming + tool approval)
├── local_context.py     — Git/directory context injection
├── commands.py          — Custom command discovery and loading
├── theme.py             — Color palette + Unicode/ASCII glyph system
├── tool_display.py      — Smart tool call formatting + result previews
├── diff_display.py      — Colored diffs + file previews for approval
├── picker.py            — Interactive model/session picker
├── providers.py         — Model provider registry
├── commands/            — Built-in command .md files
│   ├── commit.md
│   ├── pr.md
│   ├── review.md
│   ├── test.md
│   ├── fix.md
│   └── explain.md
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
- **[DeepResearch](https://github.com/vstorm-co/pydantic-deepagents/tree/main/apps/deepresearch)** — Full-featured reference app
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

---

<div align="center">

### Need help implementing this in your company?

<p>We're <a href="https://vstorm.co"><b>Vstorm</b></a> — an Applied Agentic AI Engineering Consultancy<br>with 30+ production AI agent implementations.</p>

<a href="https://vstorm.co/contact-us/">
  <img src="https://img.shields.io/badge/Talk%20to%20us%20%E2%86%92-0066FF?style=for-the-badge&logoColor=white" alt="Talk to us">
</a>

<br><br>

Made with &#10084;&#65039; by <a href="https://vstorm.co"><b>Vstorm</b></a>

</div>
