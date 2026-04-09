# Workflow Overview

This document describes the core workflows in pydantic-deepagents, illustrating how components interact during agent creation, execution, delegation, and state management.

---

## Core Workflows

### Workflow 1: Agent Creation and Execution

The main workflow: user creates an agent, the agent runs a query, and returns a result. This is the primary entry point for interacting with the system.

**Steps:**

1. User calls `create_deep_agent()` with config params (model, toolsets, capabilities, etc.)
2. Factory assembles toolsets (todo, filesystem, subagents, skills, etc.)
3. Factory creates capabilities (hooks, context, memory, etc.)
4. Factory sets up history processors (patch + eviction)
5. Factory creates `Agent` instance with assembled config
6. Factory registers `dynamic_instructions` callback for per-run prompt injection
7. User creates `DeepAgentDeps` with backend
8. User calls `agent.run(query, deps=deps)`
9. pydantic-ai runs the agent loop (LLM -> tool calls -> LLM -> ...)
10. Dynamic instructions inject todos, uploads, files summary, subagent info into system prompt
11. Result returned to user

```mermaid
sequenceDiagram
    participant User
    participant create_deep_agent
    participant Agent
    participant pydantic_ai as "pydantic-ai"
    participant LLM
    participant Tools

    User->>create_deep_agent: Call with config params
    create_deep_agent->>create_deep_agent: Assemble toolsets<br/>(todo, filesystem, subagents, skills)
    create_deep_agent->>create_deep_agent: Create capabilities<br/>(hooks, context, memory)
    create_deep_agent->>create_deep_agent: Setup history processors<br/>(patch + eviction)
    create_deep_agent->>Agent: Create Agent instance
    create_deep_agent->>Agent: Register dynamic_instructions callback
    create_deep_agent-->>User: Return configured Agent

    User->>User: Create DeepAgentDeps with backend
    User->>Agent: agent.run(query, deps=deps)
    Agent->>pydantic_ai: Start agent loop

    loop Agent Loop
        pydantic_ai->>Agent: dynamic_instructions injection
        Agent->>Agent: Inject todos, uploads, files,<br/>subagent info into system prompt
        pydantic_ai->>LLM: Send messages with system prompt
        LLM-->>pydantic_ai: Response (text or tool calls)

        alt Tool Calls Present
            pydantic_ai->>Tools: Execute tool calls
            Tools-->>pydantic_ai: Tool results
        end
    end

    pydantic_ai-->>Agent: Final result
    Agent-->>User: Return result
```

---

### Workflow 2: Subagent Delegation

The main agent delegates work to subagents for specialized tasks. Subagents run with isolated context but can share backend and filesystem access.

**Steps:**

1. Main agent calls `delegate_task` tool with description and subagent name
2. SubAgentToolset looks up subagent config (name, description, instructions)
3. `_default_deep_agent_factory` creates a new deep agent for the subagent
4. `deps.clone_for_subagent()` creates isolated deps (shares backend/files, restricts nesting)
5. Subagent runs with its own system prompt + delegated task
6. Result returned to main agent
7. Main agent continues with subagent's output

```mermaid
sequenceDiagram
    participant MainAgent as "Main Agent"
    participant SubAgentToolset
    participant AgentFactory as "Agent Factory"
    participant SubAgent as "Sub Agent"
    participant Backend

    MainAgent->>SubAgentToolset: delegate_task(description, subagent_name)
    SubAgentToolset->>SubAgentToolset: Lookup subagent config<br/>(name, description, instructions)
    SubAgentToolset->>AgentFactory: _default_deep_agent_factory(config)

    AgentFactory->>AgentFactory: Create new deep agent<br/>for subagent
    AgentFactory-->>SubAgentToolset: Return subagent instance

    SubAgentToolset->>SubAgentToolset: deps.clone_for_subagent()
    Note over SubAgentToolset: Shares backend/files,<br/>restricts nesting depth

    SubAgentToolset->>SubAgent: Run with system prompt + delegated task

    loop Subagent Execution
        SubAgent->>Backend: Read/write files as needed
        Backend-->>SubAgent: File data
    end

    SubAgent-->>SubAgentToolset: Return subagent result
    SubAgentToolset-->>MainAgent: Forward result
    MainAgent->>MainAgent: Continue with subagent output
```

