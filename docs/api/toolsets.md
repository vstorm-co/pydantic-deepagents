# Toolsets API

## TodoToolset

Task planning and tracking tools. Provided by [pydantic-ai-todo](https://github.com/vstorm-co/pydantic-ai-todo).

### Tools

| Tool | Description |
|------|-------------|
| `read_todos` | Read the current todo list state |
| `write_todos` | Update the todo list |

### Factory

```python
from pydantic_ai_todo import create_todo_toolset

def create_todo_toolset(
    storage: TodoStorageProtocol | None = None,
    *,
    id: str | None = None,
) -> FunctionToolset[Any]
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `storage` | `TodoStorageProtocol \| None` | `None` | Storage backend (defaults to in-memory) |
| `id` | `str \| None` | `None` | Optional unique ID for the toolset |

### Tool: read_todos

```python
async def read_todos() -> str
```

Read the current todo list state.

**Returns:** Formatted list of todos with status icons and summary.

### Tool: write_todos

```python
async def write_todos(todos: list[TodoItem]) -> str
```

Update the todo list with new items.

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `todos` | `list[TodoItem]` | List of todo items |

Each todo item:
```python
{
    "content": str,      # Task description
    "status": str,       # "pending", "in_progress", "completed"
    "active_form": str,  # Present continuous form
}
```

**Returns:** Confirmation message with status counts.

### Types

```python
from pydantic_ai_todo import Todo, TodoItem, TodoStorage, TodoStorageProtocol

class Todo(BaseModel):
    content: str
    status: Literal["pending", "in_progress", "completed"]
    active_form: str

class TodoStorage:
    """Default in-memory storage."""
    todos: list[Todo]
```

### System Prompt

```python
from pydantic_ai_todo import get_todo_system_prompt

def get_todo_system_prompt(storage: TodoStorageProtocol | None = None) -> str
```

Generates dynamic system prompt showing current todos.

### Standalone Usage

```python
from pydantic_ai import Agent
from pydantic_ai_todo import create_todo_toolset, TodoStorage

# Simple usage
agent = Agent("openai:gpt-4.1", toolsets=[create_todo_toolset()])

# With storage access
storage = TodoStorage()
agent = Agent("openai:gpt-4.1", toolsets=[create_todo_toolset(storage)])
result = await agent.run("Create 3 tasks")
print(storage.todos)  # Access todos directly
```

---

## Console Toolset

File operation tools. Provided by [pydantic-ai-backend](https://github.com/vstorm-co/pydantic-ai-backend).

For full documentation, see [pydantic-ai-backend Console Toolset](https://vstorm-co.github.io/pydantic-ai-backend/concepts/console/).

### Tools

| Tool | Description |
|------|-------------|
| `ls` | List directory contents |
| `read_file` | Read file with line numbers |
| `write_file` | Create or overwrite file |
| `edit_file` | Replace strings in file |
| `glob` | Find files by pattern |
| `grep` | Search file contents |
| `execute` | Run shell command (sandbox only) |

### Factory

```python
from pydantic_ai_backends import create_console_toolset

toolset = create_console_toolset(
    id="console",
    include_execute=False,
    require_write_approval=False,
    require_execute_approval=True,
)
```

### Usage with pydantic-deep

The console toolset is automatically included when you create a deep agent with `include_filesystem=True` (the default):

```python
from pydantic_deep import create_deep_agent

# Console toolset is included by default
agent = create_deep_agent()

# Or explicitly disable it
agent = create_deep_agent(include_filesystem=False)
```

---

## SubAgentToolset

Task delegation tools. Provided by [subagents-pydantic-ai](https://github.com/vstorm-co/subagents-pydantic-ai).

### Tools

| Tool | Description |
|------|-------------|
| `task` | Spawn a subagent for a task (sync or async mode) |
| `check_task` | Check status of a background task |
| `list_active_tasks` | List all running/pending tasks |
| `soft_cancel_task` | Request graceful task cancellation |
| `hard_cancel_task` | Force immediate task cancellation |

### Factory

```python
from subagents_pydantic_ai import create_subagent_toolset

def create_subagent_toolset(
    *,
    id: str = "subagents",
    subagents: list[SubAgentConfig] | None = None,
    default_model: str | None = None,
    include_general_purpose: bool = True,
    toolsets_factory: ToolsetFactory | None = None,
) -> FunctionToolset[Any]
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `id` | `str` | `"subagents"` | Unique toolset identifier |
| `subagents` | `list[SubAgentConfig] \| None` | `None` | Custom subagent configurations |
| `default_model` | `str \| None` | `None` | Default model for subagents |
| `include_general_purpose` | `bool` | `True` | Include general-purpose subagent |
| `toolsets_factory` | `ToolsetFactory \| None` | `None` | Factory to create toolsets for subagents |

### Tool: task

```python
async def task(
    ctx: RunContext[SubAgentDepsProtocol],
    description: str,
    subagent_type: str = "general-purpose",
    mode: ExecutionMode = "sync",
    priority: TaskPriority = TaskPriority.NORMAL,
    complexity: Literal["simple", "moderate", "complex"] | None = None,
    requires_user_context: bool = False,
    may_need_clarification: bool = False,
) -> str
```

Spawn a subagent to handle a task.

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `description` | `str` | Required | Task description |
| `subagent_type` | `str` | `"general-purpose"` | Subagent name |
| `mode` | `ExecutionMode` | `"sync"` | Execution mode: "sync", "async", or "auto" |
| `priority` | `TaskPriority` | `NORMAL` | Task priority for async tasks |
| `complexity` | `str \| None` | `None` | Hint for auto-mode: "simple", "moderate", "complex" |
| `requires_user_context` | `bool` | `False` | Hint for auto-mode |
| `may_need_clarification` | `bool` | `False` | Hint for auto-mode |

**Returns:** Subagent's output (sync mode) or task handle info (async mode).

### SubAgentConfig

```python
class SubAgentConfig(TypedDict, total=False):
    name: str                      # Required: Unique identifier
    description: str               # Required: When to use this subagent
    instructions: str              # Required: System prompt
    model: NotRequired[str]        # Custom model
    can_ask_questions: NotRequired[bool]  # Enable ask_parent tool
    max_questions: NotRequired[int]       # Limit questions per task
    preferred_mode: NotRequired[Literal["sync", "async", "auto"]]
    typical_complexity: NotRequired[Literal["simple", "moderate", "complex"]]
    typically_needs_context: NotRequired[bool]
    toolsets: NotRequired[list[Any]]      # Additional toolsets
    agent_kwargs: NotRequired[dict[str, Any]]  # Additional Agent kwargs (e.g., builtin_tools)
```

---

## SkillsToolset

!!! note "Future Migration"
    This implementation will be removed when skills support is added to pydantic-ai core.
    See [pydantic-ai#3780](https://github.com/pydantic/pydantic-ai/pull/3780) for progress.

Modular capability tools.

### Tools

| Tool | Description |
|------|-------------|
| `list_skills` | List available skills |
| `load_skill` | Load skill instructions |
| `read_skill_resource` | Read skill resource file |

### Factory

```python
def create_skills_toolset(
    *,
    id: str = "skills",
    directories: list[SkillDirectory] | None = None,
    skills: list[Skill] | None = None,
) -> SkillsToolset
```

### Constructor

```python
from pydantic_deep.toolsets.skills import SkillsToolset

toolset = SkillsToolset(
    skills=[...],
    directories=[...],
    descriptions={
        "list_skills": "Show all available agent capabilities",
        "load_skill": "Load instructions for a specific capability",
    },
)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skills` | `list[Skill] \| None` | `None` | Pre-loaded Skill objects |
| `directories` | `list[...] \| None` | `None` | Directories to discover skills from |
| `validate` | `bool` | `True` | Validate skill structure during discovery |
| `max_depth` | `int \| None` | `3` | Maximum depth for skill discovery |
| `id` | `str \| None` | `None` | Unique identifier for this toolset |
| `instruction_template` | `str \| None` | `None` | Custom instruction template (must include `{skills_list}`) |
| `exclude_tools` | `set[str] \| list[str] \| None` | `None` | Tool names to exclude from registration |
| `descriptions` | `dict[str, str] \| None` | `None` | Custom tool descriptions (keys: `list_skills`, `load_skill`, `read_skill_resource`, `run_skill_script`) |

### Tool: list_skills

```python
async def list_skills(
    ctx: RunContext[DeepAgentDeps],
) -> str
```

List all available skills.

**Returns:** Formatted list of skills with metadata.

### Tool: load_skill

```python
async def load_skill(
    ctx: RunContext[DeepAgentDeps],
    skill_name: str,
) -> str
```

Load full instructions for a skill.

**Returns:** Complete skill instructions.

### Tool: read_skill_resource

```python
async def read_skill_resource(
    ctx: RunContext[DeepAgentDeps],
    skill_name: str,
    resource_name: str,
) -> str
```

Read a resource file from a skill.

**Returns:** Resource file content.

### Type Definitions

#### Skill

```python
class Skill(TypedDict):
    name: str
    description: str
    path: str
    tags: list[str]
    version: str
    author: str
    frontmatter_loaded: bool
    instructions: NotRequired[str]
    resources: NotRequired[list[str]]
```

#### SkillDirectory

```python
class SkillDirectory(TypedDict):
    path: str
    recursive: NotRequired[bool]
```

#### SkillFrontmatter

```python
class SkillFrontmatter(TypedDict):
    name: str
    description: str
    tags: NotRequired[list[str]]
    version: NotRequired[str]
    author: NotRequired[str]
```

---

## CheckpointToolset

Manual checkpoint controls. See [Checkpointing](../advanced/checkpointing.md).

### Tools

| Tool | Description |
|------|-------------|
| `save_checkpoint` | Label the most recent auto-checkpoint |
| `list_checkpoints` | Show all saved checkpoints |
| `rewind_to` | Rewind to a checkpoint (raises `RewindRequested`) |

### Constructor

```python
from pydantic_deep.toolsets.checkpointing import CheckpointToolset

toolset = CheckpointToolset(
    descriptions={
        "save_checkpoint": "Bookmark the current conversation state",
        "rewind_to": "Roll back conversation to a previous bookmark",
    },
)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `store` | `CheckpointStore \| None` | `None` | Fallback checkpoint store (used if deps has no store) |
| `id` | `str` | `"deep-checkpoints"` | Toolset identifier |
| `descriptions` | `dict[str, str] \| None` | `None` | Custom tool descriptions (keys: `save_checkpoint`, `list_checkpoints`, `rewind_to`) |

Or enabled via `create_deep_agent(include_checkpoints=True)`.

---

## TeamToolset

Multi-agent team management. See [Teams](../advanced/teams.md).

### Tools

| Tool | Description |
|------|-------------|
| `spawn_team` | Create a team and register members |
| `assign_task` | Assign a task to a team member |
| `check_teammates` | Show team status and shared tasks |
| `message_teammate` | Send a message to a team member |
| `dissolve_team` | Shut down the team |

### Factory

```python
from pydantic_deep.toolsets.teams import create_team_toolset

toolset = create_team_toolset(
    id="deep-team",
    descriptions={
        "spawn_team": "Create a new team of specialized agents",
        "assign_task": "Delegate a task to a specific team member",
    },
)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `id` | `str \| None` | `"deep-team"` | Toolset identifier |
| `descriptions` | `dict[str, str] \| None` | `None` | Custom tool descriptions (keys: `spawn_team`, `assign_task`, `check_teammates`, `message_teammate`, `dissolve_team`) |

Or via `create_deep_agent(include_teams=True)`.

---

## MemoryToolset

Persistent agent memory. See [Memory](../advanced/memory.md).

### Tools

| Tool | Description |
|------|-------------|
| `read_memory` | Read full memory content |
| `write_memory` | Append new content to memory |
| `update_memory` | Find and replace text in memory |

### Constructor

```python
from pydantic_deep.toolsets.memory import AgentMemoryToolset

toolset = AgentMemoryToolset(
    agent_name="main",
    memory_dir="/.deep/memory",
    max_lines=200,
    descriptions={
        "write_memory": "Save important findings to persistent memory",
    },
)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `agent_name` | `str` | `"main"` | Agent name (used for path and prompt label) |
| `memory_dir` | `str` | `"/.deep/memory"` | Base directory for memory files |
| `max_lines` | `int` | `200` | Max lines to inject into system prompt |
| `descriptions` | `dict[str, str] \| None` | `None` | Custom tool descriptions (keys: `read_memory`, `write_memory`, `update_memory`) |

Or via `create_deep_agent(include_memory=True)`.

---

## PlanToolset

Interactive planning with ask_user and save_plan. See [Plan Mode](../advanced/plan-mode.md).

### Tools

| Tool | Description |
|------|-------------|
| `ask_user` | Ask user a question with options |
| `save_plan` | Save implementation plan to markdown file |

### Factory

```python
from pydantic_deep.toolsets.plan import create_plan_toolset

toolset = create_plan_toolset(
    plans_dir="/plans",
    descriptions={
        "ask_user": "Pose a question to the user with predefined choices",
    },
)
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `plans_dir` | `str` | `"/plans"` | Directory to save plan files |
| `id` | `str \| None` | `"deep-plan"` | Toolset identifier |
| `descriptions` | `dict[str, str] \| None` | `None` | Custom tool descriptions (keys: `ask_user`, `save_plan`) |

Or via `create_deep_agent(include_plan=True)` (default).

---

## ContextToolset

Injects project context files into system prompt. See [Context Files](../advanced/context-files.md). Has no tools — only provides instructions via `get_instructions()`.

### Constructor

```python
from pydantic_deep.toolsets.context import ContextToolset

toolset = ContextToolset(
    context_files=["/DEEP.md", "/AGENTS.md"],
    context_discovery=False,
    is_subagent=False,
    max_chars=20_000,
)
```

---

## Helper Functions

### discover_skills

```python
def discover_skills(
    directories: list[SkillDirectory],
    backend: Any | None = None,
) -> list[Skill]
```

Discover skills from filesystem directories.

### parse_skill_md

```python
def parse_skill_md(content: str) -> tuple[dict[str, Any], str]
```

Parse SKILL.md into frontmatter and instructions.

### load_skill_instructions

```python
def load_skill_instructions(skill_path: str) -> str
```

Load full instructions from a skill directory.
