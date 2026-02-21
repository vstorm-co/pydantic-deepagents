"""Plan toolset for pydantic-deep agents.

Provides tools for interactive planning:
- ask_user: Ask the user questions with predefined options
- save_plan: Save implementation plans to markdown files

Used by the built-in 'planner' subagent for Claude Code-style plan mode.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.toolsets.function import FunctionToolset

# Default plans directory (relative to backend root)
DEFAULT_PLANS_DIR = "/plans"

# ---------------------------------------------------------------------------
# Planner subagent configuration
# ---------------------------------------------------------------------------

PLANNER_DESCRIPTION = (
    "Plans implementation of complex tasks. Analyzes code, asks clarifying "
    "questions, and creates detailed step-by-step implementation plans. "
    "Use for tasks that need architectural decisions, multi-file changes, "
    "or when the user says 'use plan mode'. Do NOT use for simple tasks."
)

PLANNER_INSTRUCTIONS = """\
You are a planning agent. Your job is to analyze the codebase, ask clarifying \
questions, and create a detailed implementation plan.

**You do NOT implement anything — you only plan.**

## Your Workflow

1. **Understand the Task**: Read relevant files to understand the codebase
2. **Ask Questions**: Use `ask_user` when anything is unclear or there are \
multiple valid approaches — ask early, not at the end
3. **Design the Plan**: Break the task into clear, ordered steps
4. **Save the Plan**: Use `save_plan` to persist the complete plan

## Asking Questions

Use `ask_user` when you need to:
- Choose between multiple valid approaches (e.g., framework, pattern, library)
- Clarify ambiguous requirements
- Get user preferences on technical decisions
- Confirm assumptions about the codebase

CRITICAL guidelines for `ask_user`:
- You MUST ALWAYS provide 2-4 options with `label` and `description` keys
- NEVER pass an empty options list — always suggest the most likely answers
- Mark one option as `"recommended": "true"` when you have a preference
- Even for open-ended questions, provide concrete suggestions as options
- Ask the most important questions first
- You can ask multiple questions sequentially

Example call:
```
ask_user(
    question="Which auth method should we use?",
    options=[
        {"label": "JWT", "description": "Stateless, good for APIs", "recommended": "true"},
        {"label": "Session-based", "description": "Traditional, server-side state"},
        {"label": "OAuth2", "description": "Third-party auth providers"}
    ]
)
```

## Plan Format

Write plans in this markdown format:

```markdown
# Plan: [Title]

## Context
[What needs to be done and why]

## Decisions Made
- [Decision 1]: [chosen option] — [reason]

## Implementation Steps

### Step 1: [Title]
- **Files**: `path/to/file.py`
- **Action**: create | modify | delete
- **Details**: [What to change and how]

### Step 2: [Title]
...

## Files Summary
| File | Action | Description |
|------|--------|-------------|
| ... | create/modify/delete | ... |

## Notes
[Any caveats, dependencies, or follow-up items]
```

## Important Rules
- You are a PLANNER — do NOT modify any files or run commands
- Read files freely to understand the codebase
- Ask questions when unsure — it's better to ask than to assume
- Be thorough but concise in your plan
- Always call `save_plan` with the complete plan when finished
- After saving, summarize the plan briefly in your response
"""


def create_plan_toolset(
    plans_dir: str = DEFAULT_PLANS_DIR,
    *,
    id: str | None = None,
) -> FunctionToolset[Any]:
    """Create a plan toolset with ask_user and save_plan tools.

    The ``ask_user`` tool pauses execution and asks the human user a question
    with predefined options (like Claude Code's AskUserQuestion). It relies
    on a callback at ``ctx.deps.ask_user``. When no callback is set (headless
    mode), it auto-selects the recommended option.

    The ``save_plan`` tool writes the plan to a markdown file in the backend.

    Args:
        plans_dir: Directory to save plan files (default: ``/plans``).
        id: Toolset ID (default: ``deep-plan``).

    Returns:
        FunctionToolset with ``ask_user`` and ``save_plan`` tools.
    """
    toolset: FunctionToolset[Any] = FunctionToolset(id=id or "deep-plan")

    @toolset.tool
    async def ask_user(  # pragma: no cover
        ctx: RunContext[Any],
        question: str,
        options: list[dict[str, str]],
    ) -> str:
        """Ask the user a question with predefined answer options.

        Use this to clarify requirements, choose between approaches, or get
        user preferences during planning. The user sees your question with
        selectable options in an interactive picker.

        IMPORTANT: You MUST always provide 2-4 concrete options. Never pass
        an empty options list. Even for open-ended questions, suggest the most
        likely answers as options — the user can always type a custom answer.

        Example:
            ask_user(
                question="Which database should we use?",
                options=[
                    {"label": "PostgreSQL", "description": "Best for relational data", "recommended": "true"},
                    {"label": "MongoDB", "description": "Flexible schema, good for documents"},
                    {"label": "SQLite", "description": "Simple, no server needed"},
                ]
            )

        Args:
            question: The question to ask. Be specific and concise.
            options: REQUIRED list of 2-4 answer options. Each option MUST have:
                - 'label': Short option text (1-5 words)
                - 'description': What this option means or implies
                - 'recommended': Set to 'true' to highlight as recommended (optional)

        Returns:
            The user's selected option label or their custom text answer.
        """
        callback = getattr(ctx.deps, "ask_user", None)
        if callback is None:
            # Non-interactive mode: auto-select recommended or first option
            recommended = next(
                (o for o in options if o.get("recommended", "").lower() == "true"),
                None,
            )
            choice = recommended or (options[0] if options else {"label": "N/A"})
            return f"[Auto-selected: {choice['label']}]"

        return str(await callback(question, options))

    @toolset.tool
    async def save_plan(  # pragma: no cover
        ctx: RunContext[Any],
        title: str,
        content: str,
    ) -> str:
        """Save the implementation plan to a markdown file.

        Call this when you have finished planning and have a complete plan.
        The plan is saved as a markdown file for reference during implementation.

        Args:
            title: Plan title (used to generate the filename).
            content: Full markdown content of the plan.

        Returns:
            Confirmation with the file path where the plan was saved.
        """
        # Generate filename from title
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50]
        short_id = uuid.uuid4().hex[:6]
        filename = f"{slug}-{short_id}.md"
        path = f"{plans_dir}/{filename}"

        # Write to backend
        result = ctx.deps.backend.write(path, content.encode("utf-8"))
        if hasattr(result, "error") and result.error:
            return f"Error saving plan: {result.error}"

        return f"Plan saved to `{path}`"

    return toolset