---

### Workflow 3: History Processing Pipeline

Messages are processed before each LLM call to ensure clean, size-bounded history. This pipeline repairs orphaned tool calls and evicts oversized content.

**Steps:**

1. pydantic-ai prepares message history for next LLM request
2. `patch_tool_calls_processor` (sync) runs first:
   - Finds orphaned ToolCallParts with no matching ToolReturnParts
   - Injects synthetic "cancelled" ToolReturnParts
   - Finds orphaned ToolReturnParts with no matching ToolCallParts
   - Strips orphaned results, drops empty messages
3. `EvictionProcessor` (async) runs second:
   - Resolves backend from RunContext.deps
   - Calculates char limit from token_limit * 4
   - Finds ToolReturnParts exceeding limit
   - Saves full content to backend via write()
   - Replaces with head/tail preview + file path reference
   - Tracks evicted IDs to prevent re-processing
4. `ContextManagerCapability` checks token usage and optionally compresses history
5. Clean, size-bounded message history sent to LLM

```mermaid
flowchart LR
    subgraph PipelineStages
        direction LR
        Input["Raw Message History"] --> PatchStage
        subgraph PatchStage["Stage 1: patch_tool_calls_processor (sync)"]
            direction LR
            FindOrphans["Find orphaned<br/>ToolCallParts"] --> InjectCancelled["Inject synthetic<br/>'cancelled' returns"]
            FindOrphanReturns["Find orphaned<br/>ToolReturnParts"] --> StripOrphans["Strip orphaned results,<br/>drop empty messages"]
        end
        PatchStage --> EvictStage
        subgraph EvictStage["Stage 2: EvictionProcessor (async)"]
            direction LR
            CalcLimit["Calculate char limit<br/>(token_limit * 4)"] --> FindLarge["Find oversized<br/>ToolReturnParts"]
            FindLarge --> SaveToBackend["Save full content<br/>to backend"]
            SaveToBackend --> ReplacePreview["Replace with<br/>head/tail preview<br/>+ file path"]
        end
        EvictStage --> CompressStage
        subgraph CompressStage["Stage 3: ContextManagerCapability"]
            direction LR
            CheckTokens["Check token usage"] --> CompressHistory["Optionally compress<br/>history"]
        end
        CompressStage --> Output
    end
    Output["Clean History to LLM"]
    EvictStage --> EvictedContent["Evicted Content<br/>(stored in backend)"]
```

---

### Workflow 4: Team Coordination

Multi-agent teams coordinate through shared todo lists and a message bus, enabling parallel task execution with communication.

**Steps:**

1. Main agent calls `spawn_team` with team name and member definitions
2. `AgentTeam` created with SharedTodoList and TeamMessageBus
3. Members registered on message bus, handles created
4. Main agent calls `assign_task` for specific member
5. Task added to shared todo list, claimed by member
6. Agent factory creates subagent for member execution
7. Member runs task, can check teammates, send messages
8. Main agent calls `check_teammates` to monitor progress
9. When done, `dissolve_team` cancels remaining tasks and cleans up

```mermaid
sequenceDiagram
    participant MainAgent as "Main Agent"
    participant TeamToolset
    participant AgentTeam
    participant SharedTodoList
    participant MessageBus
    participant TeamMember1 as "Team Member 1"
    participant TeamMember2 as "Team Member 2"

    MainAgent->>TeamToolset: spawn_team(name, members[])
    TeamToolset->>AgentTeam: Create AgentTeam
    TeamToolset->>SharedTodoList: Create shared todo list
    TeamToolset->>MessageBus: Create team message bus
    TeamToolset->>MessageBus: Register members, create handles
    TeamToolset-->>MainAgent: Team created

    MainAgent->>TeamToolset: assign_task(member1, task_description)
    TeamToolset->>SharedTodoList: Add task to shared list
    SharedTodoList-->>TeamMember1: Task claimed by member
    TeamToolset->>TeamMember1: Agent factory creates subagent

    MainAgent->>TeamToolset: assign_task(member2, task_description)
    TeamToolset->>SharedTodoList: Add task to shared list
    SharedTodoList-->>TeamMember2: Task claimed by member
    TeamToolset->>TeamMember2: Agent factory creates subagent

    TeamMember1->>MessageBus: send_message(member2, update)
    MessageBus-->>TeamMember2: Receive message

    MainAgent->>TeamToolset: check_teammates()
    TeamToolset->>SharedTodoList: Query task statuses
    SharedTodoList-->>TeamToolset: Return status
    TeamToolset-->>MainAgent: Progress report

    TeamMember1-->>AgentTeam: Task complete
    TeamMember2-->>AgentTeam: Task complete

    MainAgent->>TeamToolset: dissolve_team()
    TeamToolset->>AgentTeam: Cancel remaining tasks
    TeamToolset->>MessageBus: Cleanup message bus
    TeamToolset->>SharedTodoList: Cleanup shared state
    TeamToolset-->>MainAgent: Team dissolved
```

