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

### UploadedFile

Metadata for uploaded files (from `deps.upload_file()`).

```python
class UploadedFile(TypedDict):
    path: str               # Path where file was stored (e.g., "/uploads/data.csv")
    original_name: str      # Original filename
    size: int               # File size in bytes
    line_count: int | None  # Number of lines (None for binary files)
    mime_type: str          # Detected MIME type (e.g., "text/csv")
    encoding: str | None    # Detected encoding (e.g., "utf-8", None for binary)
```

**Usage:**

```python
from pydantic_deep import DeepAgentDeps, StateBackend

deps = DeepAgentDeps(backend=StateBackend())

# Upload a file
deps.upload_file("report.csv", csv_bytes)

# Access upload metadata
for path, info in deps.uploads.items():
    print(f"File: {info['original_name']}")
    print(f"Size: {info['size']} bytes")
    print(f"Lines: {info['line_count']}")
    print(f"Type: {info['mime_type']}")
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

A skill instance with metadata, content, resources, and scripts. `Skill` is a
**dataclass** (not a TypedDict) and is accessed via attributes
(e.g. `skill.name`, not `skill["name"]`). It can be created programmatically or
loaded from filesystem directories.

```python
@dataclass
class Skill:
    name: str                            # Unique skill name
    description: str                     # Brief description of what the skill does
    content: str                         # Main instructional content
    license: str | None = None           # Optional license information
    compatibility: str | None = None     # Optional environment requirements (max 500 chars)
    resources: list[SkillResource] = []  # Resources (files or callables)
    scripts: list[SkillScript] = []      # Scripts (functions or file-based)
    uri: str | None = None               # Optional base location URI (internal use)
    metadata: dict[str, Any] | None = None  # Additional metadata fields
```

`Skill` also provides `@skill.resource` and `@skill.script` decorators for
attaching callables. See [`Skill`][pydantic_deep.features.skills.types.Skill].

### SkillsDirectory

Skill source for a single filesystem directory. Discovers and loads skills by
finding `SKILL.md` files and their associated resources and scripts.

```python
class SkillsDirectory:
    def __init__(
        self,
        *,
        path: str | Path,
        validate: bool = True,
        max_depth: int | None = 3,
        script_executor: LocalSkillScriptExecutor | CallableSkillScriptExecutor | None = None,
    ) -> None: ...
```

See [`SkillsDirectory`][pydantic_deep.features.skills.directory.SkillsDirectory].
For non-local backends, use
[`BackendSkillsDirectory`][pydantic_deep.features.skills.backend.BackendSkillsDirectory].

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
from pydantic_deep import Skill, SkillResource

skill = Skill(
    name="api-design",
    description="Design RESTful APIs",
    content="When designing APIs, follow REST conventions...",
    resources=[
        SkillResource(name="checklist.md", content="- Use nouns for resources\n..."),
    ],
)
```

### Discovering Skills from a Directory

```python
from pydantic_deep import SkillsDirectory

source = SkillsDirectory(path="~/.pydantic-deep/skills")
skills = source.get_skills()  # dict[str, Skill]
```

---

## Team Types

### SharedTodoItem

Task item for team-shared task management.

```python
@dataclass
class SharedTodoItem:
    id: str                          # Auto-generated (uuid4 hex[:8])
    content: str = ""
    status: str = "pending"          # pending | in_progress | completed
    assigned_to: str | None = None
    blocked_by: list[str] = []
    created_by: str | None = None
```

### TeamMessage

Message between team members.

```python
@dataclass
class TeamMessage:
    id: str                          # Auto-generated (uuid4 hex[:8])
    sender: str = ""
    receiver: str = ""               # Empty = broadcast
    content: str = ""
    timestamp: datetime
```

### TeamMember

Member of an agent team.

```python
@dataclass
class TeamMember:
    name: str
    role: str
    description: str
    instructions: str
    model: str = "anthropic:claude-sonnet-4-6"
    toolsets: list[Any] = []
```

---

## Checkpoint Types

### Checkpoint

Immutable snapshot of conversation state.

```python
@dataclass
class Checkpoint:
    id: str                          # UUID4
    label: str                       # Human-readable label
    turn: int                        # Model-request counter
    messages: list[ModelMessage]     # Conversation snapshot
    message_count: int
    created_at: datetime
    metadata: dict[str, Any] = {}
```

---

## Hook Types

### Hook

Hook definition for tool lifecycle events.

```python
@dataclass
class Hook:
    event: HookEvent                 # PRE_TOOL_USE | POST_TOOL_USE | POST_TOOL_USE_FAILURE
    command: str | None = None       # Shell command
    handler: Callable | None = None  # Async Python function
    matcher: str | None = None       # Regex pattern for tool_name
    timeout: int = 30
    background: bool = False
```

### HookEvent

```python
class HookEvent(str, Enum):
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    POST_TOOL_USE_FAILURE = "post_tool_use_failure"
```

---

## Style Types

### OutputStyle

Output style definition.

```python
@dataclass
class OutputStyle:
    name: str                        # Style identifier
    description: str                 # Brief description
    content: str                     # Instructions for system prompt
```

---

## Memory Types

### MemoryFile

Loaded agent memory file.

```python
@dataclass
class MemoryFile:
    agent_name: str                  # "main", "code-reviewer", etc.
    path: str                        # Full path in backend
    content: str                     # Memory file content
```

---

## Context Types

### ContextFile

Loaded project context file.

```python
@dataclass
class ContextFile:
    name: str                        # Filename: "AGENTS.md"
    path: str                        # Full path: "/project/AGENTS.md"
    content: str                     # File content
```

---

## Type Checking

`Skill` is a dataclass, so fields are accessed as attributes:

```python
from pydantic_deep import Skill

def process_skill(skill: Skill) -> None:
    # Type checker knows all fields
    print(skill.name)
    print(skill.description)
    print(skill.content)

    # Optional fields default to None / empty
    for resource in skill.resources:
        print(resource.name)
```

Types are exported from the main module:

```python
from pydantic_deep import (
    FileData,
    FileInfo,
    UploadedFile,
    WriteResult,
    EditResult,
    ExecuteResponse,
    GrepMatch,
    Todo,
    SubAgentConfig,
    CompiledSubAgent,
    Skill,
    SkillResource,
    SkillScript,
    SkillsDirectory,
)
```
