---
name: refactor
description: "Refactor code to improve structure and maintainability"
tags: [code-quality, refactoring]
version: "1.0.0"
---

# Refactor

Improve code structure without changing external behavior.

## Process

1. **Understand** — Read all related code, run existing tests
2. **Plan** — Identify what to change and why
3. **Execute** — Make changes incrementally
4. **Verify** — Run tests after each change

## Common Refactoring Patterns

### Extract
- Long function → smaller focused functions
- Repeated code → shared helper
- Magic numbers → named constants

### Simplify
- Deep nesting → early returns / guard clauses
- Complex conditionals → descriptive functions
- Large classes → smaller focused classes

### Rename
- Unclear names → descriptive names
- Inconsistent naming → consistent conventions

### Reorganize
- Related functions scattered → grouped in modules
- Circular dependencies → dependency inversion

## Rules

- Never change behavior — tests must pass before and after
- One refactoring type per commit
- If tests don't exist, write them first
- Don't refactor and add features in the same change