---

### Workflow 5: Skill Discovery and Execution

Skills are discovered from directories or backends, then loaded on-demand when the agent needs them.

**Discovery Flow:**

1. SkillsCapability creates SkillsToolset with directories
2. SkillsDirectory or BackendSkillsDirectory discovers SKILL.md files
3. Each SKILL.md parsed: frontmatter (name, description) + instructions
4. Resources (.md, .json, .yaml, etc.) and scripts (.py) discovered alongside

```mermaid
flowchart LR
    subgraph Discovery
        direction LR
        Start["SkillsCapability"] --> CreateToolset["Create SkillsToolset<br/>with directories"]
        CreateToolset --> ScanDirs["Scan directories<br/>for SKILL.md files"]
        ScanDirs --> ParseMarkdown["Parse SKILL.md:<br/>frontmatter + instructions"]
        ParseMarkdown --> DiscoverResources["Discover resources<br/>(.md, .json, .yaml)"]
        DiscoverResources --> DiscoverScripts["Discover scripts<br/>(.py files)"]
        DiscoverScripts --> Registry["Skill Registry<br/>(available skills)"]
    end
    Registry --> SystemPrompt["Skills listed in<br/>system prompt"]
```

**Execution Flow:**

1. Agent sees available skills in system prompt via `get_instructions()`
2. Agent calls `load_skill` to get full instructions, resources, scripts
3. Agent follows skill instructions (just-in-time loading)
4. Agent can `read_skill_resource` for reference material
5. Agent can `run_skill_script` for executable scripts

```mermaid
sequenceDiagram
    participant Agent
    participant SkillsToolset
    participant SkillRegistry as "Skill Registry"
    participant Backend

    Agent->>SkillsToolset: get_instructions()
    SkillsToolset->>Agent: List available skills in system prompt

    Agent->>SkillsToolset: load_skill(skill_name)
    SkillsToolset->>SkillRegistry: Lookup skill by name
    SkillRegistry-->>SkillsToolset: Return skill data
    SkillsToolset-->>Agent: Full instructions + resources + scripts

    Agent->>Agent: Follow skill instructions<br/>(just-in-time loading)

    opt Read Reference Material
        Agent->>SkillsToolset: read_skill_resource(skill_name, resource_path)
        SkillsToolset->>Backend: Load resource content
        Backend-->>SkillsToolset: Resource data
        SkillsToolset-->>Agent: Resource content
    end

    opt Execute Script
        Agent->>SkillsToolset: run_skill_script(skill_name, script_name)
        SkillsToolset->>Backend: Load and execute script
        Backend-->>SkillsToolset: Script output
        SkillsToolset-->>Agent: Execution result
    end
```

---

### Workflow 6: Checkpoint and Rewind

Conversation state is saved at configurable intervals and can be restored to rewind or fork conversations.

**Steps:**

1. CheckpointMiddleware auto-saves checkpoints (every_turn or every_tool frequency)
2. Each checkpoint captures: ID, label, turn number, messages snapshot, metadata
3. Checkpoints stored in CheckpointStore (InMemory or File-based)
4. Agent can call `save_checkpoint` to label current state
5. Agent can call `list_checkpoints` to see available snapshots
6. Agent can call `rewind_to` to restore a previous state
7. `RewindRequested` exception propagates to application run loop
8. Application catches exception, restores messages, restarts agent run
9. `fork_from_checkpoint` allows starting a new session from a checkpoint

