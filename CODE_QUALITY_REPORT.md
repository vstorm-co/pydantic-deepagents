# pydantic-deep — Code Quality, Consistency & API Design Report

**Scope:** `pydantic_deep/` (~20,300 LOC, 60+ modules)
**Baseline / "ideal API":** pydantic-ai (`../open-source/pydantic-ai`)
**Method:** 6 parallel subsystem audits, each scored against pydantic-ai's conventions (keyword-only optionals; capability flags over scattered `isinstance`; `dataclass`/`TypedDict` over `dict[str, Any]`; `assert_never` for unions; `WrapperToolset` for cross-cutting toolset behavior; consolidate duplicated logic; avoid `Any`).

---

## 1. Executive verdict

The framework is **functionally strong but structurally drifting**. The core idea (a batteries-included deep-agent factory composing pydantic-ai capabilities/toolsets) is sound, and several modules are exemplary (`goal.py`, `memory.py`, `diff.py`, `materializer.py`, MCP layering). But the codebase is accreting three classes of debt that will compound:

1. **Type erosion** — `Any` is load-bearing where pydantic-ai would use `DeepAgentDeps`/`Protocol`/`TypedDict`. This is the single most pervasive issue and it silently disables the type checker exactly where bugs hide (deps access, tool inputs, callbacks).
2. **Duplication of primitives** — the same ~10 helpers (token estimation, head/tail truncation, backend resolution, message injection, name validation, skill discovery, decorator builders) are re-implemented 2–4× each, already diverging.
3. **Surface explosion** — `create_deep_agent` (69 params × 4 copies), `__all__` (~190 names), and feature wiring that grows linearly with `if flag: append(...)` blocks.

None of this is fatal; all of it is reversible now and expensive later. The recommendations below are sequenced to kill the highest-leverage debt first.

---

## 2. Subsystem scorecard

| Subsystem | LOC | Health | Headline issue |
|---|---|---|---|
| Agent factory / public API | ~2.5k | 🟠 | 69-param signature copied 4×; `# noqa: C901` linear wiring |
| Capabilities | ~2.5k | 🟠 | all `[Any]`; Team/Plan caps are no-op toolset wrappers; hooks.py mixes 3 concerns |
| Skills | ~2.7k | 🔴 | over-engineered; local vs backend discovery duplicated wholesale; 4× decorator copy |
| Core toolsets | ~3.2k | 🟠 | `dict[str,Any]` tool inputs; teams.py/checkpointing.py do too much |
| Forking | ~4.4k | 🟠 | 21.5% of framework; 1595-line god-object coordinator; speculative judge/vote slice |
| Processors/MCP/Improve/Core | ~3.8k | 🟠 | dead EvictionProcessor; improve runs on `dict[str,Any]`; types.py is 83% fork types |

**Exemplary (keep as-is, use as the house style):** `goal.py`, `toolsets/memory.py`, `toolsets/forking/diff.py`, `toolsets/forking/materializer.py`, `processors/patch.py` (the legacy/new split here is *correct*), MCP layering.

---

## 3. Systemic / cross-cutting issues (ranked by leverage)

These cut across subsystems and are the real tech-debt drivers. Fix these and most per-file findings dissolve.

### S1 🔴 `Any` instead of `DeepAgentDeps` / `Protocol` / `TypedDict`
The deep agent has a concrete `DeepAgentDeps`, yet **every capability is `AbstractCapability[Any]`** and reaches into deps via `getattr(ctx.deps, "fork_coordinator", None)` / `hasattr(ctx.deps, "backend")` (`capabilities/forking.py:104,154`, `memory.py:58`, `context.py:51`). pydantic-ai's own capabilities (`web_search.py:19`, `process_history.py:26`) are generic over `AgentDepsT` so `ctx.deps` stays typed.
- Also: `get_instructions(self) -> Any` in 4 capabilities (base declares `AgentInstructions[AgentDepsT] | None`); `request_context: Any` in some `before_model_request` but the real `ModelRequestContext` in others (`message_queue.py:130` correct vs `hooks.py:457` Any).
- Callbacks typed `Any`: `on_context_update`/`on_before_compress`/`on_after_compress`/`on_eviction`/`on_cost_update` (`agent.py:494-567`), `ProgressCallback = Any` (`improve/analyzer.py:40`), `BranchRunnerFunc = Any` (`forking/coordinator.py:70`).

**Fix:** parametrize capabilities on `DeepAgentDeps` (or a `TypeVar` bound to it); define callback type aliases; drop the `getattr`/`hasattr` probes. Single biggest typing-discipline win.

