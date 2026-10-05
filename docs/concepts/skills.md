# Skills

!!! note "Future Migration"
    This implementation will be removed when skills support is added to pydantic-ai core.
    See [pydantic-ai#3780](https://github.com/pydantic/pydantic-ai/pull/3780) for progress.
    We will migrate to use the upstream implementation once available.

Sometimes you want to teach an agent *how* to do something — your team's git
conventions, a report format, a deploy checklist — without bloating its system
prompt with every detail up front. That's what **skills** are for.

A skill is a folder of instructions the agent discovers by name and loads only
when it's actually relevant. This is **progressive disclosure**: the agent sees
a one-line summary of every skill, and pulls in the full instructions on demand.
Cheap to have many; you only pay for the one in use.

## What are Skills?

A skill is a folder containing:

- `SKILL.md` - Definition with YAML frontmatter and instructions
- Optional resource files (templates, scripts, documents)

```
~/.pydantic-deep/skills/
├── code-review/
│   ├── SKILL.md
│   └── checklist.md
├── test-generator/
│   ├── SKILL.md
│   └── templates/
│       └── pytest.py
└── documentation/
    └── SKILL.md
```

## SKILL.md Format

```markdown
---
name: code-review
description: Review Python code for quality and security
version: 1.0.0
tags:
  - code
  - review
  - python
author: your-name
---

# Code Review Skill

Detailed instructions for the agent...

## Review Process

1. Read the entire file first
2. Check for security issues
3. Review code structure
...
```

### Frontmatter Fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Unique skill identifier |
| `description` | Yes | Brief description (shown in list) |
| `version` | No | Semantic version (default: "1.0.0") |
| `tags` | No | List of tags for categorization |
| `author` | No | Skill author |

## Progressive Disclosure

Skills use progressive disclosure to optimize token usage:

### 1. Discovery (Low Cost)

Only YAML frontmatter is loaded:

```python
# Agent calls list_skills()
# Returns:
# - code-review: Review Python code for quality and security [code, review]
# - test-generator: Generate pytest test cases [testing, python]
```

### 2. Loading (On Demand)

Full instructions loaded when needed:

```python
# Agent calls load_skill("code-review")
# Returns complete SKILL.md content
```

### 3. Resources (As Needed)

Additional files accessed individually:

```python
# Agent calls read_skill_resource("code-review", "checklist.md")
# Returns specific resource file
```

## Using Skills

### Enable Skills

```python
from pydantic_deep import create_deep_agent

agent = create_deep_agent(
    skill_directories=[
        {"path": "~/.pydantic-deep/skills", "recursive": True},
    ],
    include_skills=True,
)
```

### Available Tools

| Tool | Description |
|------|-------------|
| `list_skills` | List all available skills |
| `load_skill` | Load full instructions for a skill |
| `read_skill_resource` | Read a resource file from a skill |

### Agent Workflow

The agent typically:

1. Receives a task ("Review this code for security issues")
2. Lists available skills to find relevant ones
3. Loads the appropriate skill instructions
4. Follows the skill's guidelines
5. Accesses resources as needed

## Creating Skills

### Step 1: Create Directory

```bash
mkdir -p ~/.pydantic-deep/skills/my-skill
```

### Step 2: Write SKILL.md

```markdown
---
name: api-design
description: Design RESTful APIs following best practices
version: 1.0.0
tags:
  - api
  - rest
  - design
author: your-name
---

# API Design Skill

You are an API design expert. When designing APIs, follow these principles:

## REST Conventions

- Use nouns for resources: `/users`, `/orders`
- Use HTTP methods correctly: GET, POST, PUT, DELETE
- Version your API: `/v1/users`

## Response Format

Always return JSON with consistent structure:

```json
{
  "data": {...},
  "meta": {
    "page": 1,
    "total": 100
  }
}
```

## Error Handling

Return appropriate status codes:
- 400: Bad request
- 401: Unauthorized
- 404: Not found
- 500: Server error
```

### Step 3: Add Resources (Optional)

```bash
# Create a template file
cat > ~/.pydantic-deep/skills/api-design/openapi-template.yaml << 'EOF'
openapi: 3.0.0
info:
  title: API Name
  version: 1.0.0
paths: {}
EOF
```

## Skill Discovery

### From Directories

Use [`SkillsDirectory`][pydantic_deep.features.skills.directory.SkillsDirectory]
to discover skills from a filesystem directory. `get_skills()` returns a
`dict[str, Skill]` keyed by skill name:

```python
from pydantic_deep.features.skills import SkillsDirectory

source = SkillsDirectory(path="~/.pydantic-deep/skills")

for name, skill in source.get_skills().items():
    print(f"{skill.name}: {skill.description}")
```

### Pre-loaded Skills

To pass skills directly (without filesystem discovery), use a `SkillsToolset`:

```python
from pydantic_deep.features.skills import Skill, SkillsToolset

skill = Skill(name="code-review", description="Review code for quality", content="...")
agent = create_deep_agent(
    toolsets=[SkillsToolset(skills=[skill])],
    include_skills=False,  # avoid duplicate skills toolset
)
```

## Example: Code Review Skill

### SKILL.md

```markdown
---
name: code-review
description: Review Python code for quality, security, and best practices
version: 1.0.0
tags:
  - code
  - review
  - python
  - security
---

# Code Review Skill

When reviewing code, follow this checklist:

## Security

- [ ] No hardcoded secrets
- [ ] Input validation on external data
- [ ] No SQL injection vulnerabilities
- [ ] Proper error handling

## Code Quality

- [ ] Functions have single responsibility
- [ ] Descriptive variable names
- [ ] Type hints present
- [ ] Docstrings for public functions

## Output Format

```markdown
## Summary
[Brief assessment]

## Critical Issues
- [List security/major bugs]

## Improvements
- [Suggested improvements]

## Good Practices
- [Positive aspects]
```
```

### Usage

```python
agent = create_deep_agent(
    skill_directories=[{"path": "./skills"}],
)

result = await agent.run(
    "Load the code-review skill and review /src/auth.py",
    deps=deps,
)
```

## Best Practices

### 1. Clear Names

Use descriptive, hyphenated names:
- ✅ `code-review`, `test-generator`, `api-design`
- ❌ `cr`, `skill1`, `mySkill`

### 2. Focused Skills

Each skill should do one thing well:
- ✅ `code-review` - Reviews code
- ❌ `code-review-and-testing-and-docs` - Too broad

### 3. Actionable Instructions

Write instructions the agent can follow:

```markdown
# Good
When you find a security issue:
1. Note the file and line number
2. Describe the vulnerability
3. Suggest a fix with code example

# Bad
Be careful about security.
```

### 4. Include Examples

Show expected output format:

```markdown
## Example Review

**File:** auth.py:42
**Issue:** SQL Injection
**Severity:** Critical

```python
# Bad
query = f"SELECT * FROM users WHERE id = {user_id}"

# Good
query = "SELECT * FROM users WHERE id = ?"
cursor.execute(query, (user_id,))
```
```

### 5. Version Your Skills

Update version when making changes:

```yaml
version: 1.0.0  # Initial release
version: 1.1.0  # Added new checklist items
version: 2.0.0  # Breaking changes to format
```

## Caching and Performance

### Skill Caching

Skills are cached after first load to avoid repeated file reads:

```python
# First call reads from disk
load_skill("code-review")  # Reads SKILL.md

# Subsequent calls use cache
load_skill("code-review")  # Returns cached content (instant)
```

The cache persists for the lifetime of the agent instance. Each agent has its own cache.

### Discovery Performance

Skill discovery (via [`SkillsDirectory`][pydantic_deep.features.skills.directory.SkillsDirectory]) scans directories on agent creation:

| Factor | Impact |
|--------|--------|
| Number of skill directories | Linear scan time |
| `recursive: True` | Deeper directory traversal |
| Number of skills | More frontmatter parsing |

**Optimization tips:**

1. **Limit directories**: Only include directories with actual skills
2. **Use `recursive: False`** when skills are in known locations
3. **Pre-load skills**: Pass `Skill` objects via `SkillsToolset` to avoid discovery

```python
# Fast: Pre-loaded skills via toolset (no disk scan)
agent = create_deep_agent(
    toolsets=[SkillsToolset(skills=[my_skill])],
    include_skills=False,
)

# Moderate: Single directory, non-recursive
agent = create_deep_agent(
    skill_directories=[{"path": "./skills", "recursive": False}]
)

# Slower: Multiple directories, recursive
agent = create_deep_agent(
    skill_directories=[
        {"path": "~/.pydantic-deep/skills", "recursive": True},
        {"path": "/shared/skills", "recursive": True},
    ]
)
```

### Resource File Security

Resource file access is restricted to the skill's directory:

```python
# Valid: Within skill directory
read_skill_resource("code-review", "checklist.md")
read_skill_resource("code-review", "templates/pytest.py")

# Invalid: Path traversal blocked
read_skill_resource("code-review", "../other-skill/secret.md")  # Error
read_skill_resource("code-review", "/etc/passwd")               # Error
```

### Default Skill Directory

The default skill directory is `~/.pydantic-deep/skills`:

```python
# Uses default directory
agent = create_deep_agent(include_skills=True)

# Equivalent to:
agent = create_deep_agent(
    skill_directories=[{"path": "~/.pydantic-deep/skills", "recursive": True}]
)
```

## Skills in the workspace

By default, `skill_directories` accepts local filesystem paths (strings or dicts)
on the machine the agent is built on. A skill can also live where the agent
works — a `skills/` folder in its Docker container, its sandbox session, its
in-memory document. [`WorkspaceSkillsDirectory`][pydantic_deep.features.skills.workspace.WorkspaceSkillsDirectory]
names such a folder; the skills toolset discovers it through `ctx.workspace` the
first time a run in that workspace needs its skills.

```python
from pydantic_deep import DockerWorkspace, WorkspaceSkillsDirectory, create_deep_agent

agent = create_deep_agent(
    workspace=DockerWorkspace(runtime="python-minimal"),
    skill_directories=[
        WorkspaceSkillsDirectory(
            path="skills",  # relative to the workspace's working directory
            script_timeout=60,  # seconds
        ),
    ],
)
```

Skill scripts (`.py` files in the skill's folder or its `scripts/` subfolder)
run with `python` inside the workspace, so they see the same files and packages
as the agent.

!!! note "Scripts need a workspace that runs commands"
    In a workspace without commands — `StateWorkspace` — scripts are not
    offered; resources (`.md`, `.json`, `.yaml`, etc.) are.

To try it in memory, seed the skill into a `StateBackend` document and give the
run that document (see [Workspaces](workspaces.md#stateworkspace-in-memory-zero-side-effects)):

```python
from pydantic_ai.workspaces import WorkspaceRef
from pydantic_deep import DeepAgentDeps, StateBackend, StateWorkspace

document = StateBackend()
document.write_bytes("/skills/code-review/SKILL.md", b"""\
---
name: code-review
description: Review Python code for quality and security
---

# Code Review Skill

When reviewing code, follow these guidelines...
""")
documents = StateWorkspace(store={"session": document})

agent = create_deep_agent(skill_directories=[WorkspaceSkillsDirectory()])
result = await agent.run(
    "Review /src/app.py",
    deps=DeepAgentDeps(),
    workspace=documents.backend(WorkspaceRef(provider="state", id="session")),
)
```

### WorkspaceSkillsDirectory Options

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | `str` | `"skills"` | Folder in the workspace, relative to its working directory |
| `validate` | `bool` | `True` | Raise on an invalid skill rather than skip it with a warning |
| `max_depth` | `int \| None` | `3` | How deep below `path` a `SKILL.md` may sit (`None` for any depth) |
| `script_timeout` | `int` | `30` | Seconds a skill's script may run |

### Mixing Local and Workspace Directories

You can combine local paths and `WorkspaceSkillsDirectory` in the same agent:

```python
agent = create_deep_agent(
    workspace=DockerWorkspace(),
    skill_directories=[
        "~/.pydantic-deep/skills",  # This machine
        WorkspaceSkillsDirectory(path="skills"),  # The run's workspace
    ],
)
```

## Recap

- A skill is a `SKILL.md` folder (plus optional resources/scripts) the agent
  loads on demand — progressive disclosure keeps the prompt lean.
- Point `create_deep_agent(skill_directories=[…])` at a folder, or store skills
  in the run's workspace with `WorkspaceSkillsDirectory`.
- Many skills cost almost nothing until one is actually used.

## Next Steps

- [Skills Example](../examples/skills.md) - Complete working example
- [API Reference](../api/toolsets.md#skillstoolset) - SkillsToolset API
