# Live Run Forking

*git branch, but for cognition.*

**Live Run Forking** splits a running agent into multiple parallel branches that share the same conversation history up to the fork point, then explore different approaches in isolation. The branches run concurrently as `asyncio.Task`s with their own `DeepAgentDeps` (separate backends, todos, message queues). When branches finish, you pick a winner — manually via `merge_or_select(action="pick:<id>")`, or automatically via the built-in judge — the winner's overlay writes are flushed onto the parent backend and the rest of the branches are cancelled with their writes discarded.

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

The agent drives the fork itself — `fork_run`, `inspect_branches`, `merge_or_select` are regular tools.

## Agent-initiated forks (autonomous)

The agent can call `fork_run` itself during a normal `agent.run()` — no `/fork` command required. The CLI auto-adopts the coordinator the agent allocates, so:

- Branch panels light up automatically when the agent's `fork_run` call returns and the parent turn ends.
- `>>{label} <msg>` steering, the merge picker, and the diff / acceptance modals all behave identically to user-initiated forks.
- `/fork` is blocked while the auto-adopted fork is unresolved — the user sees an *"agent already forked — resolve it first"* notification instead of opening the picker.

The agent is responsible for resolving the fork before its turn ends (via `merge_or_select`). If it does not, the coordinator is stashed on `deps.fork_coordinator` and the **next** parent turn picks it up — so the user can still merge or abort manually. [`BASE_PROMPT`][pydantic_deep.prompts.BASE_PROMPT] includes a `## Forking` section that walks the agent through the protocol; the [`fork_run`][pydantic_deep.toolsets.forking.create_fork_toolset], [`inspect_branches`][pydantic_deep.toolsets.forking.create_fork_toolset] and [`merge_or_select`][pydantic_deep.toolsets.forking.create_fork_toolset] tool docstrings double-down on the polling / resolution contract.

### Stash + adopt mechanics

The CLI lifecycle around an unresolved agent-initiated fork:

1. `agent.run()` starts → [`LiveForkCapability.for_run`][pydantic_deep.capabilities.forking.LiveForkCapability.for_run] either allocates a fresh [`ForkCoordinator`][pydantic_deep.toolsets.forking.coordinator.ForkCoordinator] OR preserves the previous turn's coordinator if it is **not** [`is_resolved`][pydantic_deep.toolsets.forking.coordinator.ForkCoordinator.is_resolved].
2. Agent calls `fork_run` → coordinator gains a `ForkHandle` and live branches.
3. Parent turn ends → [`ChatScreen`][apps.cli.screens.chat.ChatScreen] calls [`reconcile_active_fork`][apps.cli.forking.reconcile_active_fork], which either adopts the coordinator (creating a `CLIForkSession` with `adopted=True`) or clears `app.active_fork` if the agent merged itself within the same turn.
4. User merges (`/merge` or branch-tab `Enter`) OR aborts (overview `Esc`) → coordinator overlays are released → `is_resolved` flips to `True` → next `for_run` allocates fresh.

Branches survive the parent turn ending only because step 1 preserves the coordinator and step 3 stashes it on `app.active_fork`. Manual abort (`Esc` on the overview) explicitly tears the stash down via `coordinator.aclose()`.

## Configuration

### `create_deep_agent()` parameter

| Parameter | Type | Default | Description |
|---|---|---|---|
| `forking` | `bool \| LiveForkCapability` | `False` | Opt-in: `True` enables defaults (`max_branches=10`, `max_depth=2`, `InMemoryForkStateStore`); pass a configured `LiveForkCapability` for custom limits / store. |

### `LiveForkCapability` knobs

| Knob | Type | Default | Effect |
|---|---|---|---|
| `max_branches` | `int` | `10` | Maximum branches per `fork_run` call. |
| `max_depth` | `int` | `2` | Maximum fork nesting depth. One level of fork-of-fork is allowed. |
| `store` | `ForkStateStore \| None` | `InMemoryForkStateStore()` | Where `ForkHandle` records are persisted for inspection. In-memory only — process restart loses the state. |
| `keep_artifacts` | `bool` | `False` | When `True`, the on-disk fork directory under `.pydantic-deep/forks/{fork_id}/` is preserved after merge / abort for post-hoc inspection. Independent of apply-on-merge semantics. |
| `test_command` | `str \| None` | `None` | Shell command run against each branch's materialised tree during [`ForkCoordinator.resolve`][pydantic_deep.toolsets.forking.coordinator.ForkCoordinator.resolve] to feed the `test_pass_ratio` confidence signal. See [Test-runner hook](#test-runner-hook-for-test_pass_ratio). |
| `test_timeout_s` | `float` | `60.0` | Wall-clock cap (seconds) per branch test run. On timeout the branch's `test_pass_ratio` is `None` (treated as "no signal"), not `0.0`. |