### S2 🔴 `dict[str, Any]` where a model exists
Tool inputs the model fills are untyped dicts with `m["name"]` / `o.get("label")` access that `KeyError`s on malformed output:
- `teams.spawn_team(members: list[dict[str,str]])` (`toolsets/teams.py:407`) — `TeamMember` dataclass already exists.
- `plan.ask_user(options: list[dict[str,str]])` (`toolsets/plan/toolset.py:185`) — defensive `{"label":"N/A"}` at `:204` is the tell.
- `improve/` walks the pydantic-ai wire format as raw dicts (`extractor.py:185-361`) and hand-hydrates dataclasses in an 88-line `_dict_to_session_insights` (`extractor.py:493-580`) — while `history_archive.py:222` *in the same package* already uses `ModelMessagesTypeAdapter` correctly.
- `Checkpoint.metadata: dict[str,Any]` + manual serialize/deserialize (`checkpointing.py:74,215-240`); `MCPAuth`/`MCPServerConfig` hand-rolled `to_dict`/`from_dict` (`mcp/config.py:81-182`).

**Fix:** accept structured inputs (dataclass/TypedDict) on tools; load messages via `ModelMessagesTypeAdapter`; make improve insight types + MCP config `BaseModel`.

### S3 🔴 Duplicated primitives (already diverging)
| Primitive | Copies | Locations |
|---|---|---|
| `NUM_CHARS_PER_TOKEN` (=4) | 2–3 | `eviction.py:35`, `browser.py:65`, imported in `memory.py` |
| approx token estimate | 3 | eviction, `improve/extractor.py:205`, summarization `count_tokens_approximately` |
| head/tail truncation | 3 | `eviction.create_content_preview`, `browser.py:161`, `context.py:154`, `improve/extractor.py:240` (ratios differ 0.7/0.3 vs 0.5/0.5) |
| `_resolve_backend` | 2 | `eviction.py:318` & `:536` |
| message-injection ("fresh list + reassign `request_context.messages`") | 3 | `message_queue.py:142`, `periodic_reminder.py:285`, `forking.py:159` (diverge: append-part vs append-request) |
| skill name validation | 3 | `skills/types.py:59`, `directory.py:73`, `toolset.py:545` (only one checks reserved words) |
| local vs backend skill discovery | wholesale | `skills/backend.py:321-570` duplicates `directory.py:220-441` + `local.py` |
| resource/script decorators | 4 | `skills/types.py:235-338,404-501` (~200 LOC) |
| `_flush_*` shell helpers | 3 | `forking/isolation.py:828-964` |
| hooks dispatch loops | 6 | `capabilities/hooks.py:416-487` |

**Fix:** one `pydantic_deep/_text.py` (token + truncation), one `_resolve_backend`, one message-injection helper, one skill-name validator, one skill-discovery engine parameterized over a file-access protocol, one decorator builder, one `_flush_via_shell`, one `_dispatch`.

### S4 🟠 Surface explosion in `create_deep_agent` + public API
- `create_deep_agent` = **69 params**, written **3×** (2 `@overload` + impl, `agent.py:337/415/494`) and re-declared a **4th** time as `DeepAgentSpec` (`spec.py:60-107`). The overloads differ only in `output_type`'s type. pydantic-ai keeps `Agent.__init__` at ~19 by pushing features into `toolsets`/`capabilities` lists — pydantic-deep duplicates that mechanism with ~15 `include_*` flags *plus* the lists.
- Body is ~940 lines (`# noqa: C901`): ~25 sequential `if flag: ... append(...)` blocks with inline lazy imports.
- `__all__` ≈ 190 names (re-exports forking/eviction internals + ~25 `DEFAULT_*`). Legacy `*Processor` aliases shipped next to `*Capability` with no `@deprecated`.

**Fix:** collapse overloads to vary only on `output_type` (e.g. `Unpack[TypedDict]`); make wiring table-driven (`(predicate, builder)` registry → removes `C901` + inline imports); derive `DeepAgentSpec` from `inspect.signature`; curate `__all__`; add `@deprecated`.

### S5 🟠 God-objects & oversized / concatenated files
- `forking/coordinator.py` (1595) — ≥6 responsibilities (task lifecycle, approval routing, budget, merge, judge orchestration, test-runner). Extract `ForkResolver` + `budget.py` (~−500 LOC).
- `toolsets/teams.py` (595) — data model + concurrency primitive + message bus + coordinator + toolset in one file. Split into a package.
- `toolsets/checkpointing.py` (601) & `capabilities/hooks.py` (829) — **mid-file `# noqa: E402` import walls** (`checkpointing.py:321`, `hooks.py:259`) are the seam where two files were glued. hooks.py is ~half security-policy helpers (`:516-813`) unrelated to the capability.
- `types.py` (562) — **83% is the forking subsystem's private types** (`:87-562`); belongs in `toolsets/forking/`.
- `DeepAgentDeps` (`deps.py`) — 16 fields incl. 5 private fork-bookkeeping dunders + 6 `Any`; `clone_for_subagent` enumerates fields manually (new fields silently not propagated).

**Fix:** decompose; move imports to top; relocate fork types; fold fork state into one `_fork: ForkState | None`; use `dataclasses.replace` for cloning.

