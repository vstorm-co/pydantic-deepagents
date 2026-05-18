# Live Run Forking

*git branch, but for cognition.*

**Live Run Forking** splits a running agent into multiple parallel branches that share the same conversation history up to the fork point, then explore different approaches in isolation. The branches run concurrently as `asyncio.Task`s with their own `DeepAgentDeps` (separate backends, todos, message queues). When one finishes, you pick a winner via `merge_or_select(action="pick:<id>")` and the rest are cancelled — their writes never touch the parent backend.

This page is the canonical reference for the whole feature; it grows incrementally as stages land.

| Stage | Status | What it ships |
|---|---|---|
| 1 — Kernel | **Shipped** | [`LiveForkCapability`][pydantic_deep.capabilities.forking.LiveForkCapability], [`ForkCoordinator`][pydantic_deep.toolsets.forking.coordinator.ForkCoordinator], [`BranchOverlay`][pydantic_deep.toolsets.forking.isolation.BranchOverlay], 4 agent-facing tools |
| 2 — Diff Branches | Coming | `diff_branches()` report consumed by judge / IDE |
| 3 — CLI | Coming | `/fork`, branch tabs, `MergePickerModal`, `!{branch_id}` routing |
| 4 — N branches + budget | Coming | `max_branches>2`, `max_depth>1`, per-branch `budget_usd` enforcement |
| 5 — IDE materializer | Coming | Disk mirror under `.pydantic-deep/forks/`, `pycharm diff` / `code --diff` integration |
| 6 — Autonomous judge | Coming | `MergeStrategy.kind="auto"` / `"auto_with_fallback"` / `"vote"`, confidence scoring |

## Quick start

```python
import asyncio
from pydantic_deep import (
    DeepAgentDeps,
    InMemoryCheckpointStore,
    LiveForkCapability,
    StateBackend,
    create_deep_agent,
)


async def main() -> None:
    agent = create_deep_agent(
        model="anthropic:claude-sonnet-4-6",
        forking=LiveForkCapability(),       # opt-in; default is False
        include_checkpoints=True,           # provides the rewind safety net
    )
    deps = DeepAgentDeps(
        backend=StateBackend(),
        checkpoint_store=InMemoryCheckpointStore(),
    )

    result = await agent.run(
        "Use `fork_run` to spawn TWO branches naming a Python library: "
        "Branch A picks a whimsical name, Branch B picks a technical name. "
        "Each branch returns a 5-sentence pitch. After both finish, call "
        "`inspect_branches`, then `merge_or_select(action='pick:<id>')` for "
        "the better pitch.",
        deps=deps,
    )
    print(result.output)


asyncio.run(main())
```

The agent drives the fork itself — `fork_run`, `inspect_branches`, `merge_or_select` are regular tools. There is no CLI surface yet (Stage 3).

## Configuration

### `create_deep_agent()` parameter

| Parameter | Type | Default | Description |
|---|---|---|---|
| `forking` | `bool \| LiveForkCapability` | `False` | Opt-in: `True` enables defaults (`max_branches=2`, `max_depth=1`, `InMemoryForkStateStore`); pass a configured `LiveForkCapability` for custom limits / store. |

### `LiveForkCapability` knobs (Stage 1)

| Knob | Type | Default | Effect |
|---|---|---|---|
| `max_branches` | `int` | `2` (hard-coded in Stage 1) | Maximum branches per `fork_run` call. Stage 4 lifts this. |
| `max_depth` | `int` | `1` (hard-coded in Stage 1) | Maximum fork nesting depth. Stage 4 lifts this. |
| `store` | `ForkStateStore \| None` | `InMemoryForkStateStore()` | Where `ForkHandle` records are persisted for inspection. In-memory only across all stages — process restart loses the state. |

### Per-branch isolation

[`BranchIsolation`][pydantic_deep.types.BranchIsolation] controls what each branch shares with the parent. Defaults are deliberately conservative — branches see the parent's history but mutate their own backends, todos, and message queues.

