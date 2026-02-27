---
description: "Code review of staged or specified changes"
argument-hint: "[file path or 'staged']"
---

# Code Review

Review code changes and provide actionable feedback.

1. Determine what to review:
   - If `$ARGUMENTS` is "staged" or empty: review `git diff --cached`
   - If `$ARGUMENTS` is a file path: read and review that file
   - Otherwise: review `git diff`
2. Analyze the changes for:
   - Bugs or logic errors
   - Security vulnerabilities
   - Performance issues
   - Code style and readability
   - Missing error handling
   - Missing tests
3. Provide feedback organized by severity:
   - **Critical**: Must fix before merging
   - **Suggestion**: Improvements to consider
   - **Nitpick**: Minor style or formatting issues
4. If the code looks good, say so explicitly.
