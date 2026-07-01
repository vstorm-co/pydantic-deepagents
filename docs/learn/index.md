# Tutorial — User Guide

This tutorial shows you how to use **Pydantic Deep Agents** with most of its features, step by step.

Each section gradually builds on the previous ones, but it's structured to separate topics, so you can jump straight to the one that solves your problem. It also works as a future reference — come back any time and see exactly what you need.

## Run the code

All the code blocks can be copied and run directly. Every example is a complete, self-contained Python file.

It is **highly encouraged** that you write or copy the code, edit it, and run it locally. Using it in your editor is what really shows you the benefits — how little code you write, how everything is typed, how completion just works.

Most examples use an in-memory backend (`StateBackend`), so there's nothing to set up: paste, run, watch.

## Install

You'll want pydantic-deep installed and an API key for a model provider:

```bash
pip install pydantic-deep
export ANTHROPIC_API_KEY="sk-..."   # or OPENAI_API_KEY, etc.
```

That's the whole setup. See [Installation](../installation.md) for extras (sandboxing, the CLI, MCP) and other providers.

!!! tip "In a hurry?"
    Read [Your first agent](first-agent.md) and [Files & the shell](files-and-shell.md).
    Those two pages cover what most agents need; everything after them adds one capability at a time.

## What you'll build

By the end of this guide your agent will be able to read and write files, run shell commands, plan its work, call your own tools, delegate to sub-agents, stream its thinking, ask you before doing anything risky, and remember things between sessions — each introduced on its own page, on top of the same tiny starting example.

When you want to go further — the capability lifecycle, hooks, cost budgets, parallel run-forking, agent teams — head to the [Advanced User Guide](../advanced/index.md).

Ready?

- [Your first agent →](first-agent.md)
