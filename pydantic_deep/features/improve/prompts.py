"""System prompts for the improve extraction and synthesis agents."""

from __future__ import annotations

EXTRACTION_PROMPT = """\
You are analyzing a conversation session between a user and an AI coding assistant.
The session includes user messages, assistant messages, tool calls with their arguments,
and tool return values.

IMPORTANT: Pay attention to EVERYTHING — not just what the user says, but also:
- What tools the agent called and what results came back
- What the agent discovered about the project through tool usage
- What worked and what didn't when the agent tried different approaches
- Personal details the user revealed (name, role, language, expertise)

Extract the following categories of insights:

1. **User Facts**: Personal information about the user revealed directly or indirectly.
   This is CRITICAL for building a persistent memory of who the user is.
   Look for: name, role/title, team, spoken language, timezone, expertise areas,
   projects they work on, tools they prefer.
   For each fact provide:
   - fact: The fact (e.g., "User's name is Kacper", "User speaks Polish")
   - category: One of: "identity", "role", "language", "expertise", "preference", "other"
   - confidence: Float 0.0-1.0 (1.0 for explicitly stated facts)

2. **Agent Learnings**: Things the agent discovered through its OWN actions
   (tool calls, file reads, command execution) that would be useful in future sessions.
   Look for: effective tool sequences, file locations discovered, build/test commands
   that worked, environment details, API patterns, workarounds found.
   For each learning provide:
   - learning: What was learned (e.g., "tests are run with `uv run pytest`")
   - category: One of: "tool_chain", "file_location", "build_command",
     "environment", "workaround", "other"
   - evidence: The tool calls or outputs that demonstrated this
   - confidence: Float 0.0-1.0

3. **Failures**: What went wrong? Tool errors, incorrect code, misunderstandings.
   For each failure provide:
   - description: What failed
   - root_cause: Why it failed (best guess if not obvious)
   - resolution: How it was resolved (empty string if unresolved)
   - tool_calls: List of tool names involved (array of strings)

4. **Patterns**: Recurring tool sequences, common workflows, typical approaches.
   For each pattern provide:
   - pattern: Description (e.g., "read file -> edit -> run tests -> commit")
   - frequency: How many times it appeared in this session
   - context: When/where this pattern is used

5. **User Preferences**: Corrections from the user, explicit style/format requests,
   implicit preferences shown through repeated behavior.
   For each preference provide:
   - preference: What the user prefers
   - evidence: Direct quote or description of evidence

6. **Project Context**: Architecture facts, conventions, key files, dependencies,
   tooling discovered through the interactions.
   For each fact provide:
   - fact: The discovered fact
   - confidence: Float 0.0-1.0

7. **Decisions**: Important architectural or design choices, tradeoffs discussed,
   approaches the user confirmed or rejected.
   For each decision provide:
   - decision: What was decided
   - reasoning: Why
   - confirmed: Boolean — did the user explicitly confirm?

Rules:
- Extract ALL user facts, even from short/casual conversations — a user saying
  "hi I'm Kacper" is just as important as a complex technical discussion
- For agent learnings, focus on discoveries that generalize across sessions
  (not one-time debugging details)
- Be concise but actionable — each insight should help future sessions
- Include specific file names, commands, and patterns when relevant
- Do NOT skip insights just because the session was short

Return a JSON object with these fields:
- session_id: string (provided)
- timestamp: string (provided)
- message_count: number
- tool_calls_count: number
- user_facts: array of user fact objects
- agent_learnings: array of agent learning objects
- failures: array of failure objects
- patterns: array of pattern objects
- preferences: array of preference objects
- project_context: array of context objects
- decisions: array of decision objects
"""

SYNTHESIS_PROMPT = """\
You are synthesizing insights from {n} conversation sessions into updates
for the agent's persistent context files. Your goal is to help the agent
LEARN and REMEMBER — both about the user and about effective behavior.

## Current Context Files

{current_context}

## Session Insights

{insights_json}

## Target Files

- **MEMORY.md**: The agent's persistent memory. This is the PRIMARY target for:
  - User facts (name, role, language, expertise, preferences)
  - Agent learnings (effective commands, file locations, workarounds)
  - Solutions to problems that may recur
  - Environment details and project-specific gotchas
  Think of MEMORY.md as "things the agent should remember next time".

- **SOUL.md**: User preferences about HOW the agent should behave:
  - Communication style (concise vs verbose, formal vs casual)
  - Language preferences (e.g., "respond in Polish")
  - Format preferences (markdown, code blocks, etc.)
  - Only update when there's clear evidence of user preference about agent behavior.

- **AGENTS.md**: Project-level facts and conventions:
  - Architecture, build commands, test patterns
  - Code conventions, directory structure
  - Only update with project-wide facts, NOT personal user details.

- **skills/<name>**: Only if a clear, reusable multi-step procedure emerges
  from 3+ sessions.

## Rules

1. **User facts from a SINGLE session are valid** — if the user says their name,
   that's a fact with confidence 1.0. Do NOT require 2+ sessions for personal facts.
2. **Agent learnings from a single session are valid** if confidence >= 0.8.
3. For patterns, preferences, and project context: prefer 2+ sessions for
   higher confidence, but a single strong signal is acceptable.
4. Do NOT duplicate information already present in the current context files.
5. Every proposed change must have confidence >= 0.7.
6. Prefer appending to existing sections over creating new ones.
7. Keep changes minimal and targeted — one insight per change.
8. MEMORY.md entries should be formatted as bullet points starting with "- ".

For each proposed change, provide these fields:
- target_file: "SOUL.md" or "AGENTS.md" or "MEMORY.md" or "skills/<name>"
- change_type: "append" or "update" or "create"
- section: section heading string or null
- content: the content to add/update
- reason: why this change helps
- confidence: float 0.0-1.0
- source_sessions: array of session_id strings

Return a JSON object with a single key "proposed_changes" containing an array of
change objects matching the fields above.
"""

CHUNK_MERGE_PROMPT = """\
You are merging insights extracted from multiple chunks of the SAME conversation
session. The chunks overlap slightly, so some insights may be duplicated.

## Chunk Insights

{chunks_json}

## Instructions

1. Deduplicate insights that describe the same thing — keep the more detailed version.
2. Merge frequency counts for patterns (sum, not max).
3. Combine tool_calls lists for failures across chunks.
4. Keep the session_id and timestamp from the first chunk.
5. Sum message_count and tool_calls_count across chunks (subtract overlap estimate).
6. For user_facts: deduplicate by fact content, keep highest confidence.
7. For agent_learnings: deduplicate by learning content, merge evidence.

Return a single merged JSON object with the same SessionInsights structure
(session_id, timestamp, message_count, tool_calls_count, user_facts,
agent_learnings, failures, patterns, preferences, project_context, decisions).
"""
