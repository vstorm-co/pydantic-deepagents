# System Review — pydantic-deep

_A fresh, post-refactor review hunting for gaps, edge cases, faulty architecture, poor code quality, and improvement opportunities._

**Scope:** `pydantic_deep/` (core library) + `apps/cli/` (Textual TUI).
**Method:** four focused review passes (forking/concurrency, core error-handling/edge-cases, apps/cli architecture, types/API/dead-code), each reading source and verifying claims; the highest-severity findings were then re-verified by hand against the source. Line numbers are approximate (the tree moves) — treat the symbol names as the anchor.

**Context that shapes this review:** the repo passes `mypy --strict`, `pyright`, `ruff`, and **100% test coverage**. So everything below is deliberately the class of problem those gates *cannot* catch: concurrency hazards, swallowed errors, edge-case inputs, leaky/eroded types, architectural coupling, and silent-degradation paths. Coverage proves lines execute, not that behaviour is correct on adversarial inputs.

## Severity legend

| | Meaning |
|---|---|
| **P0** | Permanent hang / crash / data loss in a *reachable* configuration |
| **P1** | Wrong behaviour or silent degradation in a realistic scenario; security |
| **P2** | Fragile / latent — fires under specific timing, input, or future change |
| **P3** | Minor / cosmetic / maintainability |

✅ = verified by hand against source during this review.

---

## A. Forking & concurrency (`toolsets/forking/`, `capabilities/`)

The overlay/diff/merge core is solid engineering; the hazards cluster in lifecycle (cancel/cleanup) and the auto-resolution path.

### A1 ✅ P0 — `merge_or_select` can hang forever when the picked winner is parked on a deferred approval
`coordinator.py` — `merge_or_select` does `result = await winner.task`; the branch task body (`_run_branch_with_approval`) parks on `await request.response.get()` whenever the branch emits a `DeferredToolRequests` (e.g. a gated `execute`). In **`auto`/`vote`** mode `resolve()` → `_commit_and_wrap()` → `merge_or_select("pick:…")` with **no human and nothing draining the branch's `pending_approval` queue** → the await never returns and the whole agent turn hangs.
**Precondition:** `interrupt_on` enabled on branches *and* non-manual merge strategy *and* the winner emitted a gated call. Reachable, not adversarial.
**Fix:** before awaiting the winner in non-manual modes, auto-resolve any outstanding `pending_approval` (deny by default), or `asyncio.wait_for(winner.task, timeout=…)` and fall back to `partial_history` on timeout.

