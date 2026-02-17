"""DeepResearch agent factory — full-featured research agent."""

from __future__ import annotations

import re
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.agent import Agent
from pydantic_ai.toolsets import AbstractToolset, FunctionToolset
from pydantic_ai_middleware import AgentMiddleware
from subagents_pydantic_ai import (
    DEFAULT_GENERAL_PURPOSE_DESCRIPTION,
    DynamicAgentRegistry,
    create_agent_factory_toolset,
)

from pydantic_deep import (
    BASE_PROMPT,
    DeepAgentDeps,
    Hook,
    HookEvent,
    HookInput,
    HookResult,
    Skill,
    create_deep_agent,
)
from pydantic_deep.toolsets.plan import create_plan_toolset
from pydantic_deep.types import SubAgentConfig

from .config import MODEL_NAME, SKILLS_DIR
from .prompts import RESEARCH_PROMPT


async def audit_logger_handler(hook_input: HookInput) -> HookResult:
    """Background POST_TOOL_USE hook: logs all tool calls."""
    import logging

    logger = logging.getLogger(__name__)
    args_preview = str(hook_input.tool_input)[:200]
    logger.info(f"HOOK AUDIT: {hook_input.tool_name}({args_preview})")
    return HookResult(allow=True)


async def safety_gate_handler(hook_input: HookInput) -> HookResult:
    """PRE_TOOL_USE hook: blocks dangerous commands in execute tool."""
    command = hook_input.tool_input.get("command", "")

    dangerous_patterns = [
        r"rm\s+-rf\s+/",
        r"rm\s+-rf\s+\*",
        r"mkfs\.",
        r"dd\s+if=.*of=/dev/",
        r"chmod\s+-R\s+777\s+/",
        r":\(\)\{",
    ]

    for pattern in dangerous_patterns:
        if re.search(pattern, command):
            return HookResult(
                allow=False,
                reason=f"BLOCKED: Command matches dangerous pattern. "
                f"The command '{command}' was blocked for safety.",
            )

    return HookResult(allow=True)


HOOKS = [
    Hook(
        event=HookEvent.POST_TOOL_USE,
        handler=audit_logger_handler,
        background=True,
    ),
    Hook(
        event=HookEvent.PRE_TOOL_USE,
        handler=safety_gate_handler,
        matcher="execute",
        timeout=5,
    ),
]

RESEARCH_PLANNER_INSTRUCTIONS = """\
You are a research planning agent. Your job is to understand the user's research \
question, ask clarifying questions, and create a structured research plan.

**You do NOT research anything — you only plan the research strategy.**

## Your Workflow

1. **Understand the Request**: Analyze what the user wants to learn
2. **Ask Questions**: Use `ask_user` to clarify scope, depth, and focus areas
3. **Design the Plan**: Break the topic into 4-6 focused research sub-topics
4. **Save the Plan**: Use `save_plan` to persist the complete plan

## Asking Questions

Use `ask_user` for:
- Level of detail (technical deep-dive vs. high-level overview)
- Time period focus (last year, last 5 years, all time)
- Specific angles (academic, industry, regulatory, etc.)
- Any constraints (specific regions, companies, technologies)

Guidelines:
- Ask 1-2 focused questions, not more
- Provide 2-3 clear options per question
- Mark one option as `"recommended": "true"`
- If the topic is clear enough, skip questions and go straight to planning

## Plan Format

```markdown
# Research Plan: [Topic]

## Research Question
[The main question to answer]

## Scope
- Depth: [technical / overview / mixed]
- Time period: [specific range or "latest"]
- Focus: [specific angles]

## Sub-Topics to Investigate

### 1. [Sub-topic title]
- **Focus**: What to search for
- **Key questions**: What to answer
- **Likely sources**: Where to look

### 2. [Sub-topic title]
...

## Expected Report Structure
[Outline of the final report sections]
```

## Important Rules
- You are a PLANNER — do NOT search the web or read files
- Ask questions when the topic is ambiguous
- Be concise — the plan should take 1-2 minutes to create, not longer
- Always call `save_plan` when finished
- After saving, briefly summarize the plan in your response
"""

_research_plan_toolset = create_plan_toolset(plans_dir="/plans")

RESEARCH_SUBAGENT_INSTRUCTIONS = """\
You are a specialized research subagent working on a delegated task.

## Your Role
You have been spawned by a parent agent to handle a specific research task. Focus \
entirely on completing the assigned task to the best of your ability.

## Communication
- If you need clarification, use the `ask_parent` tool to ask the parent agent
- Keep questions specific and actionable
- Do not ask unnecessary questions — use your judgment when possible

## CRITICAL: Tool Failures — NEVER give up

If a tool fails (search API error, timeout, connection refused, max retries exceeded):
1. **Try a different tool** — if Tavily fails, try Jina or Brave Search
2. **Try a different query** — rephrase and retry
3. **If ALL search tools fail: USE YOUR OWN KNOWLEDGE** — you have extensive training \
data. Write a thorough, detailed response from what you know.
4. **NEVER return an error message as your result** — the parent agent expects \
research findings, not excuses.
5. **NEVER ask the parent or user what to do about tool failures** — just handle it.

When using your own knowledge as fallback, note it clearly: \
"(Based on training data, not live web search)"

## Task Completion
- ALWAYS produce substantive output — detailed findings, analysis, or summaries
- Provide clear, structured results
- If web sources are unavailable, your knowledge-based response is still valuable
"""