| Flag | Default | Stage 1 effect |
|---|---|---|
| `history` | `"copy"` | Always copied. Not configurable. |
| `backend` | `"copy"` | Wraps the parent backend in a [`BranchOverlay`][pydantic_deep.toolsets.forking.isolation.BranchOverlay] — reads fall through, writes land in an overlay. `"share_readonly"` / `"share"` accepted for forward-compat. |
| `memory` | `"copy"` | Recorded; concrete effect lands when memory gets a separate path (Stage 4). |
| `todos` | `"copy"` | Branch starts with an empty todo list. |
| `message_queue` | `"isolated"` | Branch gets a fresh `MessageQueue` — external steering with `!a` is per-branch (delivered in Stage 3). |
| `team_bus` | `"shared"` | Default-shared so branches can talk via the existing peer-to-peer bus. |

## Agent-facing tools

When `forking` is enabled, the agent gains five tools:

| Tool | Surface |
|---|---|
| `fork_run(specs, isolation=None, strategy=None)` | Spawn ≤2 branch tasks (Stage 4 lifts the cap). Each `spec` needs `label` and `steer`; optional `model`, `budget_usd` (Stage 4), `extra_instructions`. |
| `inspect_branches()` | Return current per-branch state: `running`, `done`, `failed`, `terminated`. |
| `merge_or_select(action)` | Resolve the fork. Stage 1 supports `action="pick:<branch_id>"` only. |
| `terminate_branch(branch_id)` | Cancel one branch's task; the branch transitions to `terminated`. |
| `diff_branches(fork_id, paths=None)` | **Stage 2.** Build a typed [`BranchDiffReport`][pydantic_deep.types.BranchDiffReport] covering every path any branch touched. See [Diff explorer](#diff-explorer). |

## How it works

```
parent agent.run()
       │
       │ ── fork_run([A, B]) ──▶  ForkCoordinator (per-run, isolated)
       │                              │
       │                              ├─ Checkpoint("fork:<id>")     ← pre-fork anchor
       │                              ├─ clone_for_branch(deps, isolation)
       │                              ├─ asyncio.create_task(agent.run(A.steer, deps_A, history))
       │                              └─ asyncio.create_task(agent.run(B.steer, deps_B, history))
       │                                     │                              │
       │                                     ▼                              ▼
       │                                BranchOverlay A             BranchOverlay B
       │                                (writes → overlay,          (writes → overlay,
       │                                 reads fall through         reads fall through
       │                                 to parent)                 to parent)
       │
       │ ── inspect_branches() ──▶ statuses
       │
       │ ── merge_or_select("pick:A") ──▶
       │                              await task_A.result()
       │                              cancel task_B (overlay released)
       │                              Checkpoint("post-fork:<id>")  ← post-merge anchor
       │
       ▼
   parent run continues with winner's history
```

A fresh `ForkCoordinator` is allocated on every `agent.run()` via [`LiveForkCapability.for_run`][pydantic_deep.capabilities.forking.LiveForkCapability.for_run], so concurrent parent runs of the same agent never share state.

### Checkpoint integration

Forking integrates with [Checkpointing](../advanced/checkpointing.md) to give the user a rewind safety net:

- Before tasks are spawned, the coordinator saves `fork:<id>` containing the parent's pre-fork history.
- After `merge_or_select` resolves, it saves `post-fork:<id>` containing the winner's merged history.

If `include_checkpoints` is `False`, `fork_run` still works but emits a `UserWarning` — there is no rewind anchor if anything goes wrong.

!!! warning "Pre-fork anchor pruning"
    With `checkpoint_frequency="every_tool"` (the default) and `max_checkpoints=20`, a long fork run can prune the `fork:<id>` anchor before merge resolves. The `ForkHandle.parent_checkpoint_id` still references the (now-evicted) record. If the rewind affordance matters, bump `max_checkpoints` or set `checkpoint_frequency="every_turn"`.

### `BranchOverlay` write tracking

`BranchOverlay.changes()` returns the temporal-ordered `list[FileChange]` of every write in this branch. Stage 2's `diff_branches()` reads this list per branch to build the [`BranchDiffReport`](#diff-explorer); Stage 5's `ForkMaterializer` and Stage 6's judge consume the same API — preserve it across stage upgrades.

## Diff explorer

Once branches are running (or have completed), the agent compares what each branch did to shared files with a single tool call: `diff_branches(fork_id, paths=None)`. The tool returns a typed [`BranchDiffReport`][pydantic_deep.types.BranchDiffReport]; on error (`fork_id` mismatch, forking disabled, no active fork) it returns a short string instead so the agent can self-correct.

Programmatic Python callers (Stage 3 CLI, Stage 6 judge, custom tooling) use the same builder directly via [`build_diff_report`][pydantic_deep.toolsets.forking.diff.build_diff_report]:

```python
from pydantic_deep import build_diff_report

# `coordinator` is the ForkCoordinator allocated by LiveForkCapability.for_run;
# it lives on `deps.fork_coordinator` after the first agent.run().
fork_id = coordinator.fork_id  # bind to a local so the None check narrows
assert fork_id is not None, "no active fork — call fork_run first"
report = build_diff_report(fork_id, list(coordinator.branches.values()))

print(report.summary.agreement_score)        # 1.0 = unanimous, 0.0 = all-split
for pd in report.paths:
    print(pd.path, pd.agreement)             # e.g. "src/app.py split"
    for branch_id, change in pd.branches.items():
        print(" ", branch_id, change.operation)
        print(change.unified_diff_vs_parent)  # stdlib `difflib.unified_diff`
```

Unlike the agent-facing `diff_branches` tool, `build_diff_report` does not validate coordinator state — it builds a report from whatever runtimes you pass. Programmatic callers are expected to check `coordinator.fork_id` themselves before calling. This separation keeps the builder minimal and pushes the string-vs-typed error decision to the caller (typed callers prefer `if coord.fork_id != expected: raise ...` over parsing the tool's error string).

### Report shape

| Field | Notes |
|---|---|
| `BranchDiffReport.fork_id` | Echoed from the active fork. |
| `BranchDiffReport.paths: list[PathDiff]` | One entry per touched path, sorted alphabetically. |
| `BranchDiffReport.summary: DiffSummary` | Aggregate counts and `agreement_score`. |
| `PathDiff.parent_content: str \| None` | Parent backend's content; `None` if the file is new or binary. |
| `PathDiff.branches: dict[str, BranchChange]` | Keyed by branch id; one entry per branch in the fork. |
| `PathDiff.agreement` | One of the four labels below. |
| `BranchChange.unified_diff_vs_parent` | Stdlib unified diff; binary placeholder or truncated preview for large/binary files. |
| `BranchChange.new_content` | Branch's post-write content; `None` for binary, deleted, or untouched. |
| `BranchChange.is_binary` | True when the branch's content contains a null byte in the first 8 KB. |
| `DiffSummary.agreement_score` | `1.0 - split_paths / max(total_paths_touched, 1)`. |

### Agreement classification

For each path, the builder labels how the branches relate:

- `unanimous_change` — ≥2 branches touched the path with identical content.
- `unanimous_no_change` — only surfaces when an explicit `paths` filter includes paths no branch touched (kept for transparency).
- `split` — ≥2 branches touched the path with differing content.
- `unique` — exactly one branch touched the path; counted in `summary.per_branch_unique[branch_id]`.

### Binary and large-file handling

- **Binary content** (null byte in first 8 KB): `is_binary=True`, `new_content=None`, and `unified_diff_vs_parent` becomes a `[binary · {size} · sha256:{12 hex}]` placeholder.
- **Large diffs** (>500 lines): the unified diff is replaced with a head/tail preview using the same `create_content_preview` helper as [`EvictionCapability`](../advanced/eviction.md), with a `... [N lines truncated] ...` marker.

### `paths` filter

Pass `paths=["src/app.py", "src/utils.py"]` to restrict the report to specific paths. Filtered paths that no branch touched still surface as `unanimous_no_change`, so the report stays transparent — silence is never confused with "no diff."

## API reference

- [`LiveForkCapability`][pydantic_deep.capabilities.forking.LiveForkCapability] — capability registered on the agent. Owns `max_branches`, `max_depth`, `store`, and the per-run [`ForkCoordinator`][pydantic_deep.toolsets.forking.coordinator.ForkCoordinator] allocated via `for_run`.
- [`ForkCoordinator`][pydantic_deep.toolsets.forking.coordinator.ForkCoordinator] — workhorse for a single parent run. Owns branch tasks, serialises mutations via an `asyncio.Lock`, resolves merges by awaiting the picked winner.
- [`BranchOverlay`][pydantic_deep.toolsets.forking.isolation.BranchOverlay] — copy-on-write backend wrapper. Reads fall through to the parent; writes land in an isolated `StateBackend` overlay and are recorded.
- [`clone_for_branch`][pydantic_deep.toolsets.forking.isolation.clone_for_branch] — clones `DeepAgentDeps` per `BranchIsolation` policy.
- [`create_fork_toolset`][pydantic_deep.toolsets.forking.create_fork_toolset] — agent-facing tools factory. Wired automatically by `create_deep_agent(forking=...)`.
- Types: [`BranchSpec`][pydantic_deep.types.BranchSpec], [`BranchIsolation`][pydantic_deep.types.BranchIsolation], [`BranchStatus`][pydantic_deep.types.BranchStatus], [`ForkHandle`][pydantic_deep.types.ForkHandle], [`MergeStrategy`][pydantic_deep.types.MergeStrategy], [`MergeResult`][pydantic_deep.types.MergeResult], [`FileChange`][pydantic_deep.types.FileChange].
- Stage 2 diff types: [`BranchDiffReport`][pydantic_deep.types.BranchDiffReport], [`PathDiff`][pydantic_deep.types.PathDiff], [`BranchChange`][pydantic_deep.types.BranchChange], [`DiffSummary`][pydantic_deep.types.DiffSummary], [`BranchDiffAgreement`][pydantic_deep.types.BranchDiffAgreement], [`BranchDiffOperation`][pydantic_deep.types.BranchDiffOperation].
- Stage 2 builder: [`build_diff_report`][pydantic_deep.toolsets.forking.diff.build_diff_report] — public entry point shared by the `diff_branches` tool and programmatic callers.
- Errors: [`ForkBranchLimitError`][pydantic_deep.toolsets.forking.coordinator.ForkBranchLimitError], [`ForkDepthLimitError`][pydantic_deep.toolsets.forking.coordinator.ForkDepthLimitError].

## Examples

### Programmatic fork (without the agent driving it)

Useful when you want to script fork-and-pick in tests or harnesses:

```python
from pydantic_deep import (
    BranchIsolation,
    BranchSpec,
    DeepAgentDeps,
    LiveForkCapability,
    StateBackend,
    create_deep_agent,
)


fork_cap = LiveForkCapability()
agent = create_deep_agent(model="anthropic:claude-sonnet-4-6", forking=fork_cap)
deps = DeepAgentDeps(backend=StateBackend())

# Run once so the capability's for_run() allocates a per-run coordinator.
result = await agent.run("warm up the run loop", deps=deps)
coordinator = deps.fork_coordinator       # set by LiveForkCapability.for_run
assert coordinator is not None

handle = await coordinator.fork(
    [
        BranchSpec(label="conservative", steer="Take the safest approach."),
        BranchSpec(label="aggressive",  steer="Optimise for performance."),
    ],
    parent_history=list(result.all_messages()),
    isolation=BranchIsolation(),          # defaults
)

# ... wait / inspect ...

merge = await coordinator.merge_or_select(f"pick:{handle.branches[0]}")
print(merge.winner_branch_id, len(merge.history_after_merge))
```

### Inspecting overlay writes

Stage 1 already exposes the data spine that Stages 2/5/6 will consume:

```python
for branch_id, runtime in coordinator.branches.items():
    if runtime.overlay is None:
        continue
    for change in runtime.overlay.changes():
        print(branch_id, change.op, change.path, change.timestamp)
```

## Limitations / non-goals

Stage 1 deliberately shipped the minimum kernel. The following are **not** supported until later stages:

- **CLI surface** (`/fork`, branch tabs, merge picker modal, `!{branch_id}` routing) — Stage 3.
- **More than 2 branches or fork-of-fork** — Stage 4 lifts `max_branches` and `max_depth`.
- **Per-branch budget enforcement** (`BranchSpec.budget_usd`) — accepted but ignored in Stage 1. Stage 4 wires enforcement.
- **External diff tool integration** (`pycharm diff`, `code --diff`) — Stage 5.
- **Autonomous merge** (judge model, confidence scoring, vote mode) — Stage 6.
- **Persistent fork state** — `InMemoryForkStateStore` is the only store across all stages; process restart loses fork state.
- **Auto-merge of branch outputs into a single Pydantic blob** — intentionally excluded everywhere; "pick a winner" is the model.

Stage 2's `diff_branches` is purely textual — these are deferred or out of scope by design:

- **Semantic / AST-based diff** — pure text diff only.
- **Rename detection** — a branch that renames a file shows as delete+create.
- **Diff of tool-call sequences** — process diff is not tracked; only outcomes are diffed.
- **TUI rendering of the diff** — Stage 3.
- **External editor invocation** (`pycharm diff`, `code --diff`) — Stage 5.
