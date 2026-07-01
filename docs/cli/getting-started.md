# Install & first run

Let's get the pydantic-deep CLI running in your terminal and have your first conversation with it. Install, point it at a model, launch, and start typing — that's the whole path.

## Install it

The CLI ships as an extra on the `pydantic-deep` package:

<div class="termy">

```console
$ pip install "pydantic-deep[cli]"
```

</div>

That gives you the `pydantic-deep` command — a Claude Code-style AI coding assistant built on the full [pydantic-deep](../index.md) framework.

!!! tip "Prefer an isolated tool install?"
    Use [uv](https://docs.astral.sh/uv/) to install it as a standalone tool, off your project's dependencies:

    ```console
    $ uv tool install "pydantic-deep[cli]"
    ```

## Set an API key

The CLI talks to a model provider, so it needs a key. Set one environment variable for the provider you want:

<div class="termy">

```console
$ export ANTHROPIC_API_KEY="sk-ant-..."     # Anthropic (Claude)
$ export OPENAI_API_KEY="sk-..."            # OpenAI (GPT)
$ export OPENROUTER_API_KEY="sk-or-..."     # OpenRouter (many models)
$ export GOOGLE_API_KEY="..."               # Google (Gemini)
```

</div>

You only need the one that matches your model. Running [Ollama](https://ollama.com/) locally needs no key at all.

### Where keys are loaded from

You don't have to keep exporting the key every session. The CLI reads keys from several places, and the **first one to set a variable wins**:

1. **Real shell environment** — anything already in `os.environ` (e.g. `export ANTHROPIC_API_KEY=…`). Always wins.
2. **`./.pydantic-deep/.env`** — project-local, ignored by git.
3. **`./.env`** — your project's `.env`, if you keep one.
4. **`~/.pydantic-deep/.env`** — a global fallback for keys you reuse everywhere.

Project files beat the global fallback, so a per-project key in `./.env` always shadows a stale global one.

!!! info "The `/provider` flow writes them for you"
    On first launch the CLI walks you through provider setup and saves your key
    to `.pydantic-deep/keys.toml` (also git-ignored). You can re-run it any time
    with the `/provider` command — no manual file editing required.

!!! warning "Keep keys out of git"
    Both `.pydantic-deep/.env` and `.pydantic-deep/keys.toml` hold secrets. The
    `init` command git-ignores `.pydantic-deep/` for you; if you add a key to a
    plain `./.env`, make sure it's ignored too.

## Launch it

From any project directory, just run:

<div class="termy">

```console
$ pydantic-deep
```

</div>

That's it — no subcommand needed. The CLI initializes a `.pydantic-deep/` folder for the project (config, sessions, logs) and opens the interactive TUI: a rich terminal interface with streaming chat, tool-call visualization, and slash commands.

!!! example "Check it"
    Want to pick the model up front? Pass it on the command line:

    ```console
    $ pydantic-deep --model anthropic:claude-sonnet-4-6
    ```

    `--model` takes any model string Pydantic AI understands —
    `anthropic:…`, `openai:…`, `google-gla:…`, `openrouter:…`, and more.
    Command-line flags always override your saved config.

## Your first conversation

Once the TUI is up, you're in a prompt. Three special first characters change what your input means.

**Just type a message** and press Enter to talk to the agent:

```
> Read main.py and tell me what it does
```

The agent reads the file, may run a few tools (you'll see each call appear inline), then streams its answer back.

**Type `/`** to open the command picker. Slash commands control the session rather than the agent:

```
> /help          show every command and shortcut
> /model         switch models with an interactive picker
> /context       see how much of the context window you've used
> /clear         start a fresh conversation
```

**Type `@`** to reference a file. The CLI pops up a file picker and inlines the file's contents into your prompt:

```
> Explain the error handling in @apps/cli/config.py
```

**Type `!`** to run a shell command directly, without involving the model:

```
> !git status
> !make test
```

!!! tip "Sensitive tools ask first"
    When the agent wants to run something like `execute`, an approval modal
    pops up: **Y** to allow once, **A** to auto-approve, **N** to deny,
    **Esc** to cancel. You stay in control of what actually runs.

## Recap

You've got the CLI installed and talking:

- `pip install "pydantic-deep[cli]"` (or `uv tool install`) gives you the `pydantic-deep` command.
- Set a provider key as an env var, or let `/provider` save it — keys load from the shell first, then project `.env` files, then a global `~/.pydantic-deep/.env`.
- Run `pydantic-deep` with no arguments to launch the TUI; `--model` overrides the default.
- In the prompt, plain text talks to the agent, `/` opens commands, `@` inlines files, and `!` runs the shell.

Now let's dig into everything the slash commands can do.

- [Commands →](commands.md)
