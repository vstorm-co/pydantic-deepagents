---
description: "Create a pull request with auto-generated summary"
argument-hint: "[base branch]"
---

# Create Pull Request

Follow these steps:

1. Run `git branch --show-current` to get the current branch name.
2. Run `git log --oneline main..HEAD` (or `$ARGUMENTS..HEAD` if a base branch was specified) to see all commits.
3. Run `git diff main..HEAD --stat` to see changed files summary.
4. Draft a PR title and description:
   - Title: short, descriptive (under 72 chars)
   - Description: summarize the changes, motivation, and any breaking changes
5. Show the draft to the user and ask for confirmation.
6. Push the branch if not already pushed: `git push -u origin HEAD`
7. Create the PR using `gh pr create` with the confirmed title and body.
8. Show the PR URL.