SUBAGENT_CONFIGS: list[SubAgentConfig] = [
    {
        "name": "general-purpose",
        "description": DEFAULT_GENERAL_PURPOSE_DESCRIPTION,
        "instructions": RESEARCH_SUBAGENT_INSTRUCTIONS,
        "can_ask_questions": True,
        "agent_kwargs": {"retries": 3},
    },
    {
        "name": "planner",
        "description": (
            "Plans research strategy for complex topics. Asks clarifying questions "
            "and creates structured research plans with sub-topics. Use for any "
            "research task that needs multiple sources or comparative analysis."
        ),
        "instructions": RESEARCH_PLANNER_INSTRUCTIONS,
        "toolsets": [_research_plan_toolset],
    },
    {
        "name": "code-reviewer",
        "description": (
            "Reviews Python code for quality, security, and best practices. "
            "Delegate code review tasks to this subagent."
        ),
        "instructions": """You are a code review expert. When reviewing code:

1. Read the entire file before making comments
2. Check for security issues first (injection, hardcoded secrets)
3. Review code structure and design patterns
4. Check error handling completeness
5. Verify type hints and documentation

Format your review as:
## Summary
[Brief overall assessment]

## Critical Issues
- [Security or major bugs]

## Improvements
- [Suggested improvements]

## Good Practices
- [Positive aspects]
""",
    },
]


def _create_remember_toolset() -> FunctionToolset[Any]:
    """Create a simple memory toolset that persists facts to /workspace/MEMORY.md."""
    toolset: FunctionToolset[Any] = FunctionToolset(id="remember-tool")

    @toolset.tool
    async def remember(ctx: RunContext[Any], fact: str) -> str:
        """Save a fact to persistent memory.

        Call this IMMEDIATELY when the user shares ANY personal information
        (name, preferences, project details, etc.) or asks you to remember something.

        Your memory resets every session — this tool is the ONLY way to persist
        information. If you don't call this, you will forget everything.

        Examples of when to call this:
        - User says "my name is Kacper" → remember("User's name is Kacper")
        - User says "I work at Acme Corp" → remember("User works at Acme Corp")
        - User says "use Polish" → remember("User prefers Polish language")
        - User says "zapamiętaj X" → remember("X")

        Args:
            fact: The fact to save (short, clear statement).

        Returns:
            Confirmation message.
        """
        backend = ctx.deps.backend
        try:
            data = backend.read("/workspace/MEMORY.md")
            content = data.decode("utf-8") if data else ""
        except Exception:
            content = ""

        if not content.strip():
            content = "# Agent Memory\n\n"

        content = content.rstrip("\n") + "\n- " + fact + "\n"
        backend.write("/workspace/MEMORY.md", content.encode("utf-8"))
        return f"Saved to memory: {fact}"

    return toolset


PROGRAMMATIC_SKILLS = [
    Skill(
        name="quick-reference",
        description="Quick reference card for workspace commands and shortcuts",
        content="""\
# Quick Reference

## File Operations
- `read_file(path)` — Read a file (use offset/limit for large files)
- `write_file(path, content)` — Create or overwrite a file
- `edit_file(path, old_string, new_string)` — Edit specific parts of a file
- `glob(pattern)` — Find files matching a pattern (e.g., `*.py`, `/workspace/**/*.csv`)
- `grep(pattern, paths)` — Search file contents with regex

## Code Execution
- `execute(command)` — Run a shell command in the Docker sandbox
- Python 3.12 with pandas, numpy, matplotlib, scikit-learn, seaborn, plotly pre-installed

## Memory
- `remember(fact)` — Save a fact to persistent memory (name, preferences, project info)

## Subagents
- `task(description, subagent_type)` — Delegate work to a subagent (sync or async)
- `check_task(task_id)` — Check status of an async task
- `list_active_tasks()` — List all running background tasks
- `create_agent(name, description, instructions)` — Create a new dynamic subagent
- Available subagents: code-reviewer, general-purpose, planner, + dynamic

## Teams
- `spawn_team(team_name, members)` — Create an agent team for parallel work
- `assign_task(member_name, task_description)` — Assign a task to a team member
- `check_teammates()` — Check team status
- `dissolve_team()` — Shut down the team

## TODO Management
- `write_todos(todos)` — Create or update task list
- `read_todos()` — Get current task list
- `add_todo(content)` — Add a single todo
- `update_todo_status(todo_id, status)` — Update todo status

## Checkpoints
- `save_checkpoint(label)` — Save a named checkpoint
- `list_checkpoints()` — List all checkpoints
- `rewind_to(checkpoint_id)` — Rewind to a previous state

## Skills
- `list_skills()` — See available skills
- `load_skill(name)` — Load a skill's instructions

## Web Search (MCP)
- Tavily: AI-optimized search (tavily_search, tavily_extract)
- Jina: Full URL reader (jina_readurl, jina_search)

## Diagrams (Excalidraw MCP)
- `excalidraw_read_diagram_guide` — Learn element format
- `excalidraw_batch_create_elements` — Create multiple elements (preferred)
- `excalidraw_create_element` — Create a single element
- `excalidraw_align_elements` / `excalidraw_distribute_elements` — Layout
- `excalidraw_describe_scene` — Verify what's on canvas
- NEVER use `excalidraw_create_from_mermaid` — it's broken

## Tips
- Use `/workspace/` for all generated files
- Use `/uploads/` to access uploaded files
- Save charts as PNG or interactive HTML to `/workspace/`
""",
    ),
]

