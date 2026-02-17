# Agent API

## create_deep_agent

::: pydantic_deep.agent.create_deep_agent
    options:
      show_source: false

### Parameters

#### Core

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model` | `str \| Model \| None` | `"openai:gpt-4.1"` | LLM model identifier |
| `instructions` | `str \| None` | Default instructions | System prompt for the agent |
| `output_style` | `str \| OutputStyle \| None` | `None` | Output style (built-in name or custom) |
| `styles_dir` | `str \| list[str] \| None` | `None` | Directories for custom style files |
| `tools` | `Sequence[Tool \| Any] \| None` | `None` | Additional custom tools |
| `toolsets` | `Sequence[AbstractToolset] \| None` | `None` | Additional toolsets |
| `backend` | `BackendProtocol \| None` | `StateBackend()` | File storage backend |
| `output_type` | `OutputSpec \| None` | `None` | Pydantic model for structured output |
| `retries` | `int` | `3` | Max retries for tool calls |

#### Feature Toggles

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `include_todo` | `bool` | `True` | Include TodoToolset |
| `include_filesystem` | `bool` | `True` | Include Console Toolset |
| `include_subagents` | `bool` | `True` | Include SubAgentToolset |
| `include_skills` | `bool` | `True` | Include SkillsToolset |
| `include_general_purpose_subagent` | `bool` | `True` | Include general-purpose subagent |
| `include_plan` | `bool` | `True` | Include planner subagent |
| `include_execute` | `bool \| None` | `None` | Include execute tool (auto-detected) |
| `include_memory` | `bool` | `False` | Persistent agent memory |
| `include_checkpoints` | `bool` | `False` | Conversation checkpointing |
| `include_teams` | `bool` | `False` | Agent teams with shared todos |
| `image_support` | `bool` | `False` | Image file handling |
| `patch_tool_calls` | `bool` | `False` | Fix orphaned tool calls |

#### Subagents

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `subagents` | `list[SubAgentConfig] \| None` | `None` | Subagent configurations |
| `max_nesting_depth` | `int` | `0` | Max subagent nesting depth |
| `subagent_registry` | `DynamicAgentRegistry \| None` | `None` | Dynamic agent registry |

#### Skills

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skills` | `list[Skill] \| None` | `None` | Pre-loaded skills |
| `skill_directories` | `list \| None` | `None` | Skill discovery directories |

#### Context Management

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `context_manager` | `bool` | `True` | Token tracking + auto-compression |
| `context_manager_max_tokens` | `int` | `200,000` | Token budget |
| `on_context_update` | `Callable \| None` | `None` | Callback: `(pct, current, max)` |
| `context_files` | `list[str] \| None` | `None` | Context file paths |
| `context_discovery` | `bool` | `False` | Auto-discover DEEP.md, AGENTS.md, etc. |
| `history_processors` | `Sequence \| None` | `None` | History processors |
| `eviction_token_limit` | `int \| None` | `None` | Large output eviction threshold |

#### Checkpointing

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `checkpoint_frequency` | `str` | `"every_tool"` | Auto-save frequency |
| `max_checkpoints` | `int` | `20` | Max checkpoints to keep |
| `checkpoint_store` | `CheckpointStore \| None` | `None` | Checkpoint storage backend |

#### Memory

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `memory_dir` | `str \| None` | `"/.deep/memory"` | Base directory for memory files |

#### Cost Tracking

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `cost_tracking` | `bool` | `True` | Enable cost tracking |
| `cost_budget_usd` | `float \| None` | `None` | Max cumulative cost |
| `on_cost_update` | `Callable \| None` | `None` | Callback with CostInfo |

#### Middleware

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `middleware` | `Sequence[AgentMiddleware] \| None` | `None` | Custom middleware |
| `permission_handler` | `Callable \| None` | `None` | Permission callback |
| `middleware_context` | `MiddlewareContext \| None` | `None` | Shared middleware state |
| `hooks` | `list[Hook] \| None` | `None` | Claude Code-style hooks |

