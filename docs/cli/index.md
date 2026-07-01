# CLI — the terminal assistant

pydantic-deep ships its own terminal assistant: a Claude-Code-style coding agent that lives in your shell, built entirely on top of the [framework](../index.md) you've been reading about. You run it, it reads and writes your files, runs commands, searches the web, and remembers what you're working on — all inside a rich terminal UI.

It's the same agent you'd assemble with [`create_deep_agent`][pydantic_deep.create_deep_agent], wrapped in a [Textual](https://textual.textualize.io/) interface. Nothing is hidden behind a SaaS — it's your code, your machine, your model key.

## Install

```bash
pip install "pydantic-deep[cli]"
```

That's the whole install. The `[cli]` extra pulls in Textual and the TUI dependencies on top of the core framework.

!!! tip "One-line installer"
    On macOS and Linux you can also run the bootstrap script, which installs
    [uv](https://docs.astral.sh/uv/) for you and then does the rest:

    ```bash
    curl -fsSL https://raw.githubusercontent.com/vstorm-co/pydantic-deep/main/install.sh | bash
    ```

## Launch it

From any project directory, just run the command:

<div class="termy">

```console
$ cd my-project
$ pydantic-deep
```

</div>

The TUI opens. On the very first run it walks you through picking a provider and pasting an API key, then drops you into a chat. Type a request and watch the agent plan, edit files, and run commands live:

<div class="termy">

```console
$ pydantic-deep

> Find the failing test in tests/ and fix it

  ● write_todos    drafting a 3-step plan
  ● grep           "def test_" in tests/
  ● read           tests/test_auth.py
  ● edit           src/auth.py  (+4 -1)
  ● execute        pytest tests/test_auth.py  ✓ 1 passed

  Fixed it — the token check compared against the wrong field. Tests pass now.
```

</div>

You wrote one sentence. The planning, file editing, shell, and todo tracking all came for free — that's the framework doing the work.

## A tour of what it can do

The assistant is the framework's features made interactive. Here's the breadth:

- **Chat with a real coding agent.** Streaming responses, visible thinking, and every tool call rendered as it happens — no black box.
- **Files and the shell.** It reads, writes, edits, globs, and greps your project, and runs commands. Prefix a line with `!` to run a shell command yourself (`!git status`), or drop `@path/to/file` into a prompt to pull a file's contents in.
- **Subagents.** Big tasks get delegated to focused subagents that work in parallel, so the main thread stays clean.
- **MCP servers.** Connect [Model Context Protocol](sessions-forking-mcp.md) servers to give the agent extra tools — databases, issue trackers, your own services. Manage them live with `/mcp`.
- **Sessions.** Every conversation auto-saves. Resume any past one with `/load`, or manage them from the shell with `pydantic-deep threads list`.
- **Live forking.** Branch a running conversation to explore an alternative without losing your place — `/fork` to split, `/merge` to bring a branch back. See [Sessions, forking & MCP](sessions-forking-mcp.md).
- **Attachments and images.** Paste an image straight into the prompt (`/paste`) and the agent sees it; reference files with `@`.
- **Themes.** Four built-in color themes — switch instantly with `/theme ocean`.
- **Memory that sticks.** `/remember` saves a note across sessions; `/improve` reviews past sessions and proposes updates to your `AGENTS.md`, `SOUL.md`, and `MEMORY.md`.

!!! note "Headless too"
    The same agent runs non-interactively for CI, benchmarks, and scripts:

    ```bash
    pydantic-deep run "Fix the failing test in tests/test_auth.py" --json
    ```

    It prints the result (and usage stats with `--json`) and exits. See
    [Commands](commands.md) for the full `run` reference.

!!! tip "Sandbox it"
    Add `--sandbox docker` to either `pydantic-deep` or `pydantic-deep run` and
    every file and shell operation executes inside a container, with your
    working directory mounted at `/workspace`. Your code stays on disk; side
    effects stay in the box.

## Configure it

Settings live in `.pydantic-deep/config.toml` in your project, and the same
defaults drive both the TUI and headless runs. Change them from inside the app
with `/settings`, or from the shell:

```bash
pydantic-deep config set model anthropic:claude-sonnet-4-6
```

API keys are stored separately in `.pydantic-deep/keys.toml`, managed through
the `/provider` command. CLI flags always win over config-file values. Full
details in [Settings & themes](settings.md).

## Recap

- The CLI is a self-hosted, Claude-Code-style terminal assistant built on the very same `create_deep_agent` you've been learning.
- Install it with `pip install "pydantic-deep[cli]"` and launch it by running `pydantic-deep` in any project.
- Out of the box it gives you streaming chat, file and shell tools, subagents, MCP, auto-saved sessions, live forking, image attachments, themes, and persistent memory.
- Run the same agent headlessly with `pydantic-deep run`, and sandbox either mode with `--sandbox docker`.

### Where to go next

- [Install & first run →](getting-started.md) — set up a provider and send your first message.
- [Commands →](commands.md) — every slash command and `pydantic-deep` subcommand.
- [Keys & input →](keybindings.md) — shortcuts, `@` files, `!` shell, multiline input.
- [Settings & themes →](settings.md) — config file, providers, themes, sandboxing.
- [Sessions, forking & MCP →](sessions-forking-mcp.md) — save, resume, branch, and extend the assistant.
