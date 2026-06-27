# Live Run Forking

*git branch, but for cognition.*

Sometimes you don't know which approach is best until you try a few. Live Run Forking lets you split an in-flight `agent.run()` into several parallel branches — they all share the conversation history up to the fork point, then explore different ideas in isolation. When they finish, you keep one winner and throw the rest away.

The branches run concurrently as `asyncio.Task`s, each with its own [`DeepAgentDeps`][pydantic_deep.DeepAgentDeps] — separate backends, todos, and message queues. Pick a winner and its file writes are flushed onto the parent backend; the losers are cancelled and their writes discarded.

## Enable it

Forking is off by default. Turn it on with one parameter.

```python hl_lines="10 11"
import asyncio

from pydantic_deep import (
    DeepAgentDeps,
    InMemoryCheckpointStore,
    StateBackend,
    create_deep_agent,
)


async def main() -> None:
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        forking=True,                 # opt-in; default is False
        include_checkpoints=True,     # the rewind safety net
    )
    deps = DeepAgentDeps(
        backend=StateBackend(),
        checkpoint_store=InMemoryCheckpointStore(),
    )

    result = await agent.run(
        "Use `fork_run` to spawn TWO branches naming a Python library: "
        "Branch A picks a whimsical name, Branch B a technical one. Each "
        "returns a 5-sentence pitch. Then call `inspect_branches`, then "
        "`merge_or_select(action='pick:<id>')` for the better pitch.",
        deps=deps,
    )
    print(result.output)


asyncio.run(main())
```

The agent drives the whole thing — `fork_run`, `inspect_branches`, and `merge_or_select` are just tools it calls.

### What `forking=True` gives you

`forking=True` enables sensible defaults: up to 10 branches per fork, one level of fork-nesting, and an in-memory state store. When you need to tune those, pass a configured capability instead.

```python
from pydantic_deep import LiveForkCapability

agent = create_deep_agent(
    forking=LiveForkCapability(max_branches=4, max_depth=2),
)
```

!!! tip "Keep checkpoints on"
    `fork_run` still works without `include_checkpoints=True`, but it emits a
    warning — there's no anchor to rewind to if something goes sideways. The
    coordinator saves `fork:<id>` before branching and `post-fork:<id>` after
    merge, so `/load` can take you back. See [Checkpointing](../learn/sessions.md).

## The fork tools

Enable forking and the agent gains a small toolkit. The three you'll see most:

| Tool | What it does |
|---|---|
| `fork_run(specs, ...)` | Spawn the branches. Each spec needs a `label` and a `steer` (the instruction for that branch); `model`, `budget_usd`, and `extra_instructions` are optional. |
| `inspect_branches()` | Report each branch's state: `running`, `done`, `failed`, `terminated`, or one of the budget-exhausted states. |
| `merge_or_select(action)` | Resolve the fork. `"pick:<id>"` keeps a winner, `"auto"` lets a judge decide, `"abort"` discards everything. |

And four more for finer control: `terminate_branch(id)` cancels one branch, `diff_branches(fork_id)` returns a typed report of what each branch changed, `fork_cost(fork_id)` totals per-branch token spend, and `delete_file(path)` records a deletion inside the current branch so it propagates on merge.

### Branches are isolated by default

Each branch reads through to the parent's files but writes into its own overlay — a copy-on-write wrapper, so branches never step on each other. Todos start empty per branch, and each branch gets its own message queue (so you can steer one without touching the others). History is always copied. These defaults are deliberately conservative; [`BranchIsolation`][pydantic_deep.features.forking.types.BranchIsolation] lets you loosen them.

### Budgets

Cap a single branch with `budget_usd` in its spec, or the whole fork with `aggregate_budget_usd`. When a branch crosses its cap it's cancelled (state `budget_exhausted`) while siblings keep going; when the aggregate is crossed, every running branch stops (`aggregate_budget_exhausted`). A budget-killed branch keeps the work it did before the cap fired — its partial history is still a valid merge candidate.

## Acceptance modes

When you resolve with `merge_or_select(action="auto")`, a cheap judge model inspects the structured diff plus each branch's outcome and picks a winner. How decisive that is depends on the [`MergeStrategy`][pydantic_deep.features.forking.types.MergeStrategy] you set.