MAIN_INSTRUCTIONS = f"""{BASE_PROMPT}

{RESEARCH_PROMPT}

## Available Tools

- **Memory**: `remember(fact)` — save personal info, preferences, project details to persistent memory
- **Web Search**: Tavily, Brave Search, Jina URL reader, Firecrawl
- **Browser Automation**: Playwright MCP (navigate, screenshot, click, fill)
- **File Operations**: read_file, write_file, edit_file, glob, grep, ls
- **Code Execution**: `execute(command)` — Docker sandbox with Python 3.12
- **Diagrams**: Excalidraw MCP — `excalidraw_read_diagram_guide`, `excalidraw_batch_create_elements`, \
`excalidraw_create_element` (ONLY you have these — NEVER use `excalidraw_create_from_mermaid`)
- **Subagents**: `task(description, subagent_type)` — for complex research only, never for diagrams
- **Teams**: `spawn_team()`, `assign_task()` — for parallel multi-agent coordination
- **TODO**: `write_todos()`, `read_todos()`, `add_todo()`, `update_todo_status()`
- **Checkpoints**: `save_checkpoint()`, `list_checkpoints()`, `rewind_to()`
- **Skills**: `list_skills()`, `load_skill(name)` — domain knowledge
- **Plan Mode**: `task(description, subagent_type="planner")` for complex multi-step planning

## Shell Commands

You have `execute` for shell commands. It may need user approval — just call it.

## Error Handling

Fix errors yourself: install missing modules, fix paths, retry. Don't ask permission.

## File Locations

- Uploads: /uploads/
- Workspace: /workspace/
- Memory: /workspace/MEMORY.md (use `remember()` tool to write)
"""


def create_research_agent(
    mcp_servers: list[AbstractToolset],
    middleware: list[AgentMiddleware[DeepAgentDeps]] | None = None,
) -> Agent[DeepAgentDeps, str]:
    """Create the DeepResearch agent with ALL features enabled.

    Args:
        mcp_servers: MCP server toolsets (Tavily, Jina, etc.)
        middleware: Middleware list (AuditMiddleware, PermissionMiddleware)

    Returns:
        Configured agent.
    """
    agent_registry = DynamicAgentRegistry()
    factory_toolset = create_agent_factory_toolset(
        registry=agent_registry,
        default_model="openai:gpt-4.1-mini",
        max_agents=5,
        id="agent-factory",
    )

    remember_toolset = _create_remember_toolset()

    return create_deep_agent(
        model=MODEL_NAME,
        instructions=MAIN_INSTRUCTIONS,
        backend=None,
        toolsets=[*mcp_servers, factory_toolset, remember_toolset],
        include_todo=True,
        include_filesystem=True,
        include_execute=True,
        include_subagents=True,
        include_teams=True,
        include_skills=True,
        include_plan=False,
        subagents=SUBAGENT_CONFIGS,
        include_general_purpose_subagent=False,
        max_nesting_depth=2,
        subagent_registry=agent_registry,
        subagent_extra_toolsets=mcp_servers,
        skills=PROGRAMMATIC_SKILLS,
        skill_directories=[{"path": str(SKILLS_DIR), "recursive": True}],
        hooks=HOOKS,
        middleware=middleware or [],
        context_manager=True,
        context_manager_max_tokens=200_000,
        patch_tool_calls=True,
        context_files=["/workspace/DEEP.md", "/workspace/MEMORY.md"],
        image_support=True,
        include_checkpoints=True,
        checkpoint_frequency="every_turn",
        max_checkpoints=50,
        interrupt_on={"execute": True, "write_file": False},
    )
