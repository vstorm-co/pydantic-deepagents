# Agent API

## Module Constants

::: pydantic_deep.agent.DEFAULT_MODEL
    options:
      show_source: false

::: pydantic_deep.prompts.BASE_PROMPT
    options:
      show_source: false

## create_deep_agent

::: pydantic_deep.agent.create_deep_agent
    options:
      show_source: false

### Parameters

#### Core

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model` | `str \| Model \| None` | `None` (resolves to [`DEFAULT_MODEL`][pydantic_deep.agent.DEFAULT_MODEL] = `"anthropic:claude-opus-4-6"`) | LLM model identifier |
| `fallback_model` | `str \| Model \| list[str \| Model] \| None` | `None` | Fallback model(s) tried on transient errors. See [Fallback Models](../advanced/fallback-models.md) |
| `model_settings` | `dict[str, Any] \| None` | `None` | Model settings passed to the underlying model |
| `summarization_model` | `str \| None` | `None` (defaults to `DEFAULT_SUMMARIZATION_MODEL`) | Model used by the context manager for compression |
| `base_prompt` | `str \| None` | `None` (defaults to `BASE_PROMPT`) | Base system prompt to build on |
| `instructions` | `str \| None` | `None` | System prompt for the agent (replaces `BASE_PROMPT` when set) |
| `output_style` | `str \| OutputStyle \| None` | `None` | Output style (built-in name or custom) |
| `styles_dir` | `str \| list[str] \| None` | `None` | Directories for custom style files |
| `tools` | `Sequence[Tool \| Any] \| None` | `None` | Additional custom tools |
| `toolsets` | `Sequence[AbstractToolset] \| None` | `None` | Additional toolsets |
| `mcp_servers` | `Sequence[AbstractToolset] \| None` | `None` | MCP server toolsets to attach. See [MCP](../learn/web-and-mcp.md) |
| `capabilities` | `Sequence[AbstractCapability] \| None` | `None` | Additional capabilities to register |
| `backend` | `BackendProtocol \| None` | `StateBackend()` | File storage backend |
| `output_type` | `OutputSpec \| None` | `None` | Pydantic model for structured output |
| `edit_format` | `str` | `"hashline"` | Edit format used by the file edit tool |
| `retries` | `int` | `3` | Max retries for tool calls |
| `instrument` | `bool \| None` | `None` | Enable instrumentation (Logfire/OpenTelemetry) |

#### Feature Toggles

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `include_todo` | `bool` | `True` | Include TodoToolset |
| `include_filesystem` | `bool` | `True` | Include Console Toolset |
| `include_subagents` | `bool` | `True` | Include SubAgentToolset |
| `include_skills` | `bool` | `True` | Include SkillsToolset |
| `include_builtin_subagents` | `bool` | `True` | Include built-in subagents (research) |
| `include_plan` | `bool` | `True` | Include planner subagent |
| `include_execute` | `bool \| None` | `None` | Include execute tool (auto-detected) |
| `include_memory` | `bool` | `True` | Persistent agent memory |
| `include_checkpoints` | `bool` | `False` | Conversation checkpointing |
| `include_teams` | `bool` | `False` | Agent teams with shared todos |
| `include_improve` | `bool` | `False` | Self-improvement toolset |
| `include_liteparse` | `bool` | `False` | Document parsing tools (LiteParse) |
| `include_history_archive` | `bool` | `True` | Persist message history to disk |
| `stuck_loop_detection` | `bool` | `True` | Detect repetitive agent behavior |
| `forking` | `bool \| LiveForkCapability` | `False` | Live run forking (parallel branches) |
| `patch_tool_calls` | `bool` | `True` | Fix orphaned tool calls |
| `web_search` | `bool` | `True` | WebSearch capability |
| `web_fetch` | `bool` | `True` | WebFetch capability |
| `thinking` | `bool \| str` | `"high"` | Thinking effort (True/False/"minimal"/"low"/"medium"/"high"/"xhigh") |

#### Subagents

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `subagents` | `list[SubAgentConfig] \| None` | `None` | Subagent configurations |
| `max_nesting_depth` | `int` | `1` | Max subagent nesting depth |
| `subagent_registry` | `DynamicAgentRegistry \| None` | `None` | Dynamic agent registry |

#### Skills

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `skill_directories` | `list \| None` | `None` | Skill discovery directories |

#### Context Management

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `context_manager` | `bool` | `True` | Token tracking + auto-compression |
| `context_manager_max_tokens` | `int \| None` | `None` | Token budget (auto-detected from model when `None`) |
| `on_context_update` | `Callable \| None` | `None` | Callback: `(pct, current, max)` |
| `on_before_compress` | `Callable \| None` | `None` | Callback fired before compression |
| `on_after_compress` | `Callable \| None` | `None` | Callback fired after compression |
| `on_eviction` | `Callable \| None` | `None` | Callback fired when a large output is evicted |
| `context_files` | `list[str] \| None` | `None` | Context file paths |
| `context_discovery` | `bool` | `False` | Auto-discover AGENTS.md, SOUL.md |
| `history_processors` | `Sequence \| None` | `None` | History processors |
| `eviction_token_limit` | `int \| None` | `20_000` | Large output eviction threshold |
| `max_binary_content` | `int \| None` | `3` | Max binary tool results kept before pruning |

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

#### Middleware & Hooks

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `middleware` | `Sequence[Any] \| None` | `None` | Custom middleware |
| `hooks` | `list[Hook] \| None` | `None` | Claude Code-style hooks |

#### Other

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `interrupt_on` | `dict[str, bool] \| None` | `None` | Tools requiring approval |
| `plans_dir` | `str \| None` | `"/plans"` | Directory for plan files |
| `message_queue` | `MessageQueue \| None` | `None` | Steering/follow-up message queue. See [Message Queue](../advanced/message-queue.md) |
| `periodic_reminder` | `PeriodicReminderConfig \| bool \| None` | `None` | Periodic task reminders. See [Periodic Reminder](../advanced/periodic-reminder.md) |
| `history_messages_path` | `str` | `".pydantic-deep/messages.json"` | Path for the message history archive |
| `**agent_kwargs` | `Any` | - | Additional Agent constructor args |

### Returns

`Agent[DeepAgentDeps, str]` or `Agent[DeepAgentDeps, OutputDataT]` - Configured Pydantic AI agent.

When `output_type` is provided, returns an agent typed with the output model.

### Example

```python
from pydantic_deep import create_deep_agent, SubAgentConfig

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-6",
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

