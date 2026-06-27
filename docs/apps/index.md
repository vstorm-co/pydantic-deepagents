# Applications

pydantic-deep is a framework — but the best way to see what it can do is to look at real apps built on it.

This section walks through four reference applications. Each one is a complete, working program that you can read, run, and copy from. They're not toy demos: they're the same `create_deep_agent()` you met in the tutorial, dressed in a real interface and pointed at a real job.

!!! tip "Learn by reading"
    Stuck on how to wire a feature into your own app? Open the reference app that
    uses it. The CLI shows streaming and sessions; DeepResearch shows subagents
    and plan mode; Harbor shows headless evaluation. Steal freely.

## CLI — the terminal assistant

A [Textual](https://textual.textualize.io/) TUI that turns pydantic-deep into a Claude-Code-style coding assistant, right in your terminal. You get a live chat view, streaming output, tool-call diffs, slash commands, sessions you can fork and resume, and MCP support — all on top of the framework's defaults.

It's the fastest way to *use* a deep agent without writing any glue code.

[Read the CLI guide →](../cli/index.md)

## DeepResearch

An autonomous research web app. You ask a question; it plans, searches the web, runs code, spawns subagents to chase down sub-questions in parallel, and assembles a cited answer — sketching its reasoning onto an Excalidraw canvas as it goes.

It's the showcase for the heavier features: [subagents](../advanced/teams.md), [plan mode](../advanced/plan-mode.md), web search, and code execution working together in one flow.

[Explore DeepResearch →](deepresearch.md)

## ACP adapter

Run a pydantic-deep agent *inside your editor*. The ACP adapter speaks the [Agent Client Protocol](https://agentclientprotocol.com/), so editors like [Zed](https://zed.dev/) can drive your agent as a native coding assistant — same tools, same backend, no terminal required.

It's a thin bridge: point it at an agent, and your editor does the rest.

[Set up the ACP adapter →](acp.md)

## Harbor

A [Terminal-Bench](https://www.tbench.ai/) evaluation adapter. Harbor wraps a deep agent in the harness Terminal-Bench expects, so you can measure how your agent actually performs on real terminal tasks — headless, reproducible, scored.

It's how you turn "feels good" into a number.

[Run Harbor →](harbor.md)

## Recap

- The reference apps are **real programs built on the same framework** you've been learning — proof of what you can ship.
- **CLI** is a terminal assistant; **DeepResearch** is an autonomous research web app; **ACP** runs agents inside your editor; **Harbor** benchmarks them.
- Read them when you want a working pattern for a feature, not just an API.

Pick one and dive in:

- [CLI — the terminal assistant →](../cli/index.md)
- [DeepResearch →](deepresearch.md)
- [ACP adapter →](acp.md)
- [Harbor →](harbor.md)