```mermaid
stateDiagram-v2
    [*] --> Running: Start Conversation

    Running --> AutoCheckpoint: Turn/Tool Complete
    AutoCheckpoint --> Running: Checkpoint Saved

    Running --> ManualCheckpoint: save_checkpoint()
    ManualCheckpoint --> Running: Labeled Checkpoint Created

    Running --> RewindRequest: rewind_to(checkpoint_id)
    RewindRequest --> RewindRequested: Raise Exception

    RewindRequested --> ApplicationLoop: Propagate Exception
    ApplicationLoop --> RestoreMessages: Catch RewindRequested
    RestoreMessages --> Running: Restart with Restored State

    Running --> ForkRequest: fork_from_checkpoint(checkpoint_id)
    ForkRequest --> NewSession: Create New Session
    NewSession --> Running: Start from Checkpoint State

    Running --> [*]: Conversation Complete

    state AutoCheckpoint {
        [*] --> CaptureState
        CaptureState --> StoreCheckpoint
        StoreCheckpoint --> [*]
    }

    state RestoreMessages {
        [*] --> LoadCheckpoint
        LoadCheckpoint --> ReplaceHistory
        ReplaceHistory --> [*]
    }
```

---

## Data Flow

The following diagram illustrates how data flows through the system during agent execution:

```mermaid
flowchart LR
    UserQuery["User Query"] --> AgentLoop["Agent Loop"]
    AgentLoop --> LLM["LLM API"]
    LLM --> ToolCalls["Tool Calls"]
    ToolCalls --> Toolsets["Toolsets"]
    Toolsets --> Backend["Backend"]
    Toolsets --> Subagents["Subagents"]
    Toolsets --> Memory["Memory Files"]
    Backend --> ToolResults["Tool Results"]
    Subagents --> ToolResults
    Memory --> ToolResults
    ToolResults --> HistoryProcessors["History Processors"]
    HistoryProcessors --> EvictedContent["Evicted Content"]
    HistoryProcessors --> CleanHistory["Clean History"]
    CleanHistory --> AgentLoop
    AgentLoop --> FinalResult["Final Result"]
```

---

## State Management

The system manages state across multiple dimensions:

| Component | Purpose | Scope |
|-----------|---------|-------|
| **DeepAgentDeps** | Holds all runtime state (backend, files, todos, subagents, uploads) | Per-run |
| **ContextManagerCapability** | Tracks token usage and triggers compression | Per-agent |
| **Memory files** | Persist across sessions in the backend | Cross-session |
| **CheckpointStore** | Persists conversation snapshots | Cross-session |
| **SharedTodoList** | Provides asyncio-safe shared state for teams | Per-team |

---

## Error Handling

The system handles errors at multiple levels with specific exception types:

| Error Type | Source | Behavior |
|------------|--------|----------|
| **ModelRetry** | HooksCapability | Raised when a pre-tool hook denies a call; triggers LLM retry |
| **RewindRequested** | Checkpoint system | Propagates from checkpoint rewind to application layer for state restoration |
| **BudgetExceededError** | CostTracking | Raised when USD budget is exceeded during execution |
| **SkillException hierarchy** | SkillsToolset | Includes SkillNotFoundError, SkillValidationError, SkillResourceNotFoundError |
| **Orphaned tool calls** | patch_tool_calls_processor | Auto-repairs broken history by injecting synthetic returns |
| **Eviction failures** | EvictionProcessor | Gracefully falls back to original content if backend write fails |

```mermaid
flowchart TD
    subgraph ErrorHierarchy
        direction TD
        SkillException["SkillException"]
        SkillException --> SkillNotFound["SkillNotFoundError"]
        SkillException --> SkillValidation["SkillValidationError"]
        SkillException --> SkillResourceNotFound["SkillResourceNotFoundError"]
    end

    subgraph RecoveryStrategies
        direction TD
        ModelRetryNode["ModelRetry<br/>from HooksCapability"] --> RetryLoop["LLM Retry Loop"]
        RewindRequestedNode["RewindRequested<br/>from Checkpoints"] --> RestoreState["Restore State + Restart"]
        BudgetError["BudgetExceededError<br/>from CostTracking"] --> HaltExecution["Halt Execution"]
        EvictionFail["Eviction Failure"] --> FallbackOriginal["Fallback to Original Content"]
    end
```
