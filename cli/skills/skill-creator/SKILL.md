---
name: skill-creator
description: "Create new reusable skills from conversation context"
tags: [meta, productivity]
version: "1.0.0"
---

# Skill Creator

Create a new skill by generating a SKILL.md file with YAML frontmatter.

## Steps

1. Identify the task pattern the user wants to capture as a skill
2. Write clear, specific instructions that an AI agent can follow
3. Create a directory with this structure:

```
my-skill/
├── SKILL.md          # Instructions + frontmatter
├── template.md       # (optional) Template files
└── example.py        # (optional) Example scripts
```

4. The SKILL.md must have this format:

```markdown
---
name: skill-name
description: "Brief description of what this skill does"
tags: [category1, category2]
version: "1.0.0"
---

# Skill Name

## Purpose
What this skill accomplishes.

## Instructions
Step-by-step instructions for the agent.

## Examples
Concrete examples of input/output.
```

## Guidelines

- **Name**: lowercase with hyphens (e.g., `api-client-generator`)
- **Description**: one sentence, starts with a verb
- **Instructions**: specific enough that another agent can execute without context
- Include edge cases and error handling guidance
- Add examples showing expected input and output
- Place resources (templates, schemas) as separate files next to SKILL.md