### A2 ✅ P1 — `aclose()` runs lock-free, racing `merge_or_select`/`abort_fork`
`coordinator.py` — `aclose()` takes **no `self._lock`** (unlike `fork`/`merge_or_select`/`abort_fork`), iterates `self.branches.values()`, cancels tasks, and calls `materializer.cleanup()` unconditionally. A parent cancellation firing `aclose()` while a merge/abort is mid-flush interleaves two cleanup paths over the same branches + materializer.
**Fix:** take `self._lock` in `aclose()` (the cancel-await is already time-bounded so it won't starve) and make `materializer.cleanup()` idempotent (guard on a `_closed`/`is_resolved` flag).

### A3 P1 — `terminate_branch` check-then-set on `BranchStatus.state` isn't atomic vs. done-callbacks
`coordinator.py` — `terminate_branch` reads `status.state`/`task.done()` then writes, holding no lock, while the per-branch and aggregate budget watchers + the task done-callback also flip `status.state` from callback context. The documented "don't overwrite a terminal state / idempotent" guarantee can be violated when the per-branch and aggregate watchers race — the exact scenario the docstring claims to handle.
**Fix:** route all status transitions through one helper that re-checks under `self._lock`.

### A4 P1 — `_cancel_branch_task` 1 s timeout silently breaks the "quiesce losers before flush" guarantee
`coordinator.py` — losers are cancelled with `asyncio.wait_for(rt.task, timeout=_CANCEL_CLEANUP_TIMEOUT_S=1.0)` inside `contextlib.suppress`. On timeout the loser keeps running detached, yet the caller proceeds to null its overlay and flush the winner. A slow loser whose overlay reads now fall through to the parent can observe the winner's freshly-flushed bytes — the precise hazard `merge_or_select`'s docstring says it prevents.
**Fix:** on timeout, don't null the overlay / don't flush until losers are confirmed done (or shield the flush behind confirmed cancellation).

### A5 P2 — `capture_partial_history` snapshot depends on capability ordering and is a shallow copy
`forking.py` / `coordinator.py` — `before_model_request` passes `request_context.messages` into `capture_partial_history` which stores `list(messages)` (shallow). `MessageQueueCapability` and `PeriodicReminderCapability` also reassign `request_context.messages`; whether the snapshot includes injected steering/reminders is registration-order-dependent, and in-place edits by later capabilities leak into the captured history. The budget-exhausted-winner merge then replays a history the branch didn't actually see.
**Fix:** capture after a defined point in the capability chain, or deep-copy the parts that matter.

### A6 P2 — aggregate budget records costs from already-terminated branches
`budget.py` — `AggregateBudgetWatcher._per_branch[bid] = info.total_cost_usd` is written from each branch's cost callback with no lock and never skips branches already terminated, so a late callback inflates `aggregate()` (shown in `fork_cost()` and the termination message) beyond true live spend.
**Fix:** skip recording for branches in a terminal state; snapshot the dict before summing.

### A7 P2 — `_detect_vote_models` degenerates to a single model with one provider key
`coordinator.py` — with one API key, `unique` has length 1 and `[unique[i % 1] for i in range(3)]` yields three identical judges — no diversity, deterministic `_majority_pick` — identical to the `fallback*3` case it claims to improve. Callers believe they got a diverse panel.
**Fix:** `warnings.warn` when the resolved panel has < 2 distinct models; document the degenerate case.

### A8 P2 — judge `Agent`s rebuilt every `vote`/`auto` resolve (no cache)
`coordinator.py` / `judge.py` — the resolve cache only covers `auto_with_fallback`; `vote` rebuilds N `JudgeAgent`/`Agent` objects on every resolve. `LLMReminderGenerator` shows the intended `_agent` reuse the judges lack.
**Fix:** memoize `JudgeAgent` by model on the coordinator/capability.

### A9 P3 — checkpoint `save()` performed while holding `self._lock`
`coordinator.py` — both the pre-fork anchor (`fork()`) and post-fork (`merge_or_select`) checkpoint saves run inside the lock. Harmless with the in-memory store; a future file/SQLite `CheckpointStore.save` would block every coordinator op for its IO duration.

---

## B. Core library — error handling & edge cases

No unconditional P0; the theme is **silent degradation** — broad `except` blocks and `.get()` defaults that turn real failures into "looks empty / looks fine".

### B1 ✅ P1 — One malformed `SKILL.md` aborts the entire skills scan
`toolsets/skills/directory.py` — `_parse_skill_md` returns `yaml.safe_load(...)` unguarded, so `---\njust text\n---` yields a `str` (or `None` for comment-only). `_extract_skill_fields` then calls `frontmatter.get("name")` → **`AttributeError`**, which is **not** in `_discover_skills`'s `except (OSError, ValueError, KeyError)` handler → one bad file kills discovery for *all* skills (even with `validate=False`). Non-string `name`/`description` similarly raise `TypeError`/`AttributeError` downstream (`_validate_skill_metadata` `len(name)`, `xml_escape(description)`).
**Fix:** in `_parse_skill_md`, `if not isinstance(frontmatter, dict): return {}, instructions`; coerce `name`/`description` to `str` in `_extract_skill_fields`.

### B2 ✅ P1 — Backend skill discovery skips the symlink-escape containment check the filesystem path enforces
`toolsets/skills/backend.py` vs `directory.py` — the filesystem discovery explicitly verifies each resource/script resolves *inside* the skill dir ("symlink escape detected" warnings). The backend equivalents (`_discover_backend_resources`/`_discover_backend_scripts`) accept whatever `glob_info` returns and store it as a `uri` for later `read_bytes`/`execute`. A `LocalBackend`-backed `BackendSkillsDirectory` with a symlinked resource pointing outside the dir bypasses the protection. Asymmetric security.
**Fix:** mirror the containment check on the backend path.

### B3 ✅ P1 — `PatchToolCallsCapability` rebuilds `ModelRequest(parts=…)` dropping `instructions` and `timestamp`
`processors/patch.py` — when injecting synthetic cancelled-tool returns or stripping orphaned results, requests are rebuilt with `parts=` only, silently losing per-request `instructions`/`timestamp` on resume of an interrupted conversation. `eviction.py` does the equivalent rebuild *correctly* (copies both), so this is an internal inconsistency.
**Fix:** carry `instructions`/`timestamp` from the source request via `dataclasses.replace`-style copy.

### B4 P1 — Eviction silently re-admits the full oversized payload on backend write failure
`processors/eviction.py` — `if write_result.error: return None` makes `after_tool_execute` return the **original oversized** result into history (the exact thing eviction prevents), with no log and no `on_eviction` signal. A transient backend hiccup defeats token management invisibly.
**Fix:** log/emit, and fall back to a truncated preview rather than the full blob.

### B5 P1 — `improve` drops an entire session on one oversized message / untruncated prompt
`improve/extractor.py` — `_prepare_chunk_text` truncates tool-returns/args but emits `user-prompt`/`retry-prompt` content untruncated; a huge pasted prompt (or a single message over the chunk budget) is sent verbatim to `agent.run()`, raises, and `analyzer.analyze()` counts the whole session as `failed_sessions += 1` (total loss). `_estimate_message_tokens` also counts full content while the prepared text is truncated, so the estimate diverges from what's actually sent.
**Fix:** truncate user/retry prompts too; estimate on the prepared text; chunk at message granularity with a hard per-message cap.

### B6 ✅ P1 — `history_archive` masks a corrupt/partial archive as "no history saved"
`processors/history_archive.py` — `_load_messages` wraps `ModelMessagesTypeAdapter.validate_json` in a blanket `except Exception: pass` (and is `# pragma: no cover`). Corrupt JSON, schema drift after a pydantic-ai upgrade, or a partial concurrent write all surface to the agent as "No conversation history saved yet" — misleading when a populated archive exists but failed to parse.
**Fix:** log the exception; distinguish "file absent" from "load failed".

### B7 P2 — `_truncate_tool_output` can return *more* than `max_chars` and corrupt output for small budgets
`improve/extractor.py` — `tail_size = max_chars - head_size - 50` goes negative for `max_chars < ~167`; `content[-tail_size:]` then becomes a forward slice longer than the input, with a nonsensical truncation marker. Latent (callers pass 5000/1000) but `max_chars` is effectively a knob.
**Fix:** `tail_size = max(0, …)` and early-return `content[:max_chars]` below a floor.

### B8 P2 — Eviction filename keyed solely on sanitized `tool_call_id`
`processors/eviction.py` — `file_path = f"{eviction_path}/{_sanitize_id(call.tool_call_id)}"`; `_sanitize_id` maps every non-`[A-Za-z0-9_-]` char to `_`, so two IDs differing only in punctuation collide and a later write overwrites the earlier evicted file while both history messages still point at it. Low probability with today's alphanumeric pydantic-ai IDs, but a real correctness trap.
**Fix:** add a short content hash (or tool-name) suffix.

### B9 P2 — `upload_files` swallows every per-file exception with no diagnostic
`deps.py` — `except Exception: continue` drops failed uploads silently; the caller gets a shorter list with no signal of which/how-many/why. Documented as intentional, but zero observability.
**Fix:** `warnings.warn`/log skipped filenames, or return `(succeeded, failed)`.

### B10 P2 — `on_eviction` callback exceptions abort the tool result; no `token_limit` validation
`processors/eviction.py` — the `on_eviction` callback is awaited with no `try/except`, so a raising UI/logging hook crashes the run *after* the file is written; and `token_limit <= 0` is unvalidated (makes `char_limit <= 0` → everything evicted).
**Fix:** wrap the callback; validate `token_limit > 0` in `__post_init__`.

### B11 P2 — `patch_tool_calls` orphan detection assumes strict message adjacency
`processors/patch.py` — `_find_orphaned_calls` only inspects `messages[i+1]`, `_find_orphaned_results` only `messages[i-1]`. Compression/eviction that interposes a message (or two consecutive `ModelResponse`s) misclassifies answered calls as orphaned and injects spurious "cancelled" returns — corrupting valid history. Falsy `tool_call_id`s are also handled asymmetrically between the two phases.
**Fix:** match calls↔returns by a global ID set rather than adjacency.

### B12 P2 — `_load_tool_log` discards the whole log on one bad record
`improve/extractor.py` — a single record with a non-numeric `elapsed`/`result_len` (or one malformed JSONL line) trips the function-level `except Exception: return ""`, dropping *all* tool-log records — the highest-value diagnostic input for improve.
**Fix:** per-line try/except; coerce numerics defensively.

### B13 P2 — MCP import: non-string args reach a `list[str]` contract; per-entry failures swallowed
`mcp/loader.py` — `_expand` returns non-strings unchanged, so `"args": [8080]` lands in `MCPServerConfig.args: list[str]` → `TypeError` at connect; `parse_mcp_servers` wraps the loop in `except Exception: continue`, dropping malformed entries with no feedback. `mcp/config.py` `value_template.format(token=…)` also raises `KeyError`/`ValueError` on templates with extra placeholders or literal braces.
**Fix:** coerce with `str(...)` in `_expand`; log skipped entries; validate `value_template` in `__post_init__`.

### B14 P3 — BM25 history search indexes display-truncated content
`processors/history_archive.py` — the index is built from 500/200-char display previews, so a search term beyond the cutoff of a long tool result is unfindable — defeating the tool's purpose. **Fix:** index full content, truncate only for display.

### B15 P3 — Reserved-word skill-name check is an unanchored substring match
`toolsets/skills/directory.py` — flags legitimate names like `claudette-helper` / `anthropic-style-guide`. **Fix:** match on `-`-delimited segments.

### B16 P3 — `improve` "update" silently appends when the section heading isn't found
`improve/analyzer.py` — `apply_changes` for `change_type="update"` falls back to appending when the target heading doesn't match, risking duplicated/misplaced content across repeated runs with no signal. **Fix:** surface matched-vs-appended.

---

## C. apps/cli — architecture & quality

`apps/cli` is outside the coverage gate and not pyright-checked, so it carries more rough edges. The dominant issues: **blocking work on the Textual event loop** and a **2077-line `chat.py` god-object** with three copies of the stream-consumption loop.

### C1 ✅ P1 — `DiffViewModal.compose()` runs four blocking `git` subprocesses on the event loop
`modals/diff_view.py` — `compose()` (which runs on the UI loop) issues `subprocess.run(["git", …])` ×4 with 5–10 s timeouts. In a large repo the entire UI freezes for seconds (worst case ~35 s) and can't even paint.
**Fix:** yield a placeholder in `compose`, run git in `on_mount` via `run_worker(thread=True)`, mount results when done (the `mcp_view.py` `run_worker` pattern).

### C2 P1 — `reconfigure_agent` does heavy blocking work synchronously on the loop
`app.py` → `agent.py:create_cli_agent` — invoked from sync command callbacks (`/provider`, `/model`) and `mcp_view`, it runs config loads, MCP server construction, **DockerSandbox startup**, and `LocalContextToolset` git subprocesses — all on the loop. Docker startup hangs the whole TUI for seconds with no feedback.
**Fix:** run `create_cli_agent` in a worker thread; assign back on the main thread; show a spinner.

### C3 ✅ P1 — `keystore` writes plaintext API keys with default permissions
`keystore.py` — `keys.toml` is written via `path.write_text(...)` with no `chmod 0600`, and the parent dir is created with default mode. API keys land world-readable (subject to umask).
**Fix:** `os.chmod(path, 0o600)` after write; create the dir `mode=0o700`.

### C4 P1 — Three drifting copies of transcript-replay logic
`commands.py:_cmd_load`, `commands.py:_replay_branch_into_main_chat`, and the inline streaming loop in `chat.py` — all three walk `msg.parts` and call `append_user_message`/`begin_assistant_message`/`add_tool_call`/`complete_tool_call`, and have **already drifted**: unreturned calls are labelled `"Interrupted"` in one and `"No return"` in another; error detection differs (`looks_like_error(content)` vs `…(raw, check_exit_code=True)`).
**Fix:** one `replay_messages_into(msg_list, messages)` helper owned by `MessageList`, called from all three.

### C5 P1 — Estimated-cost path clobbers a legitimate zero cost
`chat.py:_sync_status_from_history` / `commands.py:/cost` — falls back to a fabricated Sonnet-rate estimate whenever `app.total_cost <= 0`, conflating "unknown" with "genuinely free/cached/un-priceable turn", and shows a wrong nonzero cost.
**Fix:** track cost-known with a `None` sentinel/flag, not an overloaded `0.0`.

### C6 P1 — `_pending_images` has no instance default; `attach_clipboard_image` is unguarded
`chat.py` — `_pending_images` is a bare class annotation initialized in `on_mount`; the app-level `ctrl+v` → `attach_clipboard_image` appends with no `hasattr` guard (unlike `_expand_file_refs`, which guards). Firing the binding before `on_mount` (or after a screen swap) raises `AttributeError`.
**Fix:** initialize in `__init__`, guard all accessors.

### C7 P2 — Fork-Esc abort task is fire-and-forget without a strong ref
`app.py:action_escape_key` — `asyncio.create_task(handler())` is stored nowhere (only a done-callback for error surfacing), bypassing the `_spawn_tracked` set the codebase added precisely so untracked tasks aren't GC'd mid-flight. The abort/terminate coroutine can be dropped.
**Fix:** route through `self._spawn_tracked(handler(), label="fork-esc")`.

### C8 P2 — Two redundant branch-"done" rendering paths can double-replay
`app.py:_attach_branch_done_callback` and `chat.py:_poll_fork_state` — branch completion is rendered both by the task done-callback and independently by the 0.5 s poll tick; the `note_streamed_messages` watermark exists specifically to fight this race. Multi-writer by design.
**Fix:** make the branch panel the single source of truth; gate replay on an idempotent "already-replayed" flag.

### C9 P2 — Pervasive `getattr(self.app, …)` defeats the known `DeepApp` type
`chat.py` — ~16 `getattr(self.app, "agent"/"deps"/…)` probes plus `# type: ignore[attr-defined]`, even though `ChatScreen.app` is typed `DeepApp`. The `getattr(..., default)` form would hide a genuine "agent never wired" bug as a silent default; since apps/cli isn't pyright-checked these accumulate.
**Fix:** access `self.app.agent` directly; keep `getattr` only for genuinely late-bound attributes.

### C10 P2 — Clipboard commands reach into widget private `_text`
`commands.py` `/copy`, `/copy-all` — `assistants[-1]._text` / `child._text` couples across module boundaries; a widget rename silently breaks copy (caught by a broad `except` → "No response to copy").
**Fix:** expose a public `text` property on the message widgets.

### C11 P2 — `watch_model_name` uses `except (NoMatches, Exception)` (i.e. bare `except Exception`)
`app.py` — swallows every watcher error silently; the intent ("only `NoMatches` is expected") is lost and a real bug setting `header.model_name` vanishes. Other watchers correctly use `contextlib.suppress(NoMatches)`.
**Fix:** catch only `NoMatches`.

### C12 P2 — Synchronous session/tool-log file IO inside the streaming worker
`chat.py:_save_session` / `_append_tool_log` — JSON dump + `write_bytes` after every turn and in `finally`, and a JSONL append on *every* tool result, all on the loop. Stutters streaming for large histories.
**Fix:** offload to a thread or an async writer queue.

### C13 P2 — `/fork diff` symlinks are never cleaned up; unguarded on Windows
`commands.py:_labeled_symlinks` — creates `{tempdir}/pd_{fork_id}/…` symlinks that accumulate across sessions; `symlink_to` can raise without privilege (Windows), aborting the diff open.
**Fix:** track + clean the temp dir (atexit / on resolve); guard with a copy fallback.

### C14 P3 — Provider→default-model table duplicated three times
`app.py:_pick_available_model`, `commands.py:_cmd_provider._PROVIDER_DEFAULT_MODELS`, `onboarding._PROVIDERS` — three drifting copies. **Fix:** one shared constant.

### Architecture — decomposing `chat.py` (2077 lines)

`ChatScreen` mixes ≥ 6 responsibilities. The single biggest win: **collapse the three copies of the stream-consumption loop** (main run, approval-continuation, and `_stream_branch_via_iter`) into one `stream_run_into(run, assistant, msg_list)` helper — that removes ~250 lines and the drift where the approval-continuation loop already lacks the thinking-display + turn-count parity the main loop has. Suggested split:

1. **`AgentRunController`** — `_run_agent`, `_agent_stream_worker`, deferred-approval loop, turn summary (~600 lines).
2. **`TranscriptReplay`** (methods on `MessageList`) — the single replay helper from C4.
3. **`ForkViewController`** — `enter/exit_fork_view`, `_poll_fork_state`, `_attach_branch_done_callback`, branch-tab focus/merge (self-contained subsystem; owns the C8 hazard).
4. **`SidePanelController`** — subagent-panel baseline-merge.
5. **`SessionPersistence`** — `_init/_save_session`, `_append_tool_log` (threaded per C12).

Also likely **dead legacy event path:** the `on_agent_token`/`on_tool_call_*`/`on_cost_updated` message handlers appear unused — the live worker writes to widgets directly and never posts those messages. Confirm and delete if so.

---

## D. Types, public API, dead code, docs

mypy/pyright pass, but several public params are **load-bearing `Any` over a type that's already imported in the same file** — the worst kind, because it silently disables checking exactly where a user is most likely to pass the wrong object.

### D1 P1 — `output_style: str | Any | None` erases a fully-known type
`agent.py` (both overloads + impl) — consumed only by `resolve_style(style: str | OutputStyle, …)`. The `Any` swallows the union, so a wrong object gets no error and no completion.
**Fix:** `output_style: str | OutputStyle | None = None` (import `OutputStyle` from the sibling `styles` module).

### D2 P1 — `checkpoint_store: Any | None` despite `CheckpointStore` already in scope
`agent.py` — `deps.checkpoint_store` is correctly `CheckpointStore | None`; `CheckpointStore` is already imported into `agent.py`. The factory param for the same concept is `Any`.
**Fix:** type it `CheckpointStore | None`.

### D3 P1 — `subagent_registry: Any | None` despite `DynamicAgentRegistry` imported & used
`agent.py` — the param the docstring calls "Optional DynamicAgentRegistry instance" is `Any`, while `DynamicAgentRegistry` is imported and used a few lines down.
**Fix:** `subagent_registry: DynamicAgentRegistry | None = None`.

### D4 P2 — `ask_user: Any` and `_branch_cost_tracking: Any` on `DeepAgentDeps`
`deps.py` — `ask_user`'s contract is concrete (`(question: str, options: list[PlanOption]) -> str | Awaitable[str]`, see `plan/toolset.py`); `_branch_cost_tracking` is read everywhere as `CostTracking | None` (so the one place the type is declared is the one place it's `Any`).
**Fix:** an `AskUserCallback` `Protocol`/alias for the former; `CostTracking | None` (TYPE_CHECKING import) for the latter.

