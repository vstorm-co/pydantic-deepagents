# Pydantic Deep Agents — 14-Day Content Plan to 10k ⭐

> **Internal marketing doc.** Not meant for the public repo — add to `.gitignore` or move to a private notes repo before pushing.
> Goal: convert the rewritten, forking-led README into a star surge. Current: ~830 ⭐. Target: momentum toward 10k.

---

## The one message (everything ladders up to this)

> **"The only AI agent that can fork itself — try 5 approaches in parallel, let an AI judge pick the winner."**

Every post, every asset, every comment reinforces this single idea. We do **not** lead with "open-source Claude Code" (that frames us as a worse copy). We lead with the thing literally no one else has: **Live Run Forking**.

Three supporting angles, used in rotation so it never feels like one ad on repeat:
1. **Forking** (the hook) — `git branch` for an agent's reasoning.
2. **Swarm + teams** (the depth) — agents that message each other and share a TODO list.
3. **Type-safe + any model + self-hosted** (the trust) — 100% typed, your keys, your machine.

---

## Phase 0 — Assets first (Day −2 and −1). Nothing ships without these.

A launch is only as good as its hero asset. **Record these before any post goes out.** The forking demo is the single highest-ROI artifact in this whole plan.

| # | Asset | What it shows | Where it's used | Tool |
|---|-------|---------------|-----------------|------|
| A1 | **`fork_demo.gif` / 60s MP4** ⭐ | `/fork` splits a real task into 3 branches streaming side by side → `/merge` → AI judge picks winner | README hero, HN, X, Reddit, YouTube | `asciinema` + `agg`, or screen-record the TUI |
| A2 | **Swarm GIF** | `spawn_team` + agents messaging each other + shared TODO list filling up | X thread, dev.to | screen-record |
| A3 | **30s "install → first answer"** | `curl … | bash` → `pydantic-deep` → real task done | Reddit r/commandline, X | screen-record |
| A4 | **Comparison card (static PNG)** | The README "Why pydantic-deep" table, branded | X, LinkedIn, Reddit | the Vstorm `content-skills` repo / Figma |
| A5 | **Architecture diagram (clean)** | Forking-centric harness diagram | dev.to deep-dive, docs | Excalidraw |

> If only ONE asset gets made, make **A1**. The fork demo is the tweet that gets quote-tweeted.

**Asset acceptance bar:** under 15s to "wow" in A1, captions/labels on every branch, no API keys visible, dark theme, ≤ 8 MB GIF (or host the MP4 and link).

---

## Phase 1 — The Forking Launch (Week 1)

Treat forking as a **product launch**, not a feature note. Coordinate the same day across HN + Reddit + X so they cross-amplify.

### Day 1 (Tue) — 🚀 Launch day

| Channel | Format | Title / hook (draft) | Asset |
|---------|--------|----------------------|-------|
| **Hacker News** | Show HN | `Show HN: An AI agent that forks itself — runs N approaches in parallel, AI judge merges the winner` | A1 + repo link |
| **X/Twitter** | Video + thread | "Most AI agents give you one shot. Ours forks. 🧵 Watch one task split into 3 branches and an AI judge pick the winner ⬇️" | A1 |
| **r/LocalLLaMA** | Text + GIF | `I built an open-source agent that branches mid-run like git — works with any model incl. local Ollama` | A1, A3 |
| **Lobsters** | Link | Same as HN, tag `ai`, `python` | A1 |

**Timing:** HN post 8:00–9:30 AM ET (Tue/Wed best). X thread same morning. Reddit early afternoon ET. Be present for the first 3 hours to answer every comment — HN ranking is driven by early engagement and author responsiveness.

**HN post body (template):**
> Hi HN — I'm the author. Pydantic Deep Agents is a deep-agent harness on top of pydantic-ai. The feature I'm most excited about: an `agent.run()` can fork mid-task into N isolated branches (copy-on-write filesystem, separate budgets, different steering), and a judge — or a real `pytest` run — picks the winner whose history continues the run. It's `git branch` for an agent's reasoning. It's also a terminal assistant and a one-function-call framework, 100% typed, MIT. Happy to answer anything about the forking internals (branch overlays, confidence scoring, the merge modes).