### S6 🟠 Capability-vs-toolset boundary incoherent
`TeamCapability` and `PlanCapability` (`capabilities/teams.py`, `plan.py`) implement *only* `__post_init__` + `get_toolset` — zero added behavior. pydantic-ai ships `Toolset(toolset=...)` for exactly this. `Skills`/`Memory`/`ContextFiles` caps only add instruction injection, which a toolset's own `get_instructions` already surfaces.

**Fix:** delete Team/Plan caps (pass `Toolset(create_*_toolset())` or register toolsets directly); evaluate collapsing the instruction-only caps. Removes ~5 classes + duplicated boilerplate.

### S7 🟢 Closed-set `str` instead of `Literal`; reaching into privates
- `str` for closed enums: `checkpointing.frequency` (`:355`), `teams.status` (`:35,235`), `stuck_loop.action` (`:96`).
- Private access across package/lib boundaries: `LocalBackend._read_bytes` (`isolation.py:58`), `StateBackend._files` (`deps.py:80`), `agent._root_capability.capabilities` reflection (`coordinator.py:1526`), skills toolset privates imported into `capabilities/browser.py:32`.

**Fix:** `Literal`/enum; widen `BackendProtocol` upstream instead of `getattr` to privates; receive deps via DI rather than reflecting into the agent.

---

## 4. Forking — proportionality call-out

Forking is **21.5% of the framework** for an off-by-default feature. The overlay/diff/merge **core is genuinely good** (clean protocols, documented trade-offs, careful cancellation). The disproportionality comes from bolting a **speculative LLM-judge + vote + confidence-math + subprocess test-runner** (~600 LOC across `coordinator.py` + `judge.py`) onto that core — gated behind `auto`/`vote` strategies whose own docstrings admit the 0.65 confidence cap "forces fallback-to-manual in practice." Also: `isolation.py` hashes the **entire tree (sha256) before/after every shell command** to detect mutations — O(tree × sha256) per `execute`. And `async_execute` (`isolation.py:638`) has **zero callers** while `_run_tests_for_branch` re-implements snapshot+subprocess from scratch.

**Recommendation:** don't quarantine — **sub-gate** the judge/vote/test-runner behind a separate flag so the valuable fork/overlay/merge path stands alone; delete `async_execute` or make the test-runner reuse it; document/gate the full-tree-hash perf cliff.

---

## 5. Legacy/new coexistence (a recurring worry — quantified)

Only **one** real legacy pair, contrary to the impression of many:
- **Eviction** — `EvictionProcessor` + `create_eviction_processor` are **dead** (wired nowhere; `agent.py:1248` uses only `EvictionCapability`). ~190 LOC + `DEFAULT_MAX_EVICTED_IDS`. → **deprecate & delete.**
- **Patch** — `patch_tool_calls_processor` (function) is **still reused** standalone by the CLI (`forking.py:233`, `screens/chat.py`, `commands.py`); the capability is a 2-line wrapper. → **keep; document intent.** (Stale `PatchToolCallsProcessor` name in its docstrings — fix.)

The native-Capabilities migration is effectively done; the processors are residue, not a parallel live system.

---

## 6. Prioritized roadmap

**P0 — high leverage, low risk (do first):**
1. **One `_text.py`** — consolidate `NUM_CHARS_PER_TOKEN` + approx-tokens + head/tail truncation (S3). Touches eviction/browser/context/improve/summarization; pure dedup.
2. **Delete dead `EvictionProcessor`** path (S5/§5) — ~190 LOC, zero risk.
3. **Type the tool inputs** for `spawn_team` / `ask_user` (S2) — fixes real `KeyError`-on-model-output bugs.
4. **Relocate fork types** out of `types.py` into `toolsets/forking/` (S5).
5. Fix stale docstring names (`PatchToolCallsProcessor`), `output_style` builtin list drift, delete dead `base_prompt` param + `extra_instructions` field.

**P1 — structural, medium effort:**
6. **Parametrize capabilities on `DeepAgentDeps`** + callback type aliases; drop getattr/hasattr probes (S1).
7. **Collapse `create_deep_agent` overloads** + **table-driven wiring** + derive `DeepAgentSpec` from signature (S4).
8. **Delete Team/Plan capabilities**, use `Toolset(...)` (S6).
9. **Split** teams.py, checkpointing.py (move imports to top), hooks.py (extract `_hooks_security.py`/`_hooks_exec.py` + `_dispatch`).
10. **Unify skills discovery** (local/backend → one engine) + dedupe the 4× decorators + 3× name validators (S3) — biggest single LOC win (~600–800 LOC).
11. Consolidate message-injection helper; `Literal` for closed-set `str`s.

**P2 — larger / judgement calls:**
12. **Decompose `ForkCoordinator`** (`ForkResolver` + `budget.py`); resolve sync/async subprocess duplication; **sub-gate the judge/vote/test-runner** (§4).
13. **Type the improve pipeline** via `ModelMessagesTypeAdapter` + `BaseModel` insight types (deletes the 88-line hydrator + synthesizer copy-loop) (S2).
14. **Curate `__all__`** + `@deprecated` legacy aliases (S4).
15. Tame `DeepAgentDeps` (`_fork` sub-object, `Protocol` for `ask_user`/`subagents`, `dataclasses.replace` clone) (S5).