### D5 P2 — `create_deep_agent` is 3 hand-maintained 68-param copies with no sync guard
`agent.py` — two `@overload` + impl, each repeating 68 params. Currently in sync, but nothing enforces it (and `DeepAgentSpec` is a 4th partial copy). The spec-drift test (`test_spec_defaults_match_factory`) is one-directional (spec→factory only) and doesn't check types.
**Fix:** a unit test that walks `typing.get_overloads(create_deep_agent)` and asserts param names + annotations match the impl (modulo `output_type`); extend the spec test to flag a new *serializable* factory param missing from the spec.

### D6 P2 — `FlushError`/`FlushReport` reachable via public `MergeResult` but not top-level importable
`__init__.py` — `MergeResult` is exported and its `errors` field is `list[FlushError]`, but `FlushError`/`FlushReport` aren't in the top-level imports/`__all__`, so a user can't import the type they need to inspect `errors`. Inconsistent with every other forking type.
**Fix:** add both to the top-level forking export block + `__all__`.

### D7 P3 — `BrowseResult` and `ResponseFormat` are exported public types with zero producers/consumers
`types.py` / `__init__.py` — `BrowseResult` is constructed/consumed nowhere (its docstring describes a wrapper that doesn't exist); `ResponseFormat = OutputSpec[object]` is a second name for an upstream type used nowhere internally.
**Fix:** wire the documented producer or drop the exports.

### D8 P3 — `DEFAULT_USAGE_LIMITS` missing from `__all__`; `unwrap_backend` ambiguous public/internal
`__init__.py` / `deps.py` — `DEFAULT_USAGE_LIMITS` is re-exported via `as`-alias but absent from `__all__` (the only such leak — all other 206 names resolve cleanly). `unwrap_backend` has a public name, is imported by 6 modules as a shared helper, yet isn't exported — pick `_unwrap_backend` (internal) or export it.

### D9 P3 — Stale docs
- **CLAUDE.md** still lists `EvictionProcessor` / `create_eviction_processor` as "legacy" — both were removed; only `EvictionCapability` exists. (`patch_tool_calls_processor` *is* still real — that entry is fine.)
- `create_deep_agent` docstring omits ~7 public params (`extra_toolsets`, `subagent_extra_toolsets`, `edit_format`, `on_before_compress`, `on_after_compress`, `on_eviction`, `stuck_loop_detection`).

---

## E. Organize by feature, not by kind — `Capability` is the unifying abstraction

> **Correction.** An earlier draft of this section claimed `Toolset` and `Capability` are orthogonal and "a capability can't expose a tool." **That is wrong.** Verified against `pydantic_ai.capabilities.AbstractCapability`: a capability exposes `get_toolset() -> AgentToolset | None`, `get_native_tools()`, `get_instructions()`, **and** every lifecycle hook (`before_model_request`, `after_tool_execute`, `wrap_run`, …). So **`Capability` is a superset** — one capability can own its tools (via `get_toolset`), its prompt (`get_instructions`), and its lifecycle behaviour. The removed `TeamCapability`/`PlanCapability` did exactly this (`get_toolset`). pydantic-ai even ships a `Toolset` capability that wraps a bare toolset.

That reframes the whole question. It isn't "tools vs lifecycle"; it's **organization by *kind* vs by *feature***. Today the repo is sliced **horizontally by kind** — every toolset in `toolsets/`, every capability in `capabilities/`, history/eviction/patch in `processors/`. The result: a single feature is smeared across two or three top-level directories, and the duplication/misfiling below are *symptoms* of that, not independent bugs.

### E0 ✅ P2 — Feature code is scattered across `toolsets/` + `capabilities/` (+ `processors/` / top-level)

Verified scatter (one feature, multiple homes):

| Feature | Pieces today | Homes |
|---|---|---|
| **memory** | `toolsets/memory.py` (tools + prompt + `load_memory`/`MemoryFile`/path helpers) · `capabilities/memory.py` (instruction-only cap) | 2 |
| **context** | `toolsets/context.py` (tool-less, prompt-only) · `capabilities/context.py` (same prompt) | 2 |
| **browser** | `toolsets/browser.py` (10 tools) · `capabilities/browser.py` (launch/close lifecycle) | 2 |
| **skills** | `toolsets/skills/` (7 files) · `capabilities/skills.py` | 2 |
| **forking** | `toolsets/forking/` (11 files) · `capabilities/forking.py` | 2 |
| **improve** | `improve/` (6-file logic pkg) · `toolsets/improve.py` (wrapper) | 2 |
| **checkpointing** | `toolsets/checkpointing/` — `CheckpointToolset` **and** the `CheckpointMiddleware` *capability* share `toolset.py` | 1 (mixed) |

To understand or delete "memory" you must touch `toolsets/memory.py` **and** `capabilities/memory.py`; the two emit the same prompt and can drift independently (E2). This is the structural cause of every finding below.

### Recommended target: one package per feature (vertical slice)

Exactly your proposal — co-locate everything a feature owns:

```
pydantic_deep/features/memory/
    __init__.py      # re-exports the public names (keeps `from pydantic_deep import …` stable)
    capability.py    # MemoryCapability — get_toolset() + get_instructions() + any hooks
    toolset.py       # AgentMemoryToolset (the read/write/update tools)
    service.py       # load_memory / format_memory_prompt / get_memory_path (pure logic, no agent deps)
    types.py         # MemoryFile, MemoryAccessError
```

Same shape for `context/`, `skills/`, `forking/`, `browser/`, `improve/`, `checkpointing/`, `teams/`, `plan/`, and the lifecycle-only ones (`stuck_loop/`, `periodic_reminder/`, `hooks/`, `message_queue/`, `eviction/`, `patch/`, `history_archive/`) — which simply have a `capability.py` and maybe `service.py`, no `toolset.py`.

**Two decisions, separable:**

1. **Co-locate (clear win, low controversy).** Move each feature's files into one package. This *alone* kills E0/E1/E2/E3: the toolset and capability sit together and trivially share one `service.py` for the prompt, so they can't drift; the misfiled `CheckpointMiddleware` is just `checkpointing/capability.py`; the duplicate context implementations are forced into one folder where the redundancy is obvious and removed.

2. **Unify registration via `Capability.get_toolset()` (more opinionated).** Make each feature a single `Capability` that returns its toolset, so `create_deep_agent` wires features through **one** channel (`capabilities=[…]`) instead of today's split between `toolsets=` and `capabilities=`. This **reverses the earlier decision** (CODE_QUALITY_REPORT S6, which deleted `TeamCapability`/`PlanCapability` toward bare toolsets). With feature-folders + the superset fact, capability-packaging is the *more* consistent model — but it's optional; you can co-locate (1) and still register bare toolsets via `toolsets=`. Recommend (1) now; adopt (2) opportunistically per feature.

**Naming:** you suggested `capabilities/<feature>/`. That reads well *if* you also adopt (2) (every feature is a capability). If you keep bare toolsets for some, a neutral top-level — `features/` (or `plugins/`) — is more honest than filing a tool-less-toolset feature under `capabilities/`. Either way: **one top-level home, one folder per feature.** `processors/` then folds in as just three feature folders (`eviction/`, `patch/`, `history_archive/`).

### The symptoms this fixes (still worth listing as concrete cleanups)

- **E1 ✅ P2 — `ContextToolset` is a tool-less `FunctionToolset` (0 tool registrations, verified) that only does `get_instructions`** — i.e. a capability in a toolset's clothes — **and** duplicates `capabilities/context.py:ContextFilesCapability`. In a `context/` folder this is one `capability.py` + one `service.py`; the duplicate dies.
- **E2 ✅ P2 — `SkillsCapability`/`MemoryCapability`/`ContextFilesCapability` are instruction-only and shadow their toolsets' `get_instructions`** (none used by `create_deep_agent`; verified). Co-located, both read the prompt from the feature's `service.py` — single source, no drift.
- **E3 P3 — `CheckpointMiddleware` (pure capability) lives in `toolsets/checkpointing/toolset.py`.** Becomes `checkpointing/capability.py`.

### Backward compatibility (the real catch)

Moving files **does** break imports — but precisely which, and for whom, matters:

- **Pinned / older-version users are unaffected.** `pip` doesn't rewrite installed code; someone on `0.3.33` keeps the old layout forever. The risk exists **only on upgrade** to the version that ships the move.
- **Top-level imports are safe.** `from pydantic_deep import AgentMemoryToolset` stays working as long as the top-level `__init__.py` keeps re-exporting it. This is the blessed surface (`__all__` ≈ 190 names) — preserve it and it costs nothing.
- **Deep submodule imports are the break.** `from pydantic_deep.toolsets.memory import AgentMemoryToolset` / `from pydantic_deep.capabilities.periodic_reminder import …` resolve to the moved files. These are **not** private: the docs themselves teach them in **17 places** (`memory`, `periodic_reminder`, `browser`, `checkpointing`, `eviction`, `hooks`, `teams`, …). So they're effectively public and a bare move breaks them on upgrade.

**Options (pick one):**

- **(A) Compat shims — non-breaking.** Leave the old module paths as one-line forwarders: `toolsets/memory.py` → `from pydantic_deep.features.memory.toolset import *  # noqa: F403` (or explicit names) + optional `warnings.warn(DeprecationWarning)`. Nothing breaks; the real code is single-sourced in `features/`; old/new paths both resolve. Cost: the old dirs persist as a shim graveyard until you drop them.
- **(B) 0.x minor break.** Pre-1.0 semver permits breaking changes in a minor bump. Move cleanly, update the 17 doc imports, write a CHANGELOG "import paths moved" section, release `0.4.0`. Cleanest tree; upgraders who used deep paths must edit imports.
- **(C) Shim-then-remove (recommended).** Ship (A) with a `DeprecationWarning` for one minor cycle, update docs to the new paths now, then delete the shims in the *next* minor. Non-breaking today, clean later.

**Recommendation:** (C). Keep top-level `__all__` rock-solid always; add deprecation shims for the documented submodule paths; migrate the docs in the same PR. Treat this as the honest cost of the reorg — it is **not** free, and that cost is a legitimate reason to (i) do it pre-1.0 rather than later, and (ii) move **one feature per release-note entry**, not all at once.

### Other migration notes
- **External toolsets are consumed, not owned**: `console`/`todo`/`subagents` come from upstream packages (`pydantic-ai-backend`, `pydantic-ai-todo`, `subagents-pydantic-ai`). pydantic-deep *wires* them; they don't get a feature folder (their glue — e.g. `_TodoProxyBinder` — can live in a small `todo/` folder).
- **Cost**: pure structural churn (imports, `__all__`, the mypy "explicit re-export" rule). 100% coverage + the gate make it mechanically safe, but it touches many files — do it **one feature per commit** (start with `memory/` as the reference, since it's the smallest 2-file split), not a big-bang.
- **Effort**: P2 architecture, M–L. Highest long-term payoff of anything in this review: it removes a whole *class* of "feature smeared across dirs → drift" defects rather than patching instances.

**Bottom line:** the right move is **not** "toolsets → capabilities" (nor the reverse) — it's **stop organizing by kind**. Give each feature one folder (`capability.py` + `toolset.py` + `service.py`/`types.py`), since `Capability` is the superset that can already own a toolset. E1–E3 then disappear structurally instead of being whack-a-mole fixes.

## Cross-cutting themes

1. **Silent degradation is the #1 pattern.** Broad `except Exception` and `.get()` defaults repeatedly convert "this failed / this is malformed" into "this is empty / this is fine": corrupt history archive (B6), one bad SKILL.md (B1), failed eviction write (B4), dropped uploads (B9), dropped MCP entries (B13), whole-session improve loss (B5). None are caught by tests (the happy path passes) or types. **A pass that adds a `logger.warning`/`warnings.warn` before each swallow would surface a large class of field bugs at near-zero risk.**
2. **Blocking work on the Textual event loop** (C1, C2, C12) is the CLI's biggest UX liability — recurring `subprocess.run`/file IO/Docker on the loop. A small `run_worker(thread=True)` helper applied consistently fixes it.
3. **Concurrency lifecycle, not the core algorithm, is where forking is fragile** (A1–A4): cancel/cleanup/await paths that mostly hold the lock — except where they don't.
4. **`Any` on parameters whose concrete type is already imported in the same file** (D1–D4) — the cheapest typing wins available; each is a one-line change that restores checking at the call site users most need it.

## Prioritized roadmap

| # | Finding | Why first | Effort |
|---|---------|-----------|--------|
| 1 | **A1** auto/vote merge deadlock on deferred approval | Permanent hang in a real config | S |
| 2 | **B1** one bad SKILL.md aborts all discovery | Easy to hit, kills a whole feature | S |
| 3 | **C1/C2** blocking git/Docker on the UI loop | Most visible CLI defect | M |
| 4 | **C3** plaintext API-key file perms | Security | S |
| 5 | **B6/B4/B9/B13** add logging before silent swallows | Broad bug-surfacing, near-zero risk | S–M |
| 6 | **A2/A4** lock `aclose` + fix loser-quiesce timeout | Data-correctness under cancel | M |
| 7 | **B3** patch.py preserves instructions/timestamp | Silent history corruption on resume | S |
| 8 | **D1–D4** type the `Any` params with already-imported types | Cheap, restores call-site safety | S |
| 9 | **C4** unify the 3 transcript-replay copies | Active drift, recurring bugs | M |
| 10 | **chat.py** collapse 3× stream-loop → 1 helper | −250 LOC, removes a bug class | M–L |

## Verified non-issues (checked, not flagged)

- `MessageQueue` uses an `asyncio.Lock` for all mutating ops; display-only reads are documented as such.
- `materializer._safe_relative` correctly strips `..`/`.` (no path traversal); `_reap_process` shields `proc.wait()` against cancellation (no zombies).
- `goal.py` evaluator's broad `except` is correct by design (defaults to *not met* + logs `exc_info`, so a hiccup never declares premature success).
- `stuck_loop` math is sound; tool *errors* route through `on_tool_execute_error`, so they correctly don't pollute no-op detection.
- `deps.get_files_summary` `len(data["content"])` is a correct line count (`FileData.content` is `list[str]`).
- Constant container types are internally consistent (`frozenset` for membership, `tuple` for ordered defaults, `dict` for maps); error conventions are consistent (`ValueError` input, `RuntimeError` lifecycle, `TypeError` wrong-type, `SkillException` hierarchy).
- Dead-code sweep of `pydantic_deep` is essentially clean apart from `BrowseResult`/`ResponseFormat` (D7).

---

_Generated by a multi-pass review; P0/P1 and surprising P2 findings were re-verified by hand against source. Severities are calibrated to reachable configurations, not adversarial timing._
