# Types API

All type definitions used in pydantic-deep.

## File Types

### FileData

Storage format for file contents.

```python
class FileData(TypedDict):
    content: list[str]  # Lines of the file
    created_at: str     # ISO 8601 timestamp
    modified_at: str    # ISO 8601 timestamp
```

### FileInfo

File metadata for listings.

```python
class FileInfo(TypedDict):
    name: str           # File or directory name
    path: str           # Full path
    is_dir: bool        # True if directory
    size: int | None    # File size in bytes (None for directories)
```

---

## Operation Results

### WriteResult

Result of write operations.

```python
@dataclass
class WriteResult:
    path: str | None = None    # Path where file was written
    error: str | None = None   # Error message if failed
```

### EditResult

Result of edit operations.

```python
@dataclass
class EditResult:
    path: str | None = None      # Path of edited file
    error: str | None = None     # Error message if failed
    occurrences: int | None = None  # Number of replacements made
```

### ExecuteResponse

Result of command execution.

```python
@dataclass
class ExecuteResponse:
    output: str                 # stdout + stderr
    exit_code: int | None = None  # Process exit code
    truncated: bool = False     # True if output was truncated
```

### GrepMatch

Single grep match result.

```python
class GrepMatch(TypedDict):
    path: str         # File path
    line_number: int  # Line number (1-indexed)
    line: str         # Matching line content
```

---

## Todo Types

### Todo

Task item for planning.

```python
class Todo(BaseModel):
    content: str                                    # Task description
    status: Literal["pending", "in_progress", "completed"]
    active_form: str  # Present continuous form (e.g., "Implementing feature")
```

**Status Values:**

| Status | Description |
|--------|-------------|
| `pending` | Not yet started |
| `in_progress` | Currently working on |
| `completed` | Done |

---

## Subagent Types

These types are provided by [subagents-pydantic-ai](https://github.com/vstorm-co/subagents-pydantic-ai).

### SubAgentConfig

Configuration for a subagent.

```python
class SubAgentConfig(TypedDict, total=False):
    # Required fields
    name: str                      # Unique identifier
    description: str               # When to use this subagent
    instructions: str              # System prompt for subagent

    # Optional fields
    model: NotRequired[str]        # Custom model (overrides default)
    can_ask_questions: NotRequired[bool]  # Enable ask_parent tool
    max_questions: NotRequired[int]       # Max questions per task
    preferred_mode: NotRequired[Literal["sync", "async", "auto"]]  # Execution preference
    typical_complexity: NotRequired[Literal["simple", "moderate", "complex"]]
    typically_needs_context: NotRequired[bool]
    toolsets: NotRequired[list[Any]]      # Additional toolsets
    agent_kwargs: NotRequired[dict[str, Any]]  # Additional Agent kwargs
```

### CompiledSubAgent

Pre-compiled subagent ready for use.

```python
@dataclass
class CompiledSubAgent:
    name: str               # Unique identifier
    description: str        # Brief description
    config: SubAgentConfig  # Original configuration
    agent: object | None    # Agent instance
```

### ExecutionMode

Execution mode for subagent tasks.

```python
ExecutionMode = Literal["sync", "async", "auto"]
```

- **sync**: Execute synchronously, blocking until completion (default)
- **async**: Execute in background, return immediately with task handle
- **auto**: Automatically decide based on task characteristics

### TaskStatus

Status of a background task.

```python
class TaskStatus(str, Enum):
    PENDING = "pending"           # Task is queued
    RUNNING = "running"           # Currently executing
    WAITING_FOR_ANSWER = "waiting_for_answer"  # Blocked on question
    COMPLETED = "completed"       # Finished successfully
    FAILED = "failed"             # Failed with error
    CANCELLED = "cancelled"       # Was cancelled
```

### TaskPriority

Priority levels for background tasks.

```python
class TaskPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"
```

### TaskHandle

Handle for managing a background task.

```python
@dataclass
class TaskHandle:
    task_id: str                    # Unique identifier
    subagent_name: str              # Name of executing subagent
    description: str                # Task description
    status: TaskStatus              # Current status
    priority: TaskPriority          # Task priority
    created_at: datetime            # When created
    started_at: datetime | None     # When started
    completed_at: datetime | None   # When finished
    result: str | None              # Result (if completed)
    error: str | None               # Error (if failed)
    pending_question: str | None    # Question waiting for answer
```

---

## Skill Types

### Skill

Complete skill definition.

```python
class Skill(TypedDict):
    name: str                            # Unique identifier
    description: str                     # Brief description
    path: str                            # Path to skill directory
    tags: list[str]                      # Categorization tags
    version: str                         # Semantic version
    author: str                          # Skill author
    frontmatter_loaded: bool             # True if only frontmatter loaded
    instructions: NotRequired[str]       # Full instructions (loaded on demand)
    resources: NotRequired[list[str]]    # Additional files in skill directory
```

### SkillDirectory

Configuration for skill discovery.

```python
class SkillDirectory(TypedDict):
    path: str                           # Path to skills directory
    recursive: NotRequired[bool]        # Search recursively (default: True)
```

### SkillFrontmatter

YAML frontmatter from SKILL.md.

```python
class SkillFrontmatter(TypedDict):
    name: str
    description: str
    tags: NotRequired[list[str]]
    version: NotRequired[str]
    author: NotRequired[str]
```

---

## Usage Examples

### Creating a Todo

```python
from pydantic_deep import Todo

todo = Todo(
    content="Implement authentication",
    status="in_progress",
    active_form="Implementing authentication",
)
```

### Creating a SubAgentConfig

```python
from pydantic_deep import SubAgentConfig

config: SubAgentConfig = {
    "name": "code-reviewer",
    "description": "Reviews code for quality and security",
    "instructions": "You are an expert code reviewer...",
}
```

### Creating a Skill

```python
from pydantic_deep import Skill

skill: Skill = {
    "name": "api-design",
    "description": "Design RESTful APIs",
    "path": "/path/to/skill",
    "tags": ["api", "rest"],
    "version": "1.0.0",
    "author": "your-name",
    "frontmatter_loaded": True,
}
```

### Creating a SkillDirectory

```python
from pydantic_deep import SkillDirectory

dirs: list[SkillDirectory] = [
    {"path": "~/.pydantic-deep/skills", "recursive": True},
    {"path": "./project-skills", "recursive": False},
]
```

---

## Type Checking

All types support runtime checking:

```python
from pydantic_deep import Skill

def process_skill(skill: Skill) -> None:
    # Type checker knows all fields
    print(skill["name"])
    print(skill["description"])

    # Optional fields
    if "instructions" in skill:
        print(skill["instructions"])
```

Types are exported from the main module:

```python
from pydantic_deep import (
    FileData,
    FileInfo,
    WriteResult,
    EditResult,
    ExecuteResponse,
    GrepMatch,
    Todo,
    SubAgentConfig,
    CompiledSubAgent,
    Skill,
    SkillDirectory,
    SkillFrontmatter,
)
```