## run_with_files

::: pydantic_deep.agent.run_with_files
    options:
      show_source: false

Convenience coroutine that uploads files to the backend before running the agent.
The uploaded files become accessible via the file tools (`read_file`, `grep`,
`glob`, `execute`).

### Signature

```python
async def run_with_files(
    agent: Agent[DeepAgentDeps, OutputDataT],
    query: str,
    deps: DeepAgentDeps,
    files: list[tuple[str, bytes]] | None = None,
    *,
    upload_dir: str = "/uploads",
) -> OutputDataT
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `agent` | `Agent[DeepAgentDeps, OutputDataT]` | Required | The agent to run |
| `query` | `str` | Required | The user query/prompt |
| `deps` | `DeepAgentDeps` | Required | Agent dependencies |
| `files` | `list[tuple[str, bytes]] \| None` | `None` | List of `(filename, content)` tuples to upload |
| `upload_dir` | `str` | `"/uploads"` | Directory to store uploads |

### Returns

`OutputDataT` - Agent output (type depends on the agent's `output_type`).

### Example

```python
from pydantic_deep import create_deep_agent, DeepAgentDeps, run_with_files
from pydantic_ai_backends import StateBackend

agent = create_deep_agent()
deps = DeepAgentDeps(backend=StateBackend())

with open("sales.csv", "rb") as f:
    result = await run_with_files(
        agent,
        "Analyze the sales data and find top products",
        deps,
        files=[("sales.csv", f.read())],
    )
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
