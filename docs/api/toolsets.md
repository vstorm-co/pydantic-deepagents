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