### Day 2 (Wed) — Technical deep-dive

| Channel | Format | Hook |
|---------|--------|------|
| **dev.to / Hashnode** | Long-form (1500w) | `How I made an AI agent fork itself: copy-on-write overlays, branch budgets, and an AI merge judge` — explains `BranchOverlay`, the four merge modes, `compute_confidence`. Cross-post to the project blog. |
| **X** | Single | Pull one diagram (A5) + 3-sentence summary linking the article. |

### Day 3 (Thu) — Proof / credibility

| Channel | Format | Hook |
|---------|--------|------|
| **X** | Thread | "We don't just claim forking helps — here's a side-by-side: same bug, 3 branches, only one passes the tests. The judge knew." (real before/after with the test-runner hook) |
| **LinkedIn** | Post | Founder voice: why parallel exploration beats one-shot agents in real production work (Vstorm's 30+ implementations angle). |

### Day 4 (Fri) — Reach a new audience

| Channel | Format | Hook |
|---------|--------|------|
| **r/Python** | Text | `Show r/Python: a 100% type-safe deep-agent framework (Pyright+MyPy strict) with run forking` — lead with the type-safety + Pydantic angle for this crowd, forking as the kicker. |
| **X** | Single | Repost A3 (install → answer in 30s), low-friction CTA: "try it in one line." |

### Day 5–7 (weekend + Mon) — Sustain & community

- **Day 5 (Sat):** X "build in public" — share a real star-count milestone or a fix you shipped from launch feedback. Authenticity compounds.
- **Day 6 (Sun):** Submit to newsletters/aggregators: **Python Weekly**, **Pycoders Weekly**, **TLDR AI**, **Console.dev**, **Hacker Newsletter**, **Awesome-AI-Agents** list (open a PR), **Awesome-Pydantic**. These have long lead times — submit now.
- **Day 7 (Mon):** Recap thread on X: "1 week ago I showed an agent that forks itself. Here's what happened + what's next." Numbers + roadmap teaser → drives the second wave.

---

## Phase 2 — Depth, comparison & ecosystem (Week 2)

Week 1 sold the hook. Week 2 proves there's a whole product behind it and seeds repeatable, evergreen content.

### Day 8 (Tue) — The comparison piece (high shareability)

| Channel | Format | Hook |
|---------|--------|------|
| **dev.to + X + LinkedIn** | Article + card (A4) | `pydantic-deep vs Claude Code vs Aider vs LangGraph vs CrewAI — when to use which` — honest, not a hit piece. Honest comparisons get shared by *both* sides' fans. The forking row is the standout. |
| **r/LocalLLaMA** | The comparison card | "Made an honest comparison table of the open agent tools — what am I missing?" (invites engagement, corrections = comments = ranking) |

### Day 9 (Wed) — Swarm / multi-agent

| Channel | Format | Hook |
|---------|--------|------|
| **X** | Thread + A2 | "Forking is parallel *approaches*. Teams are parallel *agents* — that message each other and share a TODO list. Here's a 3-agent swarm building a feature." |
| **YouTube / Loom** | 3–5 min | Screencast: build something real with a swarm + forking end to end. First long-form video → SEO + embeds. |

### Day 10 (Thu) — MCP + integrations (ride others' ecosystems)

| Channel | Format | Hook |
|---------|--------|------|
| **X** | Single + clip | "Connect GitHub, Figma (OAuth), Context7, DeepWiki — or import your Claude Code MCP servers in one keystroke." Tag the MCP/Figma communities. |
| **r/mcp or relevant Discord** | Demo | Show the `/mcp` flow importing from Claude Code. |

### Day 11 (Fri) — Tutorial / onboarding content (evergreen)

| Channel | Format | Hook |
|---------|--------|------|
| **dev.to** | Tutorial | `Build a code-review agent in 20 lines with pydantic-deep` — copy-paste, ends with structured output + a fork. Optimized for Google ("pydantic ai agent tutorial"). |
| **X** | Code screenshot | The 20-line snippet as an image (code screenshots outperform links). |

### Day 12–13 (weekend) — Community flywheel

- **Skills marketplace teaser:** announce/seed a `pydantic-deep-skills` community repo + "good first issue" labels. Ask: "what skill should the agent ship next?" Participation → contributors → stars.
- **Engage, don't broadcast:** reply to every agent-framework thread on X/Reddit this week with genuine help; mention forking only where it actually fits. Reputation > reach.
- Submit a talk/lightning proposal to a Python or AI meetup; even the submission generates a tweet.

### Day 14 (Mon) — Wrap & set the next loop

| Channel | Format | Hook |
|---------|--------|------|
| **X + LinkedIn** | Recap | "2 weeks of building in public: from 830 to ⭐ ___. Here's the roadmap." Publish a public `ROADMAP.md` (forking visualization, skills marketplace, eval harness) — momentum is itself a reason to star. |
| **Blog** | Post | Consolidate the two-week story into one canonical article for future linking. |

---

## Channel cheat-sheet (where, when, how)

| Channel | Best day/time | What works | Avoid |
|---------|---------------|------------|-------|
| **Hacker News** | Tue–Thu, 8–9:30 AM ET | "Show HN", author present, technical honesty | reposting fast; marketing tone |
| **r/LocalLLaMA** | Weekday afternoons ET | local-model angle, real GIFs, asking questions | link-only posts, hype |
| **r/Python** | Tue–Thu mornings | type-safety, clean code, "Show" posts | self-promo without substance |
| **X/Twitter** | 9–11 AM & 5–7 PM, daily | video first, threads, code screenshots, replies | bare links, posting once and leaving |
| **dev.to / Hashnode** | any weekday | tutorials, deep-dives, SEO titles | thin content |
| **LinkedIn** | Tue–Thu mornings | founder POV, production-credibility | jargon dumps |
| **Lobsters** | Tue–Thu | same as HN, needs invite/karma | over-tagging |
| **Newsletters** | submit anytime (lead time!) | Python Weekly, Pycoders, TLDR AI, Console.dev | last-minute submits |

---

## Content rules (so quality stays high)

1. **Show, don't tell.** Every flagship post carries a GIF/video. Forking is visual — exploit that.
2. **One idea per post.** Don't cram swarm + MCP + forking into one tweet.
3. **Be honest in comparisons.** Note where Claude Code/LangGraph win. Credibility is the moat.
4. **Reply within the first 3 hours.** Early author engagement drives HN/Reddit ranking more than the post itself.
5. **Always end with a soft CTA:** a single copy-paste line (`curl … | bash` or `pip install pydantic-deep`) + "⭐ if useful."
6. **Recycle, don't repeat:** same message, rotating angle (fork → swarm → trust). 

---

## Metrics & targets (review at Day 7 and Day 14)

| Metric | Day 7 target | Day 14 target |
|--------|--------------|---------------|
| GitHub stars | 1,500+ | 3,000+ |
| HN front page | reach it once | — |
| X impressions on launch thread | 50k+ | — |
| PyPI weekly downloads | 2× baseline | 4× baseline |
| New contributors / PRs | 2 | 6 |
| Newsletter pickups | 1 | 3 |

> 10k is a multi-cycle goal, not a 2-week one. This plan is **cycle one**: prove the forking hook lands, capture the audience, and stand up the flywheels (skills marketplace, roadmap, evergreen tutorials) that carry waves 2–4.

---

## Backlog — high-impact content for cycles 2–4

- **Fork-tree visualization in the TUI** → instant screenshot-bait for a relaunch.
- **Live hosted DeepResearch demo** ("try it without installing") → top-of-funnel.
- **Autonomous PR agent** (issue → fork 3 fixes → judge → open PR) → SWE-bench-style proof, huge HN potential.
- **Eval harness** built on forking+judge → attracts researchers, generates benchmark numbers (numbers drive HN).
- **"Agent that forks itself" conference talk** → recorded, evergreen, authoritative.