**Guiding principle for all of it:** when adding a feature, prefer composing a pydantic-ai capability/toolset object over adding a `create_deep_agent` kwarg + an `if`-block. That one habit change stops S4 and most of S5 from regrowing.

---

# Appendix — full per-subsystem findings

Severity legend: 🔴 high / 🟠 medium / 🟢 low / nit.

## A. Agent factory / public API (`agent.py`, `__init__.py`, `spec.py`, `subagents.py`, `prompts.py`, `styles.py`)

### API Design & Consistency
- 🔴 `agent.py:494` — `create_deep_agent` takes **69 parameters** (pydantic-ai `Agent.__init__` ~19). ~15 `include_*` flags **plus** the toolset/capability lists duplicate the same composition mechanism twice. Push `include_*` + satellite params into pre-built capability/toolset objects passed via existing `capabilities`/`toolsets` lists; keep a thin factory wiring defaults.
- 🔴 `agent.py:337 / :415 / :494` — the ~69-param signature is written **three times** (2 `@overload` + impl); only difference is `output_type` annotation. ~220 lines of pure duplication. Collapse overloads to vary only on `output_type` (`Unpack[TypedDict]`) or accept looser return type.
- 🔴 `spec.py:60-107` — `DeepAgentSpec` re-declares **48 fields a 4th time** with hand-copied defaults. `test_spec_defaults_match_factory` (`tests/test_spec.py:46`) `continue`s past fields not in the factory, so it never checks completeness — drift undetected. Derive spec from `inspect.signature(create_deep_agent)` or assert set-equality both directions.
- 🟠 `agent.py:494` — no bare `*`; all 69 params positional-or-keyword. Insert `*` after `model` (pydantic-ai convention).
- 🟠 `__init__.py:297-531` — ~190 names in `__all__` (re-exports forking/eviction internals, ~25 `DEFAULT_*`). Curate to real entry points + user-constructed types.
- 🟠 `__init__.py:154-163,419-421,471-472` — legacy aliases (`EvictionProcessor`/`create_eviction_processor`, `patch_tool_calls_processor`) shipped next to replacements with no `@deprecated` (violates project's own "Rename a Class" rule).
- 🟢 `__init__.py` — factory naming inconsistent: `create_*` vs class-based (`DeepAgent.from_spec`, `SkillsToolset(...)`). Document or unify.

### Code Quality
- 🔴 `agent.py:343,421,499` + `spec.py:62` — **`base_prompt` is a dead parameter** (declared 4×, never read; only `instructions` is consulted at `:1092`). `test_spec.py:99` pins the no-op round-trip. Implement or delete everywhere.
- 🟢 `agent.py:592-595` vs `styles.py:155` — docstring lists 4 built-in styles; `BUILTIN_STYLES` defines 7. Fix docstring.
- 🟠 `agent.py:494-1436` — ~940-line function (`# noqa: C901`): ~13 `if flag: all_toolsets.append(...)` blocks (`:899-1118`) + ~12 `if flag: all_capabilities.append(...)` (`:1237-1365`), each with inline lazy import. Make table-driven `(predicate, builder)` registry → removes `C901` and inline-import sprawl.
- 🟠 `agent.py:939-947` vs `:1066-1087` — `_make_default_deep_agent_factory` and the inline team-member factory (`# pragma: no cover`) are near-duplicate closures. Unify into one parametrized helper.
- 🟠 `agent.py:494-567` — ≥16 `Any`-typed params where precise types exist (callbacks, `subagent_registry`, `checkpoint_store`, `output_style: str | Any`). Introduce callback aliases + real protocol/class types.
- 🟢 `agent.py:1127,1146,1178,1237,1303` — `dict[str,Any]`/`list[Any]` accumulators; `all_capabilities` could be `list[AbstractCapability[Any]]`; `agent_create_kwargs` a `TypedDict`.
- 🟢 `agent.py:1432-1435` — 3 private attrs monkey-patched onto returned `Agent` with `# type: ignore`. Fragile cross-layer coupling; prefer a returned struct/accessor.
- 🟢 `agent.py:1066` — team factory is `# pragma: no cover` (untested path inside core factory); consolidation would fix.

### Top 5 (this scope)
1. Kill the 3× signature duplication (`agent.py:337/415/494`).
2. Make toolset/capability wiring table-driven (`:899-1118`, `:1237-1365`).
3. Delete the dead `base_prompt` param.
4. Auto-derive `DeepAgentSpec` from the factory signature; harden the drift test.
5. Curate `__all__`; `@deprecated` the legacy `*Processor` aliases.

## B. Capabilities (`capabilities/*`)

### Cross-cutting
- 🟠 `AbstractCapability[Any]` everywhere (`context.py:15`, `browser.py:113`, `forking.py:28`, `memory.py:20`, `message_queue.py:116`, `hooks.py:268`, `skills.py:22`, `periodic_reminder.py:241`, `stuck_loop.py:75`, `teams.py:16`, `plan.py:15`). Reference caps are generic over `AgentDepsT`. Parametrize on `DeepAgentDeps`; drop `getattr`/`hasattr` probes.
- 🟠 `get_instructions(self) -> Any` in `memory.py:54`, `browser.py:194`, `skills.py:60`, `context.py:47` (base returns `AgentInstructions[AgentDepsT] | None`). Annotate the closure.
- 🟠 "wrap a toolset + inject its instructions" copy-pasted 4× (`skills.py:47-69`, `memory.py:42-63`, `context.py:38-56`; Team/Plan minus instructions). Shared base or use pydantic-ai `Toolset`.
- 🟢 `get_serialization_name()` never overridden → caps advertise as spec-serializable when they aren't; return `None`.

### hooks.py (829)
- 🟠 Reinvents pydantic-ai's native `Hooks` (decorator registration, typed sigs). Keep the command-hook layer; consider layering on native `Hooks`.
- 🟠 Six near-identical dispatch loops (`:416-487`) → extract `_dispatch(event, *, ...)`.
- 🟠 `before_model_request(... request_context: Any)` (`:457`) vs real `ModelRequestContext` in `message_queue.py:130`. Inconsistent.
- 🟠 Mid-file `# noqa: E402` re-imports (`:259-264`); ~half the file is security-policy helpers (`:516-813`) unrelated to the capability → split to `_hooks_security.py`/`_hooks_exec.py`.
- 🟢 Hand-rolled shell quoting in `_execute_command_hook` (`:197-201`) — add a comment why `shlex.quote` isn't usable.
- 🟢 `HookResult.modified_args: dict[str,Any]` trusted verbatim from JSON (`:178-179`).

### browser.py
- 🟠 `wrap_run` `# noqa: C901` (~140 lines, nested closures) — hoist popup/route handling onto `_BrowserState`.
- 🟠 Imports toolset privates `_BrowserState`/`_check_allowed_domain`/`_require_browser` (`:32-39`) — layering violation.
- 🟢 `prepare_tools` flips `unapproved`→`function` (`:226-227`) silently defeating approval; document as policy.

### message_queue.py / periodic_reminder.py
- 🟠 "fresh list + reassign `request_context.messages`" duplicated and divergent (`message_queue.py:142-151` append-to-last-request vs `periodic_reminder.py:285-287` append-new-request; comment claims they "mirror"). Extract `_inject_user_message(...)`.
- 🟢 `format_steering`/`format_follow_up` public (`message_queue.py:206`) vs private `_render` (`periodic_reminder.py:223`) — inconsistent boundary.
- 🟢 `LiveForkCapability.for_run` (`forking.py:90-98`) manually re-lists every field in `replace()` (drops new fields) — use `replace(self)` + restore `_agent_ref`.

### stuck_loop.py
- 🟢 Clean. `action: str` (`:96`) should be `Literal["warn","error"]`.

### forking.py (capability)
- 🟠 Heavy `getattr`/`setattr` on deps for `fork_coordinator`/`_branch_id`/`_parent_fork_coordinator` (`:104,120,154-155`); `_agent_ref: Any` set externally.
- 🟢 `after_run` is a documented no-op (`:123-134`) — dead code / over-investment.

### teams.py / plan.py (capabilities)
- 🔴 **Not capabilities — toolset wrappers.** Only `__post_init__` + `get_toolset`. Use pydantic-ai `Toolset(...)`; delete both classes.
- 🟠 `teams.py` uses `Any` for `registry`/`task_fn`/`task_manager`/`_toolset` (`:31-35`) + `# type: ignore[no-any-return]` (`:46`). Import real types.

### Top 5 (this scope)
1. Delete `TeamCapability`/`PlanCapability`; collapse toolset-wrapper caps.
2. Parametrize all caps on `DeepAgentDeps`; type the closures.
3. Split hooks.py (security/exec submodules; one `_dispatch`).
4. Extract shared message-injection helper.
5. Fix `for_run` clones; `Literal` over runtime-validated `str`.

## C. Skills (`toolsets/skills/*`, ~2.7k LOC)

**Verdict:** significantly over-engineered. Triple-duplicated discovery, ~120 lines of near-verbatim decorator copy, unused types/exceptions. Disciplined consolidation could remove 600–800 LOC.

### types.py (520)
- 🔴 Decorator duplication (`:235-338` vs `:404-501`) — `Skill.resource/script` + `SkillWrapper.resource/script` are 4 byte-identical bodies (~200 lines). Extract `_build_resource`/`_build_script`.
- 🟠 `SkillResource`/`SkillScript` mix 3 modes (`content`/`function`/`uri`) with `__post_init__` runtime assert (`:89-95,143-149`). Use distinct types / tagged union.
- 🟠 Base `load`/`run` raise `ValueError`, not the skill hierarchy (`:124,176`) — callers can't `except SkillException` uniformly.
- 🟢 `SkillWrapper.function: Callable[[], str]` too narrow (`:386`); `SKILL_NAME_PATTERN` duplicated (`:28` & `directory.py:40`).

### directory.py (531) + local.py (314)
- 🔴 `SKILL_NAME_PATTERN` defined twice; name-validation re-implemented 3× differently (`directory.py:73`, `toolset.py:545`, `types.py:59`) — only one checks reserved words. One `validate_skill_name`.
- 🟠 Hand-rolled YAML fallback (`directory.py:123-181`, ~60 LOC) guards an unlikely no-pyyaml env. Drop or isolate.
- 🟠 Two frontmatter regexes (`:134` vs `:201`) can disagree.
- 🟢 `get_skills` keys by `uri` (directory) vs `name` (backend) — inconsistent dict contract.
- 🟢 `local.py:152` `stdin_data` always `None` — dead.

### backend.py (575) — duplication epicenter
- 🔴 Whole-file structural duplication of `local.py`/`directory.py`: `load` (`:67-114`↔`local.py:43-85`), discovery (`:321-407`↔`directory.py:220-344`), skill-from-file (`:506-570`↔`directory.py:381-441`). Share one engine over a file-access protocol (~400-600 LOC).
- 🟠 Extension detection diverges: `rsplit(".",1)` (`:98`) vs `Path().suffix` (`local.py:69`).
- 🟠 `field(default=None)` + type-ignore on required `backend`/`executor` (`:65,210`).
- 🟠 Backend script shell-quoting model differs from local argv model (`:165-180`); flag keys unquoted.
- 🟢 Bare `except Exception: continue` in discovery (`:341,387,475`).

### toolset.py (605)
- 🟠 Tool bodies return error strings (`:367-369,416-418,449-451`) while `get_skill` raises (`:257`). Pick one; factor repeated not-found block.
- 🟠 `_build_resource_xml`/`_build_script_xml` identical (`:292-312`) → `_build_xml(node, tag)`.
- 🟠 `get_instructions` string-concat XML (`:478-484`) vs `.format` template (`:61-77`) — two styles.
- 🟢 `descriptions: dict[str,str]` stringly-typed (`:189`) → `Literal`-keyed `TypedDict`.

### exceptions.py (41)
- 🟠 `SkillResourceNotFoundError` exported, **never raised**. Wire in or delete.
- 🟢 Otherwise justified hierarchy.

### Cross-cutting
- 🔴 `Any` pervasive: `RunContext[Any]`, `ctx: Any`, `function: Callable[..., Any]`; `DepsT` TypeVar erased to `Any` in `SkillsToolset`. Thread `DepsT` or drop.

### Top 5 (this scope)
1. Unify local/backend discovery pipeline (~400-600 LOC).
2. Collapse 4 copy-pasted decorators (`types.py`).
3. One name validator / frontmatter parser / XML builder.
4. Consistent error handling (raise vs string; use/delete `SkillResourceNotFoundError`).
5. Tighten types over `Any`/runtime checks.

## D. Core toolsets (`memory`, `context`, `checkpointing`, `teams`, `browser`, `liteparse`, `improve`, `plan`)

### Cross-cutting
- 🟠 No rule for `FunctionToolset` subclass (memory/context/checkpointing/browser/liteparse/improve) vs `create_*_toolset()` factory (teams/plan). Standardize: factory for tool-only; subclass only to override `get_instructions()` (memory/context).
- 🟠 `id` param inconsistent (some accept, some hardcode `"deep-*"`). Make universal.
- 🟢 `descriptions` override param consistently applied except `improve.py`.

### memory.py
- 🟢 Best file in scope (dataclass + free functions + canonical injection).
- 🟠 `ctx.deps.backend` bare attr (`:268,284,312,344`) vs `getattr` guard in `context.py:246` — align.

### context.py
- 🟠 `_discover_and_load` (`:124-151`) duplicates `discover`+`load`; read loop appears 3× (`:89-95,116-121,144-150`). Collapse.

### checkpointing.py (601)
- 🔴 Mid-file imports (`:321-331`) re-importing `dataclass`/`field` — split into `store.py` + `toolset.py`, imports to top.
- 🟠 `metadata: dict[str,Any]` + manual serialize/deserialize (`:74,215-240`) → `asdict` + typed `CheckpointMetadata`.
- 🟠 `frequency: str` (`:355`) → `Literal["every_turn","every_tool","manual_only"]`.
- 🟢 `_resolve_store` duplicated (`:363` & `:562`).

### teams.py (595)
- 🔴 Doing too much: data model + `SharedTodoList` + `TeamMessageBus` + `AgentTeam` + toolset. Split into a package.
- 🔴 `members: list[dict[str,str]]` (`:407`) with `m["name"]` — use `TeamMember`/TypedDict.
- 🔴 `task_manager`/`registry`/`agent_factory`/`task_fn` all `Any` (`:370-375,257`) — `TYPE_CHECKING` import real types.
- 🟠 Toolset reaches into `team._handles` (`:471,475,522,569,588`); `_team = [None]` cell hack (`:401`).
- 🟠 Brittle task-id parsing from result string (`:493-497`) — return structured handle.
- 🟠 `status: str` (`:35,235`) → `Literal`.

### browser.py (toolset half)
- 🟢 `_BrowserState` closure design sound.
- 🟠 `NUM_CHARS_PER_TOKEN` redefined (`:65`); `_truncate_content` triplicated (`browser.py:161`, `context.py:154`, eviction). One `_text.py`.
- 🟠 `_enforce_allowed_domain` runs after `page.evaluate` (`:558`) — allowlist isn't a JS sandbox; document.

### liteparse.py
- 🟠 `_CLINotFoundError` reload-stable machinery (`:27-57`, ~30 LOC) exists only to survive `importlib.reload()` in tests — test driving production complexity.

### improve.py (toolset)
- 🟠 `state: dict[str,Any]` with `.get` (`:74,100-103`) → TypedDict.
- 🟠 Outlier: no `id`/`descriptions` params.

### plan/toolset.py
- 🟢 Clean factory.
- 🟠 `options: list[dict[str,str]]` (`:185`) with `choice['label']` (`:204`) → `PlanOption` TypedDict.

### Top 5 (this scope)
1. Eliminate `dict[str,Any]` tool inputs (`spawn_team`, `ask_user`).
2. Split teams.py and checkpointing.py.
3. Consolidate text-truncation + `NUM_CHARS_PER_TOKEN` into one module.
4. Standardize toolset construction + `id`/`descriptions` params.
5. Replace `Any` on teams↔subagents boundary with `TYPE_CHECKING` imports; structured task-id return; `Literal` for closed-set `str`.

## E. Forking (`toolsets/forking/*` + `capabilities/forking.py`, ~4.4k LOC = 21.5%)

### Proportionality
- 🟠 Disproportionately large for an off-by-default capability. Five semi-independent concerns (overlay COW FS, async orchestration + budget, materialization + external diff, LLM judge + vote/confidence, subprocess test-runner). The judge/vote/test-runner trio (~600 LOC) is most speculative — sub-gate it; core fork/overlay/merge is the valuable part.

### coordinator.py (1595) — god-object
- 🔴 `ForkCoordinator` holds ≥6 responsibilities. Extract `ForkResolver` (resolve/_run_judges/_build_branch_outcomes/_compute_signals/test-runner, ~−500 LOC); move budget watchers (`:274-330`) to `budget.py`.
- 🟠 `_run_branch_with_approval` (`:660-742`) duplicates agent.run-vs-runner branching twice (`:691-700`,`:726-741`) → one `_invoke(...)`.
- 🟠 `merge_or_select`/`abort_fork`/`aclose` share copy-pasted cancel-await-timeout loop (`:945-956,1025-1034,1491-1501`) → `_quiesce_branch(...)`.
- 🟠 Two identical done-callbacks (`:625-644` & `:795-813`).
- 🟢 `BranchRunnerFunc = Any` (`:70`) — define `Protocol`. `_handle is None` guard ×5 → `_require_handle()`. `_describe_blocked_call` getattr-driven (`:197-225`).

### isolation.py (1038) — overlay
- 🟠 Snapshot/propagate over-engineered: hashes entire tree (sha256) before/after every `execute` (`:120-356`) — O(tree × sha256). Gate shell-mutation tracking behind a flag.
- 🔴 Sync/async incoherent: `async_execute` (`:638`) has **zero callers**; `_run_tests_for_branch` re-implements snapshot+subprocess. Delete or reuse.
- 🟠 `flush_to` `# noqa: C901` (`:726`); `_flush_delete/_flush_mkdir/_flush_rmdir` (`:828-964`) near-identical → `_flush_via_shell(...)`; `import shlex` ×3 → top.
- 🟠 `_read_backend_bytes` uses private `backend._read_bytes` (`:58-61`).
- 🟢 `Any` + `pyright: ignore` proliferation in flush helpers — richer `BackendProtocol`.

### __init__.py (473)
- 🟠 `create_fork_toolset` 350-line `# noqa: C901`; `merge_or_select` tool (`:202-320`) embeds action-dispatch that belongs on the coordinator.
- 🟠 Mixed `Report | str` returns — error-string concern should be a wrapper, not in return types.
- 🟢 `delete_file` tool is a branch-FS op misplaced among coordination tools; `extra_instructions` field is **dead** (coerced into `BranchSpec`, never read).

### judge/materializer/editor/store/diff
- 🟢 judge.py cleanest; minor: `count_stuck_loop_hits` string-matches stuck-loop markers (`:66-70`) — fragile cross-module contract.
- 🟢 store.py Protocol wider than any consumer (`list_all`/`remove` never called) — YAGNI; trim.
- 🟢 materializer.py / diff.py / editor.py — solid, well-scoped.

### Coupling
- 🟠 5 fork fields leak onto `DeepAgentDeps` (`deps.py:60-64`) → one `_fork_state`.
- 🟠 `create_deep_agent` imports `_PerBranchCostTracking` (`agent.py:1206`), sets `_agent_ref` post-construction (`:1435`); `_find_parent_cost_tracking` reflects into `agent._root_capability.capabilities` (`coordinator.py:1526`) — inverted DI.

### Top 5 (this scope)
1. Split `ForkCoordinator` (extract `ForkResolver` + `budget.py`).
2. Resolve sync/async subprocess duplication (delete `async_execute` or reuse).
3. Collapse `_flush_*` + the triplicate cancel-quiesce loop.
4. Sub-gate or remove the judge/vote/test-runner slice.
5. Consolidate fork state into `_fork_state`; stop reflecting into agent/pydantic-ai internals; `Protocol` for `BranchRunnerFunc`; drop dead `extra_instructions`.

**Net:** overlay/diff/merge core is good engineering; disproportionality is the speculative judge+test-runner+diff-launcher bolted on inside one 1595-line coordinator. Decompose and sub-gate, don't quarantine.

## F. Processors / MCP / Improve / Core

### Processors
- 🔴 `eviction.py:247-485` — `EvictionProcessor`/`create_eviction_processor` are **dead** (only `EvictionCapability` wired at `agent.py:1248`). Bespoke `_evicted_ids` FIFO + `DEFAULT_MAX_EVICTED_IDS` + `__call__` walk + `_resolve_backend`. Deprecate & remove (~190 LOC).
- 🟠 Two parallel eviction paths duplicate the recipe (`:387-416` vs `:573-624`); `_resolve_backend` duplicated (`:318` & `:536`).
- 🟢 `# type: ignore` on `BinaryContent` ×6 (`:137-146,825`) → one typed accessor.
- 🟢 `patch.py` legacy/new pair is **correct** (function reused by CLI; capability is adapter). Fix stale `PatchToolCallsProcessor` name in docstrings (`:17,238`).
- 🟢 `history_archive.py` cohesive; bare `except Exception: pass` (`:223`) low-priority.

### MCP — strongest area in scope
- 🟠 `MCPAuth`/`MCPServerConfig` hand-roll `to_dict`/`from_dict` (`config.py:81-182`) — make `BaseModel` or `asdict`+`TypeAdapter`.
- 🟠 `resolver` optional but positional (`registry.py:94`) — keyword-only.
- 🟢 `_load_mcp_classes -> tuple[Any,Any,Any]` (`:72`) forced by lazy import; `make_resilient` builds wrapper class per call (`:275`) — memoize.

### Improve (~1.4k LOC) — debt epicenter of this scope
- 🔴 Everything on `list[dict[str,Any]]` — `extractor.py:185-361` hand-parses wire format; `_dict_to_session_insights` (`:493-580`) is 88-line manual hydration. Use `ModelMessagesTypeAdapter` (already in `history_archive.py:222`) + `BaseModel` insight types.
- 🟠 Two type systems: dataclass insights vs synthesizer's parallel `_ProposedChangeModel`/`_SynthesisOutput` BaseModels + copy-loop (`synthesizer.py:20-35,102-113`).
- 🟠 Token estimation 3rd impl (`extractor.py:205-238`); head/tail truncation re-impl (`:240-262`).
- 🟢 `ProgressCallback = Any` (`analyzer.py:40`); hardcoded `8000` ×2 (`synthesizer.py:129-131`) → named constants.

### Core
- 🟠 `deps.py` — `DeepAgentDeps` god-object trending: 16 fields incl. 5 private fork dunders + 6 `Any` (`subagents`/`ask_user`/`context_middleware`/`checkpoint_store`/`_branch_cost_tracking`); docstring covers 5 of them. Group fork state into `_fork`; `Protocol` for `ask_user`/`subagents`.
- 🟠 `clone_for_subagent` (`:279-289`) enumerates 8 fields — new fields silently un-propagated. Use `dataclasses.replace`.
- 🟢 `__post_init__` reaches into `StateBackend._files` (`:80-82`); `object.__setattr__` on non-frozen dataclass (`:74,82`) unnecessary.
- 🟠 `types.py` — 83% (`:87-562`) is forking's private types. Move to `toolsets/forking/`; keep `types.py` cross-cutting. (`JudgeVerdict` correctly `BaseModel` with comment — good.)
- 🟢 `goal.py` — cohesive, exemplary; typed `Verdict`, graceful degradation, explicit `__all__`. No debt.

### Legacy/new count
- Eviction (dead) → remove. Patch (live function) → keep. Migration to native Capabilities is effectively done.

### Top 5 (this scope)
1. Deprecate & delete dead `EvictionProcessor` path (~190 LOC).
2. Type the improve pipeline (`ModelMessagesTypeAdapter` + `BaseModel`).
3. Relocate fork/branch types out of `types.py`.
4. Consolidate duplicated primitives (`approx_tokens` ×3, truncation ×2, `_resolve_backend` ×2).
5. Tame `DeepAgentDeps` (`_fork` sub-object, `Protocol`s, `replace` clone). Secondary: MCP config → pydantic; fix stale `PatchToolCallsProcessor` name.
