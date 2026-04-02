# Agent Spec (YAML/JSON)

Define agents declaratively using YAML or JSON files instead of Python code.

## Quick Start

Create an `agent.yaml` file:

```yaml
model: anthropic:claude-sonnet-4-6
instructions: You are a helpful coding assistant.
include_todo: true
include_filesystem: true
include_subagents: true
include_skills: true
include_plan: true
include_memory: true
memory_dir: .pydantic-deep
context_discovery: true
retries: 3
model_settings:
  temperature: 0.7
```

Load it in Python:

```python
from pydantic_deep import DeepAgent

agent, deps = DeepAgent.from_file("agent.yaml")
result = await agent.run("Create a Python script", deps=deps)
```

## API

### `DeepAgent.from_file(path, **overrides)`

Load an agent from a YAML (`.yaml`, `.yml`) or JSON (`.json`) file.

```python
# Basic loading
agent, deps = DeepAgent.from_file("agent.yaml")

# With runtime overrides (non-serializable params)
from pydantic_ai_backends import LocalBackend

agent, deps = DeepAgent.from_file(
    "agent.yaml",
    backend=LocalBackend(root_dir="/workspace"),
    on_cost_update=my_callback,
)
```

### `DeepAgent.from_spec(data, **overrides)`

Load an agent from a Python dict.

```python
agent, deps = DeepAgent.from_spec({
    "model": "anthropic:claude-sonnet-4-6",
    "include_todo": True,
    "include_memory": True,
    "memory_dir": ".pydantic-deep",
})
```

### `DeepAgent.to_file(path, **params)`

Save agent configuration to a file. Only non-default values are saved.

```python
DeepAgent.to_file(
    "agent.yaml",
    model="anthropic:claude-sonnet-4-6",
    include_memory=True,
    memory_dir=".pydantic-deep",
)
```

## Spec Format

All keys correspond 1:1 to [`create_deep_agent()`][pydantic_deep.agent.create_deep_agent] parameters.

### Core Parameters

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `model` | string | `"anthropic:claude-sonnet-4-6"` | Model identifier |
| `instructions` | string | Base prompt | Custom system prompt |
| `retries` | int | `3` | Max tool call retries |
| `output_style` | string | `null` | Output style name |

### Feature Flags

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `include_todo` | bool | `true` | Task planning tools |
| `include_filesystem` | bool | `true` | File operation tools |
| `include_subagents` | bool | `true` | Subagent delegation |
| `include_skills` | bool | `true` | Skill discovery |
| `include_plan` | bool | `true` | Plan mode subagent |
| `include_memory` | bool | `true` | Persistent memory |
| `include_checkpoints` | bool | `false` | Conversation checkpointing |
| `include_teams` | bool | `false` | Agent team management |
| `web_search` | bool | `true` | WebSearch capability |
| `web_fetch` | bool | `true` | WebFetch capability |
| `thinking` | bool/str | `"high"` | Thinking effort level |
| `include_history_archive` | bool | `true` | History persistence |

### Context Management

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `context_manager` | bool | `true` | Auto-compression |
| `context_manager_max_tokens` | int | auto | Token budget |
| `eviction_token_limit` | int | `20000` | Large output eviction |

### Model Settings

```yaml
model_settings:
  temperature: 0.7
  max_tokens: 4096
  anthropic_thinking:
    type: enabled
    budget_tokens: 10000
```

### Subagents

```yaml
subagents:
  - name: researcher
    description: Research assistant
    instructions: You research topics thoroughly.
    model: anthropic:claude-haiku-4-5-20251001
  - name: coder
    description: Code writer
    instructions: You write clean Python code.
```

## Non-Serializable Parameters

Some parameters cannot be expressed in YAML/JSON. Pass them as keyword overrides:

```python
agent, deps = DeepAgent.from_file(
    "agent.yaml",
    backend=LocalBackend(root_dir="/workspace"),
    on_cost_update=my_cost_callback,
    on_context_update=my_context_callback,
    hooks=[my_hook],
    tools=[my_custom_tool],
)
```

Non-serializable parameters: `backend`, `tools`, `toolsets`, `skills`, `hooks`,
`on_context_update`, `on_before_compress`, `on_after_compress`, `on_eviction`,
`on_cost_update`, `middleware`, `checkpoint_store`, `output_type`.

## JSON Format

The same spec works in JSON:

```json
{
  "model": "anthropic:claude-sonnet-4-6",
  "include_todo": true,
  "include_memory": true,
  "memory_dir": ".pydantic-deep",
  "model_settings": {
    "temperature": 0.7
  }
}
```

```python
agent, deps = DeepAgent.from_file("agent.json")
```