### Per-branch budgets

[`BranchSpec.budget_usd`][pydantic_deep.types.BranchSpec] is enforced. When a branch's [`CostTracking`][pydantic_ai_shields.CostTracking] cumulative cost crosses its cap, the branch is cancelled and its state transitions to [`"budget_exhausted"`][pydantic_deep.types.BranchState]; siblings keep running.

Pass a fork-wide cap at the `fork_run` call:

```python
await agent.run(
    "Try three approaches with a $5 ceiling",
    deps=deps,
)
# Inside the agent the tool call becomes:
# fork_run(
#     specs=[
#         {"label": "a", "steer": "approach 1", "budget_usd": 2.00},
#         {"label": "b", "steer": "approach 2", "budget_usd": 2.00},
#         {"label": "c", "steer": "approach 3", "budget_usd": 2.00},
#     ],
#     aggregate_budget_usd=5.00,
# )
```

When the sum of branch costs crosses `aggregate_budget_usd`, every still-running branch is terminated with state [`"aggregate_budget_exhausted"`][pydantic_deep.types.BranchState]. See [Limitations](#limitations--non-goals) below for the best-effort caveat.

### Per-branch isolation

[`BranchIsolation`][pydantic_deep.types.BranchIsolation] controls what each branch shares with the parent. Defaults are deliberately conservative — branches see the parent's history but mutate their own backends, todos, and message queues.

| Flag | Default | Effect |
|---|---|---|
| `history` | `"copy"` | Always copied. Not configurable. |
| `backend` | `"copy"` | Wraps the parent backend in a [`BranchOverlay`][pydantic_deep.toolsets.forking.isolation.BranchOverlay] — reads fall through, writes land in an overlay. `"share_readonly"` / `"share"` accepted for forward-compat. |
| `memory` | `"copy"` | Recorded; concrete effect lands when memory gets a separate path. |
| `todos` | `"copy"` | Branch starts with an empty todo list. |
| `message_queue` | `"isolated"` | Branch gets a fresh `MessageQueue` — external steering with `>>a` is per-branch. |
| `team_bus` | `"shared"` | Default-shared so branches can talk via the existing peer-to-peer bus. |

## Agent-facing tools

When `forking` is enabled, the agent gains seven tools:

| Tool | Surface |
|---|---|
| `fork_run(specs, isolation=None, strategy=None, aggregate_budget_usd=None)` | Spawn up to `max_branches` branch tasks. Each `spec` needs `label` and `steer`; optional `model`, `budget_usd`, `extra_instructions`. `aggregate_budget_usd` adds a fork-wide cap. |
| `inspect_branches()` | Return current per-branch state: `running`, `done`, `failed`, `terminated`, `budget_exhausted`, `aggregate_budget_exhausted`. |
| `merge_or_select(action)` | Resolve the fork. `action="pick:<branch_id>"` picks a winner manually; `action="auto"` lets the judge decide; `action="abort"` discards all branches. |
| `terminate_branch(branch_id)` | Cancel one branch's task; the branch transitions to `terminated`. |
| `delete_file(path)` | Delete a file inside the current branch overlay. Records the deletion so it propagates on merge. |
| `diff_branches(fork_id, paths=None)` | Build a typed [`BranchDiffReport`][pydantic_deep.types.BranchDiffReport] covering every path any branch touched. See [Diff explorer](#diff-explorer). |
| `fork_cost(fork_id)` | Return a typed [`ForkCostSummary`][pydantic_deep.types.ForkCostSummary] with per-branch [`BranchCost`][pydantic_deep.types.BranchCost] entries and an aggregate. |

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

`BranchOverlay.changes()` returns the temporal-ordered `list[FileChange]` of every write in this branch. `diff_branches()` reads this list per branch to build the [`BranchDiffReport`](#diff-explorer); the `ForkMaterializer` and judge consume the same API.

### Capturing partial history

When a branch is terminated mid-run — manually via `terminate_branch`, by a per-branch budget watcher (`budget_exhausted`), or by the fork-wide aggregate watcher (`aggregate_budget_exhausted`) — the coordinator keeps a snapshot of the branch's history in `BranchRuntime.partial_history`. That snapshot is captured on every `before_model_request`, so it reflects the state of play just before the most recent model call.

`merge_or_select("pick:<exhausted_id>")` recognises the cancellation, picks up the snapshot, and returns a [`MergeResult`][pydantic_deep.types.MergeResult] with the partial history as `history_after_merge` — rather than raising. This makes a budget-killed branch a usable merge candidate: you keep the work it did before the cap fired.

Caveat: any tool call that was in-flight at termination time is **not** reflected in the snapshot — only completed turns are. When `partial_history` is empty (true cancellation with no model request yet), `merge_or_select` raises `RuntimeError` as before.

## Diff explorer

Once branches are running (or have completed), the agent compares what each branch did to shared files with a single tool call: `diff_branches(fork_id, paths=None)`. The tool returns a typed [`BranchDiffReport`][pydantic_deep.types.BranchDiffReport]; on error (`fork_id` mismatch, forking disabled, no active fork) it returns a short string instead so the agent can self-correct.

Programmatic Python callers (CLI, judge, custom tooling) use the same builder directly via [`build_diff_report`][pydantic_deep.toolsets.forking.diff.build_diff_report]:

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

- `unanimous_change` — two or more branches touched the path with identical content.
- `unanimous_no_change` — only surfaces when an explicit `paths` filter includes paths no branch touched (kept for transparency).
- `split` — two or more branches touched the path with differing content.
- `unique` — exactly one branch touched the path; counted in `summary.per_branch_unique[branch_id]`.

### Binary and large-file handling

- **Binary content** (null byte in first 8 KB): `is_binary=True`, `new_content=None`, and `unified_diff_vs_parent` becomes a `[binary · {size} · sha256:{12 hex}]` placeholder.
- **Large diffs** (>500 lines): the unified diff is replaced with a head/tail preview using the same `create_content_preview` helper as [`EvictionCapability`](../advanced/eviction.md), with a `... [N lines truncated] ...` marker.

### `paths` filter

Pass `paths=["src/app.py", "src/utils.py"]` to restrict the report to specific paths. Filtered paths that no branch touched still surface as `unanimous_no_change`, so the report stays transparent — silence is never confused with "no diff."

## External diff tool integration

Every branch's working tree is mirrored to disk in real time so external diff tools (PyCharm, VS Code) can show the user what changed. The materialised layout lives at `.pydantic-deep/forks/{fork_id}/` and is removed on merge resolution unless [`LiveForkCapability(keep_artifacts=True)`][pydantic_deep.capabilities.forking.LiveForkCapability] is set.

```
.pydantic-deep/forks/{fork_id}/
├── manifest.json
├── parent/
│   └── <relative path of every file a branch touched, frozen at fork time>
└── branches/
    ├── approach_a/
    │   └── <same paths, post-branch-write content>
    └── approach_b/
        └── ...
```

Per-branch directories use the human-readable [`BranchSpec.label`][pydantic_deep.types.BranchSpec] (e.g. `approach_a`), not the internal UUID. The parent snapshot under `parent/` is captured lazily — the first time a branch writes a path, the materializer freezes the parent's pre-fork bytes for that path; subsequent parent writes do not update the snapshot.

### Editor detection

[`EditorDetector.detect`][pydantic_deep.toolsets.forking.editor.EditorDetector] picks the first available diff tool in this order:

1. `PYDANTIC_DEEP_DIFFTOOL` env var — explicit override, becomes `kind="custom"`. The template supports `{parent}` and `{branches}` placeholders.
2. `pycharm` on `PATH` → native 3-way diff via a single `subprocess.Popen(["pycharm", "diff", parent, a, b, c])`. For the 2-branch case the parent is passed as the middle argument (`pycharm diff a parent b`) to match PyCharm's 3-way diff "base in the middle" convention.
3. `code` on `PATH` → VS Code pairwise — one `Popen` per branch, each `["code", "--diff", parent, branch]`.
4. TUI fallback (`kind="tui"`) → the in-TUI `MergePickerModal` opens in diff-explore mode; no external process is spawned.

### `/fork diff` command

While a fork is active, the user can launch the detected diff tool from the TUI:

- `/fork diff <path>` — diff the materialised parent vs each branch's snapshot of `<path>`.
- `/fork diff` (no argument) — open a picker listing every touched path and the branches that wrote to it; pick a row + a subset of branches and the external diff tool launches.

This is the only `/fork` sub-command on the active-fork allow-list; bare `/fork` and `/fork-config` stay blocked mid-fork because they would spawn a new run and clobber the coordinator.

The `MergePickerModal` also exposes the "Open in editor" action (key: `o`) — useful when the user is already in the picker and wants to inspect a specific branch's snapshot before deciding.

## Apply on merge

[`ForkCoordinator.merge_or_select`][pydantic_deep.toolsets.forking.coordinator.ForkCoordinator.merge_or_select] picks a winner and **flushes its overlay writes onto the parent backend**. The winner's history is adopted into the parent run; discarded branches' overlays are released without flush.

```python
result = await coordinator.merge_or_select(f"pick:{winner_id}")
# Parent backend now reflects every file the winner wrote, plus a report:
print(result.applied_paths)     # ["cat.md", "dog.md"]
print(result.applied_changes)   # 2
print(result.conflicts)         # [] when parent was untouched during fork
print(result.errors)            # [] on success
```

### Conflict policy: last-write-wins

If a third actor modifies (or deletes) a path on the parent backend between fork time and merge time, the overlay's writes still land on the parent (last-write-wins). The divergence surfaces in [`MergeResult.conflicts`][pydantic_deep.types.MergeResult] so the CLI can warn the user. The merge notification renders as:

```
Merged: kept branch alpha · 2 files applied · conflicts: cat.md
```

Per-write failures (parent `WriteResult.error` non-empty or the backend raises) do not abort `flush_to` — the failing path is excluded from `applied_paths`, recorded in `MergeResult.errors` as a [`FlushError`][pydantic_deep.types.FlushError], and the remaining writes continue.

### Nested forks

When a fork spawns inside another fork (`max_depth=2`), the inner fork's parent backend IS the outer branch's [`BranchOverlay`][pydantic_deep.toolsets.forking.isolation.BranchOverlay]. `flush_to` writing into that overlay correctly propagates the winner's writes up one level; resolving the outer fork later propagates them to the root backend. No special handling required.

!!! warning "Rewind across `post-fork:<id>` does not restore files"
    The `post-fork:<fork_id>` checkpoint captures conversation history only — not file state. After a merge with apply, rewinding via `/load post-fork:<id>` restores the merged history but leaves the winner's file writes on disk. Track and revert them manually if needed. Full file-aware rewind is on the follow-up list.

## CLI integration

The Textual TUI (`pydantic-deep` CLI) has full forking support. Once `forking=True` is on the agent — flipped automatically by `create_cli_agent()` — every TUI session can fork the current run.

```text
┌─ pydantic-deep ────────────────────────────────────────┐
│ [● a] [✓ b] [+ overview]                               │  ← ForkTabsWidget
│ ──────────────────────────────────────────────────────│
│ branch a · ● running                                   │
│ > implement using a fast hash table                    │  ← BranchPanelWidget
│ tool: write src/store.py                               │
│ ...                                                    │
│                                                        │
│ ┌─ side ──────────┐                                   │
│ │ FORK: 2 · 1 …  │  ← ForkBadgeWidget                  │
│ └─────────────────┘                                   │
└────────────────────────────────────────────────────────┘
```

### Slash commands

| Command | Action |
|---|---|
| `/fork` | Open the picker modal, collect `N` `(label, steer)` pairs (where `N = app.fork_branch_count`), spawn branches. Blocked while an agent run is in flight (Esc first, then `/fork`). |
| `/fork-branches N` | Set the branch count used by the next `/fork` (range `[1, max_branches]`; default `10`). Persists to `.pydantic-deep/config.toml`. No arg → print current value. |
| `/fork-budget per-branch <usd>` | Default `budget_usd` prefilled into every branch row in the picker. Persisted. |
| `/fork-budget aggregate <usd>` | Fork-wide budget cap passed to `coordinator.fork(aggregate_budget_usd=…)`. Persisted. |
| `/fork-budget clear` | Reset both budgets to unset. |
| `/fork-model <i> <model>` | Assign a model (must include provider prefix, e.g. `anthropic:claude-opus-4-6`) to branch slot `i` (1-indexed, in `[1, fork_branch_count]`). Visible on the corresponding picker row. Persisted. |
| `/fork-model <i> clear` | Remove the override for branch `i`; that slot falls back to the agent's default model. |
| `/fork-model clear` | Remove every per-branch model override. |
| `/merge` | Open the merge picker — render each branch's diff snippets, pick the winner with `1`/`2`. Adopts the winner's `history_after_merge` into the parent. |

All three configuration commands (`/fork-branches`, `/fork-budget`, `/fork-model`) write through to `.pydantic-deep/config.toml` immediately, so settings survive CLI restarts. They configure the *next* fork — they are intentionally **not** in the active-fork allow-list, so mutating them mid-fork is blocked.

#### Worked example

```text
> /fork-branches 4
fork_branch_count = 4
> /fork-budget per-branch 0.25
per-branch budget = $0.25
> /fork-budget aggregate 2.00
aggregate budget = $2.00
> /fork-model 1 anthropic:claude-opus-4-6
Branch 1 model = anthropic:claude-opus-4-6
> /fork-model 2 openrouter:openai/gpt-4.1
Branch 2 model = openrouter:openai/gpt-4.1
> /fork
# picker opens with 4 rows. Rows 1 and 2 show their assigned models
# above the label/steer/budget inputs; rows 3 and 4 show "(default: …)".
# Every row prefills 0.25 in budget_usd. The aggregate row prefills 2.00.
# Submitting spawns four branches under a $2.00 fork-wide cap.
```

When the cumulative cost across all branches reaches `$2.00`, every still-running branch is terminated with state `aggregate_budget_exhausted` (rendered as the `$$ agg-exhausted` chip in the tab strip).

### Branch tabs

The tab strip shows one chip per branch plus a `+` overview pseudo-tab. Status badges mirror [`BranchStatus.state`][pydantic_deep.types.BranchStatus]: `●` running, `✓` done, `✗` failed, `⊘` terminated. `Tab` cycles focus through `overview → branch 0 → branch 1 → overview`.

### Steering a branch

`MessageQueue` per-branch routing (`message_queue="isolated"`, the default) means each branch has its own queue. The CLI exposes this via the `>>` steer prefix from [Message Queue (#100)](message-queue.md), extended with a branch id / label:

```text
>>a focus on tests
```

routes the message to branch `a`'s queue only. Branch `b` is unaffected. If the label doesn't match a live branch, the input is rejected with a notification — unlike the `!` shell prefix, `>>` is steering-only and never falls through. `!` keeps its #100 meaning during a fork (shell command).

While a fork is active, plain prompts and most slash commands are blocked with a notification. The allow-list is `/merge`, `/help`, `/cost`, `/tokens`, `/version`, `/quit`, `/copy`. Everything else would spawn a new `agent.run()` and silently overwrite `deps.fork_coordinator`.

### Live branch streaming

Branch panels update incrementally while their tasks run. Each poll tick (0.5 s) calls `replay_messages_append` with the branch's `partial_history`, rendering only the delta since the last tick — tool calls, tool returns, and assistant text appear as they land without clearing and re-rendering the entire panel.

When a `branch_runner` is set on the coordinator (done automatically by the CLI's `enter_fork_view`), the branch task uses `agent.iter()` instead of `agent.run()`, streaming text deltas and tool events directly into the panel's `MessageList` token-by-token. The coordinator's existing `DeferredToolRequests` approval loop and budget watcher work identically with both paths.

### Interactive branch chat

When a branch tab is focused and the branch has finished (`done`), typing plain text (no `>>` / `/` / `!` prefix) routes the message to that branch via `run_on_branch`. The branch starts a new turn with the user's message appended to its accumulated history. Each branch maintains its own `extra_message_history` so multiple follow-up turns accumulate independently.

```text
> /fork
[branch a finishes]
# Focus branch A's tab, then type:
> Can you also add error handling?
# → A resumes with the follow-up; B is unaffected
```

`run_on_branch` is blocked while the branch is still running — the user gets a notification to wait or use `>>{label} <msg>` to steer instead. When `/merge` resolves the fork, the winner's `history_after_merge` includes all parent pre-fork messages plus every branch turn (initial + interactive follow-ups).

Recursive forks from an interactive branch session are not supported — `max_depth` still gates, and `/fork` remains blocked while any fork is active.

### Stash + adopt mechanics (run_on_branch)

When a parent turn ends without `merge_or_select`, the coordinator is stashed on `deps.fork_coordinator` (see [Stash + adopt mechanics](#stash-adopt-mechanics)). The stashed coordinator hosts `run_on_branch` for interactive follow-ups — the user can continue chatting with individual branches across multiple parent turns. The materialiser stays alive while the coordinator is stashed, so on-disk artefacts under `.pydantic-deep/forks/{fork_id}/` persist between turns.

### Esc semantics

- **On a branch tab:** confirms "terminate `{label}`?" then calls [`ForkCoordinator.terminate_branch`][pydantic_deep.toolsets.forking.coordinator.ForkCoordinator.terminate_branch]. The other branches keep running.
- **On the overview tab:** confirms "abort the entire fork?" then calls [`ForkCoordinator.aclose`][pydantic_deep.toolsets.forking.coordinator.ForkCoordinator.aclose] which cancels every branch task.

Branch tab Esc reuses the same `task.cancel()` mechanism as the existing in-run Esc interrupt (#96).

### Quick start (TUI)

```bash
$ pydantic-deep
> Help me name a Python library for distributed locks.
[…agent thinks…]
> /fork
[modal: branch a = "whimsical", steer = "playful names"]
[modal: branch b = "technical", steer = "factual names"]
…both branches run in parallel, status badges update live…
> >>a make them shorter
[delivered to branch a only]
> /merge
[modal shows each branch's diff and final pitch]
[press 1 to pick branch a]
"Merged: kept branch whimsical"
```

Once the merge resolves, `app.message_history` is the winner's `history_after_merge`. The coordinator has already saved the `post-fork:{fork_id}` checkpoint anchor — `/load` lets you rewind there later.

## Autonomous merge

The default [`MergeStrategy.kind`][pydantic_deep.types.MergeStrategy] is `"auto_with_fallback"`: a cheap judge model inspects the structured diff + per-branch outcomes, picks a winner with confidence, and either auto-merges or hands off to the manual picker with the judge's pick preselected.

```python
from pydantic_deep.types import MergeStrategy

# Default — auto-with-fallback, threshold 0.80, Haiku judge.
strategy = MergeStrategy()

# Explicit auto mode — commit immediately, no widget interaction.
strategy = MergeStrategy(kind="auto", judge_model="anthropic:claude-haiku-4-5-20251001")

# Vote mode — three judges across vendors; majority wins, ties broken by confidence.
strategy = MergeStrategy(kind="vote")

# Opt out — back to manual flow.
strategy = MergeStrategy(kind="manual")
```

Pass the strategy to `fork_run` (agent-facing tool) or `ForkCoordinator.fork(..., strategy=...)` (programmatic). The CLI's `/merge` command reads the strategy off `session.handle.merge_strategy` and dispatches automatically.

### Modes

| Kind | Behaviour | Commit timing |
|---|---|---|
| `manual` | Caller picks via `merge_or_select(action="pick:<id>")`. | Caller |
| `auto` | Judge picks; coordinator commits immediately. User sees only the result + reasoning. | Inside `resolve()` |
| `auto_with_fallback` *(default)* | Judge picks. **Above threshold:** commit is deferred to the caller so `MergeAcceptanceWidget` can offer `[o]` override. **Below threshold:** caller opens the manual picker preselected with the judge's pick. | Caller (above) / Caller (below) |
| `vote` | Three judges (auto-detected from available API keys) evaluate concurrently. Majority wins, tie → highest individual confidence. | Inside `resolve()` |

### Vote judge panel detection

For `vote` mode, the judge panel is built dynamically from whichever API keys are present in the environment. Detection priority:

1. **Native providers** (Anthropic, OpenAI, Mistral, Groq, Cohere) — each contributes one cheap model when its env var is set.
2. **Google** — checked via `GOOGLE_API_KEY`, `GEMINI_API_KEY`, or `GOOGLE_GENERATIVE_AI_API_KEY`.
3. **OpenRouter** — contributes three different model-family representatives through a single key, maximising diversity when only one API key is configured.

Collected models are deduplicated and cycled to fill exactly 3 slots. If no keys are detected, the `judge_model` fallback is used three times.

### Confidence scoring

Three signals weighted into a single heuristic, then multiplied by the judge's own reported confidence:

| Signal | Source | Weight |
|---|---|---|
| `quality_spread` | `1 - agreement_score` from [`BranchDiffReport`][pydantic_deep.types.BranchDiffReport] | 0.4 |
| `test_pass_ratio` | passed / total tests across the winner branch — `None` when no `test_command` is configured | 0.4 |
| `internal_consistency` | `1 - (retry_count + stuck_loop_hits) / max(turns, 1)` for the winner | 0.2 |

`effective_confidence = heuristic × judge_confidence`. Clamped to `[0.0, 1.0]`.

### Test-runner hook for `test_pass_ratio`

By default `test_pass_ratio` is `None` — `compute_confidence` then **caps the heuristic at 0.65** before the multiplication, a deliberate safety rail. With the default threshold of 0.80 this means `auto_with_fallback` falls back to the manual picker.

Configure a `test_command` on [`LiveForkCapability`][pydantic_deep.capabilities.forking.LiveForkCapability] to lift that cap when tests actually pass:

```python
from pydantic_deep import LiveForkCapability, create_deep_agent

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
    forking=LiveForkCapability(
        test_command="pytest -q",   # any shell command; default is None
        test_timeout_s=60.0,        # wall-clock cap per branch
    ),
    include_checkpoints=True,
)
```

How it runs — inside [`ForkCoordinator.resolve`][pydantic_deep.toolsets.forking.coordinator.ForkCoordinator.resolve] each branch's overlay is materialised into a fresh tempdir (parent files as file-level symlinks, branch writes as real files, deleted paths absent), `test_command` is launched via [`asyncio.create_subprocess_exec`][asyncio.create_subprocess_exec] with `cwd` set to the tempdir, and the exit code maps to a per-branch ratio:

| Exit code / outcome | `test_pass_ratio` | Cap at 0.65 |
|---|---|---|
| `0` | `1.0` | Lifted |
| Non-zero | `0.0` | Lifted |
| Timeout (> `test_timeout_s`) | `None` | Active |
| Parent backend not `LocalBackend` (e.g. `StateBackend`) | `None` | Active |
| Command failed to spawn / overlay missing | `None` | Active |

Per-branch tests run concurrently via `asyncio.gather` so total wall-clock time is `max(branch_test_time)`, not the sum. The runner adds nothing to `branch_budget_usd` — it is wall-clock-bounded by `test_timeout_s`, not LLM cost.

!!! info "Exit-code semantics — caveat"
    The ratio is computed from the **process exit code only**: we do not parse pytest / jest counts from stdout. A `test_command` that exits 0 with zero tests collected reports `test_pass_ratio=1.0` — lifting the safety rail on a false signal. Mitigation: pick a `test_command` that fails when no tests run (e.g. add `pytest --strict-markers` plus a fixture that asserts collection > 0, or wrap with a guard script). A pytest-plugin-style counter for `passed / total` is tracked as a follow-up.

### Acceptance widget vs. picker fall-through

The deferred-commit ordering on `auto_with_fallback` is load-bearing: the acceptance widget shows *before* the merge fires, so `[o] override` can route to the manual picker with the judge's pick preselected. The widget exposes three bindings:

- `[enter]` — accept; the dispatcher calls `merge_or_select(f"pick:{winner_id}")` to commit.
- `[d]` — view diff; opens the diff explorer and re-pushes the widget on return (the verdict context survives the round-trip).
- `[o]` — override; opens [`MergePickerModal`][apps.cli.modals.merge_picker.MergePickerModal] with the judge's pick preselected and the verdict reasoning shown as a subtitle.
- `[escape]` — cancel; dismisses the widget without committing. The cached judge outcome means the next `/merge` re-shows the widget instantly without re-invoking the judge LLM.

### Judge prompt boundedness

The judge sees three sections only: the original goal, the structured `BranchDiffReport`, and one [`BranchOutcome`][pydantic_deep.types.BranchOutcome] bullet per branch (final message + cost + turns + error/retry counts). **Full per-branch message history is never included.** The prompt builder caps each section and the total length at `_MAX_JUDGE_PROMPT_CHARS = 32_000` chars (truncated tail with marker). This keeps the prompt's cost predictable and prevents the judge from reasoning over noise.

### Cost attribution

The judge runs via a freshly-constructed [`pydantic_ai.Agent`][pydantic_ai.Agent] inside [`JudgeAgent`][pydantic_deep.toolsets.forking.judge.JudgeAgent] — its calls are **not** counted against `parent_deps._branch_cost_tracking`. The judge's `result.usage` is surfaced on [`ResolveOutcome.judge_usage`][pydantic_deep.types.ResolveOutcome] (a list of usage objects for `kind="vote"`) so the caller can attribute the cost.

### Override in vote mode

`vote` mode commits immediately on the synthetic majority verdict — there is no fall-through or `[o]` override. To re-pick after a vote, rewind via the post-fork checkpoint anchor. Confirmable interactive vote mode is tracked as a follow-up.

## API reference

- [`LiveForkCapability`][pydantic_deep.capabilities.forking.LiveForkCapability] — capability registered on the agent. Owns `max_branches`, `max_depth`, `store`, and the per-run [`ForkCoordinator`][pydantic_deep.toolsets.forking.coordinator.ForkCoordinator] allocated via `for_run`.
- [`ForkCoordinator`][pydantic_deep.toolsets.forking.coordinator.ForkCoordinator] — workhorse for a single parent run. Owns branch tasks, serialises mutations via an `asyncio.Lock`, resolves merges by awaiting the picked winner.
- [`BranchOverlay`][pydantic_deep.toolsets.forking.isolation.BranchOverlay] — copy-on-write backend wrapper. Reads fall through to the parent; writes land in an isolated `StateBackend` overlay and are recorded.
- [`clone_for_branch`][pydantic_deep.toolsets.forking.isolation.clone_for_branch] — clones `DeepAgentDeps` per `BranchIsolation` policy.
- [`create_fork_toolset`][pydantic_deep.toolsets.forking.create_fork_toolset] — agent-facing tools factory. Wired automatically by `create_deep_agent(forking=...)`.
- [`build_diff_report`][pydantic_deep.toolsets.forking.diff.build_diff_report] — public entry point for the diff explorer, shared by the `diff_branches` tool and programmatic callers.
- [`ForkMaterializer`][pydantic_deep.toolsets.forking.materializer.ForkMaterializer] — real-time disk mirror for IDE integration.
- [`EditorDetector`][pydantic_deep.toolsets.forking.editor.EditorDetector] — diff tool detection and invocation (PyCharm, VS Code, custom, TUI fallback).
- [`JudgeAgent`][pydantic_deep.toolsets.forking.judge.JudgeAgent] — autonomous merge judge with structured verdict output.
- [`compute_confidence`][pydantic_deep.toolsets.forking.judge.compute_confidence], [`count_retry_parts`][pydantic_deep.toolsets.forking.judge.count_retry_parts], [`count_stuck_loop_hits`][pydantic_deep.toolsets.forking.judge.count_stuck_loop_hits] — confidence signal helpers.
- Types: [`BranchSpec`][pydantic_deep.types.BranchSpec], [`BranchIsolation`][pydantic_deep.types.BranchIsolation], [`BranchStatus`][pydantic_deep.types.BranchStatus], [`ForkHandle`][pydantic_deep.types.ForkHandle], [`MergeStrategy`][pydantic_deep.types.MergeStrategy], [`MergeResult`][pydantic_deep.types.MergeResult], [`FileChange`][pydantic_deep.types.FileChange].
- Diff types: [`BranchDiffReport`][pydantic_deep.types.BranchDiffReport], [`PathDiff`][pydantic_deep.types.PathDiff], [`BranchChange`][pydantic_deep.types.BranchChange], [`DiffSummary`][pydantic_deep.types.DiffSummary], [`BranchDiffAgreement`][pydantic_deep.types.BranchDiffAgreement], [`BranchDiffOperation`][pydantic_deep.types.BranchDiffOperation].
- Judge types: [`JudgeVerdict`][pydantic_deep.types.JudgeVerdict], [`ConfidenceSignals`][pydantic_deep.types.ConfidenceSignals], [`BranchOutcome`][pydantic_deep.types.BranchOutcome], [`ResolveOutcome`][pydantic_deep.types.ResolveOutcome].
- Cost types: [`BranchCost`][pydantic_deep.types.BranchCost], [`ForkCostSummary`][pydantic_deep.types.ForkCostSummary], [`FlushError`][pydantic_deep.types.FlushError], [`FlushReport`][pydantic_deep.types.FlushReport].
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

```python
for branch_id, runtime in coordinator.branches.items():
    if runtime.overlay is None:
        continue
    for change in runtime.overlay.changes():
        print(branch_id, change.op, change.path, change.timestamp)
```

## Limitations / non-goals

The following are **not** supported:

- **Persistent fork state** — `InMemoryForkStateStore` is the only store; process restart loses fork state.
- **Auto-merge of branch outputs into a single Pydantic blob** — intentionally excluded; "pick a winner" is the model.
- **Predictive termination** — branches are cancelled when the cap is *crossed*, not extrapolated.
- **Per-tool cost caps** within a branch.
- **Cost projection** before a branch is spawned.
- **Dynamic budget reallocation** mid-run.

!!! note "Aggregate budget enforcement is best-effort"
    Under concurrent cost callbacks the running sum can briefly exceed `aggregate_budget_usd` before every branch sees its cancel — the coordinator serialises termination dispatch under its own lock, but cost callbacks from sibling branches can race the watcher. Strict enforcement would require per-tool-call cost checks (out of scope).

Diff limitations:

- **Semantic / AST-based diff** — pure text diff only.
- **Rename detection** — a branch that renames a file shows as delete+create.
- **Diff of tool-call sequences** — process diff is not tracked; only outcomes are diffed.

IDE integration limitations:

- **Native IDE plugin** (file watcher, in-IDE accept/override buttons) — would require a JetBrains/VS Code plugin.
- **Bidirectional edits** — the user editing a branch file on disk does not flow back into the run; the on-disk tree is inspection-only.
- **Custom difftool integration beyond PyCharm / VS Code** — supported opaquely via the `PYDANTIC_DEEP_DIFFTOOL` env var; we do not ship per-tool adapters.
- **`git difftool` driver mode**.
- **Inline hunk-level accept/reject** (PyCharm plugin or TUI).
- **Real-time write-back during a fork** — branches own their overlays in isolation while running; cross-branch propagation only happens at merge.
- **File-aware checkpoint rewind across `post-fork:<id>`** — the merged conversation history is preserved by the checkpoint anchor but file writes are not.

Judge limitations:

- **Learning from past judge decisions** (RLHF-style calibration) — every fork is judged in isolation.
- **Custom confidence signal plugins** — the three built-in signals are fixed; no extension point.
- **Per-domain judge prompts** (code vs. research) — single generic prompt.
- **`combine` acceptance mode** — only meaningful for non-code outputs; intentionally excluded.
- **Streaming the judge's evaluation** — we wait for the full `JudgeVerdict`; no partial results.
- **Test-count parsing (passed / total)** — `test_pass_ratio` is computed from the process exit code only; a pytest/jest-plugin counter is a follow-up.
- **Auto-detection of `test_command`** (`pytest.ini`, `package.json`, `Makefile`) — `test_command` must be set explicitly on [`LiveForkCapability`][pydantic_deep.capabilities.forking.LiveForkCapability].
- **`cost_category="judge"` attribution in `CostTracking`** — `pydantic-ai-shields` has no such field; the judge's usage rides on [`ResolveOutcome.judge_usage`][pydantic_deep.types.ResolveOutcome] instead.
- **Override after `auto` / `vote` commit** — both modes commit immediately inside `resolve()`; switching winners after the fact requires rewinding via the `post-fork:<fork_id>` checkpoint anchor.