#### Other

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `interrupt_on` | `dict[str, bool] \| None` | `None` | Tools requiring approval |
| `plans_dir` | `str \| None` | `"/plans"` | Directory for plan files |
| `**agent_kwargs` | `Any` | - | Additional Agent constructor args |

### Returns

`Agent[DeepAgentDeps, str]` or `Agent[DeepAgentDeps, OutputDataT]` - Configured Pydantic AI agent.

When `output_type` is provided, returns an agent typed with the output model.

### Example

```python
from pydantic_deep import create_deep_agent, SubAgentConfig

agent = create_deep_agent(
    model="openai:gpt-4.1",
    instructions="You are a coding assistant.",
    subagents=[
        SubAgentConfig(
            name="reviewer",
            description="Reviews code",
            instructions="Review code for issues.",
        ),
    ],
    skill_directories=[
        {"path": "~/.pydantic-deep/skills", "recursive": True},
    ],
    interrupt_on={"execute": True},
)
```

---

## create_default_deps

::: pydantic_deep.agent.create_default_deps
    options:
      show_source: false

### Signature

```python
def create_default_deps(
    backend: BackendProtocol | None = None,
) -> DeepAgentDeps
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `backend` | `BackendProtocol \| None` | `StateBackend()` | File storage backend |

### Returns

`DeepAgentDeps` - Configured dependencies instance.

### Example

```python
from pydantic_deep import create_default_deps
from pydantic_ai_backends import LocalBackend

# With default StateBackend
deps = create_default_deps()

# With custom backend
deps = create_default_deps(backend=LocalBackend("/workspace"))
```

---

## DeepAgentDeps

::: pydantic_deep.deps.DeepAgentDeps
    options:
      show_source: false

### Definition

```python
@dataclass
class DeepAgentDeps:
    backend: BackendProtocol = field(default_factory=StateBackend)
    files: dict[str, FileData] = field(default_factory=dict)
    todos: list[Todo] = field(default_factory=list)
    subagents: dict[str, Any] = field(default_factory=dict)
    uploads: dict[str, UploadedFile] = field(default_factory=dict)
    ask_user: Callable | None = None
    share_todos: bool = False
    checkpoint_store: CheckpointStore | None = None
```

### Attributes

| Attribute | Type | Description |
|-----------|------|-------------|
| `backend` | `BackendProtocol` | File storage backend |
| `files` | `dict[str, FileData]` | In-memory file cache |
| `todos` | `list[Todo]` | Task list |
| `subagents` | `dict[str, Any]` | Pre-configured subagent instances |
| `uploads` | `dict[str, UploadedFile]` | Uploaded files metadata |
| `ask_user` | `Callable \| None` | Callback for planner's ask_user tool |
| `share_todos` | `bool` | When True, subagents share parent's todo list |
| `checkpoint_store` | `CheckpointStore \| None` | Per-session checkpoint store |

### Methods

#### get_todo_prompt

```python
def get_todo_prompt(self) -> str
```

Generate system prompt section for current todos.

#### get_files_summary

```python
def get_files_summary(self) -> str
```

Generate summary of files in memory.

#### get_subagents_summary

```python
def get_subagents_summary(self) -> str
```

Generate summary of available subagents.

#### clone_for_subagent

```python
def clone_for_subagent(self) -> DeepAgentDeps
```

Create isolated dependencies for a subagent.

- Same backend (shared)
- Empty todos (isolated)
- Empty subagents (no nested delegation)
- Same files (shared reference)

### Example

```python
from pydantic_deep import DeepAgentDeps, StateBackend, Todo

deps = DeepAgentDeps(
    backend=StateBackend(),
    todos=[
        Todo(
            content="Review code",
            status="pending",
            active_form="Reviewing code",
        ),
    ],
)

# Access todo prompt
print(deps.get_todo_prompt())

# Clone for subagent
subagent_deps = deps.clone_for_subagent()
assert subagent_deps.todos == []  # Isolated
assert subagent_deps.backend is deps.backend  # Shared
```
