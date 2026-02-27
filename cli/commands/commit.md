---
description: "Smart git commit with auto-generated message"
argument-hint: "[optional message override]"
---

# Git Commit

Follow these steps carefully:

1. Run `git status` to see the current state of the working directory.
2. Run `git diff --cached` to see what's staged.
3. If nothing is staged, run `git diff` and suggest which files to stage. Ask the user before staging.
4. Generate a commit message following Conventional Commits format:
   - `feat:` for new features
   - `fix:` for bug fixes
   - `refactor:` for code restructuring
   - `docs:` for documentation changes
   - `test:` for test additions/changes
   - `chore:` for maintenance tasks
5. If the user provided arguments: use `$ARGUMENTS` as the commit message instead.
6. Show the proposed commit message and ask for confirmation before committing.
7. Run `git commit` with the confirmed message.
8. Show the result.
