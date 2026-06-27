# Advanced User Guide

The [Tutorial](../learn/index.md) gives you everything you need to build a real agent — files, tools, planning, subagents, structured output, memory. If you've worked through it, you already know enough to ship.

This guide is the next step. Each page here adds one **power feature** on top of what you already know.

## Read this after the Tutorial

The Advanced User Guide builds on the Tutorial, so it assumes you're comfortable with the basics: creating an agent, giving it a backend, running it. If a page references something you haven't seen, the Tutorial has it.

That said, you don't need to "graduate" to anything. The features here aren't harder — they're just more specialized. Most agents do great with the Tutorial alone.

## Pick what you need

Every page in this section is **independent**. There's no order to follow and nothing you're required to read. Skim the list, find the feature that solves your problem, and jump straight to it.

Each one follows the same shape as the Tutorial: a minimal example you can paste and run, then a piece-by-piece explanation, then a recap. You'll be productive in a few minutes.

!!! tip "Most of this is opt-in"
    A lot of these features are just a flag on [`create_deep_agent()`][pydantic_deep.create_deep_agent] or one item in the `capabilities` list. You add power without rewriting anything.

## The topics

**Lifecycle & control**

- [Capabilities & lifecycle](capabilities.md) — the hook points every other feature is built on. Start here if you want to understand the machinery.
- [Hooks](hooks.md) — run your own code (or shell commands) before and after every tool call.
- [Stuck-loop detection](stuck-loop-detection.md) — catch an agent repeating itself and break the cycle.
- [Periodic reminders](periodic-reminder.md) — keep the agent on track by re-injecting context on a schedule.

**Context & cost**

- [Context management](context-management.md) — eviction, summarization, and compaction so long runs stay within budget.
- [Cost tracking & budgets](cost-tracking.md) — track token spend in USD and stop a run before it gets expensive.

**Running & steering**

- [Goal loop](goal.md) — let the agent keep working until a goal is met.
- [Monitor](monitor.md) — watch a run and react to what it does in real time.
- [Message queue & steering](message-queue.md) — send the agent new instructions mid-run.
- [Live run forking](forking.md) — branch a running agent and explore alternatives in parallel.
- [Plan mode](plan-mode.md) — have the agent draft and confirm a plan before it touches anything.

**Scaling out**

- [Agent teams](teams.md) — coordinate multiple agents with a shared todo list and a message bus.
- [Multi-user / multi-tenant](multi-user.md) — run isolated agents for many users safely.
- [Fallback models](fallback-models.md) — automatically retry on another model when one fails.

**Output & tooling**

- [Output styles](output-styles.md) — shape how the agent writes its responses.
- [Browser](browser.md) — give the agent a real browser to navigate and act on the web.
- [Document parsing](liteparse.md) — turn PDFs and other documents into text the agent can read.
- [Agent Spec](agent-spec.md) — define an agent declaratively instead of in code.

## Where to go next

Pick a page above and run the example. If you're not sure where to start, [Capabilities & lifecycle](capabilities.md) explains the foundation that ties most of these together — and from there everything else clicks into place.
