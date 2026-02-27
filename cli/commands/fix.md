---
description: "Fix failing tests or lint errors"
argument-hint: "[error description or file path]"
---

# Fix Errors

Diagnose and fix failing tests or lint errors.

1. Identify the problem:
   - If `$ARGUMENTS` is provided: focus on that specific error or file
   - Otherwise: run the test suite and linter to find failures
2. For test failures:
   - Read the failing test and the code it tests
   - Understand the expected vs actual behavior
   - Edit the source code to fix the issue (not the test, unless the test is wrong)
   - Re-run the failing test to verify the fix
3. For lint errors:
   - Run the linter (ruff, eslint, etc.)
   - Apply fixes to each reported issue
   - Re-run the linter to confirm all errors are resolved
4. Show a summary of all changes made.