```python
from pydantic_deep.types import MergeStrategy

MergeStrategy()                 # default: auto_with_fallback
MergeStrategy(kind="auto")      # judge picks, commits immediately
MergeStrategy(kind="vote")      # three judges, majority wins
MergeStrategy(kind="manual")    # you always pick
```

| Mode | Behaviour |
|---|---|
| `manual` | You pick via `merge_or_select(action="pick:<id>")`. Nothing automatic. |
| `auto` | Judge picks and commits immediately; you just see the result and its reasoning. |
| `auto_with_fallback` *(default)* | Judge picks. Above the confidence threshold (`0.80`) you get a chance to accept or override; below it, the manual picker opens with the judge's pick preselected. |
| `vote` | Three judges (auto-detected from your configured API keys) evaluate concurrently; majority wins, ties broken by confidence. Commits immediately. |

Confidence blends three signals — how much the branches disagree, an optional `test_pass_ratio`, and the winner's internal consistency (fewer retries and stuck loops) — then scales by the judge's own reported confidence.

!!! note "Wire up tests for higher confidence"
    Without a `test_command`, the judge's heuristic is capped at `0.65`, so
    `auto_with_fallback` falls back to the manual picker. Set one on the
    capability and a clean run lifts the cap:

    ```python
    LiveForkCapability(test_command="pytest -q", test_timeout_s=60.0)
    ```

    The command runs against each branch's materialised tree (requires a
    `LocalBackend`); the ratio comes from the process exit code.

## Driving it from Python

You don't have to let the agent call the tools — you can fork programmatically, which is handy in tests and harnesses. After the first `agent.run()`, the per-run coordinator lives on `deps.fork_coordinator`.

```python
from pydantic_deep import BranchIsolation, BranchSpec

result = await agent.run("warm up the run loop", deps=deps)
coordinator = deps.fork_coordinator        # set by the capability
assert coordinator is not None

handle = await coordinator.fork(
    [
        BranchSpec(label="conservative", steer="Take the safest approach."),
        BranchSpec(label="aggressive", steer="Optimise for performance."),
    ],
    parent_history=list(result.all_messages()),
    isolation=BranchIsolation(),           # defaults
)

# ... wait / inspect ...

merge = await coordinator.merge_or_select(f"pick:{handle.branches[0]}")
print(merge.winner_branch_id, len(merge.history_after_merge))
```

Merging flushes the winner's overlay writes onto the parent backend and adopts its history into the parent run. If a third actor changed a file during the fork, the winner's write still lands (last-write-wins) and the divergence shows up in [`MergeResult.conflicts`][pydantic_deep.features.forking.types.MergeResult].

!!! warning "Rewind restores history, not files"
    The `post-fork:<id>` checkpoint captures conversation history only. After a
    merge, rewinding with `/load` restores the merged history but leaves the
    winner's file writes on disk — revert those yourself if you need to.

## In the CLI

The terminal assistant has full forking support, baked in. You can fork the current run with `/fork`, steer a single branch with `>>a <message>`, watch branch panels stream live, and resolve with `/merge` — including launching an external diff tool (PyCharm, VS Code) to compare branches. See [Sessions, forking & MCP](../cli/sessions-forking-mcp.md) for the full command set.

## Recap

- `forking=True` turns on Live Run Forking with sensible defaults; pass a `LiveForkCapability` to tune limits, store, and `test_command`.
- The agent forks with `fork_run`, watches with `inspect_branches`, and resolves with `merge_or_select` — three tools among seven.
- Branches share history but isolate their backends, todos, and queues, so they never collide; the winner's writes flush onto the parent on merge.
- Acceptance modes range from fully `manual` to `auto`, `auto_with_fallback` (the default), and a multi-judge `vote`.
- Keep `include_checkpoints=True` so you always have a rewind anchor.

Where to go next:

- [Checkpointing](../learn/sessions.md) — the rewind safety net forking builds on.
- [Cost tracking & budgets](cost-tracking.md) — how per-branch budgets are enforced.
- [Sessions, forking & MCP →](../cli/sessions-forking-mcp.md) — forking from the terminal.
