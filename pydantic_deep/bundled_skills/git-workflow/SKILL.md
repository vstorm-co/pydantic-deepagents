---
name: git-workflow
description: "Git operations: commits, branches, PRs, and conflict resolution"
tags: [git, workflow]
version: "1.0.0"
---

# Git Workflow

## Commit Messages

Format: `<type>: <description>`

Types: feat, fix, refactor, test, docs, style, chore

- Description starts with lowercase verb
- Max 72 characters for first line
- Add body for complex changes

## Branch Workflow

1. Create feature branch from main: `git checkout -b feat/description`
2. Make changes in small, focused commits
3. Push and create PR
4. After review, squash-merge to main

## Conflict Resolution

1. `git fetch origin`
2. `git rebase origin/main` (or merge if team prefers)
3. For each conflict:
   - Read both versions carefully
   - Understand the intent of each change
   - Resolve preserving both intents
   - Test after resolving
4. `git rebase --continue`

## Safety Rules

- Never force-push to main/master
- Never commit secrets, credentials, or .env files
- Always check `git diff` before committing
- Use `git stash` before switching branches with uncommitted changes
